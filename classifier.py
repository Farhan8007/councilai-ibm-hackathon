"""
Change classifier for CouncilAI.

Classifies a structured diff into one of the change-type taxonomy buckets
used by the Evidence Judge's relevance weight matrix (Person A, Hour 9-14).

Strategy (per architecture.html "classifier" node): file-path heuristics
first (fast, free, deterministic — also the offline/no-API-key fallback),
then a single fast IBM Granite call to refine the call when heuristics are
ambiguous. Never blocks the pipeline if watsonx is unreachable — heuristic
result is returned with reasoning noting the fallback.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

CHANGE_TYPES = [
    "auth_change", "schema_migration", "perf_critical", "ui_only",
    "config_change", "feature_addition", "bug_fix", "refactor", "unknown",
]

# File-path heuristics, checked in priority order (first match wins for
# the primary signal; used both standalone and as a prior for the LLM call)
_PATH_RULES: List[tuple] = [
    (re.compile(r"(^|/)(migrations?|schema)/", re.I), "schema_migration"),
    (re.compile(r"\.(proto)$", re.I), "schema_migration"),
    (re.compile(r"(^|/)(auth|authn|authz|login|session|oauth|jwt)", re.I), "auth_change"),
    (re.compile(r"(^|/)(api/v\d+|public/)", re.I), "schema_migration"),
    (re.compile(r"\.(css|scss|less)$", re.I), "ui_only"),
    (re.compile(r"\.(jsx|tsx|vue|html)$", re.I), "ui_only"),
    (re.compile(r"(^|/)(config|settings)/|\.(ya?ml|toml|ini|env)$", re.I), "config_change"),
    (re.compile(r"(^|/)(test|tests|spec|__tests__)/", re.I), "bug_fix"),
    (re.compile(r"(^|/)(cache|queue|worker|batch|stream)/", re.I), "perf_critical"),
]


def _heuristic_classify(diff_schema: Dict[str, Any]) -> Dict[str, Any]:
    files = diff_schema.get("files", [])
    votes: Dict[str, int] = {}

    for f in files:
        path = f.get("path", "")
        for pattern, change_type in _PATH_RULES:
            if pattern.search(path):
                votes[change_type] = votes.get(change_type, 0) + 1
                break

    if not votes:
        # No path signal — fall back on additions vs deletions ratio as a
        # weak heuristic between feature_addition and refactor.
        total_add = sum(
            1 for f in files for h in f.get("hunks", []) for l in h.get("lines", []) if l.get("type") == "add"
        )
        total_del = sum(
            1 for f in files for h in f.get("hunks", []) for l in h.get("lines", []) if l.get("type") == "del"
        )
        if total_add and total_del and total_add < total_del * 1.5:
            return {"type": "refactor", "confidence": 0.35, "reasoning": "No path signal; edit ratio suggests a refactor."}
        if total_add:
            return {"type": "feature_addition", "confidence": 0.35, "reasoning": "No path signal; mostly additions."}
        return {"type": "unknown", "confidence": 0.2, "reasoning": "No path or line-count signal available."}

    winner = max(votes, key=votes.get)
    total_votes = sum(votes.values())
    confidence = round(min(0.9, 0.5 + 0.4 * (votes[winner] / total_votes)), 2)
    return {
        "type": winner,
        "confidence": confidence,
        "reasoning": f"File-path heuristics matched '{winner}' on {votes[winner]}/{len(files)} changed files.",
    }


def _get_watsonx_iam_token() -> str:
    api_key = os.getenv("IBM_WATSONX_API_KEY")
    if not api_key:
        raise RuntimeError("IBM_WATSONX_API_KEY not set")
    resp = httpx.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={
            "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
            "apikey": api_key,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _granite_refine(diff_schema: Dict[str, Any], prior: Dict[str, Any]) -> Dict[str, Any]:
    """
    One fast IBM Granite call to confirm/override the heuristic prior.
    Raises on any failure — callers should catch and fall back to the
    heuristic result so the pipeline never blocks on watsonx availability.
    """
    project_id = os.getenv("IBM_WATSONX_PROJECT_ID")
    url = os.getenv("IBM_WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    if not project_id:
        raise RuntimeError("IBM_WATSONX_PROJECT_ID not set")

    token = _get_watsonx_iam_token()

    file_paths = [f.get("path") for f in diff_schema.get("files", [])][:20]
    prompt = (
        "Classify this code diff. Respond ONLY with a single valid JSON object, "
        "no preamble, no markdown fences, matching exactly this schema: "
        '{"type": one of ' + json.dumps(CHANGE_TYPES) + ', "confidence": float 0-1, "reasoning": str}.\n\n'
        f"Changed files: {json.dumps(file_paths)}\n"
        f"Heuristic prior guess: {prior['type']} (confidence {prior['confidence']})\n"
        "Confirm or override the prior based on the file paths and change shape."
    )

    resp = httpx.post(
        f"{url}/ml/v1/text/generation?version=2023-05-29",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "model_id": "ibm/granite-13b-instruct-v2",
            "input": prompt,
            "project_id": project_id,
            "parameters": {"max_new_tokens": 200, "temperature": 0.0, "decoding_method": "greedy"},
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    generated_text = resp.json()["results"][0]["generated_text"].strip()

    # Be defensive: strip accidental markdown fences before parsing.
    generated_text = re.sub(r"^```(json)?|```$", "", generated_text.strip(), flags=re.MULTILINE).strip()
    parsed = json.loads(generated_text)

    if parsed.get("type") not in CHANGE_TYPES:
        raise ValueError(f"Granite returned invalid type: {parsed.get('type')}")

    return {
        "type": parsed["type"],
        "confidence": float(parsed.get("confidence", prior["confidence"])),
        "reasoning": parsed.get("reasoning", "Granite classification."),
    }


def classify_change(diff_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Classify a structured diff (diff_schema.json shape) into a change type.

    Returns: {"type": str, "confidence": float, "reasoning": str}
    """
    prior = _heuristic_classify(diff_schema)

    if not os.getenv("IBM_WATSONX_API_KEY"):
        logger.info("IBM_WATSONX_API_KEY not set — using heuristic-only classification")
        return prior

    try:
        return _granite_refine(diff_schema, prior)
    except Exception as e:
        logger.warning(f"Granite classification failed, falling back to heuristic: {e}")
        prior["reasoning"] += " (Granite call unavailable — heuristic fallback used.)"
        return prior


if __name__ == "__main__":
    sample = {
        "files": [
            {"path": "auth/login.py", "hunks": [{"lines": [{"type": "add", "content": "pass"}]}]},
            {"path": "auth/session.py", "hunks": [{"lines": [{"type": "add", "content": "pass"}]}]},
        ]
    }
    print(json.dumps(classify_change(sample), indent=2))
