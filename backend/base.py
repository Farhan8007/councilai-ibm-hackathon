"""
Base agent class for CouncilAI specialist agents.

All four specialist agents (security, architecture, testing, performance)
inherit from BaseAgent. The concrete implementation lives in agents/ at the
repo root. This module lives in backend/ so each agent can add both
backend/ and services/ to sys.path and import consistently.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional

# Import AgentResult and AgentRole from this package's models
from models import AgentResult, AgentRole  # type: ignore[import]


class BaseAgent(ABC):
    """Abstract base for all CouncilAI specialist agents."""

    role: AgentRole  # subclass must declare

    def __init__(self, watsonx_client=None):
        self._client = watsonx_client

    def run(self, diff: str, context: Optional[str] = None) -> AgentResult:
        """
        Run the agent against a unified diff.

        Args:
            diff: Raw unified diff text (from the diff pipeline)
            context: Optional extra context string

        Returns:
            AgentResult with decision, findings, and raw output
        """
        return self._run_checks(diff, context)

    @abstractmethod
    def _run_checks(self, diff: str, context: Optional[str]) -> AgentResult:
        """Implement agent-specific checks. Must return AgentResult."""
