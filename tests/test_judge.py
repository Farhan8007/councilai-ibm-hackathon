"""
Tests for the Final Judge.

Run from the repo root:
    pytest tests/test_judge.py -v

No watsonx credentials or external services required.
"""

from __future__ import annotations

import sys
import os

# Ensure both agents/ and backend/ are on sys.path.
_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "agents"))
sys.path.insert(0, os.path.join(_root, "backend"))

from models import (  # noqa: E402
    AgentRole,
    AgentResult,
    ConflictReport,
    EvidenceReport,
    JudgeDecision,
    Verdict,
)
from judge import judge  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(
    role: AgentRole = AgentRole.SECURITY,
    passed: bool = True,
    findings: list[str] | None = None,
    raw_output: str = "",
) -> AgentResult:
    return AgentResult(
        role=role,
        passed=passed,
        findings=findings or [],
        raw_output=raw_output,
    )


def _no_conflict() -> ConflictReport:
    return ConflictReport(conflicts=[], has_conflicts=False)


def _conflict(messages: list[str] | None = None) -> ConflictReport:
    msgs = messages or ["security passed but testing failed — agents disagree."]
    return ConflictReport(conflicts=msgs, has_conflicts=True)


def _evidence(
    supported: list[str] | None = None,
    unsupported: list[str] | None = None,
) -> EvidenceReport:
    return EvidenceReport(
        supported_findings=supported or [],
        unsupported_findings=unsupported or [],
    )


# ---------------------------------------------------------------------------
# Return-type contract
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_judge_decision(self):
        decision = judge([], _no_conflict(), _evidence())
        assert isinstance(decision, JudgeDecision)

    def test_verdict_is_verdict_enum(self):
        decision = judge([], _no_conflict(), _evidence())
        assert isinstance(decision.verdict, Verdict)

    def test_rationale_is_string(self):
        decision = judge([], _no_conflict(), _evidence())
        assert isinstance(decision.rationale, str)


# ---------------------------------------------------------------------------
# APPROVE cases
# ---------------------------------------------------------------------------

class TestApprove:
    def test_all_agents_pass(self):
        results = [
            _result(AgentRole.SECURITY, passed=True),
            _result(AgentRole.ARCHITECTURE, passed=True),
            _result(AgentRole.TESTING, passed=True),
        ]
        decision = judge(results, _no_conflict(), _evidence())
        assert decision.verdict == Verdict.APPROVE

    def test_empty_results_approves(self):
        decision = judge([], _no_conflict(), _evidence())
        assert decision.verdict == Verdict.APPROVE

    def test_failing_agent_only_unsupported_findings_approves(self):
        finding = "minor note"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[], unsupported=[finding])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_failing_agent_no_findings_approves(self):
        # Agent failed but emitted no findings — nothing to support or reject on.
        results = [_result(AgentRole.TESTING, passed=False, findings=[])]
        decision = judge(results, _no_conflict(), _evidence())
        assert decision.verdict == Verdict.APPROVE

    def test_rationale_mentions_approve(self):
        decision = judge([], _no_conflict(), _evidence())
        assert "APPROVE" in decision.rationale

    def test_all_unsupported_across_multiple_failing_agents(self):
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=["sec finding"]),
            _result(AgentRole.ARCHITECTURE, passed=False, findings=["arch finding"]),
        ]
        ev = _evidence(unsupported=["sec finding", "arch finding"])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE


# ---------------------------------------------------------------------------
# REJECT cases
# ---------------------------------------------------------------------------

class TestReject:
    def test_single_supported_finding_rejects(self):
        finding = "hard-coded password detected"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[finding])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_rationale_mentions_reject(self):
        finding = "hard-coded password detected"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[finding])
        decision = judge(results, _no_conflict(), ev)
        assert "REJECT" in decision.rationale

    def test_rationale_mentions_finding(self):
        finding = "dangerous eval() call"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[finding])
        decision = judge(results, _no_conflict(), ev)
        assert finding in decision.rationale

    def test_multiple_supported_findings_rejects(self):
        findings = ["finding A", "finding B", "finding C"]
        results = [_result(AgentRole.ARCHITECTURE, passed=False, findings=findings)]
        ev = _evidence(supported=findings)
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_multiple_agents_one_supported_finding_rejects(self):
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=["sec issue"]),
            _result(AgentRole.TESTING, passed=False, findings=["test issue"]),
        ]
        # Only the security finding is supported.
        ev = _evidence(supported=["sec issue"], unsupported=["test issue"])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_rationale_counts_supported_findings(self):
        findings = ["issue 1", "issue 2"]
        results = [_result(AgentRole.SECURITY, passed=False, findings=findings)]
        ev = _evidence(supported=findings)
        decision = judge(results, _no_conflict(), ev)
        assert "2" in decision.rationale  # count appears in rationale


# ---------------------------------------------------------------------------
# Supported vs unsupported findings
# ---------------------------------------------------------------------------

class TestSupportedVsUnsupported:
    def test_only_supported_findings_from_failing_agents_trigger_reject(self):
        # Two findings: one supported, one not — still REJECT because one is supported.
        results = [
            _result(
                AgentRole.SECURITY,
                passed=False,
                findings=["supported finding", "unsupported finding"],
            )
        ]
        ev = _evidence(
            supported=["supported finding"],
            unsupported=["unsupported finding"],
        )
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_supported_finding_from_passing_agent_does_not_reject(self):
        # A *passing* agent with a finding in supported_findings should not reject.
        finding = "informational note"
        results = [_result(AgentRole.SECURITY, passed=True, findings=[finding])]
        ev = _evidence(supported=[finding])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_rationale_lists_unsupported_separately(self):
        results = [
            _result(
                AgentRole.SECURITY,
                passed=False,
                findings=["supported issue", "unsupported issue"],
            )
        ]
        ev = _evidence(
            supported=["supported issue"],
            unsupported=["unsupported issue"],
        )
        decision = judge(results, _no_conflict(), ev)
        # Both findings should appear in the rationale.
        assert "supported issue" in decision.rationale
        assert "unsupported issue" in decision.rationale

    def test_finding_not_in_evidence_report_is_treated_as_unsupported(self):
        # A finding that appears in neither list of EvidenceReport is not in
        # supported_set, so it does not trigger rejection.
        finding = "mystery finding"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[], unsupported=[])  # finding absent from both lists
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE


# ---------------------------------------------------------------------------
# Conflict is contextual — does NOT cause rejection on its own
# ---------------------------------------------------------------------------

class TestConflictContextual:
    def test_conflict_without_supported_findings_approves(self):
        # Agents disagree but no failing agent has supported findings.
        results = [
            _result(AgentRole.SECURITY, passed=True),
            _result(AgentRole.TESTING, passed=False, findings=["unsupported finding"]),
        ]
        ev = _evidence(unsupported=["unsupported finding"])
        decision = judge(results, _conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_conflict_mentioned_in_rationale(self):
        results = [_result(AgentRole.SECURITY, passed=True)]
        decision = judge(results, _conflict(), _evidence())
        assert "conflict" in decision.rationale.lower() or "disagree" in decision.rationale.lower()

    def test_conflict_alone_does_not_reject(self):
        # Even with multiple conflicts, no supported failing findings → APPROVE.
        results = [
            _result(AgentRole.SECURITY, passed=True),
            _result(AgentRole.ARCHITECTURE, passed=True),
        ]
        conflict = _conflict([
            "security passed but testing failed",
            "architecture passed but performance failed",
        ])
        decision = judge(results, conflict, _evidence())
        assert decision.verdict == Verdict.APPROVE

    def test_no_conflict_mentioned_in_rationale_when_absent(self):
        decision = judge([], _no_conflict(), _evidence())
        assert "No inter-agent conflicts detected" in decision.rationale

    def test_conflict_with_supported_findings_rejects(self):
        # Conflict + supported failing finding → REJECT (finding drove it, not conflict).
        finding = "hard-coded secret"
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=[finding]),
            _result(AgentRole.ARCHITECTURE, passed=True),
        ]
        ev = _evidence(supported=[finding])
        decision = judge(results, _conflict(), ev)
        assert decision.verdict == Verdict.REJECT


# ---------------------------------------------------------------------------
# Disagreement / mixed-agent scenarios
# ---------------------------------------------------------------------------

class TestDisagreement:
    def test_two_pass_one_fail_supported_rejects(self):
        finding = "SQL injection risk"
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=[finding]),
            _result(AgentRole.ARCHITECTURE, passed=True),
            _result(AgentRole.TESTING, passed=True),
        ]
        ev = _evidence(supported=[finding])
        decision = judge(results, _conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_two_pass_one_fail_unsupported_approves(self):
        finding = "minor style note"
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=[finding]),
            _result(AgentRole.ARCHITECTURE, passed=True),
            _result(AgentRole.TESTING, passed=True),
        ]
        ev = _evidence(unsupported=[finding])
        decision = judge(results, _conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_all_fail_all_supported_rejects(self):
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=["sec"]),
            _result(AgentRole.ARCHITECTURE, passed=False, findings=["arch"]),
            _result(AgentRole.TESTING, passed=False, findings=["test"]),
        ]
        ev = _evidence(supported=["sec", "arch", "test"])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_all_fail_all_unsupported_approves(self):
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=["sec"]),
            _result(AgentRole.ARCHITECTURE, passed=False, findings=["arch"]),
        ]
        ev = _evidence(unsupported=["sec", "arch"])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_rationale_includes_role_names(self):
        finding = "dangerous pattern"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[finding])
        decision = judge(results, _no_conflict(), ev)
        assert "security" in decision.rationale


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_result_no_findings_passes(self):
        results = [_result(AgentRole.PERFORMANCE, passed=False, findings=[])]
        decision = judge(results, _no_conflict(), _evidence())
        assert decision.verdict == Verdict.APPROVE

    def test_duplicate_finding_in_supported_rejects_once(self):
        # Same finding text in supported_findings twice (unusual but valid).
        finding = "same finding"
        results = [_result(AgentRole.SECURITY, passed=False, findings=[finding])]
        ev = _evidence(supported=[finding, finding])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_empty_finding_string_not_in_supported_set(self):
        # An empty finding "" should not match anything in supported_set unless
        # someone explicitly put "" there — in practice it won't cause rejection.
        results = [_result(AgentRole.SECURITY, passed=False, findings=[""])]
        ev = _evidence(supported=[], unsupported=[""])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_passing_agents_with_many_findings_still_approves(self):
        findings = [f"note {i}" for i in range(20)]
        results = [_result(AgentRole.ARCHITECTURE, passed=True, findings=findings)]
        ev = _evidence(supported=findings)
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE

    def test_rationale_is_non_empty(self):
        decision = judge([], _no_conflict(), _evidence())
        assert decision.rationale.strip() != ""

    def test_verdict_never_pending(self):
        # PENDING is a valid Verdict value but judge() must always resolve to
        # APPROVE or REJECT, never leave the decision in a PENDING state.
        decision = judge([], _no_conflict(), _evidence())
        assert decision.verdict != Verdict.PENDING

    def test_all_four_roles_mixed(self):
        results = [
            _result(AgentRole.SECURITY, passed=False, findings=["sec"]),
            _result(AgentRole.ARCHITECTURE, passed=True, findings=[]),
            _result(AgentRole.TESTING, passed=False, findings=["test"]),
            _result(AgentRole.PERFORMANCE, passed=True, findings=[]),
        ]
        # Only the security finding is supported.
        ev = _evidence(supported=["sec"], unsupported=["test"])
        decision = judge(results, _conflict(), ev)
        assert decision.verdict == Verdict.REJECT

    def test_large_result_set_deterministic(self):
        # 100 passing agents — should always APPROVE.
        results = [
            _result(AgentRole.SECURITY, passed=True, findings=[f"note {i}"])
            for i in range(100)
        ]
        ev = _evidence(supported=[f"note {i}" for i in range(100)])
        decision = judge(results, _no_conflict(), ev)
        assert decision.verdict == Verdict.APPROVE
