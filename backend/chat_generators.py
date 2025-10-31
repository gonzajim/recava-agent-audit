"""Chat generation strategy adapters for the advisor workflow."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from agents import Agent, Runner, RunConfig, TResponseInputItem  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class ChatGenerationContext:
    """Context shared with chat generation adapters."""

    user_question: str
    conversation_history: List[TResponseInputItem]
    run_config: RunConfig
    thread_id: Optional[str] = None


@dataclass
class ChatResult:
    """Output from a chat generation adapter."""

    text: str
    citations: List[Dict[str, Any]] = field(default_factory=list)
    new_items: List[Any] = field(default_factory=list)


class ChatGenerationError(Exception):
    """Raised when the chat generator fails to produce a response."""


class ChatAdapter(ABC):
    """Strategy interface for different chat generation backends."""

    @abstractmethod
    async def generate(self, context: ChatGenerationContext) -> ChatResult:
        """Generate a response for the given context."""


class OpenAIAdapter(ChatAdapter):
    """Adapter that keeps using the existing Agents SDK runner."""

    def __init__(self, agent: Agent):
        self._agent = agent

    async def generate(self, context: ChatGenerationContext) -> ChatResult:
        try:
            temp = await Runner.run(
                self._agent,
                input=[*context.conversation_history],
                run_config=context.run_config,
            )
        except Exception as exc:
            logger.exception("OpenAI adapter failed to generate response")
            raise ChatGenerationError("openai_generation_failed") from exc

        try:
            output_text = temp.final_output_as(str)
        except Exception as exc:
            logger.exception("OpenAI adapter failed to extract final output")
            raise ChatGenerationError("openai_output_parsing_failed") from exc

        return ChatResult(text=output_text, citations=[], new_items=list(temp.new_items))


class MCPAdapter(ChatAdapter):
    """Adapter that calls the on-premise MCP Server over HTTP."""

    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def generate(self, context: ChatGenerationContext) -> ChatResult:
        payload = {
            "user_query": context.user_question,
            "thread_id": context.thread_id,
        }
        try:
            response = await self._client.post("", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.warning("Timeout contacting MCP server", exc_info=True)
            raise ChatGenerationError("mcp_timeout") from exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "MCP server returned error status %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            raise ChatGenerationError(f"mcp_http_{exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            logger.error("HTTP error contacting MCP server: %s", exc, exc_info=True)
            raise ChatGenerationError("mcp_http_error") from exc

        try:
            data = response.json()
        except ValueError as exc:
            logger.error("Failed to decode MCP response JSON: %s", response.text)
            raise ChatGenerationError("mcp_invalid_json") from exc

        text = (data.get("response_text") or "").strip()
        citations = data.get("citations") or []
        if not isinstance(citations, list):
            logger.warning("MCP citations payload is not a list; dropping value")
            citations = []

        return ChatResult(text=text, citations=citations, new_items=[])

