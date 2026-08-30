"""
CouncilAI — FastAPI backend entry point.

Run with:
    uvicorn main:app --reload          (from the backend/ directory)

Environment variables (loaded from ../.env or the shell):
    WATSONX_API_KEY   — IBM watsonx.ai API key
    WATSONX_PROJECT_ID — IBM watsonx.ai project ID
    WATSONX_URL       — watsonx.ai endpoint URL  (optional, has a default)
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Path setup — ensure the agents package is importable from backend/
# ---------------------------------------------------------------------------
_agents_dir = os.path.join(os.path.dirname(__file__), "..", "agents")
if _agents_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_agents_dir))

from models import AgentResult, HealthResponse, ReviewRequest, ReviewResponse, Verdict  # noqa: E402

# Reversibility path patterns (mirrors relevance_weights defaults).
_REVERSIBILITY_PATTERNS = [
    "migrations/", "schema/", "api/v", "public/", "event_schemas/", ".proto",
]
_REVERSIBILITY_RATIONALE_KEYWORDS = ["migration", "schema"]
# Confidence threshold below which an APPROVE is escalated.
_LOW_CONFIDENCE_THRESHOLD = 0.4


def _extract_diff_paths(diff: str) -> list[str]:
    """Return the list of 'b/' file paths added/modified in a unified diff."""
    return re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE)


def _is_reversibility_risk(paths: list[str], rationale: str) -> bool:
    """True when any changed path matches a reversibility pattern, OR the judge
    rationale contains migration/schema keywords (fallback when no paths available)."""
    if any(pat in path for path in paths for pat in _REVERSIBILITY_PATTERNS):
        return True
    lower = rationale.lower()
    return any(kw in lower for kw in _REVERSIBILITY_RATIONALE_KEYWORDS)


def _review_confidence(results: list[AgentResult]) -> float:
    """Proxy confidence: fraction of agents that passed, used when no DB score exists."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.passed) / len(results)

# Agent pipeline imports (resolved after sys.path setup above).
from security import SecurityAgent  # noqa: E402
from architecture import ArchitectureAgent  # noqa: E402
from testing import TestingAgent  # noqa: E402
from performance import PerformanceAgent  # noqa: E402
from aggregator import aggregate, detect_conflicts  # noqa: E402
from evidence import check_evidence  # noqa: E402
from judge import judge  # noqa: E402

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()  # loads ../.env when present; safe to call if file is absent

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CouncilAI",
    description=(
        "Multi-agent code review system. "
        "Security, Architecture, and Testing agents run in parallel, "
        "then Conflict Detector → Evidence Checker → Final Judge decide APPROVE/REJECT."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,null",  # "null" = file:// origin
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness probe — returns 200 when the server is up."""
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Specialist agents (one instance per process — stateless, safe to share)
# ---------------------------------------------------------------------------

_AGENTS = [
    SecurityAgent(),
    ArchitectureAgent(),
    TestingAgent(),
    PerformanceAgent(),
]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.post("/review", response_model=ReviewResponse, tags=["review"])
async def review(request: ReviewRequest) -> ReviewResponse:
    """
    Trigger a full multi-agent code review.

    1. SecurityAgent, ArchitectureAgent, TestingAgent, and PerformanceAgent
       run in parallel (ThreadPoolExecutor).
    2. aggregate() + detect_conflicts() — Conflict Detector stage.
    3. check_evidence() — Evidence Checker stage.
    4. judge() — Final Judge stage.
    5. Returns ReviewResponse with verdict, summary, and structured details.
    """
    request_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Step 1 — run specialist agents in parallel
    # ------------------------------------------------------------------
    _log = logging.getLogger(__name__)
    results = []
    with ThreadPoolExecutor(max_workers=len(_AGENTS)) as pool:
        futures = {
            pool.submit(agent.review, request.diff, request.context): agent
            for agent in _AGENTS
        }
        for future in as_completed(futures):
            agent = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                _log.error("Agent %s timed out or raised: %s", agent.role, exc)
                results.append(
                    AgentResult(
                        role=agent.role,
                        passed=False,
                        findings=[f"Agent did not complete: {type(exc).__name__}: {exc}"],
                        raw_output="",
                    )
                )

    # Restore a stable order (security, architecture, testing, performance)
    # so that the response is deterministic regardless of thread scheduling.
    _ROLE_ORDER = {a.role: i for i, a in enumerate(_AGENTS)}
    results.sort(key=lambda r: _ROLE_ORDER.get(r.role, 99))

    # ------------------------------------------------------------------
    # Step 2 — Conflict Detector
    # ------------------------------------------------------------------
    verdicts = aggregate(results)
    conflict_report = detect_conflicts(verdicts)

    # ------------------------------------------------------------------
    # Step 3 — Evidence Checker
    # ------------------------------------------------------------------
    evidence_report = check_evidence(results)

    # ------------------------------------------------------------------
    # Step 4 — Final Judge
    # ------------------------------------------------------------------
    decision = judge(results, conflict_report, evidence_report)

    # ------------------------------------------------------------------
    # Step 5 — Escalation rules
    # ------------------------------------------------------------------
    final_verdict = decision.verdict
    diff_paths = _extract_diff_paths(request.diff)
    reversibility_risk = _is_reversibility_risk(diff_paths, decision.rationale)
    confidence = _review_confidence(results)
    low_confidence_approve = (
        final_verdict == Verdict.APPROVE and confidence < _LOW_CONFIDENCE_THRESHOLD
    )

    if reversibility_risk and final_verdict == Verdict.REJECT:
        final_verdict = Verdict.ESCALATE_TO_HUMAN
    elif low_confidence_approve:
        final_verdict = Verdict.ESCALATE_TO_HUMAN

    # ------------------------------------------------------------------
    # Step 6 — Build response
    # ------------------------------------------------------------------
    failed_roles = [r.role.value for r in results if not r.passed]
    passed_roles = [r.role.value for r in results if r.passed]
    summary = (
        f"{final_verdict.value}: "
        + (
            f"{len(failed_roles)} agent(s) failed ({', '.join(failed_roles)})."
            if failed_roles
            else "all agents passed."
        )
    )

    details: dict = {
        "agents": {
            r.role.value: {
                "passed": r.passed,
                "findings": r.findings,
            }
            for r in results
        },
        "conflicts": {
            "has_conflicts": conflict_report.has_conflicts,
            "conflicts": conflict_report.conflicts,
        },
        "evidence": {
            "supported_findings": evidence_report.supported_findings,
            "unsupported_findings": evidence_report.unsupported_findings,
        },
        "rationale": decision.rationale,
    }

    return ReviewResponse(
        request_id=request_id,
        verdict=final_verdict,
        summary=summary,
        details=details,
    )
