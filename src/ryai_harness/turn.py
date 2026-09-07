"""Canonical Turn schema (issue #26, ADR 0002).

ADR 0002 defines a **Tool Call** as parsed model output: the structured
thing an Adapter produces after reading what a model generated. Nothing
in the Harness's canonical vocabulary was ever meant to also describe the
opposite direction -- what an Adapter needs in hand to build a request
*to* a Model Backend. Before this module existed, an Adapter's render
function had no principled way to receive that: for lack of a better
type, an earlier revision of one Backend's Adapter took a bare
``ToolCall`` as ``render``'s only input and had nowhere to put it in a
chat-style request except an assistant-role message -- a shape that,
against a real Backend, claims a model already produced output it was
actually being asked for.

This module is the fix: a **Turn** is everything an Adapter needs to
render a request asking a Backend to produce its *next* Tool Call. It
carries a system prompt, prior plain conversation, and the Trajectory so
far (Tool Calls the Backend already made, paired with what they
resulted in) -- and nothing else. In particular, there is no field
anywhere on this module's types that can hold a Tool Call the Backend
has not yet produced:

- :class:`Turn` has no field typed as a bare :class:`~ryai_harness.tool_call.ToolCall`.
  The only place a ``ToolCall`` appears is inside a :class:`TrajectoryStep`,
  and that step requires a :class:`~ryai_harness.tool_result.ToolResult`
  alongside it -- a call the Backend has not yet made cannot have a
  result yet, so it cannot be wrapped in a ``TrajectoryStep``, so it
  cannot reach a ``Turn`` at all. There is no optional/nullable variant
  of ``result`` that would let a caller construct one anyway.
- :class:`Message` -- prior plain conversation, unrelated to any Tool
  Call -- restricts its ``role`` to :class:`Role`, which has exactly two
  members: ``USER`` and ``ASSISTANT``. There is no ``SYSTEM`` member
  (the system prompt is ``Turn.system_prompt``, a distinct field, not a
  message with a role) and no role naming a Tool Call envelope.

The consequence: an Adapter's ``render`` can only ever place a Tool
Call's rendered envelope in an assistant-role message when that call is
part of the Trajectory -- i.e. something the Backend already did, which
is exactly where a chat-style request is supposed to show a model its
own prior turns. There is no path through this module's types by which
the call currently being solicited -- the one with no result yet --
could end up there instead. Structurally, not by convention: the same
standard issues #11, #15 and #16 hold elsewhere in this codebase.

What this module deliberately does not carry: tool schemas (what tools
are on offer this Slice), Blast Radius, or a Plan. Those are Harness-level,
per-Slice concerns (see ``context.py`` on branch issue-15-context-assembly,
not yet merged as of this module) upstream of any one Backend request;
carrying them here would duplicate that type rather than complement it.
See this module's own history/commit message for how a future integration
between the two is expected to work.

No wire-format detail lives here. Whether a rendered request encodes
``Message``/``TrajectoryStep`` content as particular JSON keys, particular
role strings, or a particular envelope syntax is entirely the rendering
Adapter's business -- this module only fixes what a Turn *is*, not how
any one Backend's dialect spells it out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import ToolResult


class Role(Enum):
    """Who spoke a plain-conversation :class:`Message`.

    Exactly two members, deliberately: no ``SYSTEM`` (the system prompt is
    :attr:`Turn.system_prompt`, a distinct field, not a role-tagged
    message) and no role naming a Tool Call envelope (that content lives
    in :class:`TrajectoryStep`, not in a ``Message``, however a given
    Adapter chooses to spell it on the wire).
    """

    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of plain conversation, unrelated to any Tool Call.

    Attributes:
        role: Who spoke -- :attr:`Role.USER` or :attr:`Role.ASSISTANT`.
        content: The message text.
    """

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """One Tool Call the Backend already made, paired with what it
    resulted in.

    ``result`` is required, with no default and no ``None`` in its type:
    a call with no result yet -- one still awaiting execution, or one
    that has not even been produced yet -- cannot be expressed as a
    ``TrajectoryStep``. That is what keeps a not-yet-produced Tool Call
    out of :class:`Turn` (see the module docstring): the only door in is
    this dataclass, and this dataclass will not open for a call that
    lacks a result.

    Attributes:
        call: The Tool Call as it was made.
        result: The Tool Result it produced.
    """

    call: ToolCall
    result: ToolResult


@dataclass(frozen=True, slots=True)
class Turn:
    """Everything an Adapter needs to render a request asking a Model
    Backend to produce its next Tool Call.

    Attributes:
        system_prompt: The system prompt for this request.
        history: Prior plain conversation, in order, preceding the
            Trajectory below. May be empty.
        trajectory: The Trajectory so far for this Slice attempt -- Tool
            Calls the Backend already made, paired with their results, in
            order. May be empty (the very first request of a Slice).
    """

    system_prompt: str
    history: tuple[Message, ...] = ()
    trajectory: tuple[TrajectoryStep, ...] = field(default_factory=tuple)
