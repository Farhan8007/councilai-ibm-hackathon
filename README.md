<div align="center">

# ⚖️ CouncilAI

![CouncilAI Logo](bob_sessions/logo.png)

### Multi-Agent Code Review System

**IBM TechXchange Pre-conference Dev Day Hackathon 2026**

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square)
![watsonx](https://img.shields.io/badge/IBM-watsonx.ai-1D3557?style=flat-square)
![Tests](https://img.shields.io/badge/tests-217%20passed-brightgreen?style=flat-square)

</div>

---

## The Problem

Today's AI-assisted code review tools look at a pull request from a **single perspective** — one model, one opinion, no accountability. When that single agent misses a security flaw or approves a poorly-tested change, there is no mechanism to catch the error before merge.

**When AI agents disagree on a code change — who decides who is right?**

---

## The Solution

CouncilAI runs **four IBM Bob specialist subagents in parallel**, each reviewing the same unified diff from its own domain of expertise. Their findings flow through a deterministic three-stage pipeline that surfaces conflicts, weighs evidence, and delivers an auditable `APPROVE` or `REJECT` verdict.

```
                 Unified Diff
                      │
        ┌─────────────┼─────────────┬─────────────┐
        ↓             ↓             ↓             ↓
    Security    Architecture    Testing      Performance
     Agent         Agent         Agent         Agent
        │             │             │             │
        └─────────────┼─────────────┴─────────────┘
                      ↓
              Conflict Detector
                      ↓
              Evidence Checker
                      ↓
                Final Judge
                      ↓
           ┌──────────┴──────────┐
           ↓                     ↓
        APPROVE               REJECT
```

---

## Specialist Agents

Each agent receives the full unified diff and analyses only the **added lines** (`+`). All four run concurrently via Python's `ThreadPoolExecutor`.

| Agent | What it checks |
|---|---|
| 🔒 **Security** | Hardcoded credentials, `eval`/`exec`/`pickle.loads`/`shell=True`/`os.system`, non-TLS `http://` URLs, hardcoded IP addresses |
| 🏗️ **Architecture** | Large contiguous additions (>50 lines), unresolved `TODO`/`FIXME`/`HACK` markers, magic numbers, circular import risk, high coupling |
| 🧪 **Testing** | Production code changed without corresponding test files, skipped/disabled tests (`pytest.skip`, `assert False`), bare `except` clauses, missing edge-case coverage |
| ⚡ **Performance** | Nested loops (O(n²) complexity), `SELECT *` queries, `time.sleep()` in async paths, list comprehensions inside loops |

Each agent operates in two modes:
- **LLM mode** — when a `WatsonxClient` is injected, it sends the diff to **IBM watsonx.ai** (`meta-llama/llama-3-3-70b-instruct`) with a structured system prompt and parses the JSON response.
- **Deterministic fallback** — regex-based heuristics run in CI or any environment without watsonx credentials, so the pipeline always produces results.

---

## Pipeline Stages

### 1 — Conflict Detector (`agents/aggregator.py`)

`aggregate()` collects each agent's `passed/failed` verdict. `detect_conflicts()` identifies every pair of agents that disagree — one passed while the other failed — and records a human-readable description of each disagreement. Conflicts are reported contextually; they do not by themselves determine the final verdict.

### 2 — Evidence Checker (`agents/evidence.py`)

`check_evidence()` classifies every finding as **supported** or **unsupported**. A finding is supported when it is non-empty _and_ its agent produced a non-empty `raw_output` narrative. This ensures the Final Judge only acts on findings the agent actually explained.

### 3 — Final Judge (`agents/judge.py`)

`judge()` applies a single deterministic rule:

- **`REJECT`** — at least one failing agent has at least one **supported** finding.
- **`APPROVE`** — every failing agent's findings are entirely unsupported, or there are no failing agents.

The response includes a structured rationale listing which findings triggered the decision, which findings were discarded as unsupported, and any inter-agent conflicts for human review.

---

## watsonx.ai Integration

`services/watsonx_client.py` wraps the official `ibm-watsonx-ai` SDK. Each specialist agent accepts an optional `watsonx_client` at construction time.

```python
# Environment variables (from .env)
WATSONX_API_KEY=...
WATSONX_PROJECT_ID=...
WATSONX_URL=https://us-south.ml.cloud.ibm.com   # default

# Default model used by all four agents
meta-llama/llama-3-3-70b-instruct
```

Each agent constructs a role-specific system prompt that constrains the model to return a strict JSON envelope — `{"passed": bool, "findings": [...], "raw_output": "..."}` — making the LLM output directly machine-readable without a separate parser.

---

## React Dashboard

`dashboard/` is a **React 18 + Vite** single-page app that connects to the FastAPI backend at `http://localhost:8000`.

**Key features:**

- **Demo PR buttons** — three embedded fixture diffs (a safe change, a security risk, and a risky database migration) can be reviewed without any GitHub credentials.
- **Live pipeline diagram** — shows each agent's pass/fail status and all three post-processing stages updating in real time as the backend responds.
- **Agent result cards** — expandable cards per agent showing individual findings.
- **Judge rationale panel** — displays the full rationale string from the Final Judge.
- **Conflict Detector & Evidence Checker panels** — surfaces conflict descriptions and the supported/unsupported finding breakdown.
- **Verdict banner** — colour-coded `APPROVE` / `REJECT` with an escalation badge when a rejection co-occurs with agent conflicts.

---

## Project Structure

```
councilai-ibm-hackathon/
├── agents/
│   ├── base.py              # BaseAgent ABC — all specialists subclass this
│   ├── security.py          # SecurityAgent
│   ├── architecture.py      # ArchitectureAgent
│   ├── testing.py           # TestingAgent
│   ├── performance.py       # PerformanceAgent
│   ├── aggregator.py        # Conflict Detector: aggregate() + detect_conflicts()
│   ├── evidence.py          # Evidence Checker: check_evidence()
│   ├── judge.py             # Final Judge: judge()
│   └── diff_parser.py       # DiffParser — unified diff → FileDiff/HunkSummary
├── backend/
│   ├── main.py              # FastAPI app; POST /review endpoint
│   ├── models.py            # Pydantic models (AgentResult, Verdict, etc.)
│   └── requirements.txt
├── services/
│   └── watsonx_client.py    # IBM watsonx.ai SDK wrapper
├── dashboard/               # React 18 + Vite frontend
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       ├── components/      # Header, DemoButtons, PipelineDiagram, ReviewResults
│       └── data/demoDiffs.js
├── tests/                   # 217 pytest tests (no watsonx credentials required)
├── bob_sessions/            # IBM Bob session screenshots (hackathon requirement)
├── .env.example             # Environment variable template
└── docker-compose.yml
```

---

## Running the App

### Prerequisites

- Python 3.11+
- Node.js 18+
- IBM watsonx.ai credentials (optional — deterministic fallback runs without them)

### 1 — Configure environment

```bash
cp .env.example .env
# Edit .env and add your WATSONX_API_KEY and WATSONX_PROJECT_ID
```

### 2 — Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# API running at http://127.0.0.1:8000
# Interactive docs at http://127.0.0.1:8000/docs
```

### 3 — Dashboard

```bash
cd dashboard
npm install
npm run dev
# Dashboard at http://localhost:5173
```

### 4 — Run a review

Open **http://localhost:5173** and click one of the three demo PR buttons to trigger the full multi-agent pipeline.

To call the API directly:

```bash
curl -X POST http://localhost:8000/review \
  -H "Content-Type: application/json" \
  -d '{"diff": "+    password = \"hunter2\"\n", "context": "login refactor"}'
```

---

## Tests

The test suite covers all four specialist agents, the Conflict Detector, Evidence Checker, Final Judge, and the `/review` HTTP endpoint. No watsonx credentials are required — tests exercise the deterministic fallback logic.

```bash
# From the repo root
pytest tests/ -v
# 217 passed in ~1s
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI Agents | IBM Bob subagents (parallel `ThreadPoolExecutor`) |
| LLM | IBM watsonx.ai — `meta-llama/llama-3-3-70b-instruct` |
| Backend | Python + FastAPI + Pydantic v2 |
| Frontend | React 18 + Vite |
| Testing | pytest (217 tests) |
| Containerisation | Docker + docker-compose |

---

## Team

| Member | Role |
|---|---|
| Farhan | Backend · Agent Orchestration |
| Fatima | Frontend · Testing · Demo |

---

## Security

Credentials are never hardcoded. All secrets are loaded from environment variables via `os.getenv()`. The `.env` file is gitignored. See [`SECURITY.MD`](SECURITY.MD) for full guidelines.

---

<div align="center">

Built with IBM Bob · watsonx.ai · IBM TechXchange Hackathon 2026

</div>

## Security Note
Demo fixtures use clearly fake placeholder credentials (e.g. `fake_secret_key_12345`) to trigger the Security Agent detection during demonstrations. No real credentials exist in this repository. Real IBM watsonx credentials are stored locally in `.env` which is gitignored.
