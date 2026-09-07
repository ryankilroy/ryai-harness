"""Canonical Tool Call schema.

A Tool Call is a request from a model to perform an action, expressed in
the Harness's own canonical form (CONTEXT.md, ADR 0002). Tools, logs and
evaluations speak only this form; the dialect a given Model Backend emits
is not a Tool Call until an Adapter has translated it.

Backend-agnostic by construction: the fields below are not borrowed from
any particular model dialect. In particular, this deliberately does *not*
look like:

- OpenAI's ``{"type": "function", "function": {"name": ..., "arguments":
  "<json string>"}}`` (arguments pre-parsed into a mapping here, not a
  JSON-encoded string; no ``type``/``function`` envelope);
- Anthropic's ``{"type": "tool_use", "id": ..., "name": ..., "input": {}}``
  (no ``type`` discriminant needed — this module has exactly one shape);
- ReAct-style ``action`` / ``action_input`` free text.

Issue #11 lays down this structure; it carries no runtime dependency and
no cross-field invariant, so there is nothing here for a later Slice to
fill in beyond what the type itself already enforces.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A single, canonical request to invoke a tool.

    Attributes:
        call_id: Opaque identifier correlating this call to its Tool
            Result. Assigned by whatever produced the call; the Harness
            does not interpret its shape.
        name: The tool's canonical name, as registered with the Harness —
            never a Backend-specific alias.
        arguments: The tool's arguments, already parsed into a canonical
            mapping. Never a serialized (e.g. JSON-string) form — parsing
            the Backend's native encoding is the Adapter's job, upstream
            of this type.
    """

    call_id: str
    name: str
    arguments: Mapping[str, object]
