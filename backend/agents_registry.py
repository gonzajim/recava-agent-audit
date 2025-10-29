"""Agent registry for advisor workflow."""

from typing import Tuple

from agents import Agent  # type: ignore


def get_agents() -> Tuple[Agent, Agent, Agent, Agent, Agent, Agent, Agent]:
    """Return the agent instances required by the workflow.

    Replace the placeholder constructors with concrete agent loading logic.
    """
    asistente_inicial = Agent(name="asistente_inicial")
    a1_estructura = Agent(name="a1_estructura")
    a2_precision = Agent(name="a2_precision")
    a3_enfoque = Agent(name="a3_enfoque")
    a4_referencias = Agent(name="a4_referencias")
    a5_temporal = Agent(name="a5_temporal")
    agent_sintesis = Agent(name="agent_sintesis")
    return (
        asistente_inicial,
        a1_estructura,
        a2_precision,
        a3_enfoque,
        a4_referencias,
        a5_temporal,
        agent_sintesis,
    )

