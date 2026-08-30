"""
Agent-side data models for CouncilAI specialist agents.

These are lightweight dataclasses used ONLY within the agents/ layer.
They are NOT the same as the SQLAlchemy ORM models in the repo-root models.py.
The sys.path injection in each agent file ensures this file shadows the root
models.py when running agent code.
"""

from __future__ import annotations
import enum
from dataclasses import dataclass, field
from typing import List


class AgentRole(str, enum.Enum):
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    TESTING = "testing"
    PERFORMANCE = "performance"


@dataclass
class AgentResult:
    """Result returned by a specialist agent."""
    role: AgentRole
    passed: bool
    findings: List[str] = field(default_factory=list)
    raw_output: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "findings": self.findings,
            "raw_output": self.raw_output,
        }
