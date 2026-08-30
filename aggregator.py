"""
Opinion aggregator for CouncilAI.

Collects the 4 agent verdicts, normalizes + persists them as Opinion /
Citation rows, and returns a simple aggregated response. Deliberately
contains NO conflict-detection or evidence-weighting logic — that is
Person A's Hour 9-14 deliverable (conflict_detector.py / evidence_judge.py).
This module only guarantees every review has 4 clean Opinion rows to
build on.
"""

import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from models import Citation, Opinion, DecisionEnum, SeverityEnum

logger = logging.getLogger(__name__)


def store_opinions(db: Session, review_id: int, verdicts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Persist each agent's verdict as an Opinion row (with nested Citation
    rows), then return the aggregated response shape:
        {review_id, verdicts: [...], conflict_count: 0, change_type: str}
    """
    stored = []

    for agent_name, verdict in verdicts.items():
        decision_raw = verdict.get("decision", "WARN")
        try:
            decision = DecisionEnum(decision_raw)
        except ValueError:
            logger.warning(f"Unrecognized decision '{decision_raw}' from {agent_name}, defaulting to WARN")
            decision = DecisionEnum.WARN

        severity_raw = verdict.get("severity")
        severity = None
        if severity_raw:
            try:
                severity = SeverityEnum(severity_raw)
            except ValueError:
                severity = None

        opinion = Opinion(
            review_id=review_id,
            agent_name=agent_name,
            decision=decision,
            confidence=float(verdict.get("confidence", 0.0)),
            severity=severity,
            reasoning_text=verdict.get("reasoning", ""),
            citations_json=verdict.get("citations", []),
            is_timeout=bool(verdict.get("is_timeout", False)),
        )
        db.add(opinion)
        db.flush()  # get opinion.id before creating citations

        for c in verdict.get("citations", []):
            db.add(Citation(
                opinion_id=opinion.id,
                file_path=c.get("file", ""),
                line_start=c.get("line_start", 0),
                line_end=c.get("line_end", c.get("line_start", 0)),
                evidence_type=c.get("evidence_type"),
                description=c.get("description"),
                snippet=c.get("snippet"),
            ))

        stored.append({
            "agent_name": agent_name,
            "decision": decision.value,
            "confidence": opinion.confidence,
            "severity": severity.value if severity else None,
            "is_timeout": opinion.is_timeout,
        })

    db.commit()

    return {
        "review_id": review_id,
        "verdicts": stored,
        "conflict_count": 0,  # populated later by Person A's conflict detector
        "status": "opinions_collected",
    }
