"""
Security specialist agent.

Placeholder checks (no LLM required):
  - Detects common secret/credential patterns in the diff.
  - Flags use of ``eval()``, ``exec()``, ``pickle.loads``, ``shell=True``.
  - Flags hard-coded IP addresses and ``http://`` (non-TLS) URLs.

Replace ``_run_checks`` body with a watsonx/Granite call when credentials
are available; everything else (interface, imports, tests) stays the same.
"""

from __future__ import annotations

import re

from base import BaseAgent  # resolved via sys.path set in base.py
from models import AgentResult, AgentRole


# ---------------------------------------------------------------------------
# Patterns that indicate a security concern
# ---------------------------------------------------------------------------

_CREDENTIAL_RE = re.compile(
    r"(password|passwd|secret|api[_-]?key|access[_-]?token)\s*=\s*['\"][^'\"]+['\"]",
    re.IGNORECASE,
)
_DANGEROUS_CALLS_RE = re.compile(
    r"\beval\s*\(|\bexec\s*\(|pickle\.loads\s*\(|shell\s*=\s*True",
)
_HARDCODED_IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_HTTP_URL_RE = re.compile(r"http://")


class SecurityAgent(BaseAgent):
    role = AgentRole.SECURITY

    def _run_checks(self, diff: str, context: str | None) -> AgentResult:
        findings: list[str] = []

        for lineno, line in enumerate(diff.splitlines(), start=1):
            if line.startswith("-"):
                # Skip removed lines — we only care about additions.
                continue

            if _CREDENTIAL_RE.search(line):
                findings.append(
                    f"Line {lineno}: possible hard-coded credential — {line.strip()[:80]}"
                )
            if _DANGEROUS_CALLS_RE.search(line):
                findings.append(
                    f"Line {lineno}: dangerous call detected — {line.strip()[:80]}"
                )
            if _HARDCODED_IP_RE.search(line):
                findings.append(
                    f"Line {lineno}: hard-coded IP address — {line.strip()[:80]}"
                )
            if _HTTP_URL_RE.search(line):
                findings.append(
                    f"Line {lineno}: non-TLS URL (http://) — {line.strip()[:80]}"
                )

        passed = len(findings) == 0
        raw = (
            "No security issues found."
            if passed
            else f"{len(findings)} security finding(s)."
        )
        return AgentResult(
            role=self.role,
            passed=passed,
            findings=findings,
            raw_output=raw,
        )
