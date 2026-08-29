"""
Embedding client for CouncilAI.

Populates Review.diff_embedding / PrecedentDecision.diff_embedding
(pgvector columns, dim=384) so the precedent engine (Person B, Hour 9-14)
has real vectors to search against from hour 6 onward.

Uses IBM watsonx's `slate-125m-english-rtrvr` embedding model (384-dim)
when IBM_WATSONX_API_KEY is set. Falls back to a deterministic hash-based
pseudo-embedding otherwise, so the pipeline and pgvector similarity search
are fully exercisable offline / without IBM credentials — the pseudo
vectors are stable per diff (same diff text -> same vector) so nearest
neighbor search still behaves sanely for demo seeding.
"""

import hashlib
import logging
import os
import struct
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384
_WATSONX_EMBED_MODEL = "ibm/slate-125m-english-rtrvr"


def _iam_token() -> str:
    api_key = os.getenv("IBM_WATSONX_API_KEY")
    if not api_key:
        raise RuntimeError("IBM_WATSONX_API_KEY not set")
    resp = httpx.post(
        "https://iam.cloud.ibm.com/identity/token",
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": api_key},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _granite_embed(text: str) -> List[float]:
    project_id = os.getenv("IBM_WATSONX_PROJECT_ID")
    url = os.getenv("IBM_WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    if not project_id:
        raise RuntimeError("IBM_WATSONX_PROJECT_ID not set")

    token = _iam_token()
    # watsonx caps embedding input length; truncate very large diffs rather
    # than failing the whole pipeline on an oversized PR.
    truncated = text[:8000]

    resp = httpx.post(
        f"{url}/ml/v1/text/embeddings?version=2023-10-25",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"model_id": _WATSONX_EMBED_MODEL, "project_id": project_id, "inputs": [truncated]},
        timeout=20.0,
    )
    resp.raise_for_status()
    vector = resp.json()["results"][0]["embedding"]
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"Unexpected embedding dim {len(vector)}, expected {EMBEDDING_DIM}")
    return vector


def _pseudo_embed(text: str) -> List[float]:
    """
    Deterministic, dependency-free fallback: repeatedly hash the text with
    an incrementing salt and unpack each digest into floats, normalized to
    [-1, 1]. Not semantically meaningful, but stable and cheap — good
    enough to keep pgvector similarity search, seeding, and the
    orchestrator's embedding step fully testable offline.
    """
    vector: List[float] = []
    salt = 0
    while len(vector) < EMBEDDING_DIM:
        digest = hashlib.sha256(f"{salt}:{text}".encode("utf-8")).digest()
        # 32 bytes -> 8 unsigned ints -> 8 floats per round
        ints = struct.unpack(">8I", digest)
        vector.extend((i / 0xFFFFFFFF) * 2 - 1 for i in ints)
        salt += 1
    return vector[:EMBEDDING_DIM]


def embed_diff(diff_text: str) -> Optional[List[float]]:
    """
    Returns a 384-dim embedding for the given diff text. Never raises —
    logs and falls back to the deterministic pseudo-embedding so a
    watsonx outage never blocks the pipeline (embeddings are used for
    precedent lookup, not for the verdict itself).
    """
    if not diff_text:
        return None

    if os.getenv("IBM_WATSONX_API_KEY"):
        try:
            return _granite_embed(diff_text)
        except Exception as e:
            logger.warning(f"Granite embedding failed, using pseudo-embedding fallback: {e}")

    return _pseudo_embed(diff_text)


if __name__ == "__main__":
    v = embed_diff("diff --git a/auth.py b/auth.py\n+def login(): pass\n")
    print(f"dim={len(v)} sample={v[:5]}")
