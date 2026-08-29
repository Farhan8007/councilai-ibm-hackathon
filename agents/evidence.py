"""
Evidence Checker.

Usage
-----
    from agents.evidence import check_evidence

    report = check_evidence([security_result, architecture_result])

``check_evidence`` inspects every finding produced by each specialist agent
and classifies it as *supported* or *unsupported* according to a simple v1
rule:

    A finding is **supported** when:
      1. The finding string itself is non-empty (after stripping whitespace).
      2. The ``raw_output`` field of the agent that produced it is non-empty
         (after stripping whitespace).

    Otherwise the finding is **unsupported**.

Rationale: ``raw_output`` is the agent's own narrative explanation.  A finding
without any accompanying narrative has no evidence backing it; a finding whose
agent produced a narrative is considered evidenced.

The function is deterministic and requires no external services.
"""

from __future__ import annotations

import sys
import os

_backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from models import AgentResult, EvidenceReport  # noqa: E402


def check_evidence(results: list[AgentResult]) -> EvidenceReport:
    """Classify every finding across all agent results as supported or unsupported.

    Parameters
    ----------
    results:
        One :class:`~models.AgentResult` per specialist agent.  An empty list
        returns an :class:`~models.EvidenceReport` with both lists empty.

    Returns
    -------
    EvidenceReport
        ``supported_findings`` — findings backed by non-empty ``raw_output``.
        ``unsupported_findings`` — findings that are empty or whose agent
        produced no ``raw_output``.
    """
    supported: list[str] = []
    unsupported: list[str] = []

    for result in results:
        has_raw = bool(result.raw_output.strip())
        for finding in result.findings:
            if finding.strip() and has_raw:
                supported.append(finding)
            else:
                unsupported.append(finding)

    return EvidenceReport(
        supported_findings=supported,
        unsupported_findings=unsupported,
    )
