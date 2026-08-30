"""
CouncilAI FastAPI Application
Main entry point for the webhook receiver and API endpoints.

Hours 0-1: Webhook + DB scaffold
Hours 1-4: HMAC validation, diff parsing, change classifier
Hours 4-9: DB schema, pipeline orchestrator, opinion aggregator
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from github_client import validate_github_webhook_signature
from models import (
    AuditLog, ChangedFile, Conflict, Opinion, PrecedentDecision,
    Review, Verdict, get_db_session, init_db,
)
from orchestrator import run_pipeline
from precedent_engine import seed_demo_precedents
from relevance_weights import get_all_weights, reload as reload_weights

# ===== SETUP =====

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifespan: initialise DB on startup."""
    try:
        init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)
        raise
    yield


app = FastAPI(
    title="CouncilAI",
    description="Multi-agent code review system with IBM watsonx",
    version="0.2.0",
    lifespan=lifespan,
)

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/dashboard-assets", StaticFiles(directory=DASHBOARD_DIR), name="dashboard-assets")


@app.get("/")
async def root():
    """Redirect to the live dashboard (no build step — served straight from dashboard/index.html)."""
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard")
async def dashboard():
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="Dashboard not built yet")
    return FileResponse(index_path)


# ===== DEPENDENCY INJECTION =====

def get_db():
    """Dependency to get database session."""
    db = get_db_session()
    try:
        yield db
    finally:
        db.close()


# ===== REQUEST/RESPONSE MODELS =====

class ReviewResponse(BaseModel):
    review_id: int
    repo: str
    pr_number: int
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str


class TestReviewRequest(BaseModel):
    """Body for POST /review/test — lets either teammate exercise the
    pipeline against a fixture diff without a live GitHub PR."""
    repo: str = "demo/councilai-demo"
    pr_number: int = 0
    pr_title: str = "Test review (fixture diff)"
    diff_text: str


DEMO_FIXTURES = {
    1: ("fixtures/demo_pr_1_clean.diff", "PR #1 — Clean approve (minor bug fix)"),
    2: ("fixtures/demo_pr_2_conflict.diff", "PR #2 — Security vs Architecture conflict"),
    3: ("fixtures/demo_pr_3_schema_migration.diff", "PR #3 — Schema migration (escalate to human)"),
}


# ===== UTILITIES =====

def extract_github_webhook_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant data from a GitHub pull_request webhook payload."""
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    return {
        "repo": f"{repo.get('owner', {}).get('login')}/{repo.get('name')}",
        "pr_number": pr.get("number"),
        "pr_title": pr.get("title"),
        "pr_url": pr.get("html_url"),
        "commit_sha": pr.get("head", {}).get("sha"),
    }


async def _run_pipeline_background(repo: str, pr_number: int, pr_title: str, pr_url: str, commit_sha: str):
    """Background-task wrapper: opens its own DB session since the
    request-scoped session is closed before the task runs."""
    db = get_db_session()
    try:
        await run_pipeline(
            db=db, repo=repo, pr_number=pr_number,
            pr_title=pr_title, pr_url=pr_url, commit_sha=commit_sha,
        )
    finally:
        db.close()


# ===== ENDPOINTS =====

@app.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """Health check endpoint. Verifies that FastAPI and database are running."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"

    return HealthResponse(status="healthy", database=db_status, version="0.2.0")


@app.post("/webhook/github", response_model=ReviewResponse)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> ReviewResponse:
    """
    GitHub webhook endpoint for PR events.

    Validates the HMAC signature, then queues the full CouncilAI pipeline
    (fetch diff -> parse -> classify -> fire agents -> aggregate) as a
    background task so the webhook responds immediately.

    Expected headers:
        X-GitHub-Event: pull_request
        X-Hub-Signature-256: sha256=...
    """
    try:
        body = await request.body()
        signature_header = request.headers.get("X-Hub-Signature-256", "")

        if not validate_github_webhook_signature(body, signature_header):
            client_host = request.client.host if request.client else "unknown"
            logger.warning(f"Invalid webhook signature from {client_host}")
            raise HTTPException(status_code=401, detail="Invalid signature")

        payload = await request.json()

        event_type = request.headers.get("X-GitHub-Event", "")
        if event_type != "pull_request":
            return ReviewResponse(
                review_id=0, repo="", pr_number=0, status="ignored",
                message=f"Event type '{event_type}' ignored (only pull_request processed)"
            )

        action = payload.get("action", "")
        if action not in ["opened", "synchronize", "reopened"]:
            return ReviewResponse(
                review_id=0, repo="", pr_number=0, status="ignored",
                message=f"Action '{action}' ignored"
            )

        webhook_data = extract_github_webhook_data(payload)
        logger.info(
            f"Received webhook for {webhook_data['repo']}#{webhook_data['pr_number']} "
            f"(action: {action})"
        )

        background_tasks.add_task(
            _run_pipeline_background,
            repo=webhook_data["repo"],
            pr_number=webhook_data["pr_number"],
            pr_title=webhook_data["pr_title"],
            pr_url=webhook_data["pr_url"],
            commit_sha=webhook_data["commit_sha"],
        )

        return ReviewResponse(
            review_id=0,
            repo=webhook_data["repo"],
            pr_number=webhook_data["pr_number"],
            status="processing",
            message="Review pipeline queued. Poll GET /review/{id} (or GET /reviews) for status.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.post("/review/{owner}/{repo_name}/{pr_number}", response_model=ReviewResponse)
async def trigger_review(
    owner: str,
    repo_name: str,
    pr_number: int,
    db: Session = Depends(get_db),
) -> ReviewResponse:
    """
    Manually trigger the pipeline for a real PR (used by demo buttons /
    Postman collection instead of waiting for a webhook). Runs
    synchronously so the response includes the aggregated verdicts —
    useful for the sync-point smoke tests in the plan.
    """
    result = await run_pipeline(db=db, repo=f"{owner}/{repo_name}", pr_number=pr_number)
    return ReviewResponse(
        review_id=result["review_id"],
        repo=f"{owner}/{repo_name}",
        pr_number=pr_number,
        status=result["status"],
        message=f"{len(result.get('verdicts', []))} opinions collected.",
    )


@app.post("/review/test")
async def trigger_test_review(body: TestReviewRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Run the pipeline against a fixture diff (e.g. test_diff.json's source
    diff, or any hand-written diff) without needing a live GitHub PR or
    webhook. This is the endpoint Person A uses to test agents against the
    real orchestrator per the Hour 4 sync note.
    """
    result = await run_pipeline(
        db=db,
        repo=body.repo,
        pr_number=body.pr_number,
        pr_title=body.pr_title,
        diff_text_override=body.diff_text,
    )
    return result


@app.post("/demo/trigger/{n}")
async def trigger_demo_pr(n: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    One-click demo trigger for the dashboard's 3 buttons (b5: demo
    polish). Runs the real pipeline against a canned fixture diff — same
    code path as a live webhook, just skipping the GitHub fetch step.
    """
    if n not in DEMO_FIXTURES:
        raise HTTPException(status_code=404, detail=f"No demo fixture #{n}. Valid: {list(DEMO_FIXTURES)}")

    fixture_path, title = DEMO_FIXTURES[n]
    full_path = os.path.join(os.path.dirname(__file__), fixture_path)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=500, detail=f"Fixture missing on disk: {fixture_path}")

    with open(full_path) as f:
        diff_text = f.read()

    result = await run_pipeline(
        db=db, repo="demo/councilai-demo", pr_number=1000 + n,
        pr_title=title, diff_text_override=diff_text,
    )
    return result


@app.get("/weights")
async def get_weights_endpoint() -> Dict[str, Any]:
    """
    Returns the current relevance weight matrix as JSON (a5 'spare time'
    item — shows judges the system is configurable, not hardcoded logic
    buried in Python). Backed by council.yaml.
    """
    return {"weights": get_all_weights()}


@app.post("/weights/reload")
async def reload_weights_endpoint() -> Dict[str, Any]:
    """Force a re-read of council.yaml without restarting the server."""
    return {"weights": reload_weights().get("weights")}


@app.post("/precedents/seed")
async def seed_precedents_endpoint(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Manually seeds the 5 demo precedent decisions from precedent_engine.py
    so the precedent engine fires reliably during the live demo (per the
    plan: vector similarity on a tiny dataset is unreliable, so these are
    hand-picked to match the 3 demo PRs almost exactly). Idempotent.
    """
    count = seed_demo_precedents(db)
    return {"seeded": count}


@app.get("/review/{review_id}")
async def get_review(review_id: int, db: Session = Depends(get_db)):
    """Get review status and data: changed files, opinions, verdict, audit trail."""
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found")

    changed_files = db.query(ChangedFile).filter(ChangedFile.review_id == review_id).all()
    opinions = db.query(Opinion).filter(Opinion.review_id == review_id).all()
    conflicts = db.query(Conflict).filter(Conflict.review_id == review_id).all()
    verdict = db.query(Verdict).filter(Verdict.review_id == review_id).first()
    audit_entries = (
        db.query(AuditLog)
        .filter(AuditLog.review_id == review_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )

    return {
        "review": {
            "id": review.id,
            "repo": review.repo,
            "pr_number": review.pr_number,
            "pr_title": review.pr_title,
            "pr_url": review.pr_url,
            "commit_sha": review.commit_sha,
            "status": review.status,
            "change_type": review.change_type.value if review.change_type else None,
            "change_confidence": review.change_confidence,
            "created_at": review.created_at.isoformat(),
        },
        "changed_files": [
            {
                "id": cf.id, "path": cf.file_path, "language": cf.language,
                "new_lines": [cf.new_lines_start, cf.new_lines_end] if cf.new_lines_start else None,
                "is_binary": cf.is_binary, "is_deleted": cf.is_deleted,
            }
            for cf in changed_files
        ],
        "opinions": [
            {
                "id": op.id, "agent_name": op.agent_name,
                "decision": op.decision.value if op.decision else None,
                "confidence": op.confidence,
                "adjusted_confidence": op.adjusted_confidence,
                "severity": op.severity.value if op.severity else None,
                "is_timeout": op.is_timeout,
            }
            for op in opinions
        ],
        "conflicts": [
            {
                "id": c.id, "conflict_type": c.conflict_type.value, "severity": c.severity.value,
                "agent_a": c.agent_a, "agent_b": c.agent_b, "divergence_score": c.divergence_score,
            }
            for c in conflicts
        ],
        "verdict": {
            "decision": verdict.final_decision.value if verdict else None,
            "confidence": verdict.final_confidence if verdict else None,
            "escalate_to_human": verdict.escalate_to_human if verdict else False,
            "github_comment_posted": verdict.github_comment_posted if verdict else False,
        } if verdict else None,
        "audit_trail": [
            {"step": a.step, "data": a.data, "ts": a.created_at.isoformat()}
            for a in audit_entries
        ],
    }


@app.get("/reviews")
async def list_reviews(limit: int = 10, offset: int = 0, db: Session = Depends(get_db)):
    """List recent reviews."""
    reviews = db.query(Review).order_by(Review.created_at.desc()).limit(limit).offset(offset).all()
    total = db.query(Review).count()

    return {
        "reviews": [
            {
                "id": r.id, "repo": r.repo, "pr_number": r.pr_number, "pr_title": r.pr_title,
                "status": r.status, "created_at": r.created_at.isoformat(),
                "verdict_status": "complete" if r.verdict else "pending",
            }
            for r in reviews
        ],
        "total": total, "limit": limit, "offset": offset,
    }


@app.get("/precedents")
async def list_precedents(limit: int = 20, db: Session = Depends(get_db)):
    """List seeded / recorded precedent decisions (precedent engine, Hour 9-14)."""
    precedents = (
        db.query(PrecedentDecision).order_by(PrecedentDecision.created_at.desc()).limit(limit).all()
    )
    return {
        "precedents": [
            {
                "id": p.id, "decision": p.decision.value, "is_human_override": p.is_human_override,
                "reasoning": p.reasoning, "created_at": p.created_at.isoformat(),
            }
            for p in precedents
        ]
    }


# ===== MAIN =====

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVER_PORT", 8000))
    host = os.getenv("SERVER_HOST", "0.0.0.0")

    logger.info(f"Starting CouncilAI on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
