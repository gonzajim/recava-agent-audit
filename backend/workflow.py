"""Lightweight workflow executor for OpenAI agent networks."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from src.app_settings import get_settings_section

logger = logging.getLogger(__name__)
_advisor_settings = get_settings_section("advisor")
_default_responses_model = _advisor_settings.get("responses_model", "gpt-5-turbo")


class WorkflowExecutor:
    """Executes simple agent workflows exported from AgentBuilder."""

    def __init__(self, client, definition: Dict[str, Any]) -> None:
        self.client = client
        self.definition = definition or {}

    async def run(
        self,
        *,
        query: str,
        user_id: str,
        session_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        assistant_id = self._assistant_id_from_defn(default_env="OPENAI_ASSISTANT_ID_COMPOSER")
        metadata = {
            "user_id": user_id,
            "session_id": session_id,
            "mode": "openai_agent_network",
        }
        if context:
            metadata["context_keys"] = sorted(context.keys())

        payload = {
            "input": [{"role": "user", "content": query}],
            "metadata": metadata,
            "extra_headers": {"OpenAI-Beta": "assistants=v2"},
        }
        if assistant_id:
            payload["assistant_id"] = assistant_id
        else:
            payload["model"] = os.getenv("OPENAI_RESPONSES_MODEL") or _default_responses_model

        logger.debug("Workflow executor invoking assistant_id=%s", assistant_id)
        response = await self.client.responses.create(**payload)

        return {
            "response_text": getattr(response, "output_text", "") or "",
            "citations": [],
            "debug": {"workflow_entrypoint": self.definition.get("entrypoint")},
        }

    def _assistant_id_from_defn(self, default_env: str) -> Optional[str]:
        try:
            entrypoint = self.definition.get("entrypoint")
            nodes = self.definition.get("nodes") or {}
            if entrypoint and entrypoint in nodes:
                node_config = nodes[entrypoint].get("config") or {}
                env_key = node_config.get("assistant_id_env")
                if env_key:
                    return os.getenv(env_key)
        except Exception as exc:
            logger.debug("Failed parsing workflow definition: %s", exc)
        return os.getenv(default_env)


def load_workflow_definition() -> Dict[str, Any]:
    """Load workflow definition from env JSON or a YAML/JSON file."""

    workflow_json = os.getenv("WORKFLOW_JSON")
    if workflow_json:
        try:
            return json.loads(workflow_json)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid WORKFLOW_JSON payload: %s", exc)

    path = os.getenv("WORKFLOW_PATH")
    if path and os.path.exists(path):
        suffix = os.path.splitext(path)[1].lower()
        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore

                with open(path, "r", encoding="utf-8") as handle:
                    return yaml.safe_load(handle) or {}
            except ImportError as exc:
                logger.error("pyyaml not installed but workflow yaml requested: %s", exc)
            except Exception as exc:
                logger.error("Failed to load workflow yaml: %s", exc)
        else:
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception as exc:
                logger.error("Failed to load workflow json: %s", exc)

    logger.info("Using default workflow definition (composer passthrough).")
    return {
        "entrypoint": "composer",
        "nodes": {"composer": {"type": "assistant", "config": {}}},
        "edges": [],
    }
