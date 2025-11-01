"""MCP tool that proxies chat completions to LM Studio."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..adapters.lmstudio_client import LMStudioClient, get_default_client
from ..fastmcp_compat import tool
from ..settings import settings

logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str = Field(description="Role of the message author (user/system/assistant).")
    content: str = Field(description="Plain text content of the message.")


class LMStudioChatInput(BaseModel):
    messages: List[ChatMessage] = Field(description="Conversation messages in OpenAI format.")
    system_prompt: Optional[str] = Field(
        default=None, description="Optional system prompt prepended to the conversation."
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(
        default=None,
        description="Optional max tokens override; defaults to MCP_MAX_COMPLETION_TOKENS.",
    )
    stream: bool = Field(default=False, description="Whether LM Studio should stream the response.")
    extra_params: Dict[str, Any] = Field(
        default_factory=dict, description="Extra parameters forwarded as-is to LM Studio."
    )


class LMStudioChatOutput(BaseModel):
    output_messages: List[ChatMessage]
    usage: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Dict[str, Any] = Field(default_factory=dict)


@tool(name="lmstudio_chat", description="Generate a response using the local LM Studio model.")
async def lmstudio_chat(payload: LMStudioChatInput) -> LMStudioChatOutput:
    client: LMStudioClient = await get_default_client()
    messages = payload.messages

    if payload.system_prompt:
        messages = [
            ChatMessage(role="system", content=payload.system_prompt),
            *messages,
        ]

    try:
        response = await client.chat_completion(
            [msg.dict() for msg in messages],
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            stream=payload.stream,
            extra_params=payload.extra_params,
        )
    finally:
        await client.close()

    choices = response.get("choices") or []
    assistant_messages = []
    for choice in choices:
        msg = (choice or {}).get("message") or {}
        if msg.get("content"):
            assistant_messages.append(ChatMessage(role=msg.get("role", "assistant"), content=msg["content"]))

    usage = response.get("usage") or {}

    return LMStudioChatOutput(
        output_messages=assistant_messages,
        usage=usage,
        raw_response=response,
    )
