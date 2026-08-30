"""
Verdict engine for CouncilAI.

PROVISIONAL implementation of Person A's Hour 9-14 / 14-19 deliverables
(conflict detector + Evidence Judge + verdict synthesis), written so the
rest of the pipeline (GitHub commenter, dashboard) has a real Verdict row
to render from hour 9 onward instead of blocking on it. The formula below
follows the plan's exact spec:

    adjusted_confidence = confidence * (0.4 + 0.6 * evidence_quality)
    weighted_score = sum(weight * adjusted_confidence * decision_sign)
    decision_sign: APPROVE=+1, REJECT=-1, WARN=0
    final: APPROVE if weighted_score > 0.5, REJECT if < -0.5, else REQUEST_CHANGES
    escalate if reversibility risk OR final_confidence < threshold

Person A's real Evidence Judge should replace the internals of
synthesize_verdict() with the 5-type conflict detector and reversibility
classifier from the plan — the function signature (review, opinions) ->
Verdict-shaped dict stays the same so nothing downstream needs to change.
"""

import logging
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import (
    Conflict, ConflictSeverityEnum, ConflictTypeEnum, DecisionEnum,
    Opinion, Verdict,
)
from relevance_weights import get_low_confidence_threshold, get_reversibility_patterns

logger = logging.getLogger(__name__)

_DECISION_SIGN = {DecisionEnum.APPROVE: 1, DecisionEnum.REJECT: -1, DecisionEnum.WARN: 0}
_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _evidence_quality(citations: Any) -> float:
    if not citations:
        return 0.1
    has_snippet = any(c.get("snippet") for c in citations) if isinstance(citations, list) else False
    return 1.0 if has_snippet else 0.5


def _detect_conflicts(opinions: List[Opinion]) -> List[Dict[str, Any]]:
    """Basic pairwise conflict detection: decision coexistence + severity gap.
    A stand-in for Person A's full 5-type detector."""
    conflicts = []
    for i in range(len(opinions)):
        for j in range(i + 1, len(opinions)):
            a, b = opinions[i], opinions[j]
            if a.decision == DecisionEnum.APPROVE and b.decision == DecisionEnum.REJECT or \
               a.decision == DecisionEnum.REJECT and b.decision == DecisionEnum.APPROVE:
                conflicts.append({
                    "conflict_type": ConflictTypeEnum.DECISION_COEXISTENCE,
                    "severity": ConflictSeverityEnum.BLOCKING,
                    "agent_a": a.agent_name, "agent_b": b.agent_name,
                    "divergence_score": 1.0,
                    "description": f"{a.agent_name} says {a.decision.value}, {b.agent_name} says {b.decision.value}.",
                })
            if a.severity and b.severity:
                gap = abs(_SEVERITY_RANK.get(a.severity.value, 0) - _SEVERITY_RANK.get(b.severity.value, 0))
                if gap > 1:
                    conflicts.append({
                        "conflict_type": ConflictTypeEnum.SEVERITY_GAP,
                        "severity": ConflictSeverityEnum.ADVISORY,
                        "agent_a": a.agent_name, "agent_b": b.agent_name,
                        "divergence_score": gap / 3.0,
                        "description": f"{a.agent_name} rated {a.severity.value}, {b.agent_name} rated {b.severity.value}.",
                    })
            if abs(a.confidence - b.confidence) > 0.4:
                conflicts.append({
                    "conflict_type": ConflictTypeEnum.CONFIDENCE_DELTA,
                    "severity": ConflictSeverityEnum.MINOR,
                    "agent_a": a.agent_name, "agent_b": b.agent_name,
                    "divergence_score": abs(a.confidence - b.confidence),
                    "description": f"Confidence delta {abs(a.confidence - b.confidence):.2f} between {a.agent_name} and {b.agent_name}.",
                })
    return conflicts


def _is_reversibility_risk(changed_file_paths: List[str]) -> bool:
    patterns = get_reversibility_patterns()
    return any(pattern in path for path in changed_file_paths for pattern in patterns)


def _build_reasoning_trace(opinions: List[Opinion], weights: Dict[str, float], weighted_score: float,
                            conflicts: List[Dict[str, Any]], final_decision: DecisionEnum) -> str:
    lines = [f"CouncilAI verdict: {final_decision.value}", ""]
    for op in opinions:
        w = weights.get(op.agent_name, 1.0)
        lines.append(
            f"- {op.agent_name} ({w}x weight): {op.decision.value}, "
            f"confidence={op.confidence:.2f} -> adjusted={op.adjusted_confidence:.2f}"
        )
        if op.reasoning_text:
            lines.append(f"    \"{op.reasoning_text[:200]}\"")
    lines.append("")
    lines.append(f"Weighted score: {weighted_score:.3f}")
    if conflicts:
        lines.append(f"{len(conflicts)} conflict(s) detected:")
        for c in conflicts:
            lines.append(f"  - [{c['severity'].value}] {c['description']}")
    else:
        lines.append("No conflicts detected among agents.")
    return "\n".join(lines)


def synthesize_verdict(
    db: Session,
    review_id: int,
    change_type: str,
    weights: Dict[str, float],
    changed_file_paths: List[str],
) -> Verdict:
    """
    Reads all Opinion rows for review_id, computes adjusted confidence,
    weighted score, detects basic conflicts, decides APPROVE / REJECT /
    REQUEST_CHANGES / ESCALATE_TO_HUMAN, writes Conflict + Verdict rows,
    and returns the Verdict.
    """
    opinions = db.query(Opinion).filter(Opinion.review_id == review_id).all()

    weighted_score = 0.0
    for op in opinions:
        quality = _evidence_quality(op.citations_json)
        op.adjusted_confidence = round(op.confidence * (0.4 + 0.6 * quality), 4)
        weight = weights.get(op.agent_name, 1.0)
        op.relevance_weight = weight
        sign = _DECISION_SIGN.get(op.decision, 0)
        weighted_score += weight * op.adjusted_confidence * sign
    db.commit()

    conflict_dicts = _detect_conflicts(opinions)
    for c in conflict_dicts:
        db.add(Conflict(review_id=review_id, **c))
    db.commit()

    if weighted_score > 0.5:
        final_decision = DecisionEnum.APPROVE
    elif weighted_score < -0.5:
        final_decision = DecisionEnum.REJECT
    else:
        final_decision = DecisionEnum.REQUEST_CHANGES

    final_confidence = round(min(1.0, abs(weighted_score) / max(1.0, sum(weights.values()))), 4)

    reversibility_risk = _is_reversibility_risk(changed_file_paths)
    low_confidence = final_confidence < get_low_confidence_threshold()
    escalate = reversibility_risk or low_confidence
    escalation_reason = None
    if escalate:
        if reversibility_risk:
            escalation_reason = "Reversibility risk: change touches a schema/migration/public-API path."
        else:
            escalation_reason = f"Low confidence ({final_confidence}) below threshold."
        final_decision = DecisionEnum.ESCALATE_TO_HUMAN

    reasoning = _build_reasoning_trace(opinions, weights, weighted_score, conflict_dicts, final_decision)

    verdict = Verdict(
        review_id=review_id,
        final_decision=final_decision,
        final_confidence=final_confidence,
        weighted_score=round(weighted_score, 4),
        reasoning_text=reasoning,
        audit_log_json=[{
            "agent": op.agent_name, "decision": op.decision.value,
            "confidence": op.confidence, "adjusted_confidence": op.adjusted_confidence,
            "weight": weights.get(op.agent_name, 1.0),
        } for op in opinions],
        escalate_to_human=escalate,
        escalation_reason=escalation_reason,
    )
    db.add(verdict)
    db.commit()
    db.refresh(verdict)
    return verdict
