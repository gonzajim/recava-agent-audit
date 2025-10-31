"""FastAPI entrypoint for RecavAI advisor mode."""

from contextlib import asynccontextmanager
import os
from typing import Any, Dict, Tuple

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .adapters import to_legacy_contract
from .agents_registry import get_agents
from .chat_generators import ChatAdapter, ChatGenerationError, MCPAdapter, OpenAIAdapter
from .schemas import AdvisorRequest, AdvisorResponse
from .workflow import WorkflowInput, run_workflow

app_state: Dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    agents = get_agents()
    app_state["agents"] = agents

    chat_adapters: Dict[str, ChatAdapter] = {
        "openai": OpenAIAdapter(agent=agents[0]),
    }

    mcp_client: httpx.AsyncClient | None = None
    mcp_url = os.getenv("MCP_SERVER_URL")
    mcp_api_key = os.getenv("MCP_API_KEY")
    if mcp_url and mcp_api_key:
        timeout = float(os.getenv("MCP_TIMEOUT_SECS", "20"))
        mcp_client = httpx.AsyncClient(
            base_url=mcp_url,
            timeout=httpx.Timeout(connect=5.0, read=timeout),
            headers={"X-API-Key": mcp_api_key},
        )
        chat_adapters["mcp"] = MCPAdapter(client=mcp_client)

    app_state["chat_adapters"] = chat_adapters

    try:
        yield
    finally:
        if mcp_client:
            await mcp_client.aclose()


app = FastAPI(title="RecavAI Advisor API", lifespan=lifespan)

# Adjust CORS origins to your Firebase Hosting domains in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/advisor/answer", response_model=AdvisorResponse)
async def advisor_answer(
    payload: AdvisorRequest,
    chat_adapter: ChatAdapter = Depends(_get_chat_adapter),
    agents: Tuple = Depends(_get_agents),
):
    try:
        wf_in = WorkflowInput(input_as_text=payload.question)
        wf_out = await run_workflow(wf_in, *agents, chat_adapter=chat_adapter)
        return AdvisorResponse(
            status="ok",
            answer=wf_out.get("respuesta_final", ""),
            citations=wf_out.get("citas", []),
            meta={
                "evaluations": wf_out.get("evaluaciones", []),
                "draft": wf_out.get("asistente_inicial", {}).get("output_text", ""),
            },
        )
    except ChatGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"advisor_generation_error: {exc}") from exc
    except Exception as exc:  # log appropriately in real deployment
        raise HTTPException(status_code=500, detail=f"advisor_error: {exc}") from exc


@app.post("/chat_assistant")
async def legacy_contract(
    payload: AdvisorRequest,
    chat_adapter: ChatAdapter = Depends(_get_chat_adapter),
    agents: Tuple = Depends(_get_agents),
):
    wf_in = WorkflowInput(input_as_text=payload.question)
    wf_out = await run_workflow(wf_in, *agents, chat_adapter=chat_adapter)
    return to_legacy_contract(wf_out)


def _get_chat_adapter() -> ChatAdapter:
    adapters = app_state.get("chat_adapters") or {}
    generator_name = os.getenv("CHAT_GENERATOR", "openai").strip().lower() or "openai"
    adapter = adapters.get(generator_name)
    if adapter:
        return adapter
    fallback = adapters.get("openai")
    if fallback:
        return fallback
    raise HTTPException(status_code=500, detail=f"Chat generator '{generator_name}' not configured")


def _get_agents():
    agents = app_state.get("agents")
    if not agents:
        raise HTTPException(status_code=500, detail="Agents not initialized")
    return agents
