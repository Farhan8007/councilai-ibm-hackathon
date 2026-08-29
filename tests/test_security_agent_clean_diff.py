import os, sys
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(_root,"agents"), os.path.join(_root,"backend")):
    if _p not in sys.path: sys.path.insert(0, _p)

from security import SecurityAgent

CLEAN_DIFF = open(os.path.join(_root, "fixtures", "clean_pr.diff")).read()

def test_security_agent_clean_diff():
    agent = SecurityAgent()
    result = agent.review(CLEAN_DIFF)
    assert result.role.value == "security"
    assert result.passed is True, f"Unexpected findings: {result.findings}"
    assert result.findings == []
    assert "No security issues found" in result.raw_output
