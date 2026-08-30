"""
Agent client for CouncilAI.

Calls Farhan's agent service via POST /review, which runs all 4 agents
internally and returns a single consolidated response. The per-agent
details are mapped back into the {agent_name: verdict_dict} shape the
orchestrator expects. Agent timeout is 30s; on any failure the affected
agents degrade to WARN verdicts rather than crashing the pipeline.
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


def _map_agent_detail(agent_name: str, detail: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a single entry from /review response's details.agents into the
    verdict_dict shape the orchestrator expects.

    passed=True  → decision="APPROVE"
    passed=False → decision="REJECT"
    confidence defaults to 0.8; raw_output becomes reasoning.
    """
    passed = detail.get("passed", False)
    findings = detail.get("findings", [])
    raw_output = detail.get("raw_output", "")

    # Build a human-readable reasoning string from available fields.
    reasoning_parts = []
    if raw_output:
        reasoning_parts.append(raw_output)
    if findings:
        reasoning_parts.append("Findings: " + "; ".join(str(f) for f in findings))
    reasoning = " | ".join(reasoning_parts) if reasoning_parts else ("Passed." if passed else "Did not pass.")

    return {
        "agent_name": agent_name,
        "decision": "APPROVE" if passed else "REJECT",
        "confidence": 0.8,
        "reasoning": reasoning,
        "citations": [],
        "is_timeout": False,
    }


async def run_council(diff_schema: Dict[str, Any], base_url: str = None) -> Dict[str, Dict[str, Any]]:
    """
    Call POST /review on Farhan's agent service, which runs all 4 agents
    internally and returns a single consolidated response. Never raises —
    any failure degrades every agent to a WARN verdict rather than crashing
    the pipeline.

    Returns: {agent_name: verdict_dict}
    """
    base_url = base_url or os.getenv("AGENT_SERVICE_URL", "http://localhost:8000")
    url = f"{base_url.rstrip('/')}/review"

    # Serialize the diff schema to a JSON string as the /review endpoint
    # expects {"diff": "<json string>", "context": ""}.
    diff_text = json.dumps(diff_schema)

    try:
        async with httpx.AsyncClient() as client:
            response = await asyncio.wait_for(
                client.post(url, json={"diff": diff_text, "context": ""}, timeout=AGENT_TIMEOUT_SECONDS),
                timeout=AGENT_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            body = response.json()
    except asyncio.TimeoutError:
        logger.error(f"/review timed out after {AGENT_TIMEOUT_SECONDS}s")
        return {name: _timeout_verdict(name) for name in AGENT_NAMES}
    except Exception as e:
        logger.error(f"/review call failed: {e}")
        return {name: _timeout_verdict(name, reason=f"Agent service call failed: {e}") for name in AGENT_NAMES}

    agents_detail: Dict[str, Any] = body.get("details", {}).get("agents", {})

    verdicts: Dict[str, Dict[str, Any]] = {}
    for name in AGENT_NAMES:
        if name in agents_detail:
            verdicts[name] = _map_agent_detail(name, agents_detail[name])
        else:
            logger.warning(f"/review response missing details for agent '{name}' — using WARN fallback")
            verdicts[name] = _timeout_verdict(name, reason=f"Agent '{name}' absent from /review response")

    return verdicts
