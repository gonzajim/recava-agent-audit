"""Async client wrapper for interacting with LM Studio's OpenAI-compatible API."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from ..settings import settings

logger = logging.getLogger(__name__)


class LMStudioClient:
    """Thin async wrapper that targets LM Studio's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        *,
        base_url: str = settings.lmstudio_base_url,
        api_key: Optional[str] = settings.lmstudio_api_key,
        timeout: float = settings.request_timeout_secs,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(connect=5.0, read=timeout),
            headers={"Authorization": f"Bearer {api_key}"} if api_key else None,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        payload.update(extra_params or {})
        payload["model"] = model or settings.lmstudio_model or "gpt-4o-mini"
        payload["max_tokens"] = max_tokens or settings.max_completion_tokens

        try:
            response = await self._client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("LM Studio request failed: %s", exc, exc_info=True)
            raise

        return response.json()


async def get_default_client() -> LMStudioClient:
    """Factory helper to build a default client instance."""
    return LMStudioClient()
