"""`ryai-harness "feature request"` — runs one feature through the Phase 2 loop."""

from __future__ import annotations

import sys

from .config import Config
from .orchestrator import run_feature
from .providers.claude import ClaudeProvider
from .providers.openrouter import OpenRouterProvider


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: ryai-harness "<feature request>"', file=sys.stderr)
        return 2
    request = sys.argv[1]
    cfg = Config.from_env()
    if not cfg.anthropic_api_key or not cfg.openrouter_api_key:
        print(
            "Missing ANTHROPIC_API_KEY or OPENROUTER_API_KEY (see .env.example)",
            file=sys.stderr,
        )
        return 2
    planner = ClaudeProvider(cfg.anthropic_api_key, cfg.planning_model)
    executor = OpenRouterProvider(cfg.openrouter_api_key, cfg.executor_model)
    outcome = run_feature(cfg, planner, executor, request)
    print(f"\n=== {outcome.status.upper()} ===\n{outcome.detail}")
    for e in outcome.events:
        print(f"  - {e}")
    return 0 if outcome.status in ("merged_ready", "rejected_plan") else 1


if __name__ == "__main__":
    raise SystemExit(main())
