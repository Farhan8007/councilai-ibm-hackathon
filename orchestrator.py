"""
Pipeline orchestrator for CouncilAI.

This is Person B's most critical Hour 4-9 deliverable: POST /review/{pr_id}
must be callable end-to-end (fetch diff -> parse -> classify -> fire all 4
agents in parallel -> collect verdicts -> store to DB) even while some
downstream pieces (conflict detection, evidence judge, verdict synthesis —
Person A, Hour 9-14 / 14-19) are still stubs. Every step is written to
AuditLog so the trace is queryable from hour 1 onward.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from aggregator import store_opinions
from agent_client import run_council
from classifier import classify_change
from diff_parser import build_diff_schema, parse_diff
from embedding import embed_diff
from github_client import fetch_pr_diff
from models import AuditLog, ChangedFile, ChangeTypeEnum, Conflict, Review
from precedent_engine import apply_precedent_boost
from pr_commenter import post_verdict_to_github
from relevance_weights import get_weights
from verdict_engine import synthesize_verdict

logger = logging.getLogger(__name__)


def _log_step(db: Session, review_id: int, step: str, data: Dict[str, Any]) -> None:
    db.add(AuditLog(review_id=review_id, step=step, data=data))
    db.commit()


async def run_pipeline(
    db: Session,
    repo: str,
    pr_number: int,
    pr_title: Optional[str] = None,
    pr_url: Optional[str] = None,
    commit_sha: Optional[str] = None,
    diff_text_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full CouncilAI review pipeline for one PR.

    If `diff_text_override` is provided (used by the /review/test fixture
    endpoint), the GitHub fetch step is skipped — this is how Person A can
    exercise the agent pipeline without a live PR.

    Returns: {review_id, verdicts: [...], conflict_count, status}
    """
    owner = repo.split("/")[0] if "/" in repo else repo

    review = Review(
        repo=repo,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_url=pr_url,
        commit_sha=commit_sha,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    review_id = review.id

    try:
        # ---- 1. Fetch diff ----
        review.status = "fetching_diff"
        db.commit()

        if diff_text_override is not None:
            diff_text = diff_text_override
        else:
            owner_name, repo_name = repo.split("/", 1)
            diff_text = await fetch_pr_diff(owner_name, repo_name, pr_number)

        if not diff_text:
            review.status = "failed"
            db.commit()
            _log_step(db, review_id, "diff_fetch_failed", {"repo": repo, "pr_number": pr_number})
            return {"review_id": review_id, "verdicts": [], "conflict_count": 0, "status": "failed",
                     "error": "Could not fetch diff"}

        review.diff_text = diff_text
        db.commit()
        _log_step(db, review_id, "diff_fetched", {"chars": len(diff_text)})

        # ---- 1b. Embed diff (feeds the precedent engine, Hour 9-14) ----
        try:
            vector = embed_diff(diff_text)
            review.diff_embedding = vector
            db.commit()
            _log_step(db, review_id, "diff_embedded", {"dim": len(vector) if vector else 0})
        except Exception as e:
            logger.warning(f"Embedding step failed, continuing without it: {e}")
            _log_step(db, review_id, "diff_embedding_failed", {"error": str(e)})

        # ---- 2. Parse diff ----
        review.status = "parsing"
        db.commit()

        changed_files, stats = parse_diff(diff_text)
        for file_info in changed_files:
            db.add(ChangedFile(
                review_id=review_id,
                file_path=file_info.path,
                language=file_info.language,
                old_lines_start=file_info.old_lines[0] if file_info.old_lines else None,
                old_lines_end=file_info.old_lines[1] if file_info.old_lines else None,
                new_lines_start=file_info.new_lines[0] if file_info.new_lines else None,
                new_lines_end=file_info.new_lines[1] if file_info.new_lines else None,
                is_binary=file_info.is_binary,
                is_renamed=file_info.is_renamed,
                is_deleted=file_info.is_deleted,
                hunk_context=file_info.hunk_context,
                hunks_json=file_info.structured_hunks,
            ))
        db.commit()
        _log_step(db, review_id, "diff_parsed", {**stats})

        # ---- 3. Classify change ----
        review.status = "classifying"
        db.commit()

        diff_schema = build_diff_schema(pr_id=pr_number, repo=repo, diff_text=diff_text)
        classification = classify_change(diff_schema)
        diff_schema["change_type"] = classification["type"]
        diff_schema["change_confidence"] = classification["confidence"]

        try:
            review.change_type = ChangeTypeEnum(classification["type"])
        except ValueError:
            review.change_type = ChangeTypeEnum.UNKNOWN
        review.change_confidence = classification["confidence"]
        review.change_reasoning = classification["reasoning"]
        db.commit()
        _log_step(db, review_id, "change_classified", classification)

        # ---- 4. Fire agents in parallel ----
        review.status = "reviewing"
        db.commit()

        verdicts = await run_council(diff_schema)
        _log_step(db, review_id, "agents_completed", {
            name: {"decision": v.get("decision"), "confidence": v.get("confidence"), "is_timeout": v.get("is_timeout")}
            for name, v in verdicts.items()
        })

        # ---- 5. Aggregate + persist opinions ----
        aggregated = store_opinions(db, review_id, verdicts)
        _log_step(db, review_id, "opinions_stored", {"count": len(aggregated["verdicts"])})

        # ---- 6. Precedent lookup + weight boost ----
        base_weights = get_weights(classification["type"])
        precedent_result = apply_precedent_boost(db, review.diff_embedding, base_weights)
        _log_step(db, review_id, "precedent_checked", {
            "precedents_found": len(precedent_result["precedents"]),
            "boosted": precedent_result["boosted"],
        })

        # ---- 7. Verdict synthesis (provisional — see verdict_engine.py docstring) ----
        changed_file_paths = [cf.path for cf in changed_files]
        verdict = synthesize_verdict(
            db=db, review_id=review_id, change_type=classification["type"],
            weights=precedent_result["weights"], changed_file_paths=changed_file_paths,
        )
        _log_step(db, review_id, "verdict_synthesized", {
            "decision": verdict.final_decision.value,
            "confidence": verdict.final_confidence,
            "escalate": verdict.escalate_to_human,
        })

        review.status = "verdict_complete"
        db.commit()

        # ---- 8. Post to GitHub (skipped for fixture/test runs with no commit_sha) ----
        github_result = {"posted": False, "response": None}
        if review.commit_sha and diff_text_override is None:
            try:
                valid_line_ranges = _build_valid_line_ranges(changed_files)
                github_result = await post_verdict_to_github(
                    db=db, review=review, verdict=verdict,
                    valid_line_ranges=valid_line_ranges,
                    precedents=precedent_result["precedents"],
                )
                _log_step(db, review_id, "github_comment_posted", {"posted": github_result["posted"]})
            except Exception as e:
                logger.error(f"GitHub comment post failed for review {review_id}: {e}", exc_info=True)
                _log_step(db, review_id, "github_comment_failed", {"error": str(e)})

        review.status = "complete"
        db.commit()

        aggregated["change_type"] = classification["type"]
        aggregated["conflict_count"] = db.query(Conflict).filter(Conflict.review_id == review_id).count()
        aggregated["verdict"] = {
            "decision": verdict.final_decision.value,
            "confidence": verdict.final_confidence,
            "escalate_to_human": verdict.escalate_to_human,
        }
        aggregated["github_comment_posted"] = github_result["posted"]
        aggregated["status"] = "complete"
        return aggregated

    except Exception as e:
        logger.error(f"Pipeline failed for review {review_id}: {e}", exc_info=True)
        review.status = "failed"
        db.commit()
        _log_step(db, review_id, "pipeline_error", {"error": str(e)})
        return {"review_id": review_id, "verdicts": [], "conflict_count": 0, "status": "failed", "error": str(e)}


def _build_valid_line_ranges(changed_files) -> Dict[str, set]:
    """file_path -> set of new-file line numbers that are add/context lines
    in a changed hunk, i.e. valid targets for a GitHub inline comment."""
    ranges: Dict[str, set] = {}
    for f in changed_files:
        lines = set()
        for hunk in f.structured_hunks:
            cursor = hunk.get("target_start", 1)
            for line in hunk.get("lines", []):
                if line["type"] in ("add", "ctx"):
                    lines.add(cursor)
                    cursor += 1
        ranges[f.path] = lines
    return ranges
