import os
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import HTTPException

os.environ.setdefault("FIREBASE_AUTH_EMULATOR_HOST", "localhost:9099")

pytest.importorskip("pytest_httpx")
from pytest_httpx import HTTPXMock  # type: ignore

from backend import auth
from backend.bigquery_service import insert_chat_turn_to_bigquery
from backend.chat_generators import (
    OnPremMCPAdapter,
    OpenAIAgentNetworkAdapter,
    SingleAssistantAdapter,
)
from backend import main as advisor_main


class DummyResponses:
    async def create(self, **kwargs):  # type: ignore[override]
        self.kwargs = kwargs
        return SimpleNamespace(output_text="respuesta")


class DummyOpenAIClient:
    def __init__(self) -> None:
        self.responses = DummyResponses()


@pytest.mark.asyncio
async def test_single_assistant_adapter_invokes_responses() -> None:
    client = DummyOpenAIClient()
    adapter = SingleAssistantAdapter(
        client=client,
        assistant_id="asst_123",
        model="gpt-5-turbo",
    )
    result = await adapter.generate(
        "Hola",
        user_id="user-1",
        session_id="thread-1",
        context={"foo": "bar"},
    )

    assert result.response_text == "respuesta"
    assert client.responses.kwargs["metadata"]["mode"] == "openai_single_assistant"
    assert client.responses.kwargs["assistant_id"] == "asst_123"


@pytest.mark.asyncio
async def test_onprem_mcp_adapter_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://mcp.local/advisor/answer",
        json={"response_text": "respuesta MCP", "citations": [{"source": "doc"}]},
        status_code=200,
    )
    adapter = OnPremMCPAdapter(base_url="http://mcp.local", api_key="secret", timeout=5.0)
    result = await adapter.generate(
        "Pregunta",
        user_id="uid-123",
        session_id="sess-1",
        context={},
    )

    assert result.response_text == "respuesta MCP"
    assert result.citations[0].source == "doc"


@pytest.mark.asyncio
async def test_onprem_mcp_adapter_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="POST",
        url="http://mcp.local/advisor/answer",
        json={"detail": "error"},
        status_code=500,
    )
    adapter = OnPremMCPAdapter(base_url="http://mcp.local/", api_key="")
    with pytest.raises(httpx.HTTPStatusError):
        await adapter.generate("Pregunta", user_id="uid", session_id="sess", context={})


@pytest.mark.asyncio
async def test_agent_network_adapter_returns_payload() -> None:
    class DummyExecutor:
        async def run(self, **kwargs):  # type: ignore[override]
            return {"response_text": "network", "citations": [{"title": "T"}]}

    adapter = OpenAIAgentNetworkAdapter(executor=DummyExecutor())
    result = await adapter.generate("Q", user_id="uid", session_id="sess", context={})

    assert result.response_text == "network"
    assert result.citations[0].title == "T"


@pytest.mark.asyncio
async def test_build_adapter_openai_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ADVISOR_GENERATION_MODE", "openai_single_assistant")

    class FakeOpenAI(DummyOpenAIClient):
        def __init__(self, api_key: str) -> None:
            super().__init__()
            self.api_key = api_key

    monkeypatch.setattr("backend.main.AsyncOpenAI", FakeOpenAI)

    adapter, resources = await advisor_main._build_adapter()
    assert isinstance(adapter, SingleAssistantAdapter)
    assert resources["mode"] == "openai_single_assistant"


@pytest.mark.asyncio
async def test_build_adapter_onprem_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADVISOR_GENERATION_MODE", "onprem_mcp_server")
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp.local")
    monkeypatch.setenv("MCP_API_KEY", "secret")

    class FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

    monkeypatch.setattr("backend.main.httpx.AsyncClient", FakeAsyncClient)

    adapter, resources = await advisor_main._build_adapter()
    assert isinstance(adapter, OnPremMCPAdapter)
    assert resources["mode"] == "onprem_mcp_server"


@pytest.mark.asyncio
async def test_build_adapter_agent_network_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ADVISOR_GENERATION_MODE", "openai_agent_network")
    monkeypatch.setenv("WORKFLOW_JSON", '{"entrypoint":"composer","nodes":{}}')

    class FakeOpenAI(DummyOpenAIClient):
        def __init__(self, api_key: str) -> None:
            super().__init__()
            self.api_key = api_key

    monkeypatch.setattr("backend.main.AsyncOpenAI", FakeOpenAI)

    adapter, resources = await advisor_main._build_adapter()
    assert isinstance(adapter, OpenAIAgentNetworkAdapter)
    assert resources["mode"] == "openai_agent_network"


@pytest.mark.asyncio
async def test_bigquery_insert_includes_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    rows: List[Dict[str, Any]] = []

    class DatasetRef:
        def __init__(self, client: Any, dataset: str) -> None:
            self.client = client
            self.dataset = dataset

        def table(self, table_id: str) -> str:
            return f"{self.dataset}.{table_id}"

    class DummyClient:
        def dataset(self, dataset: str) -> DatasetRef:
            return DatasetRef(self, dataset)

        def insert_rows_json(self, table_ref: str, payload: List[Dict[str, Any]], ignore_unknown_values: bool = False):
            rows.extend(payload)
            self.table_ref = table_ref
            self.ignore_unknown_values = ignore_unknown_values
            return []

    async def immediate(func, *args, **kwargs):  # type: ignore[override]
        return func(*args, **kwargs)

    monkeypatch.setattr("backend.bigquery_service._bq_client", DummyClient())
    monkeypatch.setattr("backend.bigquery_service._DATASET", "dataset")
    monkeypatch.setattr("backend.bigquery_service._TABLE", "table")
    monkeypatch.setattr("backend.bigquery_service.run_in_threadpool", immediate)
    monkeypatch.setattr("backend.bigquery_service.DISABLE_BIGQUERY", False)

    await insert_chat_turn_to_bigquery(
        session_id="sess",
        uid="uid",
        user_email="user@example.com",
        user_verified=True,
        query="hola",
        response_text="respuesta",
        citations=[{"source": "doc"}],
        mode="openai_single_assistant",
        endpoint_source="advisor",
    )

    assert rows[0]["mode"] == "openai_single_assistant"
    assert rows[0]["citations"][0]["source"] == "doc"


@pytest.mark.asyncio
async def test_require_firebase_user_missing_header() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_firebase_user(None)  # type: ignore[arg-type]
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_firebase_user_unverified(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_verify(_: str) -> Dict[str, Any]:
        return {"uid": "123", "email": "user@example.com", "email_verified": False}

    monkeypatch.setattr("firebase_admin.auth.verify_id_token", fake_verify)

    with pytest.raises(HTTPException) as exc_info:
        await auth.require_firebase_user("Bearer token")
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_firebase_user_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_verify(_: str) -> Dict[str, Any]:
        return {"uid": "123", "email": "user@example.com", "email_verified": True}

    monkeypatch.setattr("firebase_admin.auth.verify_id_token", fake_verify)

    user = await auth.require_firebase_user("Bearer token")
    assert user["uid"] == "123"
