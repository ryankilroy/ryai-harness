"""Canonical Tool Result schema.

The canonical record of what happened when a Tool Call executed, one per
Tool Call (CONTEXT.md, ADR 0002). ``outcome`` is mandatory and carries no
default — nothing is ever ``ok`` by absence.

Design note — absence is structurally unrepresentable:

``ToolResult`` is never wrapped in an optional anywhere in this module
(no nullable alias of this type, spelled either way round), and
``content`` is typed ``tuple[str, ...]`` — never a nullable tuple — so it
cannot double as an absence marker. An ``ok`` result with
empty content (``content=()``) is therefore a distinct, valid value:
"a search found nothing" is representable, and is not the same value as
"there is no result for this Tool Call". A caller that wants to say "no
result yet" needs a different type (e.g. wrapping in a Harness-level
in-flight state) — this module gives them nothing that lets "no result"
masquerade as a ``ToolResult``.

Issue #11 lays down this structure (the enums, the field shapes, and the
requirement — enforced by the dataclass itself, no defaults) that
``outcome`` cannot be omitted. It deliberately leaves one thing
unimplemented for the next Slice: the cross-field invariant that a
``denied`` outcome requires both ``kind`` and ``reason`` (ADR 0002). A flat
dataclass cannot express "these two fields are required together,
conditional on a third field's value" through types alone, so
``__post_init__`` below is where that check belongs — and it is currently
a stub.

Note for the implementing Slice: keep ``from __future__ import
annotations`` at the top of this module. ``tests/test_tool_result.py``
inspects ``dataclasses.fields(ToolResult)[i].type`` as a string to assert
``content`` never admits ``None``; that only works while annotations are
stringified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Outcome(Enum):
    """What happened when a Tool Call executed. No default; always stated."""

    OK = "ok"
    ERROR = "error"
    DENIED = "denied"


class DeniedKind(Enum):
    """Why a ``denied`` Tool Result's call never executed."""

    REJECTED = "rejected"
    NEEDS_REVISION = "needs-revision"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The canonical record of what happened when a Tool Call executed.

    Attributes:
        outcome: Required, no default. ``ok`` — the call executed and
            succeeded. ``error`` — the call executed and failed.
            ``denied`` — the call never executed; something upstream of
            execution refused it.
        content: The call's output, already canonicalised. Always a
            (possibly empty) tuple — never ``None`` — so an empty result
            is never confusable with an absent one.
        kind: Required, and meaningful, only when ``outcome`` is
            ``denied``: ``rejected`` (permanent policy stance) or
            ``needs-revision`` (a corrected call may succeed).
        reason: Required, and meaningful, only when ``outcome`` is
            ``denied``: free text naming why.
    """

    outcome: Outcome
    content: tuple[str, ...] = field(default_factory=tuple)
    kind: DeniedKind | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        raise NotImplementedError(
            "ToolResult does not yet enforce ADR 0002's invariant that a "
            "`denied` outcome requires both `kind` and `reason`. Issue #11 "
            "laid down the field shape; implementing this check is the "
            "next Slice's job."
        )
