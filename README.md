# CouncilAI — Person B (Platform Engineer)

## Review of Hours 0–1 (as uploaded)

Not complete. Issues found and fixed:

| Issue | Fix |
|---|---|
| `diff_parser.py`: used `patched_file.hunks` — this `unidiff` version has `PatchedFile` subclass `list` directly (no `.hunks` attr) → crashed on every diff | Iterate `patched_file` directly |
| `diff_parser.py`: `get_stats()` called `len(f.added)` / `len(f.removed)` — these are already `int` counts in this `unidiff` version, not lists | `sum(f.added ...)` |
| `main.py`: `db.execute("SELECT 1")` — raw string execute is rejected by SQLAlchemy 2.0 | Wrapped in `text("SELECT 1")` |
| No `docker-compose.yml` / pgvector setup, despite `requirements.txt` listing `pgvector` and the plan requiring `CREATE EXTENSION vector` | Added `docker-compose.yml`, `Dockerfile`, `docker/init.sql` |
| `models.py` had no pgvector column, no `AuditLog` table, no `change_type` on `Review` — required by the plan's Hour 4–9 deliverables | Added `Vector(384)` embedding columns, `AuditLog`, `ChangeTypeEnum` |
| No `diff_schema.json` / `verdict_schema.json` committed — the plan's Hour 1 sync explicitly requires these before Person A can proceed | Added under `schema/`, fixture validated against it |
| No change classifier (Hour 1–4 deliverable) | Added `classifier.py` |
| No GitHub PR diff fetch via the documented API shape (`GET /pulls/{n}` diff media type + `GET /pulls/{n}/files`), no PR-review posting helper | Added `github_client.py` |
| No pipeline orchestrator (`POST /review/{pr_id}`, Hour 4–9's "most critical deliverable" per the plan) | Added `orchestrator.py` |
| No opinion aggregator | Added `aggregator.py` |
| No agent client (schema validation, 30s timeout → WARN, retry-once, per the Hour 1 sync agreement) | Added `agent_client.py` |
| `.env.example` was malformed (no newlines) | Rewritten |

## What's implemented now (Hours 0–6 scope)

- **Hour 0–1**: FastAPI scaffold, Docker Compose (Postgres 15 + pgvector), DB models, HMAC webhook skeleton, diff schema draft.
- **Hour 1–4**: HMAC-SHA256 webhook validation (`github_client.validate_github_webhook_signature`), diff parsing → `schema/diff_schema.json`-shaped output (`diff_parser.build_diff_schema`), change classifier with file-path heuristics + optional Granite refinement (`classifier.classify_change`), `test_diff.json` fixture generation.
- **Hour 4–9 (partial, through hour 6)**: full DB schema (`reviews`, `changed_files`, `opinions`, `citations`, `conflicts`, `verdicts`, `precedent_decisions`, `audit_log`), pgvector columns for the precedent engine, `orchestrator.run_pipeline()` wiring fetch → parse → classify → fire-agents → aggregate → persist end to end, `aggregator.store_opinions()`, `agent_client.run_council()` (parallel `asyncio.gather`, 30s timeout, one retry on schema failure, WARN fallback, never raises).

Not yet implemented (correctly out of scope — Person A's Hour 9–14+ work): conflict detector, relevance weight matrix, evidence judge, verdict synthesis, reasoning trace generator. `orchestrator.py` leaves `review.status = "awaiting_verdict"` and `conflict_count: 0` as the explicit handoff point.

## Hours 6–9 additions

- **`embedding.py`**: populates `Review.diff_embedding` (pgvector, dim 384) via IBM watsonx `slate-125m-english-rtrvr-v2` when `WATSONX_API_KEY` is set, else a deterministic offline pseudo-embedding — so the precedent engine's pgvector similarity search is exercisable without IBM credentials. Wired into `orchestrator.run_pipeline()` right after the diff is fetched.
- **`fixtures/demo_pr_hour9_sync.diff`**: the exact scenario the plan's Hour 9 sync calls for — a string-formatted SQL injection in `auth.py`, a function with zero test coverage, and an O(n²) nested loop in `reports.py`.
- **`test_pipeline.py`**: Hour 9 sync harness.
  - `python test_pipeline.py` — single end-to-end run against the fixture, prints each agent's decision/confidence/timeout status.
  - `python test_pipeline.py --stress` — 3 concurrent reviews via `asyncio.gather`, checks for unhandled exceptions or DB constraint violations under concurrent load (pulled forward from Hour 19-22's stress test since the orchestrator/DB plumbing is ready).
  - Until Person A's agent service is live at `AGENT_SERVICE_URL`, agents legitimately resolve to WARN/timeout verdicts (per `agent_client.py`'s documented fallback) — that's expected and is what proves the pipeline never crashes on agent failure. Re-run once `/agents/{name}` endpoints exist to confirm real verdicts land in `opinions` with citations.

## Hours 9–24 additions (Person B remainder)

Person A's items in this range (real conflict detector, real Evidence Judge citations, dashboard-facing verdict polish) belong to your teammate — everything below is scoped to Person B's actual deliverables per the plan, plus one bridging piece:

- **`verdict_engine.py` (bridging piece, not in the original plan for B):** Person A's conflict detector + Evidence Judge (Hours 9–19) didn't exist yet as separate code, so nothing downstream (`pr_commenter.py`, the dashboard) had a real `Verdict` row to render. This implements the plan's exact formulas (`adjusted_confidence = confidence × (0.4 + 0.6 × evidence_quality)`, `weighted_score = Σ weight × adjusted_confidence × decision_sign`, `APPROVE if >0.5 / REJECT if <-0.5 / else REQUEST_CHANGES`, escalate on reversibility-risk paths or low confidence) plus a basic 3-of-5 conflict detector (decision coexistence, severity gap, confidence delta). **Swap the internals of `synthesize_verdict()` for Person A's real Evidence Judge — the function signature stays the same, so nothing else needs to change.**
- **`council.yaml` + `relevance_weights.py`**: the relevance weight matrix as a config file instead of hardcoded — a5's "spare time" item, done now since `/weights` needed a source anyway.
- **`precedent_engine.py`** (Hour 9–14, b3): pgvector cosine-similarity search (`<=>` operator) over `precedent_decisions`, confidence-weight boost above the configured similarity threshold, and `seed_demo_precedents()` — 5 hand-picked precedents matching the 3 demo PRs, since (per the plan) vector search on a tiny dataset is unreliable and needs seeding to fire reliably on stage.
- **`pr_commenter.py`** (Hour 9–14, b3): markdown verdict card exactly matching the plan's template, `post_verdict_to_github()` posts a real PR review, inline citations are filtered to lines actually inside a changed hunk (avoids the 422 the Hour-14 sync explicitly warns about) with automatic fallback to a body-only review if the inline post fails.
- **`fixtures/demo_pr_1_clean.diff` / `_2_conflict.diff` / `_3_schema_migration.diff`**: the 3 scripted demo PRs from the Hour 14–19 dashboard task — clean approve, Security-vs-Architecture conflict (SQLi fixed but a data-exposure + layering issue introduced), and an irreversible schema migration that should escalate. All validated parseable by `unidiff`.
- **`dashboard/index.html`** (Hour 14–19, b4): single-file React dashboard (CDN React, no build step — Bob-coin- and setup-friendly) with a verdict card, per-agent confidence bars, an expand/collapse reasoning-trace panel (monospace, key numbers highlighted — the Hour 19 sync's "most important UI element"), 5s live polling via `GET /review/{id}` (no page reload), an agreement-rate line ("3 of 4 agents agree" / "Split verdict: 2 APPROVE vs 2 REJECT" — b5 item), and one-click buttons for all 3 demo PRs. Served at `/dashboard` (FastAPI mounts and returns it directly — no Node/npm needed).
- **`main.py` additions**: `POST /demo/trigger/{1,2,3}` (runs the real pipeline against a fixture, no live GitHub PR needed — what the dashboard buttons call), `GET /weights` / `POST /weights/reload` (a5 spare-time item), `POST /precedents/seed`, `GET /` redirects to `/dashboard`.
- **`postman_collection.json`** (Hour 19–22, b5): the code-free demo fallback — trigger + fetch all 3 demo PRs and list reviews, no frontend required.

### Not implemented in this repo (still Person A's, correctly out of scope for B)
Real per-agent LLM calls (Security/Architecture/Testing/Performance via watsonx — `agent_client.py` calls out to `AGENT_SERVICE_URL`, which is Person A's service), the full 5-type conflict detector and reversibility classifier with real citation-overlap logic, human escalation copy tuned by hand, and the 90-second backup screen recording (that one's genuinely just you hitting record — script: open dashboard → click PR #2 → watch agents populate → expand reasoning trace → scroll to the GitHub PR comment).

### Running the full demo end to end

```bash
docker compose up -d db
python models.py
uvicorn main:app --reload --port 8000
curl -X POST http://localhost:8000/precedents/seed   # once, before demoing
open http://localhost:8000/dashboard                 # or just visit it in a browser
# click any of the 3 demo PR buttons — or, code-free fallback:
# import postman_collection.json into Postman and run the folder top to bottom
```


```bash
cp .env.example .env          # fill in GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET, IBM_WATSONX_* (optional)
docker compose up -d db       # Postgres 15 + pgvector
pip install -r requirements.txt --break-system-packages
python models.py              # creates extension + tables
python diff_parser.py         # sanity check + writes test_diff.json
uvicorn main:app --reload --port 8000
curl http://localhost:8000/health
```

Test the pipeline without a live PR or without Person A's agent service running (agents will correctly degrade to WARN/timeout verdicts until `AGENT_SERVICE_URL` is live):

```bash
curl -X POST http://localhost:8000/review/test \
  -H "Content-Type: application/json" \
  -d "{\"diff_text\": $(python3 -c 'import json;print(json.dumps(open("/dev/stdin").read()))' < some.diff)}"
```

## Verified locally (this environment has no Docker/Postgres, so DB I/O itself is untested here)

- All modules import cleanly, `main.app` registers all routes.
- `diff_parser.py` fixed and runs end-to-end; `test_diff.json` output validates against `schema/diff_schema.json`.
- `classifier.py` heuristic path runs and returns a correctly-shaped result with no watsonx credentials present.

**Next real checkpoint**: run `docker compose up`, `python models.py`, then hit `/review/test` with the fixture diff and confirm all rows land correctly in Postgres — this is the Hour 4 / Hour 9 sync from the plan.
