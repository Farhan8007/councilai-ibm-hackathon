# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Stack

Python 3.11, FastAPI, SQLAlchemy 2.0, PostgreSQL 15 + pgvector, IBM watsonx (Granite). Single flat package — all modules are in the repo root, no `src/` directory.

## Commands

```bash
# Start DB (required before running anything that touches SQLAlchemy)
docker compose up -d db

# Init DB tables (run once after `docker compose up -d db`)
python models.py

# Run the API
uvicorn main:app --reload --port 8000

# Sanity-check diff parser + write test_diff.json fixture
python diff_parser.py

# End-to-end pipeline test against fixture (no live PR or agent service needed)
python test_pipeline.py

# Stress test (3 concurrent reviews)
python test_pipeline.py --stress
```

There is **no test framework** (no pytest, no unittest runner). `test_pipeline.py` is the only test harness and is run directly with `python`.

## Critical Patterns

### SQLAlchemy 2.0
Raw string `db.execute("SELECT 1")` raises. Always wrap in `text(...)`:
```python
from sqlalchemy import text
db.execute(text("SELECT 1"))
```

### unidiff API
`PatchedFile` subclasses `list` directly — there is **no `.hunks` attribute**. Iterate `patched_file` directly. `f.added` and `f.removed` are `int` counts, not lists.

### IBM watsonx — always optional
Every watsonx call (classifier, embedder) must degrade gracefully when `IBM_WATSONX_API_KEY` is unset. The pattern: heuristic/pseudo result first, attempt real call only if key is set, `except Exception → log warning + return heuristic result`. Never raise or block the pipeline.

### Agent client fallback
`agent_client.run_council()` never raises. On timeout or schema failure it returns `{decision: "WARN", confidence: 0.2, is_timeout: true}`. The pipeline must handle WARN verdicts as normal, not as errors.

### pgvector embedding dimension
Embeddings are **384-dim** (IBM `slate-125m-english-rtrvr`). The `Vector(384)` column type in `models.py` must stay in sync. Adjust the constant `EMBEDDING_DIM` in `embedding.py` if the model changes.

### diff_text_override (fixture path)
`orchestrator.run_pipeline()` accepts `diff_text_override` to skip the GitHub fetch. Use this for all local/test runs — see `test_pipeline.py` and the `/review/test` endpoint.

## Agent/Schema Contract

Two JSON schemas under `schema/` define the inter-team contract (committed at Hour 1 sync and must not be changed without agreement):
- `schema/diff_schema.json` — what `diff_parser.build_diff_schema()` produces; agents consume this.
- `schema/verdict_schema.json` — what each agent's `/agents/{name}` endpoint must return; validated by `agent_client._validate_verdict()`.

Verdict decisions are one of: `APPROVE | REJECT | WARN`. The extended `DecisionEnum` (`REQUEST_CHANGES`, `ESCALATE_TO_HUMAN`) exists in the DB but agents only return the three-value set above.

## Handoff Boundary

`orchestrator.run_pipeline()` ends at `review.status = "awaiting_verdict"` with `conflict_count: 0`. Conflict detection, evidence judge, and verdict synthesis are downstream work (not in this repo yet).

## Environment Variables

All config via `.env` (see `.env.example`). Key ones:
- `DATABASE_URL` — required; no default.
- `AGENT_SERVICE_URL` — defaults to `http://localhost:8100`.
- `AGENT_TIMEOUT_SECONDS` — defaults to `30`.
- `IBM_WATSONX_API_KEY` / `IBM_WATSONX_PROJECT_ID` / `IBM_WATSONX_URL` — all optional; pipeline runs without them.
- `GITHUB_WEBHOOK_SECRET` — if unset, webhook accepts all requests (dev mode, logs a warning).

## Code Style

- Imports: stdlib → third-party → local, separated by blank lines.
- All public functions have docstrings.
- Logging via `logger = logging.getLogger(__name__)` in every module; never `print()` except in `__main__` blocks.
- `Optional[T]` for nullable parameters; explicit `None` defaults.
- Enums subclass both `str` and `enum.Enum` (e.g. `class DecisionEnum(str, enum.Enum)`) so they serialise as plain strings.
- No type-ignore comments; keep mypy-compatible annotations throughout.
