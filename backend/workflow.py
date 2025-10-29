"""Core workflow for advisor responses with citation aggregation."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

# NOTE: Replace these imports with the concrete implementations from your agent SDK.
from agents import Agent, Runner, RunConfig, TResponseInputItem, trace  # type: ignore

from .guardrails_utils import (
    ctx,
    guardrails_config,
    guardrails_has_tripwire,
    instantiate_guardrails,
    load_config_bundle,
    run_guardrails,
    get_guardrail_checked_text,
)

PARALLEL_TIMEOUT_SECS = 45


async def _run_agent_with_timeout(
    agent_obj: "Agent",
    conversation_history: List["TResponseInputItem"],
    run_cfg: "RunConfig",
    timeout_s: int = PARALLEL_TIMEOUT_SECS,
):
    async def _run():
        return await Runner.run(agent_obj, input=[*conversation_history], run_config=run_cfg)

    return await asyncio.wait_for(_run(), timeout=timeout_s)


def _mk_run_cfg() -> "RunConfig":
    return RunConfig(
        trace_metadata={
            "__trace_source__": "agent-builder",
            "workflow_id": "wf_68f0d1e79e088190ac1065378ce1914901e19ebba6b37747",
        }
    )


_URL_RE = re.compile(r"https?://[^\s\]\)>,;\"]+", re.IGNORECASE)


def _normalize_citation(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": (c.get("title") or c.get("titulo") or c.get("name") or "").strip(),
        "source": (c.get("source") or c.get("fuente") or "").strip(),
        "url": (c.get("url") or c.get("link") or "").strip(),
        "quote": (c.get("quote") or c.get("cita") or c.get("extracto") or "").strip(),
        "date": (c.get("date") or c.get("fecha") or "").strip(),
        "section": (c.get("section") or c.get("seccion") or "").strip(),
    }


def _extract_basic_citations_from_text(txt: str) -> List[Dict[str, Any]]:
    if not txt:
        return []
    return [_normalize_citation({"url": m.group(0)}) for m in _URL_RE.finditer(txt)]


def _dedupe_citations(citas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for c in citas:
        key = (c.get("url") or "", c.get("title") or "")
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _parse_eval_output(name: str, temp_result) -> Dict[str, Any]:
    base = {"agent": name, "veredicto": "RECHAZADO", "mejoras": "", "citas": []}
    try:
        parsed = temp_result.final_output.model_dump()
        base["veredicto"] = (parsed.get("veredicto") or "").strip().upper() or "RECHAZADO"
        base["mejoras"] = (parsed.get("mejoras") or "").strip()
        raw_citas = parsed.get("citas") or parsed.get("references") or []
        if isinstance(raw_citas, list):
            base["citas"] = [_normalize_citation(ci) for ci in raw_citas if isinstance(ci, dict)]
        return base
    except Exception:
        try:
            txt = temp_result.final_output_as(str)
        except Exception:
            txt = ""
        ver = (
            "RECHAZADO"
            if "RECHAZ" in txt.upper()
            else "APROBADO"
            if "APROB" in txt.upper()
            else "RECHAZADO"
        )
        return {
            **base,
            "veredicto": ver,
            "mejoras": txt,
            "citas": _extract_basic_citations_from_text(txt),
        }


def _collect_available_citations(evals: List[Dict[str, Any]], a4_res) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    for ev in evals:
        if ev.get("agent", "").startswith("A4"):
            collected.extend(ev.get("citas", []))
    try:
        parsed = a4_res.final_output.model_dump()
        raw = parsed.get("citas") or parsed.get("references") or []
        if isinstance(raw, list):
            collected.extend([_normalize_citation(ci) for ci in raw if isinstance(ci, dict)])
    except Exception:
        pass
    try:
        txt = a4_res.final_output_as(str)
        collected.extend(_extract_basic_citations_from_text(txt))
    except Exception:
        pass
    return _dedupe_citations(collected)


def _build_final_synthesis_prompt(
    user_question: str,
    initial_answer: str,
    evaluations: List[Dict[str, Any]],
    citations: Optional[List[Dict[str, Any]]] = None,
) -> str:
    citations = citations or []
    lines = []
    for i, c in enumerate(citations, start=1):
        title = c.get("title") or c.get("url") or "Fuente"
        url = c.get("url") or ""
        fuente = c.get("source") or ""
        fecha = c.get("date") or ""
        lines.append(f"[{i}] {title} — {fuente} {fecha} {url}".strip())
    citas_bloque = "\n".join(lines) if lines else "Ninguna"

    return f"""
### Tarea
Genera la mejor respuesta final a la pregunta del usuario aplicando, de forma mínima y precisa, las “mejoras” propuestas por los evaluadores cuyo veredicto fue RECHAZADO. Mantén lo que ya está bien según los evaluadores con veredicto APROBADO.

### Pregunta original
{user_question}

### Borrador inicial (del asistente inicial)
{initial_answer}

### Evaluaciones (A1..A5)
{evaluations}

### Citas disponibles
Estas son las únicas citas que puedes usar. Si no son necesarias, no las cites. No inventes nuevas fuentes.
{citas_bloque}

### Reglas de síntesis
1) Aplica SOLO las mejoras de los evaluadores con veredicto RECHAZADO.
2) No elimines aciertos ya validados por veredictos APROBADO.
3) Conserva el estilo y formato del asistente inicial (alcance, fuentes, advertencias).
4) Si introduces referencias, usa marcadores en línea [n] que correspondan al listado de "Citas disponibles".
5) Si no hay RECHAZADOS, devuelve el borrador inicial tal cual.

### Respuesta final requerida
Devuelve ÚNICAMENTE el texto final para el usuario (con marcadores [n] si has usado citas).
""".strip()


class WorkflowInput(BaseModel):
    input_as_text: str


async def run_workflow(
    workflow_input: WorkflowInput,
    asistente_inicial: "Agent",
    a1_estructura: "Agent",
    a2_precision: "Agent",
    a3_enfoque: "Agent",
    a4_referencias: "Agent",
    a5_temporal: "Agent",
    agent: "Agent",
) -> Dict[str, Any]:
    with trace("RecavAI-Agentic-Assistant"):
        workflow = workflow_input.model_dump()
        conversation_history: List["TResponseInputItem"] = [
            {"role": "user", "content": [{"type": "input_text", "text": workflow["input_as_text"]}]}
        ]

        guardrails_inputtext = workflow["input_as_text"]
        guardrails_result = await run_guardrails(
            ctx,
            guardrails_inputtext,
            "text/plain",
            instantiate_guardrails(load_config_bundle(guardrails_config)),
            suppress_tripwire=True,
            raise_guardrail_errors=True,
        )
        guardrails_checked = get_guardrail_checked_text(guardrails_result, guardrails_inputtext)
        if guardrails_has_tripwire(guardrails_result):
            return {
                "message": (
                    "Soy un asistente para responder preguntas relacionadas con Diligencia Debida en Sostenibilidad. "
                    "Por favor, pruebe con una pregunta sobre ese tema. "
                    "Contacto: info@observatoriorecava.es"
                ),
                "citas": [],
            }

        # asistente inicial
        init_temp = await Runner.run(
            asistente_inicial,
            input=[*conversation_history],
            run_config=_mk_run_cfg(),
        )
        conversation_history.extend([item.to_input_item() for item in init_temp.new_items])
        initial_answer_text = init_temp.final_output_as(str)
        asistente_inicial_result = {"output_text": initial_answer_text}

        eval_tasks = [
            _run_agent_with_timeout(a1_estructura, conversation_history, _mk_run_cfg()),
            _run_agent_with_timeout(a2_precision, conversation_history, _mk_run_cfg()),
            _run_agent_with_timeout(a3_enfoque, conversation_history, _mk_run_cfg()),
            _run_agent_with_timeout(a4_referencias, conversation_history, _mk_run_cfg()),
            _run_agent_with_timeout(a5_temporal, conversation_history, _mk_run_cfg()),
        ]

        try:
            a1_res, a2_res, a3_res, a4_res, a5_res = await asyncio.gather(*eval_tasks, return_exceptions=False)
        except Exception:
            a1_res = await Runner.run(a1_estructura, input=[*conversation_history], run_config=_mk_run_cfg())
            a2_res = await Runner.run(a2_precision, input=[*conversation_history], run_config=_mk_run_cfg())
            a3_res = await Runner.run(a3_enfoque, input=[*conversation_history], run_config=_mk_run_cfg())
            a4_res = await Runner.run(a4_referencias, input=[*conversation_history], run_config=_mk_run_cfg())
            a5_res = await Runner.run(a5_temporal, input=[*conversation_history], run_config=_mk_run_cfg())

        for temp in (a1_res, a2_res, a3_res, a4_res, a5_res):
            conversation_history.extend([item.to_input_item() for item in temp.new_items])

        evals: List[Dict[str, Any]] = [
            _parse_eval_output("A1 - Estructura", a1_res),
            _parse_eval_output("A2 - Precisión", a2_res),
            _parse_eval_output("A3 - Enfoque", a3_res),
            _parse_eval_output("A4 - Referencias", a4_res),
            _parse_eval_output("A5 - Temporal", a5_res),
        ]

        available_citations = _collect_available_citations(evals, a4_res)

        synthesis_prompt = _build_final_synthesis_prompt(
            user_question=guardrails_checked,
            initial_answer=initial_answer_text,
            evaluations=evals,
            citations=available_citations,
        )
        final_agent_history = [
            {"role": "user", "content": [{"type": "input_text", "text": synthesis_prompt}]}
        ]
        agent_temp = await Runner.run(agent, input=final_agent_history, run_config=_mk_run_cfg())
        conversation_history.extend([item.to_input_item() for item in agent_temp.new_items])

        return {
            "asistente_inicial": asistente_inicial_result,
            "evaluaciones": evals,
            "respuesta_final": agent_temp.final_output_as(str),
            "citas": available_citations,
        }

