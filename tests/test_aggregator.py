"""
Tests for the Opinion Aggregator and Conflict Detector.

Run from the repo root:
    pytest tests/test_aggregator.py -v

No watsonx credentials or external services required.
"""

from __future__ import annotations

import sys
import os

# Ensure both agents/ and backend/ are on sys.path.
_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "agents"))
sys.path.insert(0, os.path.join(_root, "backend"))

from models import AgentRole, AgentResult, ConflictReport  # noqa: E402
from aggregator import aggregate, detect_conflicts  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(role: AgentRole, passed: bool, findings: list[str] | None = None) -> AgentResult:
    return AgentResult(role=role, passed=passed, findings=findings or [])


# ---------------------------------------------------------------------------
# aggregate()
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_returns_dict_keyed_by_role(self):
        results = [
            _result(AgentRole.SECURITY, True),
            _result(AgentRole.ARCHITECTURE, False),
        ]
        verdicts = aggregate(results)
        assert isinstance(verdicts, dict)
        assert AgentRole.SECURITY in verdicts
        assert AgentRole.ARCHITECTURE in verdicts

    def test_passed_values_preserved(self):
        results = [
            _result(AgentRole.SECURITY, True),
            _result(AgentRole.TESTING, False),
            _result(AgentRole.PERFORMANCE, True),
        ]
        verdicts = aggregate(results)
        assert verdicts[AgentRole.SECURITY] is True
        assert verdicts[AgentRole.TESTING] is False
        assert verdicts[AgentRole.PERFORMANCE] is True

    def test_empty_list_returns_empty_dict(self):
        assert aggregate([]) == {}

    def test_single_result(self):
        results = [_result(AgentRole.ARCHITECTURE, False)]
        verdicts = aggregate(results)
        assert verdicts == {AgentRole.ARCHITECTURE: False}

    def test_all_four_roles(self):
        results = [
            _result(AgentRole.SECURITY, True),
            _result(AgentRole.ARCHITECTURE, True),
            _result(AgentRole.TESTING, True),
            _result(AgentRole.PERFORMANCE, True),
        ]
        verdicts = aggregate(results)
        assert len(verdicts) == 4

    def test_duplicate_role_last_value_wins(self):
        # If the same role appears twice, the last entry wins.
        results = [
            _result(AgentRole.SECURITY, True),
            _result(AgentRole.SECURITY, False),
        ]
        verdicts = aggregate(results)
        assert verdicts[AgentRole.SECURITY] is False

    def test_order_preserved(self):
        roles = [AgentRole.PERFORMANCE, AgentRole.TESTING, AgentRole.SECURITY]
        results = [_result(r, True) for r in roles]
        assert list(aggregate(results).keys()) == roles


# ---------------------------------------------------------------------------
# detect_conflicts()
# ---------------------------------------------------------------------------

class TestDetectConflicts:
    def test_returns_conflict_report(self):
        report = detect_conflicts({})
        assert isinstance(report, ConflictReport)

    def test_no_conflict_when_all_pass(self):
        verdicts = {
            AgentRole.SECURITY: True,
            AgentRole.ARCHITECTURE: True,
            AgentRole.TESTING: True,
        }
        report = detect_conflicts(verdicts)
        assert report.has_conflicts is False
        assert report.conflicts == []

    def test_no_conflict_when_all_fail(self):
        # Unanimous failure is not a conflict — the agents agree.
        verdicts = {
            AgentRole.SECURITY: False,
            AgentRole.ARCHITECTURE: False,
        }
        report = detect_conflicts(verdicts)
        assert report.has_conflicts is False
        assert report.conflicts == []

    def test_conflict_when_mixed(self):
        verdicts = {
            AgentRole.SECURITY: True,
            AgentRole.ARCHITECTURE: False,
        }
        report = detect_conflicts(verdicts)
        assert report.has_conflicts is True
        assert len(report.conflicts) >= 1

    def test_conflict_message_mentions_both_roles(self):
        verdicts = {
            AgentRole.SECURITY: True,
            AgentRole.TESTING: False,
        }
        report = detect_conflicts(verdicts)
        assert any("security" in c for c in report.conflicts)
        assert any("testing" in c for c in report.conflicts)

    def test_conflict_count_equals_cross_product(self):
        # 2 passing × 2 failing → 4 conflict entries.
        verdicts = {
            AgentRole.SECURITY: True,
            AgentRole.ARCHITECTURE: True,
            AgentRole.TESTING: False,
            AgentRole.PERFORMANCE: False,
        }
        report = detect_conflicts(verdicts)
        assert report.has_conflicts is True
        assert len(report.conflicts) == 4

    def test_empty_verdicts_no_conflict(self):
        report = detect_conflicts({})
        assert report.has_conflicts is False
        assert report.conflicts == []

    def test_single_passing_agent_no_conflict(self):
        report = detect_conflicts({AgentRole.SECURITY: True})
        assert report.has_conflicts is False

    def test_single_failing_agent_no_conflict(self):
        report = detect_conflicts({AgentRole.SECURITY: False})
        assert report.has_conflicts is False


# ---------------------------------------------------------------------------
# Integration: aggregate + detect_conflicts together
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_all_agents_pass_no_conflict(self):
        results = [
            _result(AgentRole.SECURITY, True),
            _result(AgentRole.ARCHITECTURE, True),
            _result(AgentRole.TESTING, True),
            _result(AgentRole.PERFORMANCE, True),
        ]
        report = detect_conflicts(aggregate(results))
        assert report.has_conflicts is False

    def test_one_agent_fails_conflict_detected(self):
        results = [
            _result(AgentRole.SECURITY, True),
            _result(AgentRole.ARCHITECTURE, True),
            _result(AgentRole.TESTING, False),
        ]
        report = detect_conflicts(aggregate(results))
        assert report.has_conflicts is True
        # 2 passing agents × 1 failing agent → 2 conflict entries.
        assert len(report.conflicts) == 2

    def test_all_agents_fail_no_conflict(self):
        results = [
            _result(AgentRole.SECURITY, False),
            _result(AgentRole.ARCHITECTURE, False),
            _result(AgentRole.TESTING, False),
        ]
        report = detect_conflicts(aggregate(results))
        assert report.has_conflicts is False

    def test_findings_do_not_affect_conflict_detection(self):
        # passed=True regardless of findings list content.
        results = [
            _result(AgentRole.SECURITY, True, findings=["something flagged"]),
            _result(AgentRole.ARCHITECTURE, True, findings=["another flag"]),
        ]
        report = detect_conflicts(aggregate(results))
        assert report.has_conflicts is False
