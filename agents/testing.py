"""
Testing specialist agent.

Placeholder checks (no LLM required):
  - Warns when new functions/classes are added without a corresponding test
    file change (heuristic: diff touches ``src/`` or ``app/`` but not
    ``test_``, ``_test``, or ``spec`` paths).
  - Flags ``assert False`` / ``pytest.skip`` / ``unittest.skip`` in added
    lines (incomplete tests committed).
  - Flags bare ``except:`` or ``except Exception:`` without re-raise
    (swallowed exceptions hide bugs).

Replace ``_run_checks`` body with a watsonx/Granite call when credentials
are available; everything else (interface, imports, tests) stays the same.
"""

from __future__ import annotations

import re

from base import BaseAgent
from models import AgentResult, AgentRole


_SKIP_RE = re.compile(r"\bpytest\.skip\b|\bunittest\.skip\b|assert\s+False\b")
_BARE_EXCEPT_RE = re.compile(r"^\s*except\s*(Exception\s*)?:\s*$")
_BARE_EXCEPT_PASS_RE = re.compile(r"^\s*except\s*(Exception\s*)?:\s*\n?\s*pass\s*$")
_FILE_HEADER_RE = re.compile(r"^(\+\+\+|---)\s+(\S+)")


def _extract_filenames(diff: str) -> list[str]:
    """Return the list of file paths touched in *diff*."""
    return [
        m.group(2)
        for line in diff.splitlines()
        if (m := _FILE_HEADER_RE.match(line))
    ]


class TestingAgent(BaseAgent):
    role = AgentRole.TESTING

    def _run_checks(self, diff: str, context: str | None) -> AgentResult:
        findings: list[str] = []
        filenames = _extract_filenames(diff)

        # Heuristic: production code changed but no test file in the diff.
        prod_changed = any(
            ("src/" in f or "app/" in f or "backend/" in f) and not f.endswith(".md")
            for f in filenames
        )
        test_changed = any(
            "test_" in f or "_test" in f or "spec" in f or "tests/" in f
            for f in filenames
        )
        if prod_changed and not test_changed:
            findings.append(
                "Production code modified but no test files detected in diff. "
                "Consider adding or updating tests."
            )

        for lineno, line in enumerate(diff.splitlines(), start=1):
            if not (line.startswith("+") and not line.startswith("+++")):
                continue
            stripped = line[1:]

            if _SKIP_RE.search(stripped):
                findings.append(
                    f"Line {lineno}: incomplete/skipped test — {stripped.strip()[:80]}"
                )
            if _BARE_EXCEPT_RE.match(stripped):
                findings.append(
                    f"Line {lineno}: bare except may swallow errors — {stripped.strip()[:80]}"
                )

        passed = len(findings) == 0
        raw = (
            "No testing concerns found."
            if passed
            else f"{len(findings)} testing finding(s)."
        )
        return AgentResult(
            role=self.role,
            passed=passed,
            findings=findings,
            raw_output=raw,
        )
