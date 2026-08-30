"""
Performance specialist agent — powered by IBM watsonx.ai (Llama 3.3 70B).

When a WatsonxClient is injected, uses the LLM for deep performance analysis.
Falls back to deterministic heuristics when no client is available
(e.g. CI without credentials).
"""

from __future__ import annotations

import json
import os
import re
import sys

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_backend = os.path.join(_root, "backend")
_services = os.path.join(_root, "services")
for _p in (_backend, _services):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from base import BaseAgent
from models import AgentResult, AgentRole
from watsonx_client import WatsonxClient  # used when watsonx_client is injected

SYSTEM_PROMPT = """You are the Performance specialist in the CouncilAI multi-agent code review pipeline.
Analyse the unified diff and identify performance issues in ADDED lines (+) only.

Check for:
1. Nested loops (for/while inside for/while) — O(n²) complexity risk
2. SELECT * queries — fetches unnecessary columns, wastes bandwidth
3. time.sleep() calls in async code — blocks the event loop
4. List comprehensions inside loop bodies — repeated allocation
5. N+1 query patterns (database queries inside loops)

Rules:
- Only flag added lines (starting with +)
- Be precise — only flag what you can clearly see in the diff
- Do NOT flag test fixtures or intentional sleep/retry patterns with a comment

Respond in this exact JSON format only, no prose:
{"passed": true/false, "findings": ["finding 1", "finding 2"], "raw_output": "brief summary"}

If no issues found: {"passed": true, "findings": [], "raw_output": "No performance concerns found."}"""


_LOOP_RE = re.compile(r"^\s*(for |while )")
_SELECT_STAR_RE = re.compile(r"SELECT\s+\*", re.IGNORECASE)
_SLEEP_RE = re.compile(r"\btime\.sleep\s*\(")
_LIST_COMP_RE = re.compile(r"\[.+\bfor\b.+\bin\b")


class PerformanceAgent(BaseAgent):
    role = AgentRole.PERFORMANCE

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

        # Track loop nesting depth across added lines.
        loop_depth = 0
        prev_indent = -1

        for lineno, line in enumerate(diff.splitlines(), start=1):
            if not (line.startswith("+") and not line.startswith("+++")):
                # Reset nesting state when we leave the added-lines window.
                loop_depth = 0
                prev_indent = -1
                continue

            stripped = line[1:]  # strip leading '+'
            indent = len(stripped) - len(stripped.lstrip())

            if _LOOP_RE.match(stripped):
                if loop_depth > 0 and indent > prev_indent:
                    findings.append(
                        f"Line {lineno}: nested loop detected — possible O(n²) complexity. "
                        f"{stripped.strip()[:80]}"
                    )
                loop_depth += 1
                prev_indent = indent
            elif indent <= prev_indent and loop_depth > 0:
                # Dedented past loop — reset.
                loop_depth = max(0, loop_depth - 1)
                prev_indent = indent

            if _SELECT_STAR_RE.search(stripped):
                findings.append(
                    f"Line {lineno}: SELECT * fetches all columns — specify needed columns. "
                    f"{stripped.strip()[:80]}"
                )
            if _SLEEP_RE.search(stripped):
                findings.append(
                    f"Line {lineno}: time.sleep() blocks the event loop — "
                    f"use asyncio.sleep() in async code. {stripped.strip()[:80]}"
                )
            if _LIST_COMP_RE.search(stripped) and loop_depth > 0:
                findings.append(
                    f"Line {lineno}: list comprehension inside loop may cause "
                    f"repeated allocations. {stripped.strip()[:80]}"
                )

        passed = len(findings) == 0
        raw = (
            "No performance concerns found."
            if passed
            else f"{len(findings)} performance finding(s)."
        )
        return AgentResult(
            role=self.role,
            passed=passed,
            findings=findings,
            raw_output=raw,
        )
