"""Planning front-end: Anthropic Claude. Implemented with stdlib only to avoid
SDK lock-in this early. This is the one assumed fixed cost in Phase 2."""
from __future__ import annotations
import json
import urllib.request
from .base import Completion

_ENDPOINT = "https://api.anthropic.com/v1/messages"
# rough public per-MTok rates; verify before trusting the spend cap
_IN_PER_MTOK = 3.0
_OUT_PER_MTOK = 15.0


class ClaudeProvider:
    def __init__(self, api_key: str, model: str):
        self._key = api_key
        self._model = model

    def complete(self, system: str, user: str) -> Completion:
        body = json.dumps({
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(
            _ENDPOINT, data=body, method="POST",
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage = data.get("usage", {})
        cost = (usage.get("input_tokens", 0) / 1e6) * _IN_PER_MTOK \
             + (usage.get("output_tokens", 0) / 1e6) * _OUT_PER_MTOK
        return Completion(text=text, usd_cost=cost)
