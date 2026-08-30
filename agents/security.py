"""
Security specialist agent — powered by IBM watsonx.ai (Llama 3.3 70B).

When a WatsonxClient is injected, uses the LLM for deep security analysis.
Falls back to deterministic regex heuristics when no client is available
(e.g. CI without credentials).
"""

from __future__ import annotations
import sys, os, re

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_backend = os.path.join(_root, "backend")
_services = os.path.join(_root, "services")
for _p in (_backend, _services):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from base import BaseAgent
from models import AgentResult, AgentRole
from watsonx_client import WatsonxClient

SYSTEM_PROMPT = """You are the Security specialist in the CouncilAI multi-agent code review pipeline.
Analyse the unified diff and identify security vulnerabilities in ADDED lines (+) only.

Check for:
1. Hard-coded credentials (passwords, API keys, secrets in string literals)
2. Code injection (eval, exec, pickle.loads, shell=True, os.system)
3. SQL injection (user input concatenated into SQL strings)
4. Non-TLS URLs (http:// in non-test code)
5. Hard-coded IP addresses in network calls

Rules:
- Only flag added lines (starting with +)
- Do NOT flag os.getenv() calls, ORM queries, or test file mocks
- Be precise — only flag what you can clearly see in the diff

Respond in this exact JSON format only, no prose:
{"passed": true/false, "findings": ["finding 1", "finding 2"], "raw_output": "brief summary"}

If no issues found: {"passed": true, "findings": [], "raw_output": "No security issues found."}"""

# ---------------------------------------------------------------------------
# Deterministic fallback patterns (used when no WatsonxClient is injected)
# ---------------------------------------------------------------------------
_CRED_RE = re.compile(
    r'(password|passwd|secret|api_key|token|auth)\s*=\s*["\'][^"\']{3,}["\']',
    re.IGNORECASE,
)
_DANGEROUS_RE = re.compile(r'\beval\s*\(|\bexec\s*\(|\bpickle\.loads\s*\(|shell\s*=\s*True|os\.system\s*\(')
_HTTP_RE = re.compile(r'http://(?!localhost|127\.0\.0\.1)')
_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')


class SecurityAgent(BaseAgent):
    role = AgentRole.SECURITY

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
        for lineno, line in enumerate(diff.splitlines(), start=1):
            if not (line.startswith("+") and not line.startswith("+++")):
                continue
            stripped = line[1:]
            if _CRED_RE.search(stripped):
                findings.append(f"Line {lineno}: possible hardcoded credential — {stripped.strip()[:80]}")
            if _DANGEROUS_RE.search(stripped):
                findings.append(f"Line {lineno}: dangerous call detected — {stripped.strip()[:80]}")
            if _HTTP_RE.search(stripped):
                findings.append(f"Line {lineno}: non-TLS http:// URL — {stripped.strip()[:80]}")
            if _IP_RE.search(stripped):
                findings.append(f"Line {lineno}: hardcoded IP address — {stripped.strip()[:80]}")
        passed = len(findings) == 0
        raw = "No security issues found." if passed else f"{len(findings)} security finding(s)."
        return AgentResult(role=self.role, passed=passed, findings=findings, raw_output=raw)
