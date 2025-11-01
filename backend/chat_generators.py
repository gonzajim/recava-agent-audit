"""Chat generation adapters supporting multiple advisor strategies."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Citation(BaseModel):
    """Citation payload returned to the frontend."""

    title: Optional[str] = None
    source: Optional[str] = None
    chunk_ids: Optional[List[str]] = None
    meta: Optional[Dict[str, Any]] = None


class ChatResult(BaseModel):
    """Response produced by an advisor adapter."""

    response_text: str
    citations: List[Citation] = Field(default_factory=list)
    debug: Optional[Dict[str, Any]] = None


class BaseChatAdapter(ABC):
    """Interface for advisor response generators."""

    @abstractmethod
    async def generate(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context: Dict[str, Any],
    ) -> ChatResult:
        """Return the assistant answer for the given query."""

    async def aclose(self) -> None:
        """Optional hook for releasing adapter resources."""
        return None


class SingleAssistantAdapter(BaseChatAdapter):
    """Adapter backed by a single OpenAI Assistant / Responses invocation."""

    def __init__(
        self,
        client,
        assistant_id: Optional[str] = None,
        model: str = "gpt-5-turbo",
        temperature: float = 0.2,
    ) -> None:
        self.client = client
        self.assistant_id = assistant_id
        self.model = model
        self.temperature = temperature

    async def generate(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context: Dict[str, Any],
    ) -> ChatResult:
        metadata = {
            "user_id": user_id,
            "session_id": session_id,
            "mode": "openai_single_assistant",
        }
        if context:
            metadata["context_keys"] = sorted(context.keys())

        payload = {
            "input": [{"role": "user", "content": query}],
            "metadata": metadata,
            "temperature": self.temperature,
            "extra_headers": {"OpenAI-Beta": "assistants=v2"},
        }

        if self.assistant_id:
            payload["assistant_id"] = self.assistant_id
        else:
            payload["model"] = self.model

        logger.debug("Invoking single assistant with metadata=%s", metadata)
        response = await self.client.responses.create(**payload)

        return ChatResult(response_text=getattr(response, "output_text", "") or "", citations=[])


class OnPremMCPAdapter(BaseChatAdapter):
    """Adapter that proxies advisor requests to the on-prem MCP server."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 60.0,
    ) -> None:
        endpoint = base_url.rstrip("/")
        if endpoint.endswith("/advisor/answer"):
            self._endpoint = endpoint
        else:
            self._endpoint = f"{endpoint}/advisor/answer"

        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self.api_key = api_key

    async def generate(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context: Dict[str, Any],
    ) -> ChatResult:
        payload = {
            "query": query,
            "user_id": user_id,
            "session_id": session_id,
            "context": context,
        }
        headers = {"x-api-key": self.api_key} if self.api_key else {}

        logger.debug("Forwarding advisor request to MCP endpoint %s", self._endpoint)
        response = await self.client.post(self._endpoint, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        citations = data.get("citations") or []
        if not isinstance(citations, list):
            logger.warning("Unexpected citations payload from MCP: %s", type(citations))
            citations = []

        return ChatResult(
            response_text=data.get("response_text", "") or "",
            citations=[Citation(**item) for item in citations if isinstance(item, dict)],
            debug=data.get("debug"),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


class OpenAIAgentNetworkAdapter(BaseChatAdapter):
    """Adapter that executes a workflow defined via AgentBuilder export."""

    def __init__(self, executor: "WorkflowExecutor") -> None:
        self.executor = executor

    async def generate(
        self,
        query: str,
        *,
        user_id: str,
        session_id: str,
        context: Dict[str, Any],
    ) -> ChatResult:
        result = await self.executor.run(
            query=query,
            user_id=user_id,
            session_id=session_id,
            context=context,
        )
        citations = result.get("citations") or []
        if not isinstance(citations, list):
            logger.warning("Workflow executor returned non-list citations")
            citations = []

        return ChatResult(
            response_text=result.get("response_text", "") or "",
            citations=[Citation(**item) for item in citations if isinstance(item, dict)],
            debug=result.get("debug"),
        )
