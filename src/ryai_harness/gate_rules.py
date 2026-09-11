"""Test Gate layer 2: the ADR 0007 rules (issue #18; ADR 0007; CONTEXT.md's
"Test Gate", "Blast Radius" and "Trajectory" entries).

Layer 1 (gate.py, issue #17) answers *what happened* when the Gate Command
ran. This module answers *whether that counts as passing*: a pure function,
:func:`evaluate_gate`, applying ADR 0007's rules -- plus the two the issue
adds beyond the ADR's own text (the ``error`` rule and the stop-condition
rule) -- in the exact stated order, to a Slice attempt's recorded facts.

Why this module does not take a :class:`ryai_harness.trajectory.Trajectory`:

``Trajectory.gate_verdict`` is mandatory, no default (trajectory.py) -- and
it is exactly the value this module computes. A type whose construction
requires already knowing this function's answer cannot be this function's
input without forcing every caller to invent a placeholder verdict first
(assign FAIL, call evaluate_gate, then overwrite it) -- the same
value-standing-in-for-absence failure mode issue #11's ``ToolResult.outcome``
and trajectory.py's own ``TerminationReason.HARNESS_ERROR`` exist to rule
out. :class:`SliceRecord` is the narrower, honest input: the same five
fields the issue's own input description names (Tool Results, the diff, the
gate command's ToolResult, and the termination reason -- see below for
``tool_calls``) minus the two fields only a *graded* Trajectory can have
(``gate_verdict`` itself, and ``cost``/``duration_seconds``, which no rule
below consults). Whatever assembles a real ``Trajectory`` builds one from a
``SliceRecord`` plus this function's :class:`Verdict`. See
``tests/test_gate_rules.py``'s ``TestSliceRecordMatchesTrajectoryShape`` for
the structural check pinning that ``SliceRecord``'s five fields agree with
``Trajectory``'s in name and type.

``tool_calls`` is in this module's input for one reason: the ``error`` rule
below ("no later Tool Result *retrying that same Tool Call*") cannot be
decided from ``tool_results`` alone -- nothing on a ``ToolResult`` says
which call produced it beyond position, and correlating "the same call,
retried" needs the calls themselves. ``ToolCall.call_id`` is opaque and
per-call by contract (tool_call.py) and can never match across a retry, and
the dataclass's auto-generated ``__eq__`` includes it -- so retry
correlation here compares ``.name`` and ``.arguments`` only
(:func:`_is_retry_of`), never whole-object equality and never ``call_id``.
The issue's own parenthetical list of Trajectory inputs omits Tool Calls;
that is a gap in that list against the issue's own rule text, not a design
choice made here.

The ``needs-revision`` rule is deliberately looser: ADR 0007 clears it on
*any* later ``ok`` Tool Result anywhere in the attempt, not tied to the
same call (a corrected-and-retried call reads as ordinary iteration). The
``error`` rule is deliberately tighter: it requires a retry of *that same*
call. Mirroring one rule's logic onto the other is the bug this module's
tests are written to catch (see ``TestErrorRule`` in test_gate_rules.py).

``exit_code != 0`` is the whole of the first rule's check, and it
deliberately does not special-case ``exit_code is None`` (the Gate Command
never completing -- see gate.py's module docstring): ``None`` is not zero,
so it fails the same rule as any other non-zero exit, with no separate
branch needed. ``TerminationReason.HARNESS_ERROR`` is not among the "stop
condition" set the last rule checks (``ITERATION_CAP``, ``COST_CAP``,
``WALL_CLOCK_CAP``): a ``HARNESS_ERROR`` attempt's Gate Command never ran,
so its ``exit_code`` is already ``None`` and rule 1 (nonzero exit) fires
first -- this module does not rely on that happening to work out silently;
it is pinned directly by ``TestStopConditionRule.test_harness_error_falls_
through_the_nonzero_exit_rule_first`` in the test module.

Zero I/O, no Sandbox, no Backend, no dependency on gate.py's layer 1 (this
module takes an already-decoded ``exit_code: int | None``, never a
``GateRun`` -- layer 2 must not import layer 1, only the smaller value
layer 1 hands upward). ``tests/test_gate_rules.py`` enforces this by
scanning this module's own imports (AST), the same discipline as
``test_trajectory.py``'s networked-import scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import DeniedKind, Outcome, ToolResult
from ryai_harness.trajectory import GateVerdict, TerminationReason

# The three loop-exit termination reasons that are not a model-initiated
# finish -- HARNESS_ERROR is deliberately excluded; see this module's
# docstring for why.
_STOP_CONDITIONS = frozenset(
    {
        TerminationReason.ITERATION_CAP,
        TerminationReason.COST_CAP,
        TerminationReason.WALL_CLOCK_CAP,
    }
)


class Rule(Enum):
    """Which ADR 0007 rule fired, in the fixed order :func:`evaluate_gate`
    checks them. There is no "none" member here -- a passing
    :class:`Verdict` carries ``rule=None`` directly; see that class."""

    NONZERO_EXIT = "nonzero-exit"
    UNPLANNED_EMPTY_DIFF = "unplanned-empty-diff"
    REJECTED = "rejected"
    UNRESOLVED_NEEDS_REVISION = "unresolved-needs-revision"
    UNRECOVERED_ERROR = "unrecovered-error"
    STOP_CONDITION = "stop-condition"


@dataclass(frozen=True, slots=True)
class BlastRadius:
    """The Plan's declared Blast Radius (CONTEXT.md), narrowed to the one
    field ADR 0007's rules consume: whether the Plan declared an empty
    Blast Radius up front. Other Blast Radius facts (paths, concepts) are
    not added here -- nothing in this module's rules reads them; they land
    on this type when a rule needs them, not preemptively.

    Attributes:
        empty: True when the Plan declared, in advance, that this Slice was
            expected to produce no diff (e.g. a read-only investigation).
            A Slice whose diff turns out empty is only a rule violation
            when this is False.
    """

    empty: bool


@dataclass(frozen=True, slots=True)
class SliceRecord:
    """The Slice attempt facts :func:`evaluate_gate` grades -- the same
    five fields the issue's own input description names (plus
    ``tool_calls``; see this module's docstring), minus the two fields
    only a graded ``Trajectory`` can have (``gate_verdict`` -- this
    module's own output -- and ``cost``/``duration_seconds``, which no
    rule consults). See this module's docstring for why the fuller
    ``Trajectory`` type is not used here.

    Attributes:
        tool_calls: Every Tool Call issued during the attempt, in the
            order issued -- same shape as ``Trajectory.tool_calls``.
        tool_results: Every Tool Result produced, one per Tool Call, in
            the same order as ``tool_calls`` -- same shape as
            ``Trajectory.tool_results``.
        diff: The attempt's captured diff. ``""`` means a real, captured
            "no changes," never an absent capture -- same contract as
            ``Trajectory.diff``.
        gate_command_result: The Gate Command's raw ``ToolResult`` --
            carried here for shape parity with ``Trajectory`` (the
            issue's own input list names it), though no rule below reads
            it directly: the already-decoded ``exit_code`` parameter is
            what the first rule consults.
        termination_reason: Why the attempt's agent loop stopped -- same
            shape as ``Trajectory.termination_reason``.
    """

    tool_calls: tuple[ToolCall, ...]
    tool_results: tuple[ToolResult, ...]
    diff: str
    gate_command_result: ToolResult
    termination_reason: TerminationReason


@dataclass(frozen=True, slots=True)
class Verdict:
    """The Test Gate's layer-2 verdict: a pass/fail outcome plus, on a
    failure, which rule fired. Field named ``gate_verdict`` rather than
    ``outcome`` to avoid colliding with ``ToolResult.outcome``'s
    established meaning elsewhere in this codebase.

    Attributes:
        gate_verdict: ``GateVerdict.PASS`` or ``GateVerdict.FAIL``
            (trajectory.py) -- the value that belongs on a graded
            ``Trajectory``'s own ``gate_verdict`` field verbatim.
        rule: The :class:`Rule` that fired, or ``None`` exactly when
            ``gate_verdict`` is ``GateVerdict.PASS``. Enforced in
            ``__post_init__``, mirroring ``ToolResult``'s own
            cross-field-invariant pattern (tool_result.py).
    """

    gate_verdict: GateVerdict
    rule: Rule | None

    def __post_init__(self) -> None:
        if self.gate_verdict is GateVerdict.PASS and self.rule is not None:
            raise ValueError(f"a PASS Verdict must not name a rule, got rule={self.rule!r}")
        if self.gate_verdict is GateVerdict.FAIL and self.rule is None:
            raise ValueError("a FAIL Verdict must name which rule fired")


def evaluate_gate(record: SliceRecord, blast_radius: BlastRadius, exit_code: int | None) -> Verdict:
    """Apply ADR 0007's rules, in order, to one Slice attempt.

    Pure: reads only its three arguments, does no I/O, touches no Sandbox
    and no Model Backend. Checks the rules in the exact order ADR 0007
    (and issue #18) state them, returning at the first that fires --
    "passes otherwise" is deliberately not this function's logic; it
    passes only on the explicit conjunction of every rule below not
    firing:

    1. the gate command exited non-zero (``exit_code != 0``, which
       ``None`` -- the command never completed -- also satisfies);
    2. the recorded diff is empty and the Blast Radius was not declared
       empty;
    3. any Tool Result is ``denied``/``rejected``;
    4. any Tool Result is ``denied``/``needs-revision`` with no later
       ``ok`` Tool Result anywhere in the attempt;
    5. any Tool Result is ``error`` with no later Tool Result, retrying
       that same Tool Call (:func:`_is_retry_of`), that is ``ok``;
    6. the attempt's loop ended on a stop condition (iteration, cost, or
       wall-clock cap) rather than a model-initiated finish.
    """
    if exit_code != 0:
        return Verdict(GateVerdict.FAIL, Rule.NONZERO_EXIT)

    if record.diff == "" and not blast_radius.empty:
        return Verdict(GateVerdict.FAIL, Rule.UNPLANNED_EMPTY_DIFF)

    results = record.tool_results
    calls = record.tool_calls

    for result in results:
        if result.outcome is Outcome.DENIED and result.kind is DeniedKind.REJECTED:
            return Verdict(GateVerdict.FAIL, Rule.REJECTED)

    for i, result in enumerate(results):
        if result.outcome is Outcome.DENIED and result.kind is DeniedKind.NEEDS_REVISION:
            later_results = results[i + 1 :]
            if not any(later.outcome is Outcome.OK for later in later_results):
                return Verdict(GateVerdict.FAIL, Rule.UNRESOLVED_NEEDS_REVISION)

    for i, result in enumerate(results):
        if result.outcome is not Outcome.ERROR:
            continue

        original_call = calls[i] if i < len(calls) else None
        resolved = False
        if original_call is not None:
            for j in range(i + 1, len(results)):
                later_call = calls[j] if j < len(calls) else None
                if (
                    later_call is not None
                    and results[j].outcome is Outcome.OK
                    and _is_retry_of(later_call, original_call)
                ):
                    resolved = True
                    break

        if not resolved:
            return Verdict(GateVerdict.FAIL, Rule.UNRECOVERED_ERROR)

    if record.termination_reason in _STOP_CONDITIONS:
        return Verdict(GateVerdict.FAIL, Rule.STOP_CONDITION)

    return Verdict(GateVerdict.PASS, None)


def _is_retry_of(candidate: ToolCall, original: ToolCall) -> bool:
    """True when ``candidate`` is a retry of ``original``: same tool
    ``name`` and ``arguments``, never ``call_id`` (opaque and per-call by
    contract; see tool_call.py) and never whole-object equality (which
    would include ``call_id`` via the frozen dataclass's auto
    ``__eq__``).
    """
    return candidate.name == original.name and candidate.arguments == original.arguments
