"""Trajectory writer + diff capture (issue #16, ADR 0001, ADR 0003, ADR 0007).

Per CONTEXT.md and ADR 0003, every Slice attempt — including, especially,
one that failed or errored before completion — produces a Trajectory: the
complete record of that attempt in canonical form. This module defines
that record's shape (:class:`Trajectory`), the two fields issue #16 adds
beyond CONTEXT.md's prior definition (the diff and the termination
reason), and the two operations that make the record real: capturing the
diff from the Sandbox's bind-mounted repo, and persisting the record
locally.

Diff capture (AC 4, 5, 6): a Slice's diff is captured from the *host*
side of the Sandbox's bind mount, against the commit the Slice started
from — never from what the model claimed it did, and never by shelling
into the container. The stock ``python:3.12-slim`` image sandbox.py runs
(issue #14) ships no ``git`` binary, and this ticket's blast radius may
not change that image (sandbox.py is issue #14's, not this ticket's) — so
in-container diffing is not an option even before considering that a
uid-1000 process would hit git's "detected dubious ownership" against a
host-owned checkout. This is not a weaker guarantee than "captured from
the Sandbox": ``SandboxConfig.repo_path`` *is* the bind-mounted repo — a
bind mount, not a copy — so a container-authored write is visible at that
same host path the instant the container makes it. ``capture_diff``
therefore takes the repo path, not a ``Sandbox`` instance: diff capture
does not need the container running, only the same checkout the Sandbox
mounted. Implementers: do not use ``git diff --exit-code`` — exit 1 (its
"differences found" signal) is a plain nonzero exit to ``subprocess``,
indistinguishable there from a real git failure, and if this were ever
run through ``Sandbox.run`` instead, issue #14's Sandbox appends a
literal ``"exit status: <n>"`` element to ``content`` on any nonzero
exit, which would corrupt captured diff text.

A model that creates a wholly new file is an ordinary Slice shape, and
plain ``git diff <base_commit>`` never shows untracked paths — a diff
mechanism that silently dropped them would make AC 6 false for that
shape. ``capture_diff`` is therefore required to run, in order:
``git ls-files --others --exclude-standard`` to list untracked paths
that are *not* ``.gitignore``'d (this is the only step that decides
which untracked paths count — a bare ``git add -A`` must not be used,
because it would also stage every already-tracked modification, which
is not this function's decision to make); ``git add -N -- <path>`` (git's
"intent to add") for each such path, which records the path in the
index without staging its content; then plain
``git diff <base_commit>`` (no ``--cached``), which — because of those
intent-to-add entries — reports new files as additions with their full
working-tree content, alongside ordinary tracked-file changes. This is
a real, deliberate side effect: it leaves the checkout's index holding
those intent-to-add entries after ``capture_diff`` returns, on the same
checkout a Sandbox bind-mounts (AC 6's own premise already establishes
that ``repo_path`` is not a disposable copy). No committed state
changes and no file content changes; only the index gains entries for
paths that were already present, untracked, and not ignored.

Persistence (AC 3): ``write_trajectory`` persists a Trajectory to a local
path only. Per ADR 0001, Trajectories never leave the developer's
machine; ``tests/test_trajectory.py`` enforces this structurally by
scanning this module's own imports for anything networked, so this
module must never import ``socket``, ``urllib``, ``http``, or a
third-party HTTP client — not "must not call them," must not *import*
them, so the constraint holds even before either function is filled in.

Termination reason (AC 7): a Slice attempt ends for exactly one stated
reason, never inferred by its absence — the same discipline ADR 0002 and
issue #11 apply to ``ToolResult.outcome``. Four of
:class:`TerminationReason`'s five members are the ones AC 7 names
verbatim: a model-initiated finish, and each of the loop's three stop
conditions (iteration cap, cost cap, wall-clock cap). The fifth,
``HARNESS_ERROR``, exists because AC 2 requires a full Trajectory for a
Slice that *errored before completion* — before the loop reached any of
those four outcomes on purpose. Recording ``MODEL_FINISHED`` for a crash
would be exactly the failure mode issue #11 exists to prevent (a value
that is wrong, not absent, is worse than an admitted "we don't know"), so
that path gets its own named value rather than being folded into one of
the other four or left to a caller's judgment call.

Gate command result and verdict (AC 1, 2): ``Trajectory.gate_command_result``
is a plain, non-optional ``ToolResult`` (never wrapped in a nullable —
see the note on ``Trajectory.diff`` below, which applies here too) and
``Trajectory.gate_verdict`` is a mandatory, no-default
:class:`GateVerdict`. For the successful and failing-gate paths this is
straightforward: the gate command actually ran, and its ``ToolResult`` is
recorded verbatim. For the errored-before-completion path (AC 2), where
the gate command never ran at all, the documented convention (see
``Trajectory.gate_command_result``'s docstring) is an ``Outcome.ERROR``
result whose content states plainly that the gate never ran, paired with
``GateVerdict.FAIL``. No third ``GateVerdict`` member (e.g. "not run") is
added for this: that would reintroduce, one field over, the exact
absence-as-a-value problem ``TerminationReason.HARNESS_ERROR`` above was
just added to avoid. "The gate did not run" is truthfully "not passed" —
recorded as a stated fact about a real ``ToolResult``, not as an omission
naming nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import ToolResult


class TerminationReason(Enum):
    """Why a Slice attempt's agent loop stopped. Mandatory wherever it is
    used as a field — no default, never inferred by absence, same
    discipline as ``ToolResult.outcome`` (ADR 0002, issue #11).

    ``MODEL_FINISHED``, ``ITERATION_CAP``, ``COST_CAP`` and
    ``WALL_CLOCK_CAP`` are the four values AC 7 names: a model-initiated
    finish, and each of the three stop conditions that end a Slice
    attempt against the model's will. ``HARNESS_ERROR`` is a fifth value
    this module adds so a Slice that errored before completion (AC 2) has
    a truthful reason to record rather than a borrowed or absent one —
    see this module's docstring for why that value earns its own member
    instead of reusing one of the other four.
    """

    MODEL_FINISHED = "model-finished"
    ITERATION_CAP = "iteration-cap"
    COST_CAP = "cost-cap"
    WALL_CLOCK_CAP = "wall-clock-cap"
    HARNESS_ERROR = "harness-error"


class GateVerdict(Enum):
    """The Test Gate's verdict on a Slice attempt (ADR 0007). Mandatory
    wherever it is used as a field — no default, never inferred by
    absence.

    Exactly two members. A Slice attempt that errored before the gate
    command ever ran is still recorded as ``FAIL`` (paired with a
    ``gate_command_result`` that states plainly the gate did not run —
    see this module's docstring) rather than by adding a third member:
    "the gate did not run" is truthfully "did not pass," not a distinct
    kind of not-yet-known verdict this module needs to represent.
    """

    PASS = "pass"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Trajectory:
    """The complete record of one Slice attempt, in canonical form
    (CONTEXT.md, ADR 0003). Every field below is mandatory — none has a
    default — so nothing that assembles a Trajectory can omit a field by
    accident; a Slice that failed, or one that errored before completion,
    still produces a value with every field genuinely populated, never a
    partially-filled record (AC 1, AC 2).

    Attributes:
        tool_calls: Every Tool Call issued during the Slice attempt, in
            the order issued.
        tool_results: Every Tool Result produced during the Slice
            attempt, one per Tool Call, in the same order as
            ``tool_calls``.
        diff: The Slice's diff, captured (via :func:`capture_diff`) from
            the Sandbox's bind-mounted repo against the commit the Slice
            started from — never from what the model claimed it did (AC
            6). Typed as a plain ``str``, never wrapped in a nullable, so
            it cannot be ``None``: a Slice that edited nothing records
            this as the empty string, ``""`` — a real, present value
            meaning "captured; there were no changes" — which is
            structurally distinct from a missing field meaning "capture
            never happened." The two can never be confused because the
            second one is not a value this type can hold (AC 4, AC 5).
            See ``tests/test_trajectory.py`` for the same field-type
            assertion issue #11 uses on ``ToolResult.content`` (this
            module keeps ``from __future__ import annotations``, which
            that assertion style depends on).
        gate_command_result: The canonical ``ToolResult`` of running the
            gate command (e.g. the project's test suite) for this Slice
            attempt. Never wrapped in a nullable, for the same reason as
            ``diff`` above. For a Slice attempt that errored before the
            gate command ever ran (AC 2), the documented convention is an
            ``Outcome.ERROR`` result whose ``content`` states plainly
            that the gate did not run — see this module's docstring —
            rather than omitting this field, which this type does not
            allow in the first place.
        gate_verdict: The Test Gate's verdict for this Slice attempt
            (ADR 0007). See :class:`GateVerdict`.
        termination_reason: Why the agent loop stopped for this Slice
            attempt. See :class:`TerminationReason`.
        cost: Total cost attributed to this Slice attempt. Per ADR 0003 /
            CONTEXT.md's Trajectory entry, cost is attributed wholly to
            the Slice that caused it — a retry or a reviewer pass
            triggered while producing this Slice's outcome is part of
            this total, not tracked apart from this Trajectory.
        duration_seconds: Total wall-clock duration of the Slice attempt.
    """

    tool_calls: tuple[ToolCall, ...]
    tool_results: tuple[ToolResult, ...]
    diff: str
    gate_command_result: ToolResult
    gate_verdict: GateVerdict
    termination_reason: TerminationReason
    cost: float
    duration_seconds: float


def capture_diff(repo_path: Path, base_commit: str) -> str:
    """Capture the diff of ``repo_path`` against ``base_commit``.

    ``repo_path`` is the *host* path bind-mounted into a Sandbox
    container (``SandboxConfig.repo_path``) — a bind mount, not a copy,
    so any change a container made under that mount is already present
    at this same host path by the time a Slice attempt ends. This
    function therefore never touches Docker or a running container; it
    reads the checkout directly, which is what makes the captured diff a
    fact about what the Sandbox's filesystem actually holds rather than
    what the model claimed it did (AC 6).

    Returns the diff as a single string. A Slice that made no changes
    returns the empty string ``""`` — a captured, present value, never
    ``None`` and never omitted (AC 4, AC 5; see ``Trajectory.diff``).

    Implementers: do not shell out with ``git diff --exit-code`` — see
    this module's docstring for why that flag is unsafe here. Plain
    ``git diff <base_commit>`` (no ``--exit-code``) exits 0 whether or
    not there were changes, which is the contract this function's tests
    rely on.

    New, untracked files must also be captured (a model creating a new
    file is an ordinary Slice shape) — plain ``git diff`` alone never
    shows them. See this module's docstring for the required
    ``git ls-files --others --exclude-standard`` + ``git add -N``
    (intent-to-add) sequence, the documented index-mutation side effect
    it carries, and why a bare ``git add -A`` must not be used instead.
    ``.gitignore``'d paths must never appear in the returned diff.
    """
    raise NotImplementedError


def write_trajectory(trajectory: Trajectory, path: Path) -> None:
    """Persist ``trajectory`` to ``path`` as local JSON. Nothing in this
    function — or anywhere in this module — may transmit a Trajectory
    off the machine (ADR 0001); ``tests/test_trajectory.py`` enforces
    this structurally by scanning this module's own imports.

    On-disk shape (a JSON object; every key always present, following
    ``Trajectory``'s own no-omitted-field discipline):

    - ``"tool_calls"``: array of ``{"call_id", "name", "arguments"}``.
    - ``"tool_results"``: array of
      ``{"outcome", "content", "kind", "reason"}`` — ``content`` an
      array of strings; ``kind``/``reason`` are ``null`` when not
      ``"denied"`` (``ToolResult`` already allows this — see
      tool_result.py — this module does not change that).
    - ``"diff"``: string. ``""`` for a Slice that made no changes — a
      present, empty string, never a missing key and never ``null``.
    - ``"gate_command_result"``: one
      ``{"outcome", "content", "kind", "reason"}`` object, same shape as
      an entry in ``tool_results``.
    - ``"gate_verdict"``: ``"pass"`` or ``"fail"`` (``GateVerdict.value``).
    - ``"termination_reason"``: one of ``"model-finished"``,
      ``"iteration-cap"``, ``"cost-cap"``, ``"wall-clock-cap"``,
      ``"harness-error"`` (``TerminationReason.value``).
    - ``"cost"``: number.
    - ``"duration_seconds"``: number.

    Every ``ToolCall.arguments`` mapping is assumed JSON-serializable
    (str/int/float/bool/None/list/dict values) — the canonical Tool Call
    schema (issue #11) does not itself guarantee this, so an
    implementation that hits a non-serializable argument value should
    fail loudly rather than silently drop or coerce it.
    """
    raise NotImplementedError
