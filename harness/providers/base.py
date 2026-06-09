"""Thin provider interface. The orchestrator only knows this protocol, so planning
and execution vendors are swappable and the loop is testable with a mock."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Completion:
    text: str
    usd_cost: float = 0.0   # best-effort; used to enforce the per-feature spend cap


class Provider(Protocol):
    def complete(self, system: str, user: str) -> Completion: ...
