"""
GitHub API client for CouncilAI.

Covers:
  - HMAC-SHA256 webhook signature validation
  - Fetching the full unified diff for a PR
  - Fetching per-file metadata (GET /pulls/{number}/files) for language /
    rename / binary detection
  - Posting the verdict back as a PR review (used from Hour 9+, stubbed
    here so Person B's Hour 4-9 orchestrator can call it once the verdict
    engine exists)
"""

import hashlib
import hmac
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def validate_github_webhook_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Validate GitHub webhook HMAC-SHA256 signature using constant-time comparison.

    Args:
        request_body: Raw request body bytes
        signature_header: X-Hub-Signature-256 header value (format: sha256=...)

    Returns:
        True if signature is valid, False otherwise
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").encode()

    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET not set — accepting unsigned webhooks (DEVELOPMENT ONLY)")
        return True

    if not signature_header or "=" not in signature_header:
        logger.error("Missing or malformed X-Hub-Signature-256 header")
        return False

    try:
        algorithm, signature_hex = signature_header.split("=", 1)
    except ValueError:
        return False

    if algorithm != "sha256":
        logger.error(f"Unexpected algorithm: {algorithm}")
        return False

    expected_signature = hmac.new(secret, request_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature_hex)


def _auth_headers(accept: str = "application/vnd.github.v3+json") -> Dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {"Accept": accept}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


async def fetch_pr_diff(owner: str, repo: str, pr_number: int) -> Optional[str]:
    """
    Fetch the full unified diff text for a PR directly from the PR
    resource, using the diff media type. This is the simplest way to get
    a complete, ready-to-parse multi-file unified diff.

    GET /repos/{owner}/{repo}/pulls/{pr_number}
    Accept: application/vnd.github.v3.diff
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = _auth_headers(accept="application/vnd.github.v3.diff")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)
            response.raise_for_status()
            return response.text
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub diff fetch failed ({e.response.status_code}): {e.response.text[:300]}")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch PR diff: {e}")
        return None


async def fetch_pr_files(owner: str, repo: str, pr_number: int) -> List[Dict[str, Any]]:
    """
    Fetch per-file metadata for a PR.

    GET /repos/{owner}/{repo}/pulls/{pr_number}/files

    Returns a list of dicts with keys like: filename, status, additions,
    deletions, changes, patch (per-file unified diff fragment). Useful for
    language/rename/binary detection and for the change classifier's
    file-path heuristics.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"
    headers = _auth_headers()
    files: List[Dict[str, Any]] = []
    page = 1

    try:
        async with httpx.AsyncClient() as client:
            while True:
                response = await client.get(
                    url, headers=headers, params={"per_page": 100, "page": page}, timeout=15.0
                )
                response.raise_for_status()
                batch = response.json()
                files.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub files fetch failed ({e.response.status_code}): {e.response.text[:300]}")
    except Exception as e:
        logger.error(f"Failed to fetch PR files: {e}")

    return files


async def fetch_diff_from_github(diff_url: str) -> Optional[str]:
    """
    Legacy helper: fetch a raw diff directly from a webhook-provided
    diff_url. Kept for backward compatibility with the webhook path that
    already has diff_url on the payload.
    """
    headers = _auth_headers(accept="application/vnd.github.v3.raw")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(diff_url, headers=headers, timeout=15.0)
            response.raise_for_status()
            return response.text
    except Exception as e:
        logger.error(f"Failed to fetch diff from GitHub: {e}")
        return None


async def post_pr_review(
    owner: str,
    repo: str,
    pr_number: int,
    commit_id: str,
    body_markdown: str,
    event: str,
    inline_comments: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Post the CouncilAI verdict as a PR review.

    POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews
    {
      "commit_id": commit_id,
      "body": body_markdown,
      "event": "APPROVE" | "REQUEST_CHANGES" | "COMMENT",
      "comments": [{"path": ..., "line": ..., "body": ...}, ...]
    }

    Note: `line` must fall within a changed hunk (not a pure context line)
    or GitHub returns 422. Callers should fall back to a file-level /
    review-body-only comment if inline placement is uncertain — see
    Hour 9-14 sync note in the plan.
    """
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    headers = _auth_headers()
    payload: Dict[str, Any] = {
        "commit_id": commit_id,
        "body": body_markdown,
        "event": event,
    }
    if inline_comments:
        payload["comments"] = inline_comments

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=15.0)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"GitHub review post failed ({e.response.status_code}): {e.response.text[:500]}")
        return None
    except Exception as e:
        logger.error(f"Failed to post PR review: {e}")
        return None
