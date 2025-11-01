from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from agents import Agent, FileSearchTool, ModelSettings  # type: ignore
from openai import AsyncOpenAI
from pydantic import BaseModel
from types import SimpleNamespace

from .config_loader import AppConfig, load_app_config


class A1EstructuraSchema(BaseModel):
    veredicto: str
    mejoras: str


class A2PrecisionSchema(BaseModel):
    veredicto: str
    mejoras: str


class A3EnfoqueSchema(BaseModel):
    veredicto: str
    mejoras: str


class A4ReferenciasSchema(BaseModel):
    veredicto: str
    mejoras: str


class A5TemporalSchema(BaseModel):
    veredicto: str
    mejoras: str


_SCHEMA_MAP = {
    "A1EstructuraSchema": A1EstructuraSchema,
    "A2PrecisionSchema": A2PrecisionSchema,
    "A3EnfoqueSchema": A3EnfoqueSchema,
    "A4ReferenciasSchema": A4ReferenciasSchema,
    "A5TemporalSchema": A5TemporalSchema,
}


@dataclass
class AgentsBundle:
    client: AsyncOpenAI
    file_search: FileSearchTool
    guardrails_ctx: Any
    asistente_inicial: Agent
    a1_estructura: Agent
    a2_precision: Agent
    a3_enfoque: Agent
    a4_referencias: Agent
    a5_temporal: Agent
    agente_final: Agent


def _build_model_settings(cfg: Dict[str, Any]) -> ModelSettings:
    kwargs = {
        "temperature": cfg.get("temperature"),
        "top_p": cfg.get("top_p"),
        "max_tokens": cfg.get("max_tokens"),
        "store": cfg.get("store", True),
    }
    kwargs = {key: value for key, value in kwargs.items() if value is not None}
    if "reasoning" in cfg and isinstance(cfg["reasoning"], dict):
        from openai.types.shared.reasoning import Reasoning

        kwargs["reasoning"] = Reasoning(**cfg["reasoning"])
    return ModelSettings(**kwargs)


def _build_agent(name: str, cfg: Dict[str, Any], file_search: FileSearchTool) -> Agent:
    model_settings = _build_model_settings(cfg)
    agent_kwargs: Dict[str, Any] = {
        "name": name,
        "instructions": cfg.get("instructions", ""),
        "model": cfg.get("model"),
        "tools": [file_search],
        "model_settings": model_settings,
    }
    schema_name = cfg.get("output_schema")
    if schema_name and schema_name in _SCHEMA_MAP:
        agent_kwargs["output_type"] = _SCHEMA_MAP[schema_name]
    return Agent(**agent_kwargs)


def _build_agents(app_cfg: AppConfig) -> AgentsBundle:
    client = AsyncOpenAI()
    file_search = FileSearchTool(vector_store_ids=app_cfg.vector_store_ids)
    guardrails_cfg = app_cfg.guardrails
    guardrails_ctx = SimpleNamespace(guardrail_llm=client, guardrails_config=guardrails_cfg)

    inicial = app_cfg.agent_cfg("inicial")
    a1_cfg = app_cfg.agent_cfg("a1")
    a2_cfg = app_cfg.agent_cfg("a2")
    a3_cfg = app_cfg.agent_cfg("a3")
    a4_cfg = app_cfg.agent_cfg("a4")
    a5_cfg = app_cfg.agent_cfg("a5")
    final_cfg = app_cfg.agent_cfg("final")

    return AgentsBundle(
        client=client,
        file_search=file_search,
        guardrails_ctx=guardrails_ctx,
        asistente_inicial=_build_agent(inicial["name"], inicial, file_search),
        a1_estructura=_build_agent(a1_cfg["name"], a1_cfg, file_search),
        a2_precision=_build_agent(a2_cfg["name"], a2_cfg, file_search),
        a3_enfoque=_build_agent(a3_cfg["name"], a3_cfg, file_search),
        a4_referencias=_build_agent(a4_cfg["name"], a4_cfg, file_search),
        a5_temporal=_build_agent(a5_cfg["name"], a5_cfg, file_search),
        agente_final=_build_agent(final_cfg["name"], final_cfg, file_search),
    )


_BUNDLE_CACHE: Optional[AgentsBundle] = None
_BUNDLE_LOCK: Optional[asyncio.Lock] = None


def _get_bundle_lock() -> asyncio.Lock:
    global _BUNDLE_LOCK  # pylint: disable=global-statement
    if _BUNDLE_LOCK is None:
        _BUNDLE_LOCK = asyncio.Lock()
    return _BUNDLE_LOCK


async def reset_agents_bundle() -> None:
    global _BUNDLE_CACHE  # pylint: disable=global-statement
    lock = _get_bundle_lock()
    async with lock:
        bundle = _BUNDLE_CACHE
        _BUNDLE_CACHE = None
        if bundle is not None:
            close_fn = getattr(bundle.client, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:  # pragma: no cover - defensive
                    pass
            aclose_fn = getattr(bundle.client, "aclose", None)
            if callable(aclose_fn):
                try:
                    await aclose_fn()
                except Exception:  # pragma: no cover - defensive
                    pass


async def get_agents_bundle(force_reload: bool = False) -> AgentsBundle:
    global _BUNDLE_CACHE  # pylint: disable=global-statement
    lock = _get_bundle_lock()
    async with lock:
        if force_reload or _BUNDLE_CACHE is None:
            app_cfg = load_app_config(force_reload=force_reload)
            _BUNDLE_CACHE = _build_agents(app_cfg)
        return _BUNDLE_CACHE
