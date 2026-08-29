import os, sys
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_root,"agents"), os.path.join(_root,"backend")):
    if _d not in sys.path: sys.path.insert(0, _d)

from testing import TestingAgent

_DIFF = open(os.path.join(_root, "fixtures", "clean_pr.diff")).read()

def test_testing_agent_clean_diff():
    agent = TestingAgent()
    result = agent.review(_DIFF)
    assert result.passed is True, f"Expected passed=True.\nFindings: {result.findings}"
    assert result.findings == []
