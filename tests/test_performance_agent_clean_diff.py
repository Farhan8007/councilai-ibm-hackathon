import os, sys
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_root,"agents"), os.path.join(_root,"backend")):
    if _d not in sys.path: sys.path.insert(0, _d)

from performance import PerformanceAgent

CLEAN_DIFF = open(os.path.join(_root, "fixtures", "clean_pr.diff")).read()

def test_performance_agent_clean_diff():
    agent = PerformanceAgent()
    result = agent.review(CLEAN_DIFF)
    assert result.role.value == "performance"
    assert result.passed is True, f"Unexpected findings: {result.findings}"
    assert result.findings == []
