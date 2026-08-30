"""
Pydantic models for the CouncilAI API.

Organised into three layers:
  1. Request / response envelopes used by the HTTP routes.
  2. Agent-result types that each specialist agent will populate.
  3. Pipeline-stage types for Conflict Detector, Evidence Checker, Final Judge.

Layers 2 and 3 are defined as stubs now so that later tasks can fill in
fields without changing import paths or breaking the existing routes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class Verdict(str, Enum):
    """Top-level pipeline decision."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    PENDING = "PENDING"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class AgentRole(str, Enum):
    """Which specialist produced a result."""

    SECURITY = "security"
    ARCHITECTURE = "architecture"
    TESTING = "testing"
    PERFORMANCE = "performance"


# ---------------------------------------------------------------------------
# Layer 1 — HTTP request / response
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    """Payload sent by the client to trigger a code review."""

    diff: str = Field(..., description="Unified diff or raw code change to review.")
    context: str | None = Field(
        default=None,
        description="Optional surrounding context (e.g. PR description, file names).",
    )


class HealthResponse(BaseModel):
    status: str = "ok"


class ReviewResponse(BaseModel):
    """Envelope returned to the client after the full pipeline runs."""

    request_id: str
    verdict: Verdict
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layer 2 — Specialist agent results (stubs for later tasks)
# ---------------------------------------------------------------------------


class AgentResult(BaseModel):
    """Base class for results produced by a specialist agent."""

    role: AgentRole
    passed: bool
    findings: list[str] = Field(default_factory=list)
    raw_output: str = ""


# ---------------------------------------------------------------------------
# Layer 3 — Pipeline stage types (stubs for later tasks)
# ---------------------------------------------------------------------------


class ConflictReport(BaseModel):
    """Output of the Conflict Detector stage."""

    conflicts: list[str] = Field(default_factory=list)
    has_conflicts: bool = False


class EvidenceReport(BaseModel):
    """Output of the Evidence Checker stage."""

    supported_findings: list[str] = Field(default_factory=list)
    unsupported_findings: list[str] = Field(default_factory=list)


class JudgeDecision(BaseModel):
    """Output of the Final Judge stage."""

    verdict: Verdict
    rationale: str
