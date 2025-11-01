from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from pydantic import BaseModel

from agents import Runner, RunConfig, TResponseInputItem, trace  # type: ignore

from .agents_factory import get_agents_bundle

PARALLEL_TIMEOUT_SECS = 45


def guardrails_has_tripwire(results):
    return any(getattr(result, "tripwire_triggered", False) is True for result in (results or []))


def get_guardrail_checked_text(results, fallback_text):
    for result in (results or []):
        info = getattr(result, "info", None) or {}
        if isinstance(info, dict) and ("checked_text" in info):
            return info.get("checked_text") or fallback_text
    return fallback_text


def build_guardrail_fail_output(results):
    failures = []
    for result in (results or []):
        if getattr(result, "tripwire_triggered", False):
            info = getattr(result, "info", None) or {}
            failure = {"guardrail_name": info.get("guardrail_name")}
            for key in (
                "flagged",
                "confidence",
                "threshold",
                "hallucination_type",
                "hallucinated_statements",
                "verified_statements",
            ):
                if key in (info or {}):
                    failure[key] = info.get(key)
            failures.append(failure)
    return {"failed": len(failures) > 0, "failures": failures}


class WorkflowInput(BaseModel):
    input_as_text: str


async def _run_agent(agent_obj, conversation_history: List[TResponseInputItem], trace_meta: dict):
    return await Runner.run(
        agent_obj,
        input=[*conversation_history],
        run_config=RunConfig(trace_metadata=trace_meta),
    )


async def run_workflow(workflow_input: WorkflowInput) -> Dict[str, Any]:
    """
    Flujo: Inicial → (A1..A5 en paralelo) → Final
    Configurable desde config/agents.yaml
    """
    bundle = await get_agents_bundle()
    guardrails_cfg = bundle.guardrails_ctx.guardrails_config

    with trace("RecavAI-Agentic-Assistant"):
        workflow = workflow_input.model_dump()

        conversation_history: List[TResponseInputItem] = [
            {"role": "user", "content": [{"type": "input_text", "text": workflow["input_as_text"]}]}
        ]

        from guardrails.runtime import instantiate_guardrails, load_config_bundle, run_guardrails  # type: ignore

        ctx = bundle.guardrails_ctx
        guardrails_result = await run_guardrails(
            ctx,
            workflow["input_as_text"],
            "text/plain",
            instantiate_guardrails(load_config_bundle(guardrails_cfg)),
            suppress_tripwire=True,
            raise_guardrail_errors=True,
        )
        if guardrails_has_tripwire(guardrails_result):
            return {
                "message": (
                    "Soy un asistente para preguntas de Diligencia Debida en Sostenibilidad. "
                    "Formula una pregunta relacionada. Contacto: info@observatoriorecava.es"
                )
            }

        trace_meta = {"__trace_source__": "agent-builder", "workflow_id": "wf_parallel_a1a5"}
        inicial_temp = await _run_agent(bundle.asistente_inicial, conversation_history, trace_meta)
        conversation_history.extend([item.to_input_item() for item in inicial_temp.new_items])
        inicial_out_text = inicial_temp.final_output_as(str)

        snapshot_history = [*conversation_history]
        tasks = [
            _run_agent(bundle.a1_estructura, snapshot_history, trace_meta),
            _run_agent(bundle.a2_precision, snapshot_history, trace_meta),
            _run_agent(bundle.a3_enfoque, snapshot_history, trace_meta),
            _run_agent(bundle.a4_referencias, snapshot_history, trace_meta),
            _run_agent(bundle.a5_temporal, snapshot_history, trace_meta),
        ]
        a1_res, a2_res, a3_res, a4_res, a5_res = await asyncio.wait_for(
            asyncio.gather(*tasks), timeout=PARALLEL_TIMEOUT_SECS
        )
        for temp in (a1_res, a2_res, a3_res, a4_res, a5_res):
            conversation_history.extend([item.to_input_item() for item in temp.new_items])

        def _parsed(temp):
            try:
                return temp.final_output.model_dump()
            except Exception:
                return {}

        a1_parsed, a2_parsed, a3_parsed, a4_parsed, a5_parsed = map(
            _parsed, (a1_res, a2_res, a3_res, a4_res, a5_res)
        )

        def _mejoras_si_rechazado(parsed):
            verdict = (parsed or {}).get("veredicto", "")
            if isinstance(verdict, str) and verdict.strip().upper() == "RECHAZADO":
                return (parsed or {}).get("mejoras", "") or ""
            return ""

        mejoras = [
            ("A1 - Estructura", _mejoras_si_rechazado(a1_parsed)),
            ("A2 - Precisión", _mejoras_si_rechazado(a2_parsed)),
            ("A3 - Enfoque", _mejoras_si_rechazado(a3_parsed)),
            ("A4 - Referencias", _mejoras_si_rechazado(a4_parsed)),
            ("A5 - Temporal", _mejoras_si_rechazado(a5_parsed)),
        ]
        mejoras = [(name, text.strip()) for (name, text) in mejoras if text and text.strip()]

        original_query = workflow["input_as_text"]
        composite_prompt = [
            "Pregunta original:",
            original_query,
            "",
            "Aplica SOLO las siguientes mejoras propuestas por los evaluadores con veredicto RECHAZADO.",
            "Si no hay mejoras, devuelve la mejor versión de la respuesta del Asistente Inicial.",
            "",
        ]
        if mejoras:
            composite_prompt.append("Mejoras a aplicar:")
            for nombre, texto in mejoras:
                composite_prompt.append(f"- {nombre}: {texto}")

        conversation_history.append(
            {"role": "user", "content": [{"type": "input_text", "text": "\n".join(composite_prompt)}]}
        )

        final_temp = await _run_agent(bundle.agente_final, conversation_history, trace_meta)
        conversation_history.extend([item.to_input_item() for item in final_temp.new_items])

        return {
            "asistente_inicial": inicial_out_text,
            "a1": a1_parsed,
            "a2": a2_parsed,
            "a3": a3_parsed,
            "a4": a4_parsed,
            "a5": a5_parsed,
            "final": final_temp.final_output_as(str),
        }
