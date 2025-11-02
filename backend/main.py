"""FastAPI entrypoint for RecavAI advisor service with pluggable strategies."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, Tuple

import httpx
import yaml
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel

from src.agents_factory import get_agents_bundle, reset_agents_bundle
from src.app_settings import get_settings_section
from src.config_loader import (
    AppConfig,
    list_instruction_files,
    load_app_config,
    read_config_yaml,
    read_instruction_files,
    save_app_config,
    write_instruction_files,
)

from .auth import require_admin_user, require_firebase_user
from .bigquery_service import insert_chat_turn_to_bigquery
from .chat_generators import (
    BaseChatAdapter,
    OnPremMCPAdapter,
    OpenAIAgentNetworkAdapter,
    SingleAssistantAdapter,
)
from .workflow import WorkflowExecutor, load_workflow_definition

logger = logging.getLogger(__name__)

app = FastAPI(title="RecavAI Advisor API")

_web_settings = get_settings_section("web")
_allowed_origins = _web_settings.get("cors_allowed_origins") or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Idempotency-Key"],
)

router = APIRouter()


class AgentsConfigUpdate(BaseModel):
    yaml: str
    instructions: Dict[str, str] | None = None


async def _build_adapter() -> Tuple[BaseChatAdapter, Dict[str, Any]]:
    advisor_settings = get_settings_section("advisor")

    mode_value = os.getenv("ADVISOR_GENERATION_MODE") or advisor_settings.get(
        "generation_mode", "openai_single_assistant"
    )
    mode = str(mode_value).strip().lower()
    resources: Dict[str, Any] = {"mode": mode}

    if mode == "openai_single_assistant":
        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        model_name = os.getenv("OPENAI_RESPONSES_MODEL") or advisor_settings.get(
            "responses_model", "gpt-5-turbo"
        )
        temperature_value = os.getenv("OPENAI_RESPONSES_TEMPERATURE")
        if temperature_value is None:
            temperature_value = advisor_settings.get("responses_temperature", 0.2)

        adapter = SingleAssistantAdapter(
            client=client,
            assistant_id=os.getenv("OPENAI_ASSISTANT_ID_ASESOR"),
            model=str(model_name),
            temperature=float(temperature_value),
        )
        resources["openai_client"] = client
        return adapter, resources

    if mode == "onprem_mcp_server":
        base_url = os.environ["MCP_SERVER_URL"]
        api_key = os.environ.get("MCP_API_KEY", "")
        timeout_value = os.getenv("MCP_TIMEOUT_SECS")
        if timeout_value is None:
            timeout_value = advisor_settings.get("mcp_timeout_secs", 60.0)
        timeout = float(timeout_value)
        client = httpx.AsyncClient(timeout=timeout)
        adapter = OnPremMCPAdapter(base_url=base_url, api_key=api_key, client=client)
        resources["httpx_client"] = client
        return adapter, resources

    if mode == "openai_agent_network":
        client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        definition = load_workflow_definition()
        executor = WorkflowExecutor(client=client, definition=definition)
        adapter = OpenAIAgentNetworkAdapter(executor=executor)
        resources["openai_client"] = client
        resources["workflow_definition"] = definition
        return adapter, resources

    raise ValueError(f"Modo de generación no soportado: {mode}")


@app.on_event("startup")
async def startup_event() -> None:
    adapter, resources = await _build_adapter()
    app.state.chat_adapter = adapter
    app.state.adapter_resources = resources
    app.state.advisor_mode = resources.get("mode", "openai_single_assistant")
    logger.info("Advisor backend initialized with mode=%s", app.state.advisor_mode)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    adapter: BaseChatAdapter = getattr(app.state, "chat_adapter", None)
    if adapter:
        try:
            await adapter.aclose()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Failed to close adapter cleanly: %s", exc)

    resources: Dict[str, Any] = getattr(app.state, "adapter_resources", {})
    httpx_client: httpx.AsyncClient = resources.get("httpx_client")
    if httpx_client:
        await httpx_client.aclose()


@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "mode": getattr(app.state, "advisor_mode", None)}


def _get_adapter() -> BaseChatAdapter:
    adapter = getattr(app.state, "chat_adapter", None)
    if not adapter:
        raise HTTPException(status_code=503, detail="Advisor engine not Initialised")
    return adapter


def _get_mode() -> str:
    return getattr(app.state, "advisor_mode", "openai_single_assistant")


@router.get("/admin/agents-config")
async def get_agents_config(_: Dict[str, Any] = Depends(require_admin_user)) -> Dict[str, Any]:
    config = load_app_config()
    yaml_text = read_config_yaml()
    instruction_files = list_instruction_files(config)
    instructions = read_instruction_files(instruction_files)
    return {"yaml": yaml_text, "instructions": instructions}


@router.put("/admin/agents-config")
async def update_agents_config(
    payload: AgentsConfigUpdate,
    _: Dict[str, Any] = Depends(require_admin_user),
) -> Dict[str, Any]:
    try:
        parsed = yaml.safe_load(payload.yaml)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"YAML inválido: {exc}") from exc

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="La configuración debe ser un objeto YAML.")

    instructions_payload = payload.instructions or {}
    if instructions_payload:
        allowed_files = set(list_instruction_files(AppConfig(parsed)))
        for path in instructions_payload:
            if allowed_files and path not in allowed_files:
                raise HTTPException(
                    status_code=400,
                    detail=f"El archivo {path} no está referenciado en la configuración.",
                )
    try:
        if instructions_payload:
            write_instruction_files(instructions_payload)
        save_app_config(parsed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo guardar la configuración: {exc}") from exc

    await reset_agents_bundle()
    await get_agents_bundle(force_reload=True)

    config = load_app_config(force_reload=True)
    instruction_files = list_instruction_files(config)
    instructions = read_instruction_files(instruction_files)
    return {"yaml": read_config_yaml(), "instructions": instructions}


@router.post("/advisor/answer")
async def advisor_answer(request: Request, user: Dict[str, Any] = Depends(require_firebase_user)) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Invalid JSON payload: %s", exc)
        raise HTTPException(status_code=400, detail="Payload inválido") from exc

    query = (payload.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query es obligatorio")

    session_id = (
        payload.get("session_id")
        or payload.get("thread_id")
        or payload.get("conversation_id")
        or uuid.uuid4().hex
    )
    context = payload.get("context") or {}
    mode = _get_mode()
    adapter = _get_adapter()

    started = time.perf_counter()
    try:
        result = await adapter.generate(
            query,
            user_id=user.get("uid", ""),
            session_id=str(session_id),
            context=context,
        )
    except httpx.HTTPStatusError as exc:
        logger.error("MCP backend returned %s for mode=%s", exc.response.status_code, mode)
        raise HTTPException(status_code=502, detail="advisor_backend_error") from exc
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Advisor adapter failed in mode=%s: %s", mode, exc)
        raise HTTPException(status_code=502, detail="advisor_generation_error") from exc
    duration_ms = int((time.perf_counter() - started) * 1000)

    citations_payload = [c.model_dump(exclude_none=True) for c in result.citations]

    await insert_chat_turn_to_bigquery(
        session_id=str(session_id),
        uid=user.get("uid"),
        user_email=user.get("email"),
        user_verified=user.get("email_verified"),
        query=query,
        response_text=result.response_text,
        citations=citations_payload,
        mode=mode,
        endpoint_source="advisor",
    )

    logger.info(
        "advisor_answer_completed mode=%s duration_ms=%s",
        mode,
        duration_ms,
    )

    return {"answer": result.response_text, "citations": citations_payload}


@router.post("/chat_assistant")
async def chat_assistant_proxy(request: Request, user: Dict[str, Any] = Depends(require_firebase_user)) -> Dict[str, Any]:
    """Backward compatible endpoint used by the legacy frontend."""
    return await advisor_answer(request, user)


app.include_router(router)
