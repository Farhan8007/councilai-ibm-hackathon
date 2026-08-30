"""
IBM watsonx.ai client stub for CouncilAI specialist agents.

This module lives in services/ so agents can import it via the sys.path
injection at the top of each agent file. When WATSONX_API_KEY is set in
the environment, it initialises a real IBM watsonx.ai client. Otherwise
it provides a no-op stub that lets the agents fall back to their
deterministic heuristics without crashing at import time.
"""

from __future__ import annotations
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class WatsonxClient:
    """
    Thin wrapper around ibm_watsonx_ai.foundation_models.ModelInference.

    Usage::

        client = WatsonxClient()          # returns stub when no API key
        result = client.generate(prompt="...", max_new_tokens=400)
    """

    def __init__(self):
        self._model = None
        api_key = os.getenv("WATSONX_API_KEY")
        if not api_key:
            logger.debug("WATSONX_API_KEY not set — WatsonxClient running in stub mode")
            return

        try:
            from ibm_watsonx_ai import Credentials
            from ibm_watsonx_ai.foundation_models import ModelInference

            project_id = os.getenv("WATSONX_PROJECT_ID", "")
            url = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
            model_id = os.getenv("WATSONX_MODEL_ID", "meta-llama/llama-3-3-70b-instruct")

            self._model = ModelInference(
                model_id=model_id,
                credentials=Credentials(api_key=api_key, url=url),
                project_id=project_id,
            )
            logger.info("WatsonxClient initialised with model %s", model_id)
        except Exception as exc:
            logger.warning("WatsonxClient init failed (%s) — falling back to stub mode", exc)
            self._model = None

    def generate(self, prompt: str, max_new_tokens: int = 400, temperature: float = 0.1) -> str:
        """
        Generate text from the given prompt.

        Returns an empty string in stub mode so callers can detect the
        fallback and use their deterministic heuristics instead.
        """
        if self._model is None:
            return ""
        params = {
            "max_new_tokens": max_new_tokens,
            "temperature": temperature,
        }
        try:
            response = self._model.generate(prompt=prompt, params=params)
            return response.get("results", [{}])[0].get("generated_text", "")
        except Exception as exc:
            logger.warning("WatsonxClient.generate failed: %s", exc)
            return ""
