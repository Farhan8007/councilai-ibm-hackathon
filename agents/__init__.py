"""
CouncilAI specialist agents package.

Import the concrete agents from here:

    from agents import SecurityAgent, ArchitectureAgent, TestingAgent, PerformanceAgent
    from agents import aggregate, detect_conflicts
    from agents import check_evidence
"""

from agents.security import SecurityAgent
from agents.architecture import ArchitectureAgent
from agents.testing import TestingAgent
from agents.performance import PerformanceAgent
from agents.base import BaseAgent
from agents.aggregator import aggregate, detect_conflicts
from agents.evidence import check_evidence
from agents.judge import judge
__all__ = [
    "BaseAgent",
    "SecurityAgent",
    "ArchitectureAgent",
    "TestingAgent",
    "PerformanceAgent",
    "aggregate",
    "detect_conflicts",
    "check_evidence",
    "judge",
]
