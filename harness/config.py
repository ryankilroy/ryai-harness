"""Central config. Everything tunable lives here and is read from the environment,
so the same code runs on any machine with no local state that matters."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    planning_model: str
    openrouter_api_key: str
    executor_model: str
    product_repo: str
    gate_command: str
    max_retries: int
    max_cad_per_feature: float

    @staticmethod
    def from_env() -> "Config":
        return Config(
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            planning_model=os.environ.get("PLANNING_MODEL", "claude-opus-4-8"),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            executor_model=os.environ.get("EXECUTOR_MODEL", "deepseek/deepseek-chat"),
            product_repo=os.environ.get("PRODUCT_REPO", "./"),
            gate_command=os.environ.get("GATE_COMMAND", "npm run gate"),
            max_retries=int(os.environ.get("MAX_RETRIES", "2")),
            max_cad_per_feature=float(os.environ.get("MAX_CAD_PER_FEATURE", "2.00")),
        )
