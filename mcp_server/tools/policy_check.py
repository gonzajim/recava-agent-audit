"""Policy evaluation tool exposed through MCP."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from ..fastmcp_compat import tool


class PolicyCheckInput(BaseModel):
    text: str = Field(description="Text to evaluate against the policy.")
    policy_name: str = Field(description="Identifier of the policy to check.")


class PolicyFinding(BaseModel):
    rule: str
    severity: str
    description: str


class PolicyCheckOutput(BaseModel):
    passed: bool
    findings: List[PolicyFinding] = Field(default_factory=list)


@tool(name="policy_check", description="Evaluate a text against a named compliance policy.")
async def policy_check(payload: PolicyCheckInput) -> PolicyCheckOutput:
    """Placeholder policy checker – replace with your domain logic."""
    # TODO: wire this to your actual policy evaluation logic.
    findings: List[PolicyFinding] = []

    if "riesgo" in payload.text.lower():
        findings.append(
            PolicyFinding(
                rule="RISK_ALERT",
                severity="medium",
                description="The term 'riesgo' indicates potential compliance concerns.",
            )
        )

    return PolicyCheckOutput(passed=not findings, findings=findings)
