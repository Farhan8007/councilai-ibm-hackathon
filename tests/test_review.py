"""
Integration tests for the POST /review pipeline.

Run from the repo root:
    pytest tests/test_review.py -v

No watsonx credentials or external services required — all agents use their
deterministic placeholder logic.

TestClient drives the full FastAPI app (main.py) through a real in-process
HTTP request, exercising:
    1. Specialist agents (in parallel)
    2. Conflict Detector (aggregate + detect_conflicts)
    3. Evidence Checker (check_evidence)
    4. Final Judge (judge)
    5. ReviewResponse envelope
"""

from __future__ import annotations

import sys
import os
import warnings

# Suppress the httpx/starlette deprecation warning so test output is clean.
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*httpx.*starlette.*",
)

# Ensure backend/ is on the path before importing main.
_root = os.path.dirname(os.path.dirname(__file__))
_backend = os.path.join(_root, "backend")
_agents = os.path.join(_root, "agents")
for _p in (_backend, _agents):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from models import Verdict  # noqa: E402

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# A diff that triggers NO agent findings — all four agents pass.
# Uses a docs/ path so TestingAgent's prod-without-test heuristic is not triggered.
CLEAN_DIFF = """\
--- a/docs/README.md
+++ b/docs/README.md
@@ -1,3 +1,6 @@
+# Greeting
+
+A simple greeting utility.
"""

# Triggers SecurityAgent (hard-coded credential on added line).
CREDENTIAL_DIFF = '+    api_key = "AKIA1234ABCD5678"\n'

# Triggers PerformanceAgent (SELECT *).
SELECT_STAR_DIFF = '+    cursor.execute("SELECT * FROM users")\n'

# Triggers TestingAgent (pytest.skip on added line).
SKIP_DIFF = "+    pytest.skip('not implemented yet')\n"

# Triggers ArchitectureAgent (TODO marker).
TODO_DIFF = "+    # TODO: clean this up before release\n"

# Triggers multiple agents: credential (Security) + nested loop (Performance).
MULTI_TRIGGER_DIFF = (
    '+    password = "hunter2"\n'
    "+for i in range(n):\n"
    "+    for j in range(m):\n"
    "+        print(i, j)\n"
)


def _post(diff: str, context: str | None = None) -> dict:
    """POST /review and return the parsed JSON body."""
    payload: dict = {"diff": diff}
    if context is not None:
        payload["context"] = context
    resp = client.post("/review", json=payload)
    assert resp.status_code == 200, f"Unexpected status {resp.status_code}: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Response envelope contract
# ---------------------------------------------------------------------------

class TestResponseContract:
    def test_returns_200(self):
        resp = client.post("/review", json={"diff": CLEAN_DIFF})
        assert resp.status_code == 200

    def test_response_has_required_keys(self):
        body = _post(CLEAN_DIFF)
        for key in ("request_id", "verdict", "summary", "details"):
            assert key in body, f"Missing key: {key}"

    def test_request_id_is_uuid_string(self):
        import uuid
        body = _post(CLEAN_DIFF)
        # Must be a valid UUID string.
        uuid.UUID(body["request_id"])  # raises ValueError if invalid

    def test_unique_request_ids(self):
        id1 = _post(CLEAN_DIFF)["request_id"]
        id2 = _post(CLEAN_DIFF)["request_id"]
        assert id1 != id2

    def test_verdict_is_valid_enum_value(self):
        body = _post(CLEAN_DIFF)
        assert body["verdict"] in (Verdict.APPROVE, Verdict.REJECT, Verdict.PENDING)

    def test_verdict_never_pending(self):
        # The pipeline must always resolve to APPROVE or REJECT.
        body = _post(CLEAN_DIFF)
        assert body["verdict"] != Verdict.PENDING

    def test_summary_is_non_empty_string(self):
        body = _post(CLEAN_DIFF)
        assert isinstance(body["summary"], str)
        assert body["summary"].strip() != ""

    def test_details_contains_expected_keys(self):
        body = _post(CLEAN_DIFF)
        for key in ("agents", "conflicts", "evidence", "rationale"):
            assert key in body["details"], f"Missing details key: {key}"

    def test_details_agents_has_four_roles(self):
        body = _post(CLEAN_DIFF)
        assert set(body["details"]["agents"].keys()) == {
            "security", "architecture", "testing", "performance"
        }

    def test_details_each_agent_has_passed_and_findings(self):
        body = _post(CLEAN_DIFF)
        for role, info in body["details"]["agents"].items():
            assert "passed" in info, f"'passed' missing for {role}"
            assert "findings" in info, f"'findings' missing for {role}"
            assert isinstance(info["findings"], list)


# ---------------------------------------------------------------------------
# APPROVE — clean diff
# ---------------------------------------------------------------------------

class TestApprove:
    def test_clean_diff_approves(self):
        body = _post(CLEAN_DIFF)
        assert body["verdict"] == Verdict.APPROVE

    def test_clean_diff_all_agents_pass(self):
        body = _post(CLEAN_DIFF)
        for role, info in body["details"]["agents"].items():
            assert info["passed"] is True, f"{role} unexpectedly failed"

    def test_clean_diff_no_conflicts(self):
        body = _post(CLEAN_DIFF)
        assert body["details"]["conflicts"]["has_conflicts"] is False

    def test_clean_diff_no_supported_findings(self):
        body = _post(CLEAN_DIFF)
        assert body["details"]["evidence"]["supported_findings"] == []

    def test_summary_says_approve(self):
        body = _post(CLEAN_DIFF)
        assert "APPROVE" in body["summary"]

    def test_rationale_says_approve(self):
        body = _post(CLEAN_DIFF)
        assert "APPROVE" in body["details"]["rationale"]


# ---------------------------------------------------------------------------
# REJECT — supported findings from failing agents
# ---------------------------------------------------------------------------

class TestReject:
    def test_credential_diff_rejects(self):
        body = _post(CREDENTIAL_DIFF)
        assert body["verdict"] == Verdict.REJECT

    def test_credential_diff_security_fails(self):
        body = _post(CREDENTIAL_DIFF)
        assert body["details"]["agents"]["security"]["passed"] is False

    def test_credential_diff_has_security_findings(self):
        body = _post(CREDENTIAL_DIFF)
        findings = body["details"]["agents"]["security"]["findings"]
        assert len(findings) >= 1

    def test_select_star_rejects(self):
        body = _post(SELECT_STAR_DIFF)
        assert body["verdict"] == Verdict.REJECT

    def test_select_star_performance_fails(self):
        body = _post(SELECT_STAR_DIFF)
        assert body["details"]["agents"]["performance"]["passed"] is False

    def test_summary_says_reject(self):
        body = _post(CREDENTIAL_DIFF)
        assert "REJECT" in body["summary"]

    def test_summary_names_failed_roles(self):
        body = _post(CREDENTIAL_DIFF)
        assert "security" in body["summary"]

    def test_rationale_says_reject(self):
        body = _post(CREDENTIAL_DIFF)
        assert "REJECT" in body["details"]["rationale"]

    def test_supported_findings_non_empty_on_reject(self):
        body = _post(CREDENTIAL_DIFF)
        assert len(body["details"]["evidence"]["supported_findings"]) >= 1

    def test_pytest_skip_rejects(self):
        body = _post(SKIP_DIFF)
        assert body["verdict"] == Verdict.REJECT

    def test_todo_rejects(self):
        body = _post(TODO_DIFF)
        assert body["verdict"] == Verdict.REJECT


# ---------------------------------------------------------------------------
# Conflict detection — contextual, does NOT change verdict on its own
# ---------------------------------------------------------------------------

class TestConflicts:
    def test_conflict_reported_when_agents_disagree(self):
        # Credential triggers Security failure while other agents may pass.
        body = _post(CREDENTIAL_DIFF)
        conflicts = body["details"]["conflicts"]
        # At least security failed; if any passed, has_conflicts must be True.
        agents = body["details"]["agents"]
        any_passed = any(v["passed"] for v in agents.values())
        any_failed = any(not v["passed"] for v in agents.values())
        if any_passed and any_failed:
            assert conflicts["has_conflicts"] is True

    def test_conflicts_key_is_list(self):
        body = _post(CLEAN_DIFF)
        assert isinstance(body["details"]["conflicts"]["conflicts"], list)

    def test_all_pass_no_conflicts(self):
        body = _post(CLEAN_DIFF)
        assert body["details"]["conflicts"]["has_conflicts"] is False
        assert body["details"]["conflicts"]["conflicts"] == []

    def test_conflict_present_in_rationale_when_detected(self):
        body = _post(CREDENTIAL_DIFF)
        if body["details"]["conflicts"]["has_conflicts"]:
            rationale = body["details"]["rationale"].lower()
            assert "conflict" in rationale or "disagree" in rationale


# ---------------------------------------------------------------------------
# Evidence structure
# ---------------------------------------------------------------------------

class TestEvidence:
    def test_evidence_keys_present(self):
        body = _post(CLEAN_DIFF)
        ev = body["details"]["evidence"]
        assert "supported_findings" in ev
        assert "unsupported_findings" in ev

    def test_supported_findings_is_list(self):
        body = _post(CLEAN_DIFF)
        assert isinstance(body["details"]["evidence"]["supported_findings"], list)

    def test_unsupported_findings_is_list(self):
        body = _post(CLEAN_DIFF)
        assert isinstance(body["details"]["evidence"]["unsupported_findings"], list)

    def test_clean_diff_both_evidence_lists_empty(self):
        body = _post(CLEAN_DIFF)
        assert body["details"]["evidence"]["supported_findings"] == []
        assert body["details"]["evidence"]["unsupported_findings"] == []

    def test_rejected_diff_has_supported_findings(self):
        body = _post(CREDENTIAL_DIFF)
        if body["verdict"] == Verdict.REJECT:
            assert len(body["details"]["evidence"]["supported_findings"]) >= 1


# ---------------------------------------------------------------------------
# Multi-trigger — multiple agents fail simultaneously
# ---------------------------------------------------------------------------

class TestMultipleTriggers:
    def test_multi_trigger_rejects(self):
        body = _post(MULTI_TRIGGER_DIFF)
        assert body["verdict"] == Verdict.REJECT

    def test_multi_trigger_security_and_performance_fail(self):
        body = _post(MULTI_TRIGGER_DIFF)
        agents = body["details"]["agents"]
        assert agents["security"]["passed"] is False
        assert agents["performance"]["passed"] is False

    def test_multi_trigger_findings_non_empty(self):
        body = _post(MULTI_TRIGGER_DIFF)
        sec_findings = body["details"]["agents"]["security"]["findings"]
        perf_findings = body["details"]["agents"]["performance"]["findings"]
        assert len(sec_findings) >= 1
        assert len(perf_findings) >= 1


# ---------------------------------------------------------------------------
# /health smoke-test (ensures the route still works after pipeline wiring)
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_diff_approves(self):
        # Empty diff — no agent finds anything to flag.
        body = _post("")
        assert body["verdict"] == Verdict.APPROVE

    def test_context_field_accepted(self):
        body = _post(CLEAN_DIFF, context="PR: add greeting utility")
        assert body["verdict"] == Verdict.APPROVE

    def test_context_none_accepted(self):
        body = _post(CLEAN_DIFF, context=None)
        assert "verdict" in body

    def test_removed_lines_only_not_flagged(self):
        # Lines starting with '-' — SecurityAgent ignores them.
        diff = '-    api_key = "AKIA1234ABCD5678"\n'
        body = _post(diff)
        assert body["details"]["agents"]["security"]["passed"] is True

    def test_response_is_deterministic(self):
        # Same diff → same verdict on two consecutive calls.
        b1 = _post(CREDENTIAL_DIFF)
        b2 = _post(CREDENTIAL_DIFF)
        assert b1["verdict"] == b2["verdict"]

    def test_large_diff_does_not_crash(self):
        # 200 clean added lines — should always succeed.
        diff = "\n".join(f"+    x_{i} = {i}" for i in range(200))
        resp = client.post("/review", json={"diff": diff})
        assert resp.status_code == 200
