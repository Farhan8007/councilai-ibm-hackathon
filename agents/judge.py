"""
Final Judge.

Usage
-----
    from agents.judge import judge

    decision = judge(results, conflict_report, evidence_report)

Decision rule (deterministic, no external services required):

    REJECT  — at least one specialist agent *failed* AND at least one of that
              agent's findings appears in ``evidence_report.supported_findings``.
    APPROVE — every failing agent's findings are entirely unsupported (or there
              are no failing agents at all).

Conflicts are contextual information only.  The presence of a ConflictReport
with ``has_conflicts=True`` does NOT by itself cause rejection; it is included
in the rationale for human review.
"""

from __future__ import annotations

import sys
import os

_backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from models import (  # noqa: E402
    AgentResult,
    ConflictReport,
    EvidenceReport,
    JudgeDecision,
    Verdict,
)


def judge(
    results: list[AgentResult],
    conflict_report: ConflictReport,
    evidence_report: EvidenceReport,
) -> JudgeDecision:
    """Apply the Final Judge decision rule and return a :class:`~models.JudgeDecision`.

    Parameters
    ----------
    results:
        One :class:`~models.AgentResult` per specialist agent.
    conflict_report:
        Output of the Conflict Detector stage.  Used for rationale only.
    evidence_report:
        Output of the Evidence Checker stage.  Determines whether failing
        findings are backed by evidence and therefore cause rejection.

    Returns
    -------
    JudgeDecision
        ``verdict`` is ``REJECT`` when any failing agent has at least one
        supported finding; ``APPROVE`` otherwise.
        ``rationale`` describes which agents failed, which findings were
        supported/unsupported, and whether conflicts were detected.
    """
    supported_set: set[str] = set(evidence_report.supported_findings)

    # Collect failing agents and split their findings by evidence status.
    reject_triggers: list[str] = []   # supported findings from failing agents
    unsupported_blocks: list[str] = []  # unsupported findings from failing agents

    for result in results:
        if result.passed:
            continue
        for finding in result.findings:
            if finding in supported_set:
                reject_triggers.append(f"[{result.role.value}] {finding}")
            else:
                unsupported_blocks.append(f"[{result.role.value}] {finding}")

    verdict = Verdict.REJECT if reject_triggers else Verdict.APPROVE

    # Build a structured rationale.
    parts: list[str] = []

    if verdict == Verdict.REJECT:
        parts.append(
            f"REJECT: {len(reject_triggers)} supported finding(s) from failing agent(s)."
        )
        for item in reject_triggers:
            parts.append(f"  • {item}")
    else:
        parts.append("APPROVE: no supported findings from failing agents.")

    if unsupported_blocks:
        parts.append(
            f"Unsupported finding(s) not counted toward rejection ({len(unsupported_blocks)}):"
        )
        for item in unsupported_blocks:
            parts.append(f"  – {item}")

    if conflict_report.has_conflicts:
        parts.append(
            f"Conflict note ({len(conflict_report.conflicts)} disagreement(s) detected — "
            "contextual only, does not affect verdict):"
        )
        for conflict in conflict_report.conflicts:
            parts.append(f"  ↔ {conflict}")
    else:
        parts.append("No inter-agent conflicts detected.")

    return JudgeDecision(verdict=verdict, rationale="\n".join(parts))
