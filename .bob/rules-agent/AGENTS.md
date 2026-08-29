# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Coding Rules (Non-Obvious)

- **Credential safety is mandatory**: Never use literal strings for secrets. Always `os.getenv()` / `process.env`. The `.bobignore` actively blocks logging of credential patterns — this is a hackathon rule, not optional.
- **`bob_sessions/` must only contain exported screenshots**, not live session artefacts. Do not programmatically write files there.
- **`config.json` / `config.yaml` / `secrets.*` are gitignored globally** — do not create files with those names for app configuration. Use `settings.py` or `.env`-backed classes instead.
- **Agent pipeline order is fixed**: Security → Architecture → Testing all run in parallel via `spawn_subagent`; Conflict Detector, Evidence Checker, and Final Judge run sequentially after. Do not reorder or merge these stages.
- **All source directories are currently empty scaffolds.** Before writing any code, create the appropriate dependency file first (`requirements.txt` for backend, `package.json` for frontend).
- Backend entry point convention (from README): `uvicorn main:app` — keep the FastAPI app object in `backend/main.py`.
