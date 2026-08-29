"""
Architecture specialist agent — powered by IBM watsonx.ai (Llama 3.3 70B).

When a WatsonxClient is injected, uses the LLM for deep design analysis.
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

SYSTEM_PROMPT = """You are the Architecture specialist in the CouncilAI multi-agent code review pipeline.
Analyse the unified diff and identify architectural concerns in ADDED lines (+) only.

Check for:
1. Large functions or classes (contiguous added-line blocks > 50 lines) — suggest splitting
2. TODO / FIXME / HACK / NOQA markers left in code
3. Magic numbers (bare integer literals that should be named constants)
4. Circular import risk (module importing from its own package at top level)
5. High coupling (classes directly instantiating many other concrete classes)

Rules:
- Only flag added lines (starting with +)
- Be precise — only flag what you can clearly see in the diff
- Do NOT flag test files for magic numbers

Respond in this exact JSON format only, no prose:
{"passed": true/false, "findings": ["finding 1", "finding 2"], "raw_output": "brief summary"}

If no issues found: {"passed": true, "findings": [], "raw_output": "No architecture concerns found."}"""


_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|NOQA)\b", re.IGNORECASE)
_MAGIC_NUMBER_RE = re.compile(r"(?<!['\"\w])\b(?!0\b)\d{2,}\b(?!['\"\w])")


class ArchitectureAgent(BaseAgent):
    role = AgentRole.ARCHITECTURE

    # Maximum consecutive added lines before flagging a long function.
    _LONG_BLOCK_THRESHOLD = 50

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
