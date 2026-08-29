"""
services/watsonx_client.py
Reusable IBM watsonx.ai client for CouncilAI specialist agents.
Uses the official ibm-watsonx-ai SDK with the chat API.
"""

from __future__ import annotations
import os
import warnings
from ibm_watsonx_ai import Credentials
from ibm_watsonx_ai.foundation_models import ModelInference

DEFAULT_MODEL = "meta-llama/llama-3-3-70b-instruct"


class WatsonxClient:
    def __init__(self, api_key=None, project_id=None, url=None):
        self._api_key = api_key or os.getenv("WATSONX_API_KEY", "")
        self._project_id = project_id or os.getenv("WATSONX_PROJECT_ID", "")
        self._url = (url or os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")).rstrip("/")

    def generate(self, prompt, model_id=DEFAULT_MODEL, max_new_tokens=500, temperature=0.2):
        credentials = Credentials(url=self._url, api_key=self._api_key)
        model = ModelInference(
            model_id=model_id,
            credentials=credentials,
            project_id=self._project_id,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            response = model.chat(
                messages=[{"role": "user", "content": prompt}],
                params={
                    "max_tokens": max_new_tokens,
                    "temperature": temperature,
                },
            )
        return response["choices"][0]["message"]["content"].strip()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    client = WatsonxClient()
    result = client.generate(prompt="Reply with exactly one word: hello", max_new_tokens=10)
    print(f"Watsonx response: {repr(result)}")
    print("Credentials OK.")
