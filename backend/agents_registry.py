"""Agent registry for advisor workflow."""

import os
from typing import Tuple

from agents import Agent  # type: ignore

VECTOR_STORE_ID = os.getenv("OPENAI_VECTOR_STORE_ID")


def _bind_vector_store(agent: Agent) -> Agent:
    """Attach the OpenAI vector store to the agent if supported by the SDK."""
    if VECTOR_STORE_ID and hasattr(agent, "with_vector_store"):
        try:
            return agent.with_vector_store(VECTOR_STORE_ID)
        except Exception:
            # SDK does not support fluent helper; fall back silently.
            pass
    if VECTOR_STORE_ID and hasattr(agent, "vector_store_id"):
        setattr(agent, "vector_store_id", VECTOR_STORE_ID)
    return agent


def get_agents() -> Tuple[Agent, Agent, Agent, Agent, Agent, Agent, Agent]:
    """Return the agent instances required by the workflow.

    Replace the placeholder constructors with concrete agent loading logic.
    """
    asistente_inicial = _bind_vector_store(Agent(name="asistente_inicial"))
    a1_estructura = Agent(name="a1_estructura")
    a2_precision = Agent(name="a2_precision")
    a3_enfoque = Agent(name="a3_enfoque")
    a4_referencias = _bind_vector_store(Agent(name="a4_referencias"))
    a5_temporal = Agent(name="a5_temporal")
    agent_sintesis = _bind_vector_store(Agent(name="agent_sintesis"))
    return (
        asistente_inicial,
        a1_estructura,
        a2_precision,
        a3_enfoque,
        a4_referencias,
        a5_temporal,
        agent_sintesis,
    )
