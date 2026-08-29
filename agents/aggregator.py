"""
Opinion Aggregator and Conflict Detector.

Usage
-----
    from agents.aggregator import aggregate, detect_conflicts

    results = [security_result, architecture_result, testing_result]
    report = detect_conflicts(aggregate(results))

``aggregate`` collects the verdicts (passed/failed) from each specialist
agent result and returns a plain dict keyed by role.

``detect_conflicts`` compares those verdicts and returns a
:class:`~models.ConflictReport`.  A *conflict* exists when at least one
agent passed and at least one agent failed — i.e. the specialists disagree
on whether the diff is acceptable.

Both functions are deterministic and require no external services.
"""

from __future__ import annotations

import sys
import os

_backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

from models import AgentResult, AgentRole, ConflictReport  # noqa: E402


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def aggregate(results: list[AgentResult]) -> dict[AgentRole, bool]:
    """Return a mapping of ``{role: passed}`` for each result.

    Parameters
    ----------
    results:
        One :class:`~models.AgentResult` per specialist agent.  Duplicates
        (same role appearing more than once) are resolved by keeping the
        *last* entry, matching list order.

    Returns
    -------
    dict[AgentRole, bool]
        Ordered by the position of each role's first occurrence in *results*.
    """
    verdicts: dict[AgentRole, bool] = {}
    for r in results:
        verdicts[r.role] = r.passed
    return verdicts


def detect_conflicts(verdicts: dict[AgentRole, bool]) -> ConflictReport:
    """Identify roles that disagree and return a :class:`~models.ConflictReport`.

    A conflict is recorded for every pair of agents (A, B) where A passed
    and B failed.  This gives a concrete, human-readable description of *who*
    disagrees and *in which direction*.

    Parameters
    ----------
    verdicts:
        Output of :func:`aggregate`.

    Returns
    -------
    ConflictReport
        ``has_conflicts`` is ``True`` when any pair disagrees.
        ``conflicts`` contains one string per disagreeing pair.
    """
    passed_roles = [role for role, ok in verdicts.items() if ok]
    failed_roles = [role for role, ok in verdicts.items() if not ok]

    conflicts: list[str] = []
    for p in passed_roles:
        for f in failed_roles:
            conflicts.append(
                f"{p.value} passed but {f.value} failed — agents disagree on this change."
            )

    return ConflictReport(conflicts=conflicts, has_conflicts=bool(conflicts))
