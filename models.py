"""
SQLAlchemy ORM models for CouncilAI
Database schema for review pipeline, agent verdicts, citations, conflicts, audit log.
"""

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON,
    ForeignKey, Enum, Boolean, create_engine, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from pgvector.sqlalchemy import Vector
from dotenv import load_dotenv
import enum
import os

load_dotenv()

Base = declarative_base()

# ===== ENUMS =====
class DecisionEnum(str, enum.Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    WARN = "WARN"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"

class SeverityEnum(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class ConflictTypeEnum(str, enum.Enum):
    DECISION_COEXISTENCE = "DECISION_COEXISTENCE"
    SEVERITY_GAP = "SEVERITY_GAP"
    OVERLAPPING_CITATIONS = "OVERLAPPING_CITATIONS"
    CONFIDENCE_DELTA = "CONFIDENCE_DELTA"
    WEIGHT_INVERSION = "WEIGHT_INVERSION"

class ConflictSeverityEnum(str, enum.Enum):
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"
    MINOR = "MINOR"

class ChangeTypeEnum(str, enum.Enum):
    AUTH_CHANGE = "auth_change"
    SCHEMA_MIGRATION = "schema_migration"
    PERF_CRITICAL = "perf_critical"
    UI_ONLY = "ui_only"
    CONFIG_CHANGE = "config_change"
    FEATURE_ADDITION = "feature_addition"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    UNKNOWN = "unknown"

# ===== MAIN MODELS =====

class Review(Base):
    """
    Represents a GitHub PR review request.
    Triggered by webhook when PR is opened/updated/reopened.
    """
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    repo = Column(String(255), nullable=False, index=True)  # owner/repo
    pr_number = Column(Integer, nullable=False)
    pr_title = Column(String(512), nullable=True)
    pr_url = Column(String(512), nullable=True)
    commit_sha = Column(String(40), nullable=True)  # Head SHA for commenting

    diff_text = Column(Text, nullable=True)  # Raw git diff
    diff_url = Column(String(512), nullable=True)

    change_type = Column(Enum(ChangeTypeEnum), nullable=True, index=True)
    change_confidence = Column(Float, nullable=True)
    change_reasoning = Column(Text, nullable=True)

    # pgvector embedding of the diff text, used by the precedent engine
    # (IBM Granite embeddings are 384-dim for slate models; adjust if a
    # different embedding model is used)
    diff_embedding = Column(Vector(384), nullable=True)

    status = Column(String(30), default="pending", index=True)  # pending|parsing|classifying|reviewing|complete|failed

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    opinions = relationship("Opinion", back_populates="review", cascade="all, delete-orphan")
    conflicts = relationship("Conflict", back_populates="review", cascade="all, delete-orphan")
    verdict = relationship("Verdict", uselist=False, back_populates="review", cascade="all, delete-orphan")
    changed_files = relationship("ChangedFile", back_populates="review", cascade="all, delete-orphan")
    audit_entries = relationship("AuditLog", back_populates="review", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Review {self.repo}#{self.pr_number}>"


class ChangedFile(Base):
    """
    Represents a single file changed in a PR.
    Parsed from the diff.
    """
    __tablename__ = "changed_files"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False, index=True)

    file_path = Column(String(512), nullable=False)
    language = Column(String(50), nullable=True)
    old_lines_start = Column(Integer, nullable=True)
    old_lines_end = Column(Integer, nullable=True)
    new_lines_start = Column(Integer, nullable=True)
    new_lines_end = Column(Integer, nullable=True)
    is_binary = Column(Boolean, default=False)
    is_renamed = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)

    hunk_context = Column(Text, nullable=True)  # Surrounding code for LLM analysis
    hunks_json = Column(JSON, nullable=True, default=list)  # Structured hunks per diff_schema.json

    # Relationships
    review = relationship("Review", back_populates="changed_files")

    def __repr__(self):
        return f"<ChangedFile {self.file_path}>"


class Opinion(Base):
    """
    Represents a single agent's verdict on a review.
    One row per agent per review (4 agents = 4 opinions per review).
    """
    __tablename__ = "opinions"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False, index=True)

    agent_name = Column(String(50), nullable=False)  # security, architecture, testing, performance
    decision = Column(Enum(DecisionEnum), nullable=False)
    confidence = Column(Float, nullable=False)  # 0.0 to 1.0
    adjusted_confidence = Column(Float, nullable=True)  # after Evidence Judge re-scoring
    severity = Column(Enum(SeverityEnum), nullable=True)
    relevance_weight = Column(Float, nullable=True)  # from the relevance weight matrix

    reasoning_text = Column(Text, nullable=True)
    citations_json = Column(JSON, nullable=True, default=list)  # List of Citation objects
    is_timeout = Column(Boolean, default=False)  # true if agent hit the 30s timeout

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    review = relationship("Review", back_populates="opinions")
    citations = relationship("Citation", back_populates="opinion", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Opinion {self.agent_name} on Review#{self.review_id}: {self.decision}>"


class Citation(Base):
    """
    Represents evidence cited by an agent.
    Points to specific lines in the diff where the concern exists.
    """
    __tablename__ = "citations"

    id = Column(Integer, primary_key=True)
    opinion_id = Column(Integer, ForeignKey("opinions.id"), nullable=False, index=True)

    file_path = Column(String(512), nullable=False)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)

    evidence_type = Column(String(100), nullable=True)  # e.g., OWASP_A03, SQL_INJECTION, CIRCULAR_DEPENDENCY
    description = Column(Text, nullable=True)
    snippet = Column(Text, nullable=True)  # Actual code snippet from the diff

    # Relationships
    opinion = relationship("Opinion", back_populates="citations")

    def __repr__(self):
        return f"<Citation {self.file_path}:{self.line_start}-{self.line_end}>"


class Conflict(Base):
    """
    Represents a detected conflict between agents.
    """
    __tablename__ = "conflicts"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False, index=True)

    conflict_type = Column(Enum(ConflictTypeEnum), nullable=False)
    severity = Column(Enum(ConflictSeverityEnum), nullable=False)  # BLOCKING, ADVISORY, MINOR

    agent_a = Column(String(50), nullable=False)
    agent_b = Column(String(50), nullable=False)

    divergence_score = Column(Float, nullable=False)  # 0.0 to 1.0
    description = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    review = relationship("Review", back_populates="conflicts")

    def __repr__(self):
        return f"<Conflict {self.conflict_type}: {self.agent_a} vs {self.agent_b}>"


class Verdict(Base):
    """
    Represents the final verdict after all agents, conflict detection, and evidence judge.
    One row per review.
    """
    __tablename__ = "verdicts"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False, index=True, unique=True)

    final_decision = Column(Enum(DecisionEnum), nullable=False)
    final_confidence = Column(Float, nullable=False)
    weighted_score = Column(Float, nullable=True)

    reasoning_text = Column(Text, nullable=True)  # Human-readable judicial opinion
    audit_log_json = Column(JSON, nullable=True, default=list)  # Complete trace of decisions

    escalate_to_human = Column(Boolean, default=False)
    escalation_reason = Column(Text, nullable=True)

    github_comment_posted = Column(Boolean, default=False)
    github_comment_url = Column(String(512), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    review = relationship("Review", back_populates="verdict")

    def __repr__(self):
        return f"<Verdict Review#{self.review_id}: {self.final_decision}>"


class PrecedentDecision(Base):
    """
    Stores historical review decisions for the precedent engine.
    Each human override is logged here. Seeded manually for demo reliability
    (see precedent_engine.py: seed_demo_precedents()).
    """
    __tablename__ = "precedent_decisions"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=True)

    diff_embedding = Column(Vector(384), nullable=True)  # from Granite embeddings
    diff_text_hash = Column(String(64), nullable=True)  # SHA256 hash of diff for deduplication

    decision = Column(Enum(DecisionEnum), nullable=False)
    reasoning = Column(Text, nullable=True)

    is_human_override = Column(Boolean, default=False)
    original_verdict = Column(Enum(DecisionEnum), nullable=True)  # What CouncilAI said
    human_decision = Column(Enum(DecisionEnum), nullable=True)  # What human said
    override_reason = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<PrecedentDecision {self.decision}>"


class AuditLog(Base):
    """
    Append-only, step-by-step trace of everything the pipeline did for a
    review: diff parsed, change classified, each agent's raw + adjusted
    confidence, each conflict found, and the final verdict synthesis.
    Zero-truncation - every step is logged here in addition to being
    folded into Verdict.audit_log_json for convenience.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False, index=True)

    step = Column(String(100), nullable=False)  # e.g. "diff_parsed", "evidence_weighting"
    data = Column(JSON, nullable=True, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    review = relationship("Review", back_populates="audit_entries")

    def __repr__(self):
        return f"<AuditLog {self.step} @ Review#{self.review_id}>"


# ===== DATABASE SETUP =====

_engine = None
_SessionLocal = None


def get_db_engine():
    """Create (or return cached) SQLAlchemy engine from DATABASE_URL."""
    global _engine
    if _engine is None:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable not set")
        _engine = create_engine(database_url, echo=False)
    return _engine


def get_db_session():
    """Get a new database session from the shared connection pool."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_db_engine())
    return _SessionLocal()

def init_db():
    """Initialize database tables. Requires the pgvector extension to
    already exist (see docker/init.sql / CREATE EXTENSION vector)."""
    engine = get_db_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables initialized (pgvector extension enabled)")

if __name__ == "__main__":
    init_db()
