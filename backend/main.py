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

import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from models import HealthResponse, ReviewRequest, ReviewResponse, Verdict

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


@app.post("/review", response_model=ReviewResponse, tags=["review"])
async def review(request: ReviewRequest) -> ReviewResponse:
    """
    Trigger a full multi-agent code review.

    This is a stub that will be wired to the specialist agents,
    Conflict Detector, Evidence Checker, and Final Judge in later tasks.
    """
    # Placeholder: returns PENDING until the agent pipeline is implemented.
    request_id = str(uuid.uuid4())
    return ReviewResponse(
        request_id=request_id,
        verdict=Verdict.PENDING,
        summary="Agent pipeline not yet implemented.",
        details={},
    )
