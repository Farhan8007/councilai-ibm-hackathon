"""
Verdict engine for CouncilAI.

Wires the real CouncilAI pipeline into synthesize_verdict():

    1. Convert each Opinion DB row → AgentResult (Pydantic)
    2. Run the pipeline stages:
          aggregate()        → {AgentRole: passed}
          detect_conflicts() → ConflictReport
          check_evidence()   → EvidenceReport
          judge()            → JudgeDecision (APPROVE | REJECT)
    3. Map judge verdict → DecisionEnum for the initial final_decision.
    4. Retain existing DB-level work:
          - adjusted_confidence / relevance_weight written back to Opinion rows
          - weighted_score computed from the weight matrix
          - Conflict rows persisted (from the DB-level pairwise detector)
          - Escalation rules (reversibility risk, low confidence) can promote
            final_decision to ESCALATE_TO_HUMAN
          - audit_log_json, reasoning_text, Verdict row all written as before

The function signature (db, review_id, change_type, weights, changed_file_paths)
→ Verdict is unchanged so no caller (orchestrator.py, tests) needs updating.
"""

import importlib.util
import logging
import sys
import os
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import (
    Conflict, ConflictSeverityEnum, ConflictTypeEnum, DecisionEnum,
    Opinion, Verdict,
)
from relevance_weights import get_low_confidence_threshold, get_reversibility_patterns

# ---------------------------------------------------------------------------
# Bootstrap: import backend/models.py (Pydantic) under a distinct module name
# so it never clobbers the root models.py (SQLAlchemy) in sys.modules.
# ---------------------------------------------------------------------------

def _import_backend_models():
    """Load backend/models.py explicitly, cached under 'backend.models'."""
    key = "backend.models"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key,
        os.path.join(os.path.dirname(__file__), "backend", "models.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


_bm = _import_backend_models()
AgentResult = _bm.AgentResult
AgentRole = _bm.AgentRole
PipelineVerdict = _bm.Verdict

# Add agents/ to sys.path so the pipeline functions (aggregator, evidence, judge)
# are importable.  They themselves inject backend/ onto sys.path so that their
# own `from models import ...` picks up backend/models.py correctly.
_agents_dir = os.path.join(os.path.dirname(__file__), "agents")
if _agents_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_agents_dir))

# Ensure backend/ is also on sys.path for the agents' own imports.
_backend_dir = os.path.join(os.path.dirname(__file__), "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from aggregator import aggregate, detect_conflicts  # noqa: E402
from evidence import check_evidence  # noqa: E402
from judge import judge  # noqa: E402

logger = logging.getLogger(__name__)

_DECISION_SIGN = {DecisionEnum.APPROVE: 1, DecisionEnum.REJECT: -1, DecisionEnum.WARN: 0}
_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

# Maps opinion.agent_name strings → pipeline AgentRole enum values.
_AGENT_NAME_TO_ROLE: Dict[str, AgentRole] = {
    role.value: role for role in AgentRole
}


# ---------------------------------------------------------------------------
# Opinion → AgentResult conversion
# ---------------------------------------------------------------------------

def _opinion_to_agent_result(op: Opinion) -> AgentResult:
    """Convert a DB Opinion row to the pipeline's AgentResult Pydantic model.

    Mapping rules (per task spec):
      - agent_name → AgentRole  (falls back to SECURITY if name is unknown)
      - APPROVE decision → passed=True; all other decisions → passed=False
      - reasoning_text → raw_output
      - citations_json[*].description → findings (when available)
    """
    role = _AGENT_NAME_TO_ROLE.get(
        (op.agent_name or "").lower(),
        AgentRole.SECURITY,
    )

    passed = op.decision == DecisionEnum.APPROVE

    raw_output = op.reasoning_text or ""

    # Extract citation descriptions as findings when present.
    findings: List[str] = []
    if op.citations_json and isinstance(op.citations_json, list):
        for citation in op.citations_json:
            if isinstance(citation, dict):
                desc = citation.get("description", "")
                if desc:
                    findings.append(desc)

    return AgentResult(
        role=role,
        passed=passed,
        findings=findings,
        raw_output=raw_output,
    )


# ---------------------------------------------------------------------------
# Pipeline verdict → DecisionEnum
# ---------------------------------------------------------------------------

def _pipeline_verdict_to_decision(pipeline_verdict: PipelineVerdict) -> DecisionEnum:
    """Map the Final Judge's APPROVE/REJECT to DecisionEnum."""
    if pipeline_verdict == PipelineVerdict.APPROVE:
        return DecisionEnum.APPROVE
    return DecisionEnum.REJECT


# ---------------------------------------------------------------------------
# DB-level helpers (unchanged from original)
# ---------------------------------------------------------------------------

def _evidence_quality(citations: Any) -> float:
    if not citations:
        return 0.1
    has_snippet = any(c.get("snippet") for c in citations) if isinstance(citations, list) else False
    return 1.0 if has_snippet else 0.5


def _detect_db_conflicts(opinions: List[Opinion]) -> List[Dict[str, Any]]:
    """DB-level pairwise conflict detection: decision coexistence + severity gap.
    Produces Conflict rows — separate from the pipeline ConflictReport."""
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


def _build_reasoning_trace(
    opinions: List[Opinion],
    weights: Dict[str, float],
    weighted_score: float,
    db_conflict_dicts: List[Dict[str, Any]],
    pipeline_rationale: str,
    final_decision: DecisionEnum,
) -> str:
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
    if db_conflict_dicts:
        lines.append(f"{len(db_conflict_dicts)} DB conflict(s) detected:")
        for c in db_conflict_dicts:
            lines.append(f"  - [{c['severity'].value}] {c['description']}")
    else:
        lines.append("No DB conflicts detected among agents.")
    lines.append("")
    lines.append("--- Pipeline judge rationale ---")
    lines.append(pipeline_rationale)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize_verdict(
    db: Session,
    review_id: int,
    change_type: str,
    weights: Dict[str, float],
    changed_file_paths: List[str],
) -> Verdict:
    """
    Reads all Opinion rows for review_id, runs the full CouncilAI pipeline
    (aggregate → detect_conflicts → check_evidence → judge), computes adjusted
    confidence and weighted score, persists Conflict rows, decides on the
    final DecisionEnum (subject to escalation rules), writes the Verdict row,
    and returns it.
    """
    opinions = db.query(Opinion).filter(Opinion.review_id == review_id).all()

    # ------------------------------------------------------------------
    # 1. DB-level confidence adjustments and weighted score (unchanged)
    # ------------------------------------------------------------------
    weighted_score = 0.0
    for op in opinions:
        quality = _evidence_quality(op.citations_json)
        op.adjusted_confidence = round(op.confidence * (0.4 + 0.6 * quality), 4)
        weight = weights.get(op.agent_name, 1.0)
        op.relevance_weight = weight
        sign = _DECISION_SIGN.get(op.decision, 0)
        weighted_score += weight * op.adjusted_confidence * sign
    db.commit()

    # ------------------------------------------------------------------
    # 2. DB-level conflict rows (pairwise detector, writes Conflict table)
    # ------------------------------------------------------------------
    db_conflict_dicts = _detect_db_conflicts(opinions)
    for c in db_conflict_dicts:
        db.add(Conflict(review_id=review_id, **c))
    db.commit()

    # ------------------------------------------------------------------
    # 3. CouncilAI pipeline: Opinion → AgentResult → pipeline stages
    # ------------------------------------------------------------------
    agent_results = [_opinion_to_agent_result(op) for op in opinions]

    verdicts_map = aggregate(agent_results)
    conflict_report = detect_conflicts(verdicts_map)
    evidence_report = check_evidence(agent_results)
    judge_decision = judge(agent_results, conflict_report, evidence_report)

    # Map pipeline APPROVE/REJECT → DecisionEnum
    final_decision = _pipeline_verdict_to_decision(judge_decision.verdict)

    # ------------------------------------------------------------------
    # 4. Confidence and escalation rules (unchanged)
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # 5. Build reasoning trace incorporating both DB conflicts and pipeline
    # ------------------------------------------------------------------
    reasoning = _build_reasoning_trace(
        opinions, weights, weighted_score, db_conflict_dicts,
        judge_decision.rationale, final_decision,
    )

    # ------------------------------------------------------------------
    # 6. Persist Verdict row (unchanged)
    # ------------------------------------------------------------------
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
