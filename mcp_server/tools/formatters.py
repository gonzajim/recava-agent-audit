"""Formatting utilities exposed as MCP tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..fastmcp_compat import tool


class FormatInput(BaseModel):
    draft: str = Field(description="Input draft text to format.")
    style: Literal["formal", "executive", "bullet"] = Field(default="formal")


class FormatOutput(BaseModel):
    final: str


@tool(name="format_answer", description="Apply presentation formatting to a draft answer.")
async def format_answer(payload: FormatInput) -> FormatOutput:
    draft = payload.draft.strip()

    if payload.style == "executive":
        final = f"Resumen Ejecutivo:\n\n{draft}"
    elif payload.style == "bullet":
        bullet_lines = [f"- {line.strip()}" for line in draft.splitlines() if line.strip()]
        final = "\n".join(bullet_lines)
    else:
        final = draft

    return FormatOutput(final=final)
