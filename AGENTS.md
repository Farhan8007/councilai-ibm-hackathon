# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Overview

CouncilAI is an IBM TechXchange Hackathon 2026 project: a multi-agent code review system using IBM Bob subagents in parallel (Security, Architecture, Testing agents) with a Conflict Detector → Evidence Checker → Final Judge pipeline.

## Stack

| Layer | Technology |
|---|---|
| AI Agents | IBM Bob subagents (parallel `spawn_subagent`) |
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

Three IBM Bob specialist subagents run **in parallel** via `spawn_subagent`, each reviewing the same code change:
- 🔒 Security Agent
- 🏗️ Architecture Agent
- 🧪 Testing Agent

Results flow through: **Conflict Detector → Evidence Checker → Final Judge** → `APPROVE` / `REJECT`

## Commands (once code is added)

```bash
# Backend (from backend/)
uvicorn main:app --reload

# Frontend (from frontend/)
npm run dev

# Tests (from tests/)
pytest             # Python tests
npm test           # JS tests
```

## Notes

- All source directories (`backend/`, `frontend/`, `agents/`, `tests/`) are currently empty scaffolds (`.gitkeep` only). Build tooling and dependency files are not yet committed.
- `docs/` is for architecture documentation.
