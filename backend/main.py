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
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
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
    # Step 5 — Build response
    # ------------------------------------------------------------------
    failed_roles = [r.role.value for r in results if not r.passed]
    passed_roles = [r.role.value for r in results if r.passed]
    summary = (
        f"{decision.verdict.value}: "
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
        verdict=decision.verdict,
        summary=summary,
        details=details,
    )
