# CouncilAI Development Log

---

## Project Overview

CouncilAI is a multi-agent code review system built for the **IBM TechXchange Pre-conference Dev Day Hackathon 2026**. It addresses a fundamental weakness in AI-assisted code review: single-perspective tools have no accountability mechanism when they miss a flaw or approve a poorly-tested change.

CouncilAI solves this by running **four IBM Bob specialist subagents in parallel** — Security, Architecture, Testing, and Performance — each reviewing the same unified diff from its own domain. Their findings flow through a deterministic three-stage pipeline (Conflict Detector → Evidence Checker → Final Judge) that surfaces inter-agent disagreements, weighs the evidence behind each finding, and delivers an auditable `APPROVE` or `REJECT` verdict with full rationale.

**Stack:** Python + FastAPI (backend), React 18 + Vite (frontend), IBM watsonx.ai / Llama 3.3 70B (LLM), pytest (217 tests), Docker + docker-compose.

---

## What Was Built

### Multi-Agent AI Code Review System

- **Four parallel specialist agents**, each subclassing `BaseAgent` (`agents/base.py`) and implementing `_run_checks()`:
  - 🔒 **SecurityAgent** — hardcoded credentials, `eval`/`exec`/`pickle.loads`/`shell=True`/`os.system`, non-TLS `http://` URLs, hardcoded IP addresses.
  - 🏗️ **ArchitectureAgent** — large contiguous additions (>50 lines), unresolved `TODO`/`FIXME`/`HACK` markers, magic numbers, circular import risk, high coupling.
  - 🧪 **TestingAgent** — production code changed without test files, skipped/disabled tests, bare `except` clauses, missing edge-case coverage hints.
  - ⚡ **PerformanceAgent** — nested loops (O(n²)), `SELECT *` queries, `time.sleep()` in async paths, list comprehensions inside loops.
- Each agent operates in two modes: **LLM mode** (via `WatsonxClient`, `meta-llama/llama-3-3-70b-instruct`) with a structured JSON-constrained system prompt, and **deterministic fallback** (regex heuristics) for CI and no-credentials environments.

### Parallel Agent Execution

- All four agents run concurrently via Python's `ThreadPoolExecutor` in `backend/main.py`.
- Results are re-sorted to a stable order (security, architecture, testing, performance) regardless of thread scheduling.

### Conflict Detector

- `agents/aggregator.py` — `aggregate()` collects each agent's `passed`/`failed` verdict; `detect_conflicts()` identifies every agent pair that disagrees and produces a human-readable description of each disagreement.
- Conflicts are reported contextually; they do not alone determine the final verdict.

### Evidence Checker

- `agents/evidence.py` — `check_evidence()` classifies each finding as **supported** (non-empty finding + non-empty `raw_output` from the agent) or **unsupported**.
- Ensures the Final Judge only acts on findings the agent actually explained.

### Final Judge

- `agents/judge.py` — `judge()` applies a single deterministic rule:
  - **`REJECT`** — at least one failing agent has at least one supported finding.
  - **`APPROVE`** — every failing agent's findings are unsupported, or there are no failing agents.
- Returns a structured rationale: triggered findings, discarded findings, and inter-agent conflicts.

### Explainable APPROVE / REJECT Verdicts

- Every decision is accompanied by a full rationale string listing which supported findings triggered rejection, which were discarded as unsupported, and any conflict notes.
- Rationale is machine-parseable and rendered as structured cards in the dashboard.

### Human Review Required Scenarios

- When a `REJECT` verdict co-occurs with agent conflicts, the dashboard escalates to a **"HUMAN REVIEW REQUIRED"** warning badge.
- The third demo scenario (risky database migration) is specifically flagged with `escalate: true`.

### Backend Orchestration and API

- FastAPI app in `backend/main.py` with `POST /review` and `GET /health` endpoints.
- CORS configured for local frontend origins.
- Request IDs generated per review for traceability.
- Timeout-safe exception handling per future: an agent failure synthesises a `passed=False` result rather than crashing the pipeline.

### IBM watsonx.ai Integration

- `services/watsonx_client.py` wraps the official `ibm-watsonx-ai` SDK.
- Each agent accepts an optional `watsonx_client` at construction; without credentials, deterministic fallback runs automatically.
- Environment variables: `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`.

### React Dashboard

- Built with React 18 + Vite in `dashboard/`.
- Components: `Header`, `DemoButtons`, `PipelineDiagram`, `ReviewResults`.
- CouncilAI logo and IBM TechXchange branding in the header.

### Demo Scenarios

Three embedded fixture diffs in `dashboard/src/data/demoDiffs.js`:

| # | Label | Expected Verdict |
|---|---|---|
| 1 | PR #1 — Safe Code Change | `APPROVE` |
| 2 | PR #2 — Security Risk | `REJECT` |
| 3 | PR #3 — Risky Database Migration | `REJECT` + Human Review Required |

---

## Development Progress

### Phase 1 — Project Scaffolding (2026-08-29, morning)

- **Initial project structure** (`c2e0b53`): `.bobignore`, `.gitignore`, `.env.example`, `README.md`, `SECURITY.MD` committed.
- **CouncilAI README** (`8408c8e`): Initial README explaining concept and goals.
- **Logo and branding** (`122eebc`): CouncilAI logo added to `bob_sessions/`.
- **Env config template** (`50c6e33`): `.env.example` with watsonx credential placeholders.
- **Interactive architecture diagram** (`7d99c06`): Architecture diagram committed in dashboard.
- **Platform initial commit** (`05395ad`): Platform-side initial scaffolding committed — `diff_parser.py`, `agent_client.py`, `aggregator.py`, `classifier.py`, `embedding.py`, `orchestrator.py`, `verdict_engine.py`, `models.py`, `main.py`, Dockerfile, docker-compose, fixtures, schemas, Postman collection.

### Phase 2 — Core Agent Pipeline (2026-08-29, afternoon)

- **All four specialist agents scaffolded** (`f7dcca4`): `BaseAgent` ABC, `SecurityAgent`, `ArchitectureAgent`, `TestingAgent`, `PerformanceAgent` implemented with deterministic regex checks. `backend/main.py` and `backend/models.py` created. `conftest.py`, `pytest.ini`, and `tests/test_agents.py` (206 tests) added. Bob project rules committed to `.bob/`.
- **Conflict Detector** (`d89f1ec`): `agents/aggregator.py` with `aggregate()` and `detect_conflicts()`. `tests/test_aggregator.py` added (206 tests).
- **Evidence Checker** (`8aceaed`): `agents/evidence.py` with `check_evidence()`. `tests/test_evidence.py` added (249 tests).
- **Final Judge** (`ff439a2`): `agents/judge.py` with `judge()`. `tests/test_judge.py` added (404 tests).
- **Judge exported from agents package** (`09f22f8`): `agents/__init__.py` updated.
- **Parallel pipeline integrated into backend** (`8ac001e`): `backend/main.py` updated to run all four agents via `ThreadPoolExecutor`, wire the three pipeline stages, and return a `ReviewResponse`. `tests/test_review.py` added (366 tests).

### Phase 3 — Test Cases and Fixtures (2026-08-29, Session 2)

- **Specialist agent test cases and clean fixture** (`2dad085`): `fixtures/clean_pr.diff` added; four clean-diff test files created (`test_security_agent_clean_diff.py`, `test_architecture_agent_clean_diff.py`, `test_testing_agent_clean_diff.py`, `test_performance_agent_clean_diff.py`).
- **SQL injection subagent disagreement demo** (`486d928`): Bob Session 3 staged two subagents with opposing mandates against a SQL injection line; both returned REJECT, demonstrating convergence on critical findings.

### Phase 4 — Reliability Fix: Timeout Handling (2026-08-29, Session 4)

- **Agent timeout crash fixed** (`92eb644`): `future.result()` previously re-raised on any agent exception, crashing the whole pipeline. Patched with a `try/except` that synthesises a `passed=False` `AgentResult` so the downstream judge still runs.
- **Impact log and README updated** (`359a91d`, `992a24f`): README corrected from three to four agents; AGENTS.md fully regenerated.

### Phase 5 — watsonx.ai Integration (2026-08-29, Session 5)

- **All four agents wired to watsonx.ai** (`3419e8c`): `services/watsonx_client.py` created. Each agent updated to accept a `WatsonxClient` and send role-specific system prompts to `meta-llama/llama-3-3-70b-instruct`, parsing the JSON response. Deterministic fallback preserved for tests.
- **Tested**: Security agent correctly returned `REJECT` on SQL injection fixture. 155 tests passing.
- **Impact log updated** (`c029005`).

### Phase 6 — Platform Integration and Merge (2026-08-29–30)

- **Platform stack integration** (`cbcf0fa`): `agent_client.py`, `classifier.py`, `orchestrator.py`, `verdict_engine.py`, `precedent_engine.py`, `relevance_weights.py`, `pr_commenter.py`, fixture diffs, `council.yaml`, `postman_collection.json`, and a single-page dashboard HTML prototype added.
- **Platform integration validated** (`21ec77d`): All four agent files (`security.py`, `architecture.py`, `testing.py`, `performance.py`), `backend/base.py`, `backend/models.py`, `services/watsonx_client.py` finalised. `tests/test_github_ingestion.py` added (439 tests).
- **Merge** (`ce5156e`): `platformengineer/fatima` branch merged into main.
- **Post-merge import conflicts resolved** (`c8971f7`): Import conflicts fixed, `agents/diff_parser.py` created, `backend/requirements.txt` updated. Tests restored to 181/181 passing.
- **Code cleanup pass** (`f4631cc`): Dead code removed across agents and backend; star imports and redundant re-exports normalised. 155 tests passed after cleanup.
- **Verdict engine wired end-to-end** (`196bb80`): `verdict_engine.py` wired to `aggregator.detect_conflicts`, `evidence.check_evidence`, and `judge.judge`. `tests/test_verdict_engine.py` added (515 tests). Full pipeline verified at 217/217 tests passing.

### Phase 7 — React Dashboard (2026-08-30, afternoon)

- **Full React dashboard built and committed** (`0172b81`): React 18 + Vite project scaffolded. All components implemented: `Header`, `DemoButtons`, `PipelineDiagram`, `ReviewResults`. `api.js` and `demoDiffs.js` created. CSS modules, global styles, `vite.config.js`, `dashboard/package.json`. README substantially updated.
- **Demo diff labels refined** (`1d86755`): Button labels and descriptions updated to "Safe Code Change", "Security Risk", "Risky Database Migration" for clarity during demo.

---

## Bugs, Issues, and Fixes

### 1 — DiffParser `.hunks` Generator Bug (Session 1)

- **Problem:** `DiffParser` was accessing `.hunks` on a `PatchedFile` object, which returns a generator. On multi-hunk diffs, the generator was exhausted silently, causing all downstream agents to receive incomplete hunk data.
- **Cause:** `unidiff`'s `PatchedFile.hunks` is a generator, not a list. Iterating it once consumed it, leaving nothing for subsequent accesses.
- **Fix:** The generator was materialised into a list on first access so all downstream agents receive the complete hunk data.
- **Result:** Agents correctly process multi-hunk diffs.

### 2 — `DiffParser.from_string` API Mismatch (Platform Branch)

- **Problem:** The platform-side `diff_parser.py` called `PatchSet(self.diff_text)` directly, which failed silently with newer versions of `unidiff`.
- **Cause:** The `unidiff` API changed; the correct call is `PatchSet.from_string()`.
- **Fix:** Updated to `PatchSet.from_string(self.diff_text)` and changed the bare `except` to re-raise so parse failures are visible (`f594d15`).
- **Result:** Diff parsing works reliably and errors surface correctly.

### 3 — Agent Timeout Crashes Entire Pipeline (Session 4)

- **Problem:** In `backend/main.py`, `future.result()` inside the `as_completed` loop re-raises any exception thrown by an agent. A single agent timeout or unhandled exception caused the entire `/review` endpoint to return HTTP 500, discarding all other agents' results.
- **Cause:** Missing `try/except` around `future.result()`. Would have caused a live HTTP 500 mid-demo.
- **Fix:** Wrapped each `future.result()` call in `try/except`. On failure, a `passed=False` `AgentResult` is synthesised with a `findings` entry describing the failure. The pipeline continues with partial results (`92eb644`).
- **Result:** A single agent failure no longer crashes the pipeline. The judge still runs with partial data.

### 4 — Post-Merge Import Conflicts (2026-08-30)

- **Problem:** After merging the platform branch into main, import conflicts appeared because the platform-side and agent-side code had overlapping module names and different `sys.path` assumptions.
- **Cause:** Both branches defined `models.py` (one at repo root, one at `backend/models.py`), and the `diff_parser` module existed in two locations with different implementations.
- **Fix:** Import paths normalised; `agents/diff_parser.py` created as the canonical agent-layer parser; `backend/base.py` adjusted. Test count restored to 181/181 (`c8971f7`).
- **Result:** No import errors; all tests pass.

### 5 — Environment Variable Model Mismatch (2026-08-30)

- **Problem:** After the merge, `.env.example` still referenced `ibm/granite-3-8b-instruct` for agent model configuration, which diverged from the `meta-llama/llama-3-3-70b-instruct` model actually wired into the agents.
- **Cause:** Platform branch `.env.example` used an earlier model ID.
- **Fix:** All four `*_AGENT_MODEL` entries in `.env.example` updated to `meta-llama/llama-3-3-70b-instruct` (`c8971f7`).
- **Result:** Environment template matches the runtime configuration.

### 6 — Demo Button Labels Were Verbose and Technical

- **Problem:** Initial demo PR button descriptions included full technical detail (e.g., "Null guard for format_currency + matching test"), which was harder for hackathon judges to read at a glance.
- **Cause:** Original labels were written as developer notes rather than demo-facing copy.
- **Fix:** Labels simplified to "Safe Code Change", "Security Risk", "Risky Database Migration" (`1d86755`).
- **Result:** Demo buttons communicate the scenario immediately without requiring technical context.

---

## Dashboard Evolution

### Initial Implementation

The first dashboard was a single static HTML file (`dashboard/index.html`) committed as part of the platform integration (`cbcf0fa`). It demonstrated the concept but was not wired to the backend API.

### Full React Dashboard (2026-08-30)

The complete React 18 + Vite dashboard was built in a single large commit (`0172b81`, 3,413 line insertions):

- **`Header.jsx`** — CouncilAI logo (served from `dashboard/public/logo.png`), title, IBM TechXchange 2026 subtitle, and a live status indicator dot.
- **`DemoButtons.jsx`** — Three scenario buttons (Safe Code Change, Security Risk, Risky Database Migration) with colour-coded expected verdict tags (green `APPROVE`, red `REJECT`, amber `HUMAN REVIEW REQUIRED`) and a spinner while the pipeline runs.
- **`PipelineDiagram.jsx`** — Live pipeline visualization with four agent cards (Security, Architecture, Testing, Performance) and three post-processing stage boxes (Conflict Detector, Evidence Checker, Final Judge), connected by animated dashed arrows. Each node reflects its actual pass/fail/loading/idle state from backend results in real time.
- **`ReviewResults.jsx`** — Full results panel including:
  - **Verdict banner** — colour-coded `APPROVE` (green) / `REJECT` (red) with an amber `⚠ HUMAN REVIEW REQUIRED` escalation badge when a rejection co-occurs with conflicts.
  - **Agent result cards** — expandable cards per agent showing PASS/FAIL status and expandable findings lists.
  - **Judge Rationale panel** — parses the structured rationale string from `judge.py` into distinct sections: decision headline, "Triggered by" supported findings (with agent icon and `supported` badge), "Discarded (unsupported)" findings, and "Agent Disagreements" conflict rows with pass/fail chip pairs.
  - **Conflict Detector panel** — `Clean` or `Conflicts` badge; lists all conflict descriptions.
  - **Evidence Checker panel** — shows supported and unsupported finding counts and lists.
  - **Loading, error, and empty states** — SVG loading ring ("Pipeline running…"), error box with backend restart hint, empty state with instructions.
  - **`HighlightedFinding`** component — inline `<code>` badges for backtick tokens, `SELECT *`, line references, and quoted strings.
- **`api.js`** — `reviewDiff()` fetches `POST /review` from `http://localhost:8000`.
- **`demoDiffs.js`** — Three embedded fixture diffs with labels, descriptions, context strings, expected verdicts, and escalation flags.
- **`global.css`** and CSS Modules — dark-themed design system with CSS custom properties for colours, consistent card and badge styling across all components.

### Demo Label Refinement (2026-08-30)

Button labels updated from developer-style descriptions to judge-facing copy: "Safe Code Change", "Security Risk", "Risky Database Migration" (`1d86755`).

---

## Documentation Improvements

- **`SECURITY.MD`** (`c2e0b53`): Full credential safety policy — never hardcode secrets, use `os.getenv()`, all secrets gitignored, `.bobignore` patterns protect credentials from Bob session logs.
- **`AGENTS.md`** (initial, `f7dcca4`): Bob project rules committed for agent, ask, and plan modes; repo-level `AGENTS.md` written with pipeline description and key file table.
- **`AGENTS.md`** (regenerated, `992a24f`): Fully regenerated to reflect real modules, four-agent architecture, pipeline stages, timeout behaviour, and actual `ThreadPoolExecutor` mechanism.
- **`README.md`** updates (`8408c8e`, `992a24f`, `0172b81`): Evolved from a brief concept description to a comprehensive document covering: problem statement, architecture diagram, specialist agent table, pipeline stage explanations, watsonx.ai integration details, full project structure tree, running instructions, test suite description, and tech stack table.
- **`.env.example`** (`50c6e33`, `c8971f7`): Template updated with all four agent model variables aligned to the runtime model.
- **`postman_collection.json`** (`cbcf0fa`): Postman collection for API testing added.
- **`council.yaml`** (`cbcf0fa`): Agent configuration file committed.

---

## Verification and Testing

- **First tests** (`f7dcca4`): `tests/test_agents.py` — 206 tests covering all four specialist agents in deterministic mode.
- **Aggregator tests** (`d89f1ec`): `tests/test_aggregator.py` — 206 tests for `aggregate()` and `detect_conflicts()`.
- **Evidence tests** (`8aceaed`): `tests/test_evidence.py` — 249 tests for `check_evidence()`.
- **Judge tests** (`ff439a2`): `tests/test_judge.py` — 404 tests for `judge()`.
- **Review endpoint tests** (`8ac001e`): `tests/test_review.py` — 366 tests covering `POST /review` end-to-end with the FastAPI test client.
- **Clean diff tests** (`2dad085`): Four per-agent clean-diff test files confirming agents pass on benign changes.
- **Platform ingestion tests** (`21ec77d`): `tests/test_github_ingestion.py` — 439 tests.
- **Verdict engine tests** (`196bb80`): `tests/test_verdict_engine.py` — 515 tests for the end-to-end verdict pipeline.
- **Post-merge validation** (`c8971f7`): 181/181 tests passing after import conflict resolution.
- **Cleanup validation** (`f4631cc`): 155 tests passing after dead-code cleanup.
- **Final validation**: `pytest tests/` → **217 passed in ~1.03s** (current state, verified by running test suite).

All tests exercise the deterministic fallback logic; no watsonx credentials are required to run the suite.

---

## Current Project Status

The project is fully functional end-to-end:

- **Backend** (`uvicorn main:app --reload` from `backend/`) starts cleanly, exposes `POST /review` and `GET /health`, runs all four specialist agents in parallel, and returns a structured JSON verdict with full pipeline details.
- **React dashboard** (`npm run dev` from `dashboard/`) connects to the backend, presents three demo scenarios, and visualises the full pipeline state in real time — agent statuses, verdict banner, judge rationale, conflict detector output, evidence checker output, and human review escalation.
- **217 tests pass** in ~1 second with no credentials required.
- **watsonx.ai integration** is wired and tested; the deterministic fallback ensures the system works without live credentials.
- **Three demo scenarios** cover the full verdict spectrum: safe approval, security-triggered rejection, and a rejection with human review escalation.
- **Docker support** is available via `docker-compose.yml` and `Dockerfile`.

---

## Remaining Work

No known functional bugs or broken features. The following are potential areas for future improvement identified from the project's current state:

- The `StarletteDeprecationWarning` emitted by `fastapi.testclient` (recommending `httpx2`) is a dependency ecosystem note, not a project bug. It does not affect test results or runtime behaviour.
- The four specialist agents currently use regex-based heuristics in deterministic fallback mode. Expanding the heuristic rule sets would increase coverage without requiring watsonx credentials.
- The `frontend/` directory (separate from `dashboard/`) exists as an empty scaffold and has not been developed.

---

*Last updated: 2026-08-30 · CouncilAI · IBM TechXchange Pre-conference Dev Day Hackathon 2026*
