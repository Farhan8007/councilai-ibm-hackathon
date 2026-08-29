import os, sys
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _d in (os.path.join(_root,"agents"), os.path.join(_root,"backend")):
    if _d not in sys.path: sys.path.insert(0, _d)

from architecture import ArchitectureAgent

_DIFF = open(os.path.join(_root, "fixtures", "clean_pr.diff")).read()

def test_architecture_agent_clean_diff():
    agent = ArchitectureAgent()
    result = agent.review(_DIFF)
    assert result.role.value == "architecture"
    assert result.passed is True, f"Unexpected findings:\n" + "\n".join(result.findings)
    assert result.findings == []
