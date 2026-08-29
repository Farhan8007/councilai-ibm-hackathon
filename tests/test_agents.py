"""
Tests for the four specialist agents.

Run from the repo root:
    pytest tests/test_agents.py -v

No watsonx credentials required — only the deterministic placeholder logic
is exercised here.
"""

from __future__ import annotations

import sys
import os

# Ensure both agents/ and backend/ are on sys.path.
_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(_root, "agents"))
sys.path.insert(0, os.path.join(_root, "backend"))

from models import AgentRole, AgentResult  # noqa: E402
from security import SecurityAgent  # noqa: E402
from architecture import ArchitectureAgent  # noqa: E402
from testing import TestingAgent  # noqa: E402
from performance import PerformanceAgent  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CLEAN_DIFF = """\
--- a/app/utils.py
+++ b/app/utils.py
@@ -1,3 +1,6 @@
+def greet(name: str) -> str:
+    return f"Hello, {name}"
"""

# ---------------------------------------------------------------------------
# BaseAgent contract
# ---------------------------------------------------------------------------

def test_review_returns_agent_result():
    result = SecurityAgent().review(CLEAN_DIFF)
    assert isinstance(result, AgentResult)


def test_review_accepts_context():
    result = SecurityAgent().review(CLEAN_DIFF, context="PR: add greeting util")
    assert isinstance(result, AgentResult)


def test_watsonx_client_stored():
    sentinel = object()
    agent = SecurityAgent(watsonx_client=sentinel)
    assert agent._client is sentinel


# ---------------------------------------------------------------------------
# SecurityAgent
# ---------------------------------------------------------------------------

class TestSecurityAgent:
    def test_role(self):
        assert SecurityAgent().role == AgentRole.SECURITY

    def test_clean_diff_passes(self):
        result = SecurityAgent().review(CLEAN_DIFF)
        assert result.passed is True
        assert result.findings == []

    def test_hardcoded_password_fails(self):
        diff = '+    password = "hunter2"\n'
        result = SecurityAgent().review(diff)
        assert result.passed is False
        assert any("credential" in f.lower() for f in result.findings)

    def test_eval_call_fails(self):
        diff = "+    eval(user_input)\n"
        result = SecurityAgent().review(diff)
        assert result.passed is False
        assert any("dangerous" in f.lower() for f in result.findings)

    def test_http_url_fails(self):
        diff = '+    url = "http://example.com/api"\n'
        result = SecurityAgent().review(diff)
        assert result.passed is False
        assert any("http://" in f for f in result.findings)

    def test_removed_lines_ignored(self):
        # A credential on a REMOVED line should not trigger a finding.
        diff = '-    password = "old_secret"\n'
        result = SecurityAgent().review(diff)
        assert result.passed is True


# ---------------------------------------------------------------------------
# ArchitectureAgent
# ---------------------------------------------------------------------------

class TestArchitectureAgent:
    def test_role(self):
        assert ArchitectureAgent().role == AgentRole.ARCHITECTURE

    def test_clean_diff_passes(self):
        result = ArchitectureAgent().review(CLEAN_DIFF)
        assert result.passed is True

    def test_todo_comment_fails(self):
        diff = "+    # TODO: remove before release\n"
        result = ArchitectureAgent().review(diff)
        assert result.passed is False
        assert any("TODO" in f or "marker" in f.lower() for f in result.findings)

    def test_large_block_fails(self):
        # 51 consecutive added lines — should be flagged.
        lines = "\n".join(f"+    x_{i} = {i}" for i in range(51))
        result = ArchitectureAgent().review(lines)
        assert result.passed is False
        assert any("large" in f.lower() for f in result.findings)

    def test_small_block_passes(self):
        lines = "\n".join(f"+    x_{i} = {i}" for i in range(10))
        result = ArchitectureAgent().review(lines)
        # No large-block finding; magic-number findings may exist but that's fine.
        assert not any("large" in f.lower() for f in result.findings)


# ---------------------------------------------------------------------------
# TestingAgent
# ---------------------------------------------------------------------------

class TestTestingAgent:
    def test_role(self):
        assert TestingAgent().role == AgentRole.TESTING

    def test_no_prod_files_passes(self):
        # Diff only touches docs — no prod-without-test warning.
        diff = "--- a/README.md\n+++ b/README.md\n+ Some update\n"
        result = TestingAgent().review(diff)
        assert result.passed is True

    def test_prod_without_test_warns(self):
        diff = (
            "--- a/backend/utils.py\n+++ b/backend/utils.py\n"
            "+def helper(): pass\n"
        )
        result = TestingAgent().review(diff)
        assert result.passed is False
        assert any("test" in f.lower() for f in result.findings)

    def test_prod_with_test_passes(self):
        diff = (
            "--- a/backend/utils.py\n+++ b/backend/utils.py\n+def helper(): pass\n"
            "--- a/tests/test_utils.py\n+++ b/tests/test_utils.py\n+def test_helper(): pass\n"
        )
        result = TestingAgent().review(diff)
        # The prod-without-test finding should not appear.
        assert not any("no test" in f.lower() or "without test" in f.lower() for f in result.findings)

    def test_pytest_skip_fails(self):
        diff = "+    pytest.skip('not ready')\n"
        result = TestingAgent().review(diff)
        assert result.passed is False
        assert any("skip" in f.lower() or "incomplete" in f.lower() for f in result.findings)


# ---------------------------------------------------------------------------
# PerformanceAgent
# ---------------------------------------------------------------------------

class TestPerformanceAgent:
    def test_role(self):
        assert PerformanceAgent().role == AgentRole.PERFORMANCE

    def test_clean_diff_passes(self):
        result = PerformanceAgent().review(CLEAN_DIFF)
        assert result.passed is True

    def test_select_star_fails(self):
        diff = '+    cursor.execute("SELECT * FROM users")\n'
        result = PerformanceAgent().review(diff)
        assert result.passed is False
        assert any("SELECT *" in f for f in result.findings)

    def test_sleep_fails(self):
        diff = "+    time.sleep(5)\n"
        result = PerformanceAgent().review(diff)
        assert result.passed is False
        assert any("sleep" in f.lower() for f in result.findings)

    def test_nested_loop_fails(self):
        diff = (
            "+for i in range(n):\n"
            "+    for j in range(m):\n"
            "+        print(i, j)\n"
        )
        result = PerformanceAgent().review(diff)
        assert result.passed is False
        assert any("nested" in f.lower() for f in result.findings)

    def test_single_loop_passes(self):
        diff = "+for i in range(10):\n+    print(i)\n"
        result = PerformanceAgent().review(diff)
        assert not any("nested" in f.lower() for f in result.findings)
