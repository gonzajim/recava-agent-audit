"""Lightweight tests for MCP adapter behaviour."""

from typing import Any, Dict

import httpx
import pytest

pytest.importorskip("pytest_httpx")
from pytest_httpx import HTTPXMock  # type: ignore

from backend.chat_generators import (
    ChatGenerationContext,
    ChatGenerationError,
    MCPAdapter,
)


class DummyRunConfig:
    """Minimal stub to satisfy ChatGenerationContext."""

    pass


@pytest.mark.asyncio
async def test_mcp_adapter_success(httpx_mock: HTTPXMock):
    response_payload: Dict[str, Any] = {
        "response_text": "Hola mundo",
        "citations": [{"url": "https://example.com"}],
    }
    httpx_mock.add_response(method="POST", json=response_payload, status_code=200)

    async with httpx.AsyncClient(base_url="http://fake-mcp") as client:
        adapter = MCPAdapter(client=client)
        ctx = ChatGenerationContext(
            user_question="¿Qué es la sostenibilidad?",
            conversation_history=[],
            run_config=DummyRunConfig(),  # not used by MCP adapter
            thread_id="thread-123",
        )
        result = await adapter.generate(ctx)
        assert result.text == "Hola mundo"
        assert result.citations == response_payload["citations"]


@pytest.mark.asyncio
async def test_mcp_adapter_timeout(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ReadTimeout("Timeout"))

    async with httpx.AsyncClient(base_url="http://fake-mcp") as client:
        adapter = MCPAdapter(client=client)
        ctx = ChatGenerationContext(
            user_question="Pregunta",
            conversation_history=[],
            run_config=DummyRunConfig(),
            thread_id="thread-456",
        )
        with pytest.raises(ChatGenerationError):
            await adapter.generate(ctx)
