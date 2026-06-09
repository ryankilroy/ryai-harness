"""Offline provider. Returns scripted responses so the orchestrator loop is fully
testable without keys or network — the harness's own deterministic gate."""
from __future__ import annotations
from typing import Callable
from .base import Completion


class MockProvider:
    def __init__(self, responder: Callable[[str, str], str]):
        self._responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> Completion:
        self.calls.append((system, user))
        return Completion(text=self._responder(system, user), usd_cost=0.0)
