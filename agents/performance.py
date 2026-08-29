"""
Performance specialist agent.

Placeholder checks (no LLM required):
  - Flags nested loops (``for``/``while`` inside ``for``/``while``) in added
    lines — a common source of O(n²) complexity.
  - Flags ``SELECT *`` in SQL strings.
  - Flags ``time.sleep`` calls (blocking I/O in async paths).
  - Flags list comprehensions inside a loop body (repeated allocation).

Replace ``_run_checks`` body with a watsonx/Granite call when credentials
are available; everything else (interface, imports, tests) stays the same.
"""

from __future__ import annotations

import re

from base import BaseAgent
from models import AgentResult, AgentRole


_LOOP_RE = re.compile(r"^\s*(for |while )")
_SELECT_STAR_RE = re.compile(r"SELECT\s+\*", re.IGNORECASE)
_SLEEP_RE = re.compile(r"\btime\.sleep\s*\(")
_LIST_COMP_RE = re.compile(r"\[.+\bfor\b.+\bin\b")


class PerformanceAgent(BaseAgent):
    role = AgentRole.PERFORMANCE

    def _run_checks(self, diff: str, context: str | None) -> AgentResult:
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
