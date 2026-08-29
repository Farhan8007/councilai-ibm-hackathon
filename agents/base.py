"""
Shared abstract interface for all CouncilAI specialist agents.

Each concrete agent:
  - Subclasses ``BaseAgent``
  - Implements ``_run_checks(diff, context) -> AgentResult``
  - Is constructed with no required arguments (ready to swap in a watsonx
    client via ``__init__`` when credentials become available)

Replacing the placeholder logic with a real LLM call requires only editing
``_run_checks`` — the interface and callers stay unchanged.
"""

from __future__ import annotations

import sys
import os
from abc import ABC, abstractmethod

# Allow ``from agents.base import BaseAgent`` even when the repo root is on
# sys.path but ``backend/`` is not.  We add ``backend/`` lazily so that
# models.py is always importable without callers needing to set PYTHONPATH.
_backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from models import AgentResult, AgentRole  # noqa: E402


class BaseAgent(ABC):
    """Abstract specialist agent.

    Parameters
    ----------
    watsonx_client:
        Optional watsonx.ai client instance.  Accepted now so that concrete
        subclasses can store it without interface changes later.
    """

    role: AgentRole  # must be set as a class attribute by each subclass

    def __init__(self, watsonx_client: object | None = None) -> None:
        self._client = watsonx_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(self, diff: str, context: str | None = None) -> AgentResult:
        """Run the agent against *diff* and return a structured result.

        Parameters
        ----------
        diff:
            Unified diff or raw code snippet to review.
        context:
            Optional surrounding context (PR description, file names, etc.).
        """
        return self._run_checks(diff, context)

    # ------------------------------------------------------------------
    # Extension point
    # ------------------------------------------------------------------

    @abstractmethod
    def _run_checks(self, diff: str, context: str | None) -> AgentResult:
        """Perform analysis and return an :class:`AgentResult`.

        Override this method in each concrete agent.  When watsonx credentials
        are available, replace the deterministic logic here with an LLM call
        via ``self._client``.
        """
