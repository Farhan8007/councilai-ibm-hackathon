"""
Agent client for CouncilAI.

Calls Person A's agent service (one HTTP call per agent, run in parallel
by the orchestrator via asyncio.gather). Validates every response against
schema/verdict_schema.json — no silent malformed verdicts, per the Hour 1
sync agreement. Agent timeout is 30s; on timeout or repeated schema
failure, returns a WARN verdict rather than crashing the pipeline.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

import httpx
from jsonschema import Draft7Validator

logger = logging.getLogger(__name__)

AGENT_NAMES = ["security", "architecture", "testing", "performance"]

_SCHEMA_PATH = Path(__file__).parent / "schema" / "verdict_schema.json"
_VERDICT_VALIDATOR = Draft7Validator(json.loads(_SCHEMA_PATH.read_text()))

AGENT_TIMEOUT_SECONDS = float(os.getenv("AGENT_TIMEOUT_SECONDS", "30"))


def _timeout_verdict(agent_name: str, reason: str = "Agent timed out — manual review required") -> Dict[str, Any]:
    return {
        "agent_name": agent_name,
        "decision": "WARN",
        "confidence": 0.2,
        "reasoning": reason,
        "citations": [],
        "is_timeout": True,
    }


def _validate_verdict(payload: Dict[str, Any]) -> bool:
    errors = list(_VERDICT_VALIDATOR.iter_errors(payload))
    if errors:
        logger.warning(f"Verdict schema validation failed: {[e.message for e in errors]}")
        return False
    return True


async def _call_one_agent(agent_name: str, diff_schema: Dict[str, Any], base_url: str) -> Dict[str, Any]:
    """
    Call a single agent endpoint: POST {base_url}/agents/{agent_name}
    Body: the structured diff (schema/diff_schema.json shape)
    Retries once on schema validation failure, then falls back to WARN.
    """
    url = f"{base_url.rstrip('/')}/agents/{agent_name}"

    async def _attempt() -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=diff_schema, timeout=AGENT_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()

    for attempt in range(2):
        try:
            payload = await asyncio.wait_for(_attempt(), timeout=AGENT_TIMEOUT_SECONDS)
            if _validate_verdict(payload):
                payload["agent_name"] = agent_name
                payload["is_timeout"] = False
                return payload
            logger.warning(f"{agent_name} attempt {attempt + 1}: invalid schema, retrying" if attempt == 0 else f"{agent_name}: invalid schema on retry, falling back to WARN")
        except asyncio.TimeoutError:
            logger.error(f"{agent_name} agent timed out after {AGENT_TIMEOUT_SECONDS}s")
            return _timeout_verdict(agent_name)
        except Exception as e:
            logger.error(f"{agent_name} agent call failed (attempt {attempt + 1}): {e}")
            if attempt == 1:
                return _timeout_verdict(agent_name, reason=f"Agent call failed: {e}")

    return _timeout_verdict(agent_name, reason="Agent returned malformed output twice — schema validation failed")


async def run_council(diff_schema: Dict[str, Any], base_url: str = None) -> Dict[str, Dict[str, Any]]:
    """
    Fire all 4 agents in parallel. Never raises — a single agent failure
    degrades to a WARN verdict for that agent rather than crashing the
    pipeline (asyncio.gather(..., return_exceptions=True) equivalent).

    Returns: {agent_name: verdict_dict}
    """
    base_url = base_url or os.getenv("AGENT_SERVICE_URL", "http://localhost:8100")

    results = await asyncio.gather(
        *[_call_one_agent(name, diff_schema, base_url) for name in AGENT_NAMES],
        return_exceptions=True,
    )

    verdicts: Dict[str, Dict[str, Any]] = {}
    for name, result in zip(AGENT_NAMES, results):
        if isinstance(result, Exception):
            logger.error(f"{name} agent raised unexpectedly: {result}")
            verdicts[name] = _timeout_verdict(name, reason=f"Unhandled exception: {result}")
        else:
            verdicts[name] = result

    return verdicts
