# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Documentation Context (Non-Obvious)

- `bob_sessions/` is a **hackathon submission requirement**, not a dev artifact folder. It must contain IBM Bob session screenshots for judging.
- `SECURITY.MD` (uppercase `.MD`) contains the project's mandatory credential rules — consult it before advising on any configuration or secret management.
- All source directories (`backend/`, `frontend/`, `agents/`, `tests/`, `docs/`) are **empty scaffolds** as of project start. No actual source code or config files exist yet.
- The multi-agent pipeline (three parallel Bob subagents → Conflict Detector → Evidence Checker → Final Judge) is the core architectural concept; all Q&A about system design should reference this flow.
