"""Test Gate layer 1: run the configured gate command in a Slice's Sandbox
(issue #17; CONTEXT.md's "Test Gate" and "Gate Command" terms; ADR 0007 is
context, not scope here).

This module answers exactly one question: *what happened* when the Gate
Command ran? It does not decide *whether that counts as passing* — that is
ADR 0007's rule logic, layer 2, owned by issue #18. Layer 1 hands layer 2 a
:class:`GateRun`; layer 2 turns that (plus the rest of the Slice's Trajectory
— tool calls, tool results, denials) into a
:class:`ryai_harness.trajectory.GateVerdict`. Keeping that boundary sharp is
the whole point of this module: #18 must be able to build its rule function
against :class:`GateRun` without reading this module's internals or Sandbox's.

Two things this module deliberately does NOT do, both load-bearing for the
boundary above:

- It never reads model output. :func:`run_gate_command` takes a
  :class:`GateCommand` and a :class:`ryai_harness.sandbox.Sandbox` — nothing
  else reaches it. Whether the Slice's tool calls succeeded, were denied, or
  produced a diff is layer 2's concern, decided from the rest of the
  Trajectory; this module cannot see any of that even if it wanted to.
- It never reads the repository itself. The Gate Command is *configuration*,
  captured once by the Harness before the Slice begins (see CONTEXT.md's
  "Gate Command" entry) and passed in as an already-built ``GateCommand``.
  This module does not open files, does not accept a path, and does not
  re-derive the command string from the mounted repo at call time — so a
  Slice that edits the file the command happens to read from cannot change
  which command grades it. (It *can* change what that command's own logic
  does when re-run, e.g. editing ``gate.sh``'s contents — that is a property
  of the command, not of this module, and is by design: the AC this guards
  is "which command runs," not "what that command reads.")

The Gate Command runs as an ordinary Tool Call against the Sandbox — the same
``name="shell"`` / ``arguments={"command": ...}`` contract
:meth:`ryai_harness.sandbox.Sandbox.run` already documents — but it is the
Harness's own invocation, not one issued by the model. Its
:class:`~ryai_harness.tool_result.ToolResult` belongs on
:class:`ryai_harness.trajectory.Trajectory`'s ``gate_command_result`` field,
never folded into ``tool_calls``/``tool_results``, which are for calls the
model issued.

Exit-code decoding lives here, once. :meth:`Sandbox.run` encodes a nonzero
exit as an extra ``f"exit status: {n}"`` element appended to a *successful*
(``Outcome.OK``) ``ToolResult``'s ``content`` — deliberately, so that a
nonzero exit is not confused with the Sandbox's own two cap trips
(``Outcome.ERROR``, reserved for the wall-clock timeout and the memory cap;
see sandbox.py's module docstring). A caller that wants the exit code as a
value, not as text embedded in a tuple, would otherwise have to parse that
convention itself — and issue #18's rule function is exactly such a caller.
:class:`GateRun` decodes it once here so #18 never has to know the
convention exists: ``exit_code`` is ``0`` or a positive int when the command
ran to completion, and ``None`` when it did not (the Sandbox's wall-clock
timeout or memory cap tripped first — ``tool_result.outcome`` is
``Outcome.ERROR`` in that case, and no exit code exists to report, not a
missing one).
"""

from __future__ import annotations

from dataclasses import dataclass

from ryai_harness.sandbox import Sandbox
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult

# call_id for the Harness's own Gate Command invocation. Never correlated
# against a model-issued ToolCall (this result never lands in
# Trajectory.tool_calls/tool_results -- see this module's docstring), so a
# fixed sentinel is fine; ToolCall.call_id is opaque to the Harness by
# contract (see tool_call.py).
_GATE_COMMAND_CALL_ID = "gate-command"

# Prefix Sandbox.run appends to `content`'s last element exactly when
# `proc.returncode != 0` (see sandbox.py's `run` docstring) -- decoded here,
# once, so no caller of this module has to know the convention exists.
_EXIT_STATUS_PREFIX = "exit status: "


@dataclass(frozen=True, slots=True)
class GateCommand:
    """The Gate Command, captured once as configuration before a Slice
    begins (CONTEXT.md's "Gate Command" entry). A plain wrapper around the
    shell command string — no path, no repo reference, nothing this module
    could use to re-derive the command from the mounted repo at call time.

    Attributes:
        command: The shell command to run inside the Slice's Sandbox, e.g.
            ``"pytest -q"``. Passed to
            :meth:`ryai_harness.sandbox.Sandbox.run` verbatim as
            ``arguments["command"]`` — this module does no shell quoting,
            wrapping, or interpretation of its own.
    """

    command: str


@dataclass(frozen=True, slots=True)
class GateRun:
    """The outcome of running one Gate Command in a Sandbox.

    Attributes:
        tool_result: The canonical
            :class:`~ryai_harness.tool_result.ToolResult` from running the
            Gate Command via :meth:`Sandbox.run`, unmodified. This is the
            value that belongs on
            :class:`ryai_harness.trajectory.Trajectory`'s
            ``gate_command_result`` field verbatim.
        exit_code: The Gate Command's exit code, decoded once here from
            ``tool_result``'s content so no caller has to parse it: ``0`` or
            a positive int when the command ran to completion, ``None`` when
            it did not because the Sandbox's wall-clock timeout or memory
            cap tripped first (``tool_result.outcome is Outcome.ERROR`` in
            that case — see this module's docstring).
    """

    tool_result: ToolResult
    exit_code: int | None


def run_gate_command(sandbox: Sandbox, gate_command: GateCommand) -> GateRun:
    """Run ``gate_command`` inside ``sandbox`` and report what happened.

    Runs the configured Gate Command as a Tool Call against the given,
    already-open Sandbox (the Harness's own invocation, not a model-issued
    one — see this module's docstring for why its result does not belong on
    Trajectory's ``tool_calls``/``tool_results``), and reports the raw
    :class:`~ryai_harness.tool_result.ToolResult` alongside a decoded
    ``exit_code``.

    This function decides nothing about pass/fail — that is ADR 0007's rule
    logic (issue #18), applied to the returned :class:`GateRun` together
    with the rest of the Slice's Trajectory.
    """
    tool_result = sandbox.run(
        ToolCall(
            call_id=_GATE_COMMAND_CALL_ID,
            name="shell",
            arguments={"command": gate_command.command},
        )
    )
    return GateRun(tool_result=tool_result, exit_code=_decode_exit_code(tool_result))


def _decode_exit_code(tool_result: ToolResult) -> int | None:
    """Decode the exit code ``Sandbox.run`` embedded in ``tool_result``.

    ``Outcome.ERROR`` means one of the Sandbox's two cap trips fired before
    the command could finish (see sandbox.py's module docstring) — there is
    no exit code to report, so this returns ``None``, not a sentinel int.

    ``Outcome.OK`` means the command ran to completion. ``Sandbox.run``
    appends a second, ``f"exit status: {n}"`` element to ``content`` only
    when the command's return code was non-zero, so ``content`` has exactly
    one element on a 0 exit and exactly two otherwise (see sandbox.py's
    ``run`` docstring: "an extra ... element ... appended"). That arity, not
    a substring search over the whole output, is what this checks — the
    command's own stdout/stderr can legitimately contain text that looks
    like this suffix (see ``TestFailingGateCommand`` in test_gate.py), even
    at the very start of a 0-exit command's single-element output, so
    matching on the last element's prefix alone would misdecode that case.
    """
    if tool_result.outcome is not Outcome.OK:
        return None

    if len(tool_result.content) > 1 and tool_result.content[-1].startswith(_EXIT_STATUS_PREFIX):
        return int(tool_result.content[-1][len(_EXIT_STATUS_PREFIX) :])

    return 0
