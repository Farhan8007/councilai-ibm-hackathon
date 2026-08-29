Session 3 — dramatic disagreement
Staged 2 subagents with opposing mandates against the SQL injection line in auth.py.
Both returned REJECT — but Subagent A broke its ship-fast mandate to do it.
Demonstrates that even conflicting agents converge on critical security findings,
which is exactly what CouncilAI's Evidence Judge is built to handle.
Session 4 — orchestrator timeout review
Bob traced future.result() in the as_completed loop — found it re-raises on
any agent exception, crashing the whole pipeline and discarding other agents'
results. Patched with try/except that synthesises a passed=False AgentResult
so the downstream judge still runs. Would have caused HTTP 500 mid-demo.
Session 5 — README + AGENTS.md
README updated: three → four agents, diagram and table corrected.
AGENTS.md fully regenerated: now reflects real modules, pipeline stages,
timeout behaviour, and actual ThreadPoolExecutor mechanism.
watsonx integration — all 4 agents
All 4 specialist agents now support real LLM-powered review via WatsonxClient
(meta-llama/llama-3-3-70b-instruct). Deterministic fallback preserved for tests.
Security agent tested against SQL injection fixture — correctly returned REJECT.
155 tests still passing.
