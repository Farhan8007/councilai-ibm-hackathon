"""
Tests for the Evidence Checker.

Run from the repo root:
    pytest tests/test_evidence.py -v

No watsonx credentials or external services required.
"""

from __future__ import annotations

import sys
import os

# Ensure both agents/ and backend/ are on sys.path.
_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "agents"))
sys.path.insert(0, os.path.join(_root, "backend"))

from models import AgentRole, AgentResult, EvidenceReport  # noqa: E402
from evidence import check_evidence  # noqa: E402


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


# ---------------------------------------------------------------------------
# Return-type contract
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_evidence_report(self):
        report = check_evidence([])
        assert isinstance(report, EvidenceReport)

    def test_empty_results_both_lists_empty(self):
        report = check_evidence([])
        assert report.supported_findings == []
        assert report.unsupported_findings == []


# ---------------------------------------------------------------------------
# Single-agent cases
# ---------------------------------------------------------------------------

class TestSingleAgent:
    def test_finding_with_raw_output_is_supported(self):
        result = _result(
            findings=["Line 3: hard-coded password"],
            raw_output="1 security finding(s).",
        )
        report = check_evidence([result])
        assert "Line 3: hard-coded password" in report.supported_findings
        assert report.unsupported_findings == []

    def test_finding_without_raw_output_is_unsupported(self):
        result = _result(
            findings=["Line 3: hard-coded password"],
            raw_output="",
        )
        report = check_evidence([result])
        assert "Line 3: hard-coded password" in report.unsupported_findings
        assert report.supported_findings == []

    def test_empty_finding_is_unsupported_even_with_raw_output(self):
        result = _result(
            findings=[""],
            raw_output="some output",
        )
        report = check_evidence([result])
        assert report.supported_findings == []
        assert "" in report.unsupported_findings

    def test_whitespace_only_finding_is_unsupported(self):
        result = _result(
            findings=["   "],
            raw_output="some output",
        )
        report = check_evidence([result])
        assert report.supported_findings == []
        assert "   " in report.unsupported_findings

    def test_whitespace_only_raw_output_makes_finding_unsupported(self):
        result = _result(
            findings=["real finding"],
            raw_output="   ",
        )
        report = check_evidence([result])
        assert report.supported_findings == []
        assert "real finding" in report.unsupported_findings

    def test_no_findings_produces_empty_report(self):
        result = _result(findings=[], raw_output="No issues found.")
        report = check_evidence([result])
        assert report.supported_findings == []
        assert report.unsupported_findings == []

    def test_multiple_findings_all_supported(self):
        result = _result(
            findings=["finding A", "finding B", "finding C"],
            raw_output="3 finding(s).",
        )
        report = check_evidence([result])
        assert len(report.supported_findings) == 3
        assert report.unsupported_findings == []

    def test_multiple_findings_all_unsupported(self):
        result = _result(
            findings=["finding A", "finding B"],
            raw_output="",
        )
        report = check_evidence([result])
        assert report.supported_findings == []
        assert len(report.unsupported_findings) == 2

    def test_finding_order_preserved(self):
        findings = ["first", "second", "third"]
        result = _result(findings=findings, raw_output="has output")
        report = check_evidence([result])
        assert report.supported_findings == findings


# ---------------------------------------------------------------------------
# Multiple agent results
# ---------------------------------------------------------------------------

class TestMultipleAgents:
    def test_two_agents_both_supported(self):
        results = [
            _result(AgentRole.SECURITY, findings=["sec finding"], raw_output="sec output"),
            _result(AgentRole.ARCHITECTURE, findings=["arch finding"], raw_output="arch output"),
        ]
        report = check_evidence(results)
        assert "sec finding" in report.supported_findings
        assert "arch finding" in report.supported_findings
        assert report.unsupported_findings == []

    def test_two_agents_both_unsupported(self):
        results = [
            _result(AgentRole.SECURITY, findings=["sec finding"], raw_output=""),
            _result(AgentRole.ARCHITECTURE, findings=["arch finding"], raw_output=""),
        ]
        report = check_evidence(results)
        assert report.supported_findings == []
        assert "sec finding" in report.unsupported_findings
        assert "arch finding" in report.unsupported_findings

    def test_mixed_agents_one_supported_one_unsupported(self):
        results = [
            _result(AgentRole.SECURITY, findings=["sec finding"], raw_output="has output"),
            _result(AgentRole.TESTING, findings=["test finding"], raw_output=""),
        ]
        report = check_evidence(results)
        assert "sec finding" in report.supported_findings
        assert "test finding" in report.unsupported_findings

    def test_four_agents_all_roles(self):
        results = [
            _result(AgentRole.SECURITY, findings=["s1"], raw_output="out"),
            _result(AgentRole.ARCHITECTURE, findings=["a1"], raw_output="out"),
            _result(AgentRole.TESTING, findings=["t1"], raw_output=""),
            _result(AgentRole.PERFORMANCE, findings=["p1"], raw_output=""),
        ]
        report = check_evidence(results)
        assert sorted(report.supported_findings) == ["a1", "s1"]
        assert sorted(report.unsupported_findings) == ["p1", "t1"]

    def test_agent_with_no_findings_does_not_pollute_report(self):
        results = [
            _result(AgentRole.SECURITY, findings=[], raw_output="No issues."),
            _result(AgentRole.ARCHITECTURE, findings=["arch issue"], raw_output="1 issue."),
        ]
        report = check_evidence(results)
        assert report.supported_findings == ["arch issue"]
        assert report.unsupported_findings == []

    def test_total_finding_count_equals_sum_of_all_findings(self):
        results = [
            _result(AgentRole.SECURITY, findings=["s1", "s2"], raw_output="out"),
            _result(AgentRole.TESTING, findings=["t1"], raw_output=""),
            _result(AgentRole.PERFORMANCE, findings=[], raw_output="out"),
        ]
        report = check_evidence(results)
        total = len(report.supported_findings) + len(report.unsupported_findings)
        assert total == 3  # s1 + s2 + t1

    def test_duplicate_finding_strings_kept_separately(self):
        # Same finding text from two different agents — both kept independently.
        results = [
            _result(AgentRole.SECURITY, findings=["same finding"], raw_output="out"),
            _result(AgentRole.ARCHITECTURE, findings=["same finding"], raw_output="out"),
        ]
        report = check_evidence(results)
        assert report.supported_findings.count("same finding") == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_passed_false_findings_still_classified(self):
        # passed=False is orthogonal to evidence classification.
        result = _result(
            passed=False,
            findings=["bad thing found"],
            raw_output="1 finding.",
        )
        report = check_evidence([result])
        assert "bad thing found" in report.supported_findings

    def test_passed_true_with_findings_still_classified(self):
        # passed=True with findings (unusual but valid) — classify normally.
        result = _result(
            passed=True,
            findings=["minor note"],
            raw_output="",
        )
        report = check_evidence([result])
        assert "minor note" in report.unsupported_findings

    def test_raw_output_whitespace_variants(self):
        for raw in ("", " ", "\t", "\n", "  \n  "):
            result = _result(findings=["a finding"], raw_output=raw)
            report = check_evidence([result])
            assert "a finding" in report.unsupported_findings, (
                f"Expected unsupported for raw_output={raw!r}"
            )

    def test_single_result_no_findings_no_raw(self):
        result = _result(findings=[], raw_output="")
        report = check_evidence([result])
        assert report.supported_findings == []
        assert report.unsupported_findings == []
