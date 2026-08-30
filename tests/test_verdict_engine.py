"""
Tests for verdict_engine.py — the wiring of the CouncilAI pipeline into
synthesize_verdict().

Run from the repo root:
    pytest tests/test_verdict_engine.py -v

No database or watsonx credentials required: all DB interactions are mocked
via unittest.mock so the tests are fully in-memory.
"""

from __future__ import annotations

import importlib.util as _ilu
import sys
import os
from typing import Any
from unittest.mock import MagicMock, patch
import pytest

# ── sys.path setup ──────────────────────────────────────────────────────────
# verdict_engine.py lives at the repo root; tests/ is one level down.
_root = os.path.dirname(os.path.dirname(__file__))


def _load_module(key: str, path: str):
    """Load a Python file under a specific sys.modules key, cached."""
    if key in sys.modules:
        return sys.modules[key]
    spec = _ilu.spec_from_file_location(key, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


# Load backend/models.py (Pydantic) under 'backend.models'.
# This is always available (no optional C-extensions like pgvector needed).
_bm = _load_module("backend.models", os.path.join(_root, "backend", "models.py"))
AgentRole = _bm.AgentRole
AgentResult = _bm.AgentResult
PipelineVerdict = _bm.Verdict

# Define lightweight enum stand-ins for the ORM DecisionEnum values.
# The root models.py requires pgvector (a C-extension), which may not be
# installed in the test environment.  verdict_engine.py imports DecisionEnum
# at module level from models.py (root), so we only need the *values* here
# for constructing mock Opinion objects — they don't need to be the real class.
import enum as _enum

class DecisionEnum(str, _enum.Enum):  # noqa: N801
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    WARN = "WARN"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"

class ConflictTypeEnum(str, _enum.Enum):  # noqa: N801
    DECISION_COEXISTENCE = "DECISION_COEXISTENCE"
    SEVERITY_GAP = "SEVERITY_GAP"

class ConflictSeverityEnum(str, _enum.Enum):  # noqa: N801
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"
    MINOR = "MINOR"

# Ensure repo root and agents/ are on sys.path before importing verdict_engine.
if _root not in sys.path:
    sys.path.insert(0, _root)
_agents = os.path.join(_root, "agents")
if _agents not in sys.path:
    sys.path.insert(0, _agents)

# ── Stub out optional heavy dependencies ────────────────────────────────────
# root models.py (SQLAlchemy ORM) requires pgvector and sqlalchemy.  We stub
# both so that verdict_engine.py can be imported without a DB or C-extensions.

import types as _types

def _stub_module(name: str, **attrs):
    """Insert a bare fake module under *name* if not already present."""
    if name not in sys.modules:
        m = _types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]


# pgvector stubs
_pgvector = _stub_module("pgvector")
_pgvector_sa = _stub_module("pgvector.sqlalchemy")
_pgvector_sa.Vector = lambda dim: None  # Column(Vector(384)) → no-op

# SQLAlchemy stubs — only the names root models.py uses at module level.
# Column/ForeignKey/Enum/etc. return None (column definitions are just attrs).
_noop = lambda *a, **kw: None  # noqa: E731

_sa = _stub_module(
    "sqlalchemy",
    Column=_noop, String=_noop, Integer=None, Float=None, DateTime=None,
    Text=None, JSON=None, ForeignKey=_noop, Enum=_noop, Boolean=None,
    create_engine=_noop, text=_noop,
)
_sa_ext = _stub_module("sqlalchemy.ext")
_sa_ext_decl = _stub_module("sqlalchemy.ext.declarative")

# declarative_base() must return a *class* (not a namespace) because ORM
# models inherit from it.
class _FakeBase:  # noqa: N801 — fake SQLAlchemy Base
    __tablename__ = ""
    metadata = _types.SimpleNamespace(create_all=lambda **kw: None)
    def __init_subclass__(cls, **kw): pass  # absorb __tablename__ etc.

_sa_ext_decl.declarative_base = lambda: _FakeBase

_sa_orm = _stub_module("sqlalchemy.orm")
_sa_orm.relationship = _noop
_sa_orm.sessionmaker = _noop
_sa_orm.Session = object

# dotenv stub
_stub_module("dotenv").load_dotenv = lambda: None

# Build a *merged* sys.modules['models'] that satisfies both:
#   • verdict_engine.py  → needs ORM symbols: Conflict, Opinion, DecisionEnum, …
#                          (verdict_engine.Verdict is patched in tests via unittest.mock)
#   • agents/aggregator, evidence, judge → needs Pydantic symbols: AgentResult, AgentRole,
#                                          Verdict (Pydantic enum with APPROVE/REJECT)
#
# Strategy: copy ORM symbols first, then overlay Pydantic symbols so that
# 'Verdict' resolves to the Pydantic enum (needed by judge.py: Verdict.APPROVE).
# verdict_engine.py's own 'Verdict' binding is patched in _run() so the ORM
# class is never needed by the synthesize_verdict tests.
_root_models = _load_module("root.models", os.path.join(_root, "models.py"))
_merged = _types.ModuleType("models")
# Copy everything from root models (ORM enums, ORM classes)
for _k, _v in vars(_root_models).items():
    setattr(_merged, _k, _v)
# Overlay Pydantic symbols — Verdict (Pydantic enum) wins, satisfying judge.py
for _k, _v in vars(_bm).items():
    if not _k.startswith("_"):
        setattr(_merged, _k, _v)
# Expose the ORM Verdict under a private alias so verdict_engine tests can patch it.
_merged.OrmVerdict = _root_models.Verdict

_prev_models = sys.modules.get("models")
sys.modules["models"] = _merged

import verdict_engine as ve  # noqa: E402

# Restore so subsequent imports keep using backend/models.py (existing tests).
if _prev_models is not None:
    sys.modules["models"] = _prev_models
else:
    sys.modules.pop("models", None)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_opinion(
    agent_name: str = "security",
    decision: DecisionEnum = DecisionEnum.APPROVE,
    confidence: float = 0.9,
    reasoning_text: str = "All good.",
    citations_json: Any = None,
    severity=None,
) -> MagicMock:
    """Return a mock that looks like a DB Opinion row."""
    op = MagicMock()
    op.agent_name = agent_name
    op.decision = decision
    op.confidence = confidence
    op.reasoning_text = reasoning_text
    op.citations_json = citations_json
    op.severity = severity
    op.adjusted_confidence = None  # will be set by synthesize_verdict
    op.relevance_weight = None
    return op


def _make_db(opinions):
    """Return a mock SQLAlchemy Session that yields *opinions* on query."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = opinions
    return db


def _run(opinions, weights=None, changed_file_paths=None, review_id=1):
    """Call synthesize_verdict with a mock DB and return (verdict_kwargs, db)."""
    weights = weights or {"security": 1.0, "architecture": 1.0, "testing": 1.0, "performance": 1.0}
    changed_file_paths = changed_file_paths or []
    db = _make_db(opinions)

    # Capture the Verdict(...) kwargs by intercepting the constructor.
    captured = {}

    original_verdict_cls = None

    # Patch root models.Verdict so we don't need a real DB connection.
    with patch("verdict_engine.Verdict") as mock_verdict_cls, \
         patch("verdict_engine.Conflict"):
        instance = MagicMock()
        mock_verdict_cls.return_value = instance
        result = ve.synthesize_verdict(
            db=db,
            review_id=review_id,
            change_type="feature_addition",
            weights=weights,
            changed_file_paths=changed_file_paths,
        )
        # Extract the kwargs passed to Verdict(...)
        assert mock_verdict_cls.called, "Verdict() was never called"
        captured = mock_verdict_cls.call_args[1]  # keyword arguments
        return captured, db, result


# ── _opinion_to_agent_result ─────────────────────────────────────────────────

class TestOpinionToAgentResult:
    """Unit tests for the Opinion → AgentResult conversion helper."""

    def test_approve_maps_to_passed_true(self):
        op = _make_opinion(decision=DecisionEnum.APPROVE)
        result = ve._opinion_to_agent_result(op)
        assert result.passed is True

    def test_reject_maps_to_passed_false(self):
        op = _make_opinion(decision=DecisionEnum.REJECT)
        result = ve._opinion_to_agent_result(op)
        assert result.passed is False

    def test_warn_maps_to_passed_false(self):
        op = _make_opinion(decision=DecisionEnum.WARN)
        result = ve._opinion_to_agent_result(op)
        assert result.passed is False

    def test_request_changes_maps_to_passed_false(self):
        op = _make_opinion(decision=DecisionEnum.REQUEST_CHANGES)
        result = ve._opinion_to_agent_result(op)
        assert result.passed is False

    def test_escalate_maps_to_passed_false(self):
        op = _make_opinion(decision=DecisionEnum.ESCALATE_TO_HUMAN)
        result = ve._opinion_to_agent_result(op)
        assert result.passed is False

    def test_agent_name_to_role_security(self):
        op = _make_opinion(agent_name="security")
        result = ve._opinion_to_agent_result(op)
        assert result.role == AgentRole.SECURITY

    def test_agent_name_to_role_architecture(self):
        op = _make_opinion(agent_name="architecture")
        result = ve._opinion_to_agent_result(op)
        assert result.role == AgentRole.ARCHITECTURE

    def test_agent_name_to_role_testing(self):
        op = _make_opinion(agent_name="testing")
        result = ve._opinion_to_agent_result(op)
        assert result.role == AgentRole.TESTING

    def test_agent_name_to_role_performance(self):
        op = _make_opinion(agent_name="performance")
        result = ve._opinion_to_agent_result(op)
        assert result.role == AgentRole.PERFORMANCE

    def test_unknown_agent_name_falls_back_to_security(self):
        op = _make_opinion(agent_name="unknown_bot")
        result = ve._opinion_to_agent_result(op)
        assert result.role == AgentRole.SECURITY

    def test_reasoning_text_becomes_raw_output(self):
        op = _make_opinion(reasoning_text="Found a SQL injection risk.")
        result = ve._opinion_to_agent_result(op)
        assert result.raw_output == "Found a SQL injection risk."

    def test_none_reasoning_becomes_empty_raw_output(self):
        op = _make_opinion(reasoning_text=None)
        result = ve._opinion_to_agent_result(op)
        assert result.raw_output == ""

    def test_citation_descriptions_become_findings(self):
        citations = [
            {"description": "Hard-coded password on line 5", "snippet": "pwd='abc'"},
            {"description": "eval() call detected"},
        ]
        op = _make_opinion(citations_json=citations)
        result = ve._opinion_to_agent_result(op)
        assert result.findings == [
            "Hard-coded password on line 5",
            "eval() call detected",
        ]

    def test_citations_without_description_are_skipped(self):
        citations = [{"snippet": "some_code"}, {"file": "app.py"}]
        op = _make_opinion(citations_json=citations)
        result = ve._opinion_to_agent_result(op)
        assert result.findings == []

    def test_empty_description_strings_are_skipped(self):
        citations = [{"description": ""}, {"description": "real finding"}]
        op = _make_opinion(citations_json=citations)
        result = ve._opinion_to_agent_result(op)
        assert result.findings == ["real finding"]

    def test_no_citations_gives_empty_findings(self):
        op = _make_opinion(citations_json=None)
        result = ve._opinion_to_agent_result(op)
        assert result.findings == []

    def test_returns_agent_result_instance(self):
        op = _make_opinion()
        result = ve._opinion_to_agent_result(op)
        assert isinstance(result, AgentResult)


# ── _pipeline_verdict_to_decision ────────────────────────────────────────────

class TestPipelineVerdictToDecision:
    def test_approve_maps_to_approve(self):
        assert ve._pipeline_verdict_to_decision(PipelineVerdict.APPROVE) == DecisionEnum.APPROVE

    def test_reject_maps_to_reject(self):
        assert ve._pipeline_verdict_to_decision(PipelineVerdict.REJECT) == DecisionEnum.REJECT

    def test_pending_maps_to_reject(self):
        # PENDING is not expected but must not crash — treated as REJECT for safety.
        assert ve._pipeline_verdict_to_decision(PipelineVerdict.PENDING) == DecisionEnum.REJECT


# ── synthesize_verdict: pipeline integration ─────────────────────────────────

class TestSynthesizeVerdictPipeline:
    """Tests that the pipeline functions are actually called and that their
    output drives final_decision (before escalation)."""

    def test_all_approve_opinions_yields_approve(self):
        # Use a single agent with a code snippet so evidence_quality=1.0,
        # giving adjusted_confidence=0.9 > low_confidence_threshold (0.5).
        ops = [
            _make_opinion(
                "security", DecisionEnum.APPROVE,
                reasoning_text="ok",
                citations_json=[{"description": "clean", "snippet": "x=1"}],
            ),
        ]
        kwargs, _, _ = _run(ops, weights={"security": 1.0})
        assert kwargs["final_decision"] == DecisionEnum.APPROVE

    def test_any_reject_with_reasoning_yields_reject(self):
        # Security agent rejects with a non-empty reasoning_text (raw_output),
        # which makes its citation-derived finding "supported" → REJECT.
        # Use snippet-bearing citations so adjusted_confidence is high enough
        # that security's negative score dominates (weighted_score < -0.5)
        # and confidence stays above the low-confidence threshold.
        ops = [
            _make_opinion(
                "security", DecisionEnum.REJECT,
                reasoning_text="Hard-coded password detected.",
                citations_json=[{"description": "password='abc'", "snippet": "pwd='abc'"}],
            ),
        ]
        kwargs, _, _ = _run(ops, weights={"security": 1.0})
        assert kwargs["final_decision"] == DecisionEnum.REJECT

    def test_reject_without_reasoning_yields_approve(self):
        # Failing agent has no reasoning_text (empty raw_output) → unsupported
        # findings → judge returns APPROVE.  Use a snippet so confidence is
        # above threshold and escalation does not override the verdict.
        ops = [
            _make_opinion(
                "security", DecisionEnum.REJECT,
                reasoning_text="",
                citations_json=[{"description": "maybe a risk", "snippet": "x=1"}],
            ),
        ]
        kwargs, _, _ = _run(ops, weights={"security": 1.0})
        assert kwargs["final_decision"] == DecisionEnum.APPROVE

    def test_no_opinions_escalates_due_to_low_confidence(self):
        # Zero opinions → weighted_score=0 → final_confidence=0 < threshold →
        # escalation fires.  Verify ESCALATE_TO_HUMAN rather than bare APPROVE.
        kwargs, _, _ = _run([])
        assert kwargs["final_decision"] == DecisionEnum.ESCALATE_TO_HUMAN
        assert kwargs["escalate_to_human"] is True

    def test_verdict_row_written_to_db(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, reasoning_text="fine")]
        _, db, _ = _run(ops)
        assert db.add.called
        assert db.commit.called

    def test_confidence_and_weighted_score_populated(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, confidence=0.8, reasoning_text="ok")]
        kwargs, _, _ = _run(ops, weights={"security": 1.0})
        assert "final_confidence" in kwargs
        assert "weighted_score" in kwargs
        assert isinstance(kwargs["final_confidence"], float)
        assert isinstance(kwargs["weighted_score"], float)

    def test_audit_log_contains_agent_entry(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, confidence=0.9, reasoning_text="ok")]
        kwargs, _, _ = _run(ops)
        log = kwargs["audit_log_json"]
        assert len(log) == 1
        assert log[0]["agent"] == "security"
        assert log[0]["decision"] == "APPROVE"

    def test_reasoning_text_includes_pipeline_rationale(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, reasoning_text="clean")]
        kwargs, _, _ = _run(ops)
        assert "Pipeline judge rationale" in kwargs["reasoning_text"]

    def test_reasoning_text_includes_agent_line(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, confidence=0.9, reasoning_text="clean")]
        kwargs, _, _ = _run(ops)
        assert "security" in kwargs["reasoning_text"]


# ── synthesize_verdict: escalation rules ─────────────────────────────────────

class TestSynthesizeVerdictEscalation:
    def test_reversibility_risk_escalates(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, reasoning_text="ok")]
        # A path matching a reversibility pattern.
        kwargs, _, _ = _run(ops, changed_file_paths=["migrations/0042_add_column.sql"])
        assert kwargs["final_decision"] == DecisionEnum.ESCALATE_TO_HUMAN
        assert kwargs["escalate_to_human"] is True
        assert "Reversibility risk" in kwargs["escalation_reason"]

    def test_no_reversibility_risk_no_escalation_on_approve(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, reasoning_text="ok")]
        # High enough confidence: weighted_score will be > 0 with confidence=0.9
        # Ensure we're not below low-confidence threshold by using high weights.
        kwargs, _, _ = _run(
            ops,
            weights={"security": 10.0},
            changed_file_paths=["app/utils.py"],
        )
        # confidence = abs(weighted_score) / sum(weights); since weight is high
        # and confidence is 0.9, final_confidence should exceed the 0.5 threshold.
        if not kwargs["escalate_to_human"]:
            assert kwargs["final_decision"] == DecisionEnum.APPROVE

    def test_escalation_overrides_approve(self):
        ops = [_make_opinion("security", DecisionEnum.APPROVE, reasoning_text="ok")]
        kwargs, _, _ = _run(ops, changed_file_paths=["schema/v2.sql"])
        assert kwargs["final_decision"] == DecisionEnum.ESCALATE_TO_HUMAN

    def test_escalation_overrides_reject(self):
        ops = [
            _make_opinion(
                "security", DecisionEnum.REJECT,
                reasoning_text="sql injection",
                citations_json=[{"description": "sqli"}],
            ),
        ]
        kwargs, _, _ = _run(ops, changed_file_paths=["migrations/drop_table.sql"])
        assert kwargs["final_decision"] == DecisionEnum.ESCALATE_TO_HUMAN


# ── synthesize_verdict: DB conflict rows ─────────────────────────────────────

class TestSynthesizeVerdictDbConflicts:
    """Verify that DB-level Conflict rows are persisted by synthesize_verdict."""

    def test_approve_reject_pair_creates_conflict_row(self):
        ops = [
            _make_opinion("security", DecisionEnum.APPROVE),
            _make_opinion("architecture", DecisionEnum.REJECT),
        ]
        db = _make_db(ops)
        with patch("verdict_engine.Verdict"), patch("verdict_engine.Conflict") as mock_conflict:
            ve.synthesize_verdict(
                db=db,
                review_id=99,
                change_type="feature_addition",
                weights={"security": 1.0, "architecture": 1.0},
                changed_file_paths=[],
            )
            assert mock_conflict.called, "Conflict() should be instantiated for APPROVE/REJECT pair"

    def test_no_conflict_row_when_all_approve(self):
        ops = [
            _make_opinion("security", DecisionEnum.APPROVE),
            _make_opinion("architecture", DecisionEnum.APPROVE),
        ]
        db = _make_db(ops)
        with patch("verdict_engine.Verdict"), patch("verdict_engine.Conflict") as mock_conflict:
            ve.synthesize_verdict(
                db=db,
                review_id=99,
                change_type="feature_addition",
                weights={"security": 1.0, "architecture": 1.0},
                changed_file_paths=[],
            )
            assert not mock_conflict.called, "No Conflict rows expected when all agents agree"

    def test_confidence_delta_creates_conflict_row(self):
        ops = [
            _make_opinion("security", DecisionEnum.APPROVE, confidence=0.9),
            _make_opinion("architecture", DecisionEnum.APPROVE, confidence=0.4),
        ]
        db = _make_db(ops)
        with patch("verdict_engine.Verdict"), patch("verdict_engine.Conflict") as mock_conflict:
            ve.synthesize_verdict(
                db=db,
                review_id=99,
                change_type="feature_addition",
                weights={"security": 1.0, "architecture": 1.0},
                changed_file_paths=[],
            )
            # delta = 0.5 > 0.4 threshold → one CONFIDENCE_DELTA conflict row
            assert mock_conflict.called
