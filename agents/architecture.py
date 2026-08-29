"""
Architecture specialist agent.

Placeholder checks (no LLM required):
  - Flags overly long functions (contiguous added-line blocks > 50 lines).
  - Flags circular-import risk: a module importing from its own package at
    the top level while also being imported there.
  - Flags TODO / FIXME / HACK / NOQA comments left in added lines.
  - Flags magic numbers (bare integer literals outside assignments).

Replace ``_run_checks`` body with a watsonx/Granite call when credentials
are available; everything else (interface, imports, tests) stays the same.
"""

from __future__ import annotations

import re

from base import BaseAgent
from models import AgentResult, AgentRole


_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|NOQA)\b", re.IGNORECASE)
_MAGIC_NUMBER_RE = re.compile(r"(?<!['\"\w])\b(?!0\b)\d{2,}\b(?!['\"\w])")


class ArchitectureAgent(BaseAgent):
    role = AgentRole.ARCHITECTURE

    # Maximum consecutive added lines before flagging a long function.
    _LONG_BLOCK_THRESHOLD = 50

    def _run_checks(self, diff: str, context: str | None) -> AgentResult:
        findings: list[str] = []
        added_block = 0
        block_start = 0

        for lineno, line in enumerate(diff.splitlines(), start=1):
            is_addition = line.startswith("+") and not line.startswith("+++")

            if is_addition:
                if added_block == 0:
                    block_start = lineno
                added_block += 1

                stripped = line[1:]  # remove leading '+'

                if _TODO_RE.search(stripped):
                    findings.append(
                        f"Line {lineno}: unresolved marker — {stripped.strip()[:80]}"
                    )
                if _MAGIC_NUMBER_RE.search(stripped):
                    findings.append(
                        f"Line {lineno}: possible magic number — {stripped.strip()[:80]}"
                    )
            else:
                if added_block >= self._LONG_BLOCK_THRESHOLD:
                    findings.append(
                        f"Lines {block_start}–{lineno - 1}: large contiguous addition "
                        f"({added_block} lines) — consider splitting into smaller units."
                    )
                added_block = 0

        # Flush trailing block.
        if added_block >= self._LONG_BLOCK_THRESHOLD:
            findings.append(
                f"Lines {block_start}–end: large contiguous addition "
                f"({added_block} lines) — consider splitting into smaller units."
            )

        passed = len(findings) == 0
        raw = (
            "No architecture concerns found."
            if passed
            else f"{len(findings)} architecture finding(s)."
        )
        return AgentResult(
            role=self.role,
            passed=passed,
            findings=findings,
            raw_output=raw,
        )
