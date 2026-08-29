"""
Testing specialist agent — powered by IBM watsonx.ai (Llama 3.3 70B).

When a WatsonxClient is injected, uses the LLM for deep test-quality analysis.
Falls back to deterministic heuristics when no client is available
(e.g. CI without credentials).
"""

from __future__ import annotations

import re
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_backend = os.path.join(_root, "backend")
_services = os.path.join(_root, "services")
for _p in (_backend, _services):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from base import BaseAgent
from models import AgentResult, AgentRole
from watsonx_client import WatsonxClient

SYSTEM_PROMPT = """You are the Testing specialist in the CouncilAI multi-agent code review pipeline.
Analyse the unified diff and identify test-quality issues in ADDED lines (+) only.

Check for:
1. Production code changes with no corresponding test file changes in the diff
2. Skipped or disabled tests (pytest.skip, unittest.skip, assert False)
3. Bare except clauses that swallow exceptions (hides bugs in tests)
4. Missing edge-case coverage (no None/empty/boundary checks visible)
5. Hardcoded test data that should use fixtures or factories

Rules:
- Only flag added lines (starting with +)
- Be precise — only flag what you can clearly see in the diff
- Do NOT flag test utility helpers as missing tests

Respond in this exact JSON format only, no prose:
{"passed": true/false, "findings": ["finding 1", "finding 2"], "raw_output": "brief summary"}

If no issues found: {"passed": true, "findings": [], "raw_output": "No testing concerns found."}"""


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

    def __init__(self, watsonx_client=None):
        super().__init__(watsonx_client)
        self._client = watsonx_client

    def _run_checks(self, diff: str, context: str | None) -> AgentResult:
        if self._client is not None:
            return self._run_watsonx(diff)
        return self._run_deterministic(diff)

    def _run_watsonx(self, diff: str) -> AgentResult:
        prompt = f"{SYSTEM_PROMPT}\n\nDiff to review:\n{diff}"
        try:
            raw = self._client.generate(prompt=prompt, max_new_tokens=400, temperature=0.1)
            import json
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON in response: {raw}")
            data = json.loads(match.group())
            return AgentResult(
                role=self.role,
                passed=bool(data.get("passed", True)),
                findings=data.get("findings", []),
                raw_output=data.get("raw_output", raw),
            )
        except Exception as exc:
            return AgentResult(
                role=self.role,
                passed=False,
                findings=[f"Agent error: {exc}"],
                raw_output=str(exc),
            )

    def _run_deterministic(self, diff: str) -> AgentResult:
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
