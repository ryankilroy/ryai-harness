"""Implementer role — the well-scoped, high-frequency step, runs on the OSS tier.
Takes one task plus the spec and (on retries) the last gate failure, and returns a
unified diff to apply to the product repo."""
from __future__ import annotations
from ..providers.base import Provider

_SYSTEM = """You implement ONE task for the 'I am Grem' TypeScript browser extension.
Return ONLY a unified diff (git apply compatible) against the repo. No prose, no fences.
The change must make the deterministic gates pass: lint, typecheck, unit, spec-conformance."""


def implement(provider: Provider, spec_markdown: str, task: str, last_failure: str | None) -> str:
    user = f"# Spec\n{spec_markdown}\n\n# Task\n{task}\n"
    if last_failure:
        user += f"\n# Previous gate failure (fix this)\n{last_failure}\n"
    return provider.complete(_SYSTEM, user).text
