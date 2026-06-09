"""OSS execution tier: OpenRouter (OpenAI-compatible). Per-token, pay-per-use.
Cheap/frequent work runs here; escalation to a stronger model is Phase 3, not now."""
from __future__ import annotations
import json
import urllib.request
from .base import Completion

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider:
    def __init__(self, api_key: str, model: str):
        self._key = api_key
        self._model = model

    def complete(self, system: str, user: str) -> Completion:
        body = json.dumps({
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }).encode()
        req = urllib.request.Request(
            _ENDPOINT, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
        text = data["choices"][0]["message"]["content"]
        # OpenRouter returns usage; cost varies by model so we leave it best-effort.
        return Completion(text=text, usd_cost=0.0)
