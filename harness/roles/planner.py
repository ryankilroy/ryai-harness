"""Planner role — the judgment-heavy step, runs on the proprietary model.
Turns a one-paragraph feature request into a spec (in the product repo's format)
and an ordered task list. Output is structured so the operator can approve it."""
from __future__ import annotations
import json
from dataclasses import dataclass
from ..providers.base import Provider

_SYSTEM = """You are the planning front-end of a deterministic software harness.
Given a feature request for the 'I am Grem' browser extension, produce a plan as
STRICT JSON with keys:
  "spec_filename": kebab-case path under specs/, e.g. "0002-intervention-prompt.md"
  "spec_markdown": a full spec following the repo TEMPLATE (front-matter with
       status: ready, intent, checkable acceptance criteria as '- [ ]' items, out-of-scope)
  "tasks": an ordered array of atomic task strings, each independently implementable
Return ONLY the JSON object, no prose."""


@dataclass
class Plan:
    spec_filename: str
    spec_markdown: str
    tasks: list[str]


def make_plan(provider: Provider, feature_request: str) -> Plan:
    out = provider.complete(_SYSTEM, feature_request)
    data = json.loads(out.text)
    return Plan(
        spec_filename=data["spec_filename"],
        spec_markdown=data["spec_markdown"],
        tasks=list(data["tasks"]),
    )
