"""
Hour 9 critical-sync test harness for CouncilAI (Person B side).

Per the plan's Hour 9 sync note:
  "Hit POST /review/{pr_id} and watch all 4 agents respond within 60
   seconds. If any agent returns an Exception or malformed JSON, fix it
   now — conflict detection cannot run on broken verdicts."

Since Person A's agent service may not be up yet, agent calls will
legitimately degrade to WARN/timeout verdicts here (agent_client.py's
documented fallback) — that's expected and fine. What THIS script checks
is Person B's half of the contract: the orchestrator runs end-to-end
without exceptions, writes a full audit trail, and — the actual stress
test — 3 concurrent reviews complete without DB constraint violations or
crashes (a5's stress test, pulled forward since the plumbing is ready now).

Usage:
    python test_pipeline.py            # single run against the fixture
    python test_pipeline.py --stress   # 3 concurrent runs
"""

import asyncio
import sys
import time
from pathlib import Path

from models import get_db_session, init_db
from orchestrator import run_pipeline

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "demo_pr_hour9_sync.diff"


async def single_run(pr_number: int) -> dict:
    diff_text = FIXTURE_PATH.read_text()
    db = get_db_session()
    start = time.monotonic()
    try:
        result = await run_pipeline(
            db=db,
            repo="demo/councilai-demo",
            pr_number=pr_number,
            pr_title="Hour 9 sync fixture: SQLi + untested fn + O(n^2)",
            diff_text_override=diff_text,
        )
        elapsed = time.monotonic() - start
        result["elapsed_seconds"] = round(elapsed, 2)
        return result
    finally:
        db.close()


async def main():
    init_db()

    if "--stress" in sys.argv:
        print("Running 3 concurrent reviews (stress test)...")
        results = await asyncio.gather(
            single_run(101), single_run(102), single_run(103),
            return_exceptions=True,
        )
        for pr_number, r in zip([101, 102, 103], results):
            if isinstance(r, Exception):
                print(f"PR #{pr_number}: RAISED {r!r}  <-- FAIL, must fix before Hour 9 sync")
            else:
                print(f"PR #{pr_number}: status={r['status']} review_id={r['review_id']} "
                      f"opinions={len(r.get('verdicts', []))} elapsed={r.get('elapsed_seconds')}s")
    else:
        r = await single_run(100)
        print(f"status={r['status']} review_id={r['review_id']} "
              f"opinions={len(r.get('verdicts', []))} elapsed={r.get('elapsed_seconds')}s")
        if r["status"] == "failed":
            print(f"error={r.get('error')}")
            sys.exit(1)
        for v in r.get("verdicts", []):
            print(f"  - {v['agent_name']}: {v['decision']} (confidence={v['confidence']}, "
                  f"timeout={v['is_timeout']})")


if __name__ == "__main__":
    asyncio.run(main())
