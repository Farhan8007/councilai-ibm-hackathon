"""
Precedent engine for CouncilAI (Hours 9-14, Person B).

Embeds the current diff (already done in orchestrator.py via embedding.py
and stored on Review.diff_embedding), searches pgvector for the top-3
most similar past PrecedentDecision rows, and — if similarity exceeds the
configured threshold — boosts the matching agent's relevance weight.

Per the plan's explicit advice: vector similarity on a tiny hackathon
dataset is unreliable, so `seed_demo_precedents()` manually inserts a
handful of precedents that are guaranteed to match the 3 demo PRs almost
exactly (same diff text -> same deterministic pseudo-embedding when no
watsonx key is set, or a real close match when it is set) so the
precedent engine visibly fires during the live demo.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from embedding import embed_diff
from models import DecisionEnum, PrecedentDecision
from relevance_weights import get_precedent_config

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def find_similar_precedents(db: Session, embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
    """
    pgvector cosine-similarity search: returns up to top_k precedents with
    their similarity score (1 - cosine_distance), highest first.
    Uses the pgvector `<=>` cosine distance operator directly since the
    ORM's Vector type doesn't expose a comparator for it.
    """
    if not embedding:
        return []

    vector_literal = "[" + ",".join(str(x) for x in embedding) + "]"

    rows = db.execute(
        text(
            """
            SELECT id, decision, reasoning, is_human_override,
                   1 - (diff_embedding <=> :vec) AS similarity
            FROM precedent_decisions
            WHERE diff_embedding IS NOT NULL
            ORDER BY diff_embedding <=> :vec
            LIMIT :k
            """
        ),
        {"vec": vector_literal, "k": top_k},
    ).fetchall()

    return [
        {
            "id": r.id,
            "decision": r.decision,
            "reasoning": r.reasoning,
            "is_human_override": r.is_human_override,
            "similarity": round(float(r.similarity), 4),
        }
        for r in rows
    ]


def apply_precedent_boost(
    db: Session,
    embedding: Optional[List[float]],
    weights: Dict[str, float],
) -> Dict[str, Any]:
    """
    Looks up similar precedents and, if the top match clears the
    configured similarity threshold, boosts every agent's weight by the
    configured multiplier (the plan doesn't specify a per-agent boost
    target, so this boosts the whole matrix uniformly — simplest correct
    reading of "boost matching agent's confidence weight").

    Returns: {"precedents": [...], "boosted": bool, "weights": adjusted_weights}
    """
    cfg = get_precedent_config()
    threshold = cfg.get("similarity_boost_threshold", 0.85)
    multiplier = cfg.get("similarity_boost_multiplier", 1.5)

    precedents = find_similar_precedents(db, embedding) if embedding else []
    boosted = bool(precedents) and precedents[0]["similarity"] > threshold

    adjusted_weights = dict(weights)
    if boosted:
        adjusted_weights = {agent: w * multiplier for agent, w in weights.items()}
        logger.info(f"Precedent boost applied: top match similarity={precedents[0]['similarity']}")

    return {"precedents": precedents, "boosted": boosted, "weights": adjusted_weights}


# ===== DEMO SEEDING =====

_DEMO_PRECEDENTS = [
    {
        "fixture": "demo_pr_1_clean.diff",
        "decision": DecisionEnum.APPROVE,
        "reasoning": "Minor bug fix, all 4 agents agreed, no security or architectural concerns raised.",
        "is_human_override": False,
    },
    {
        "fixture": "demo_pr_2_conflict.diff",
        "decision": DecisionEnum.REJECT,
        "reasoning": "Security agent flagged SQL injection (3.0x weight on auth_change); overruled Architecture's APPROVE.",
        "is_human_override": False,
    },
    {
        "fixture": "demo_pr_2_conflict.diff",
        "decision": DecisionEnum.REJECT,
        "reasoning": "A near-identical auth-path SQL injection fix from a prior sprint, human-confirmed REJECT.",
        "is_human_override": True,
        "original_verdict": DecisionEnum.WARN,
        "human_decision": DecisionEnum.REJECT,
        "override_reason": "Automated verdict under-weighted the injection risk; human reviewer escalated.",
    },
    {
        "fixture": "demo_pr_3_schema_migration.diff",
        "decision": DecisionEnum.ESCALATE_TO_HUMAN,
        "reasoning": "Schema migration touching migrations/ — reversibility risk, prior migration of this shape needed a human sign-off.",
        "is_human_override": False,
    },
    {
        "fixture": "demo_pr_hour9_sync.diff",
        "decision": DecisionEnum.REJECT,
        "reasoning": "SQL injection + untested function + O(n^2) loop — same shape as this fixture, rejected previously.",
        "is_human_override": False,
    },
]


def seed_demo_precedents(db: Session) -> int:
    """
    Idempotent: skips a fixture if a precedent with the same diff_text_hash
    already exists. Returns the number of rows inserted.
    """
    inserted = 0
    for entry in _DEMO_PRECEDENTS:
        fixture_path = FIXTURES_DIR / entry["fixture"]
        if not fixture_path.exists():
            logger.warning(f"Precedent seed skipped, fixture missing: {fixture_path}")
            continue

        diff_text = fixture_path.read_text()
        diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

        existing = (
            db.query(PrecedentDecision)
            .filter(PrecedentDecision.diff_text_hash == diff_hash, PrecedentDecision.reasoning == entry["reasoning"])
            .first()
        )
        if existing:
            continue

        vector = embed_diff(diff_text)
        db.add(PrecedentDecision(
            diff_embedding=vector,
            diff_text_hash=diff_hash,
            decision=entry["decision"],
            reasoning=entry["reasoning"],
            is_human_override=entry.get("is_human_override", False),
            original_verdict=entry.get("original_verdict"),
            human_decision=entry.get("human_decision"),
            override_reason=entry.get("override_reason"),
        ))
        inserted += 1

    db.commit()
    logger.info(f"Seeded {inserted} precedent decisions")
    return inserted


if __name__ == "__main__":
    from models import get_db_session, init_db

    init_db()
    session = get_db_session()
    try:
        n = seed_demo_precedents(session)
        print(f"✓ Seeded {n} new precedent decisions")
    finally:
        session.close()
