# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Coding Rules (Non-Obvious)

- **Credential safety is mandatory**: Never use literal strings for secrets. Always `os.getenv()` / `process.env`. The `.bobignore` actively blocks logging of credential patterns — this is a hackathon rule, not optional.
- **`bob_sessions/` must only contain exported screenshots**, not live session artefacts. Do not programmatically write files there.
- **`config.json` / `config.yaml` / `secrets.*` are gitignored globally** — do not create files with those names for app configuration. Use `settings.py` or `.env`-backed classes instead.
- **Agent pipeline order is fixed**: Security → Architecture → Testing → Performance all run in parallel via `ThreadPoolExecutor` in `backend/main.py`; Conflict Detector, Evidence Checker, and Final Judge run sequentially after. Do not reorder or merge these stages.
- Backend entry point convention (from README): `uvicorn main:app` — keep the FastAPI app object in `backend/main.py`.

## Project Overview

CouncilAI is an IBM TechXchange Hackathon 2026 project: a multi-agent code review system that runs four IBM Bob specialist subagents in parallel (Security, Architecture, Testing, Performance) with a Conflict Detector → Evidence Checker → Final Judge pipeline.

## Stack

| Layer | Technology |
|---|---|
| AI Agents | IBM Bob subagents (parallel `spawn_subagent` / `ThreadPoolExecutor`) |
| LLM | watsonx.ai / IBM Granite |
| Backend | Python + FastAPI (`backend/`) |
| Frontend | React (`frontend/`) |
| Agent definitions | `agents/` |
| Tests | `tests/` |

## Setup

```bash
# Backend
cd backend && pip install -r requirements.txt

# Frontend
cd frontend && npm install

# Environment
cp .env.example .env   # then fill in watsonx credentials
```

## Security — CRITICAL

- **Never hardcode credentials.** All secrets go in `.env` (gitignored).
- Use `os.getenv('VAR')` in Python, `process.env.VAR` in JS.
- `.bobignore` prevents Bob from logging credential patterns — do NOT remove patterns from it.
- `.gitignore` blocks `config.json`, `config.yaml`, `secrets.*`, `*token*`, `*password*`, `*credentials*` — avoid naming files with those patterns.
- `bob_sessions/` is **required** for hackathon submission; committed screenshots go there.

## Architecture

Four IBM Bob specialist agents run **in parallel** via `ThreadPoolExecutor` (see `backend/main.py`), each reviewing the same diff:

- 🔒 **SecurityAgent** (`agents/security.py`) — regex-based checks for hardcoded credentials, `eval()`/`exec()`/`pickle.loads`/`shell=True`, hardcoded IPs, and non-TLS URLs.
- 🏗️ **ArchitectureAgent** (`agents/architecture.py`) — evaluates design patterns, scalability, and coupling.
- 🧪 **TestingAgent** (`agents/testing.py`) — checks coverage hints, edge cases, and test quality signals.
- ⚡ **PerformanceAgent** (`agents/performance.py`) — flags nested loops (O(n²)), `SELECT *`, `time.sleep()` in async paths, and list comprehensions inside loops.

Results flow through three sequential pipeline stages:

1. **Conflict Detector** (`agents/aggregator.py` → `aggregate()` + `detect_conflicts()`) — identifies agents that disagree (one passed, another failed).
2. **Evidence Checker** (`agents/evidence.py` → `check_evidence()`) — classifies each finding as supported (agent produced `raw_output`) or unsupported.
3. **Final Judge** (`agents/judge.py` → `judge()`) — `REJECT` if any failing agent has at least one supported finding; `APPROVE` otherwise. Conflicts are contextual only.

```
               IBM Bob
                  │
     ┌────────────┼────────────┬────────────┐
     ↓            ↓            ↓            ↓
 Security   Architecture  Testing    Performance
   Agent       Agent       Agent       Agent
     │            │            │            │
     └────────────┼────────────┴────────────┘
                  ↓
           Conflict Detector
                  ↓
           Evidence Checker
                  ↓
             Final Judge
                  ↓
        ┌─────────┴─────────┐
        ↓                   ↓
     APPROVE              REJECT
```

## Key Files

| File | Purpose |
|---|---|
| `backend/main.py` | FastAPI app; `POST /review` endpoint; parallel agent fan-out with timeout-safe `try/except` per future |
| `backend/models.py` | Pydantic models: `AgentResult`, `AgentRole`, `ConflictReport`, `EvidenceReport`, `JudgeDecision`, `Verdict` |
| `agents/base.py` | `BaseAgent` ABC — all specialist agents subclass this; implement `_run_checks()` |
| `agents/security.py` | `SecurityAgent` — credential / dangerous-call / IP / HTTP pattern checks |
| `agents/architecture.py` | `ArchitectureAgent` — design and coupling checks |
| `agents/testing.py` | `TestingAgent` — test quality and coverage checks |
| `agents/performance.py` | `PerformanceAgent` — O(n²) loop, SELECT *, sleep, list-comp checks |
| `agents/diff_parser.py` | `DiffParser` — parses unified diffs into `FileDiff` / `HunkSummary` objects via `unidiff` |
| `agents/aggregator.py` | `aggregate()` + `detect_conflicts()` — Conflict Detector stage |
| `agents/evidence.py` | `check_evidence()` — Evidence Checker stage |
| `agents/judge.py` | `judge()` — Final Judge stage |

## Agent Timeout Behaviour

If any specialist agent raises (e.g. network timeout, unhandled exception), `backend/main.py` catches the exception per-future and synthesises a `passed=False` `AgentResult` with a `findings` entry describing the failure. The pipeline continues with partial results — it never returns HTTP 500 due to a single agent failure.

## Commands

```bash
# Backend (from backend/)
uvicorn main:app --reload

# Frontend (from frontend/)
npm run dev

# Tests (from repo root)
pytest tests/
```
