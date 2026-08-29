# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Architecture Constraints (Non-Obvious)

- **Agent parallelism is a core design constraint**, not an optimisation. The three specialist agents (Security, Architecture, Testing) MUST run concurrently via `spawn_subagent`; sequential execution breaks the intended latency profile.
- **Pipeline stages are strictly sequential after the parallel phase**: Conflict Detector must receive all three agent outputs before running; Evidence Checker must receive Conflict Detector output; Final Judge is last. Design data flow accordingly.
- **`.gitignore` blocks `config.json` and `config.yaml` globally** — any plan involving JSON/YAML app config files under those names will silently fail to commit. Plan alternative naming (`app_config.json`, `settings.yaml`, etc.) or use environment-variable-backed config.
- **No dependency files exist yet** (`requirements.txt`, `package.json`). Any plan that assumes an existing environment must first account for bootstrapping these.
- **`docs/` is designated for architecture documentation** — route design docs and ADRs there, not to the root.
- Backend is FastAPI (Python); frontend is React. No ORM, database, or message queue is defined yet — any plan introducing persistence must make that choice explicitly.
