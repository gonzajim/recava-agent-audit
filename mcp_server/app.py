"""FastMCP application exposing local tools over streamable HTTP."""

from __future__ import annotations

import logging

from fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .settings import settings
from .tools.formatters import format_answer
from .tools.lmstudio_chat import lmstudio_chat
from .tools.policy_check import policy_check

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

server = FastMCP(name="recava-mcp-server")

server.add_tool(lmstudio_chat)
server.add_tool(policy_check)
server.add_tool(format_answer)


@server.custom_route("/healthz", methods=["GET"], name="healthz")
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "lmstudio_base_url": settings.lmstudio_base_url,
            "version": "0.1.0",
        }
    )


@server.custom_route("/info", methods=["GET"], name="info")
async def info(_: Request) -> JSONResponse:
    tools = await server.get_tools()
    return JSONResponse(
        {
            "tools": sorted(tools.keys()),
            "max_completion_tokens": settings.max_completion_tokens,
        }
    )


app = server.http_app()

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
