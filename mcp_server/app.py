"""FastMCP application exposing local tools over streamable HTTP."""

from __future__ import annotations

import logging

from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Server  # type: ignore

from .settings import settings
from .tools.formatters import format_answer
from .tools.lmstudio_chat import lmstudio_chat
from .tools.policy_check import policy_check

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

server = Server()

server.register_tool(lmstudio_chat)
server.register_tool(policy_check)
server.register_tool(format_answer)


@server.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "lmstudio_base_url": settings.lmstudio_base_url,
        "version": "0.1.0",
    }


@server.get("/info")
async def info():
    return {
        "tools": [tool.name for tool in server.tools],
        "max_completion_tokens": settings.max_completion_tokens,
    }


app = server.create_app()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def run() -> None:
    """Local entrypoint for running with uvicorn/uv in development."""
    import uvicorn

    uvicorn.run(
        "mcp_server.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    run()
