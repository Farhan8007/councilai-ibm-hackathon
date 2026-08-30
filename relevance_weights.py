"""
Relevance weight matrix loader for CouncilAI.

Reads council.yaml so the matrix is configurable without a code change
(a5 "enterprise extensibility" item). Falls back to the plan's hardcoded
defaults if council.yaml is missing or malformed, so the pipeline never
breaks on a config typo mid-demo.
"""

import logging
import os
from pathlib import Path
from typing import Dict

import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "council.yaml"

_HARDCODED_DEFAULT = {
    "auth_change": {"security": 3.0, "architecture": 1.5, "testing": 1.0, "performance": 0.5},
    "schema_migration": {"security": 1.5, "architecture": 2.0, "testing": 2.5, "performance": 1.0},
    "feature_addition": {"security": 1.5, "architecture": 1.5, "testing": 3.0, "performance": 1.0},
    "refactor": {"security": 1.0, "architecture": 3.0, "testing": 1.5, "performance": 2.0},
    "default": {"security": 1.0, "architecture": 1.0, "testing": 1.0, "performance": 1.0},
}

_cache: Dict = {}


def _load() -> Dict:
    global _cache
    if _cache:
        return _cache
    try:
        raw = yaml.safe_load(_CONFIG_PATH.read_text())
        _cache = raw or {}
    except Exception as e:
        logger.warning(f"Could not load council.yaml, using hardcoded defaults: {e}")
        _cache = {"weights": _HARDCODED_DEFAULT}
    return _cache


def get_weights(change_type: str) -> Dict[str, float]:
    """Relevance weight per agent for a given change_type, falling back to 'default'."""
    cfg = _load()
    weights = cfg.get("weights", _HARDCODED_DEFAULT)
    return weights.get(change_type, weights.get("default", _HARDCODED_DEFAULT["default"]))


def get_all_weights() -> Dict:
    """Full matrix, for the /weights endpoint."""
    cfg = _load()
    return cfg.get("weights", _HARDCODED_DEFAULT)


def get_reversibility_patterns() -> list:
    cfg = _load()
    return cfg.get("escalation", {}).get("reversibility_path_patterns", [
        "migrations/", "schema/", "api/v", "public/", "event_schemas/", ".proto",
    ])


def get_low_confidence_threshold() -> float:
    cfg = _load()
    return float(cfg.get("escalation", {}).get("low_confidence_threshold", 0.5))


def get_precedent_config() -> Dict:
    cfg = _load()
    return cfg.get("precedent", {"similarity_boost_threshold": 0.85, "similarity_boost_multiplier": 1.5})


def reload():
    """Force a re-read of council.yaml (useful for the /weights endpoint or tests)."""
    global _cache
    _cache = {}
    return _load()
