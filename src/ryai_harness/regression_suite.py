"""Regression Suite eligibility + promotion check (issue #23, ADR 0003,
ADR 0006, CONTEXT.md).

Two connected behaviours, per the issue:

**Eligibility.** Per ADR 0003, a failed Slice's Trajectory is
automatically eligible for promotion into the Regression Suite — the
Suite is grown from real failures, never authored synthetically,
so a failure is the raw material. "Automatically" is satisfied here by
:func:`is_eligible_for_promotion` being a *derived* predicate over
:class:`~ryai_harness.trajectory.Trajectory.gate_verdict` alone, not a
stored flag. No ``eligible`` field is added to ``Trajectory``: that
dataclass is frozen/slots with eight mandatory, no-default fields, and
its on-disk JSON shape is a documented contract
(``trajectory.write_trajectory``'s docstring) that every existing
construction site and test already relies on. A derived predicate can
never be forgotten or set wrong for a Trajectory that already exists;
a stored flag could be both. ``gate_verdict`` alone is the complete
signal — per issue #16's docstring, even a Slice that errored before
the gate command ran still records ``GateVerdict.FAIL`` (paired with an
``Outcome.ERROR`` gate result stating the gate never ran), so there is
no failure path this predicate misses by looking at ``gate_verdict``
only. Re-deriving "failed" from ``termination_reason`` or Tool Result
outcomes would duplicate issue #18's Test Gate Layer 2 rule engine
inside this ticket, which is not this ticket's Blast Radius.

Enumeration (:func:`eligible_trajectories`) filters an in-memory
collection of Trajectories. There is no Trajectory store or JSON loader
in this codebase yet (``trajectory.py`` only ever writes one); building
one is new surface this ticket does not ask for. A disk-backed loader
is implied by any future replay work, not by eligibility or enumeration
themselves.

**Promotion check** (ADR 0006). A candidate Model Backend promotes to
Working Backend the moment it passes 100% of the current Regression
Suite, and only if the Suite is non-empty — an empty Suite makes the
100% bar vacuous, since every candidate trivially passes zero entries.
:func:`check_promotion` is a pure function over the candidate's
per-case pass/fail results (``case_passes``): one bool per current
Suite entry, true if the candidate passed that case. Its length *is*
the Suite's size, so an empty sequence is exactly "Suite is empty" —
no separate size parameter is needed or accepted. The verdict is a
first-class, inspectable value (:class:`PromotionVerdict`), not only an
exception, because declining is a routine, expected outcome under ADR
0006 (an empty or thin Suite), not an error condition — "reports
insufficient evidence" needs a value to report.

No partial-percentage bar exists anywhere in this module: the pass
check is ``all(case_passes)``, never a ratio or a threshold compared
against a number less than 1. ``tests/test_regression_suite.py`` pins
this structurally, by parsing this module's own source and asserting no
division appears in :func:`check_promotion`'s body — not just that
today's test inputs happen to produce the right verdict.

No dwell timer gates promotion either: :func:`check_promotion` takes no
time-shaped input, and this module imports no time-related machinery.
``tests/test_regression_suite.py`` checks both structurally, the same
way ``tests/test_trajectory.py`` scans ``trajectory.py``'s imports for
networked modules.

Turning an eligible Trajectory into a replayable regression case, and
running a candidate Backend against that replayed case, are explicitly
out of scope for this ticket (deferred to a future spec) — nothing in
this module represents a regression case, a Suite store, or a replay
step. ``case_passes`` is deliberately abstract (a bare sequence of
bools) precisely so this module commits to none of that.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import Enum

from ryai_harness.trajectory import GateVerdict, Trajectory


class PromotionVerdict(Enum):
    """The result of checking a candidate Backend against the current
    Regression Suite (ADR 0006). Exactly three members, one per outcome
    the ticket names: a Suite too thin to mean anything, a full pass,
    and anything short of a full pass. No fourth, partial-percentage
    member exists, and none ever will — see this module's docstring."""

    PROMOTED = "promoted"
    NOT_PROMOTED = "not-promoted"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"


def is_eligible_for_promotion(trajectory: Trajectory) -> bool:
    """Whether ``trajectory`` is eligible for promotion into the
    Regression Suite: true exactly when the Slice attempt it records
    failed its Test Gate (``gate_verdict is GateVerdict.FAIL``), per
    ADR 0003. See this module's docstring for why this is a derived
    predicate rather than a stored field, and why ``gate_verdict`` alone
    is the complete signal.
    """
    return trajectory.gate_verdict is GateVerdict.FAIL


def eligible_trajectories(trajectories: Iterable[Trajectory]) -> tuple[Trajectory, ...]:
    """Enumerate the eligible Trajectories in ``trajectories``, in the
    order given. Purely a filter over :func:`is_eligible_for_promotion`
    — an in-memory operation only; see this module's docstring for why
    no disk-backed loader is built here.
    """
    return tuple(t for t in trajectories if is_eligible_for_promotion(t))


def check_promotion(case_passes: Sequence[bool]) -> PromotionVerdict:
    """Check a candidate Backend's Regression Suite run for promotion
    (ADR 0006).

    ``case_passes`` holds one bool per current Suite entry — true if the
    candidate passed that entry — so its length is the Suite's size.

    Returns:
        ``PromotionVerdict.INSUFFICIENT_EVIDENCE`` if ``case_passes`` is
        empty (the Suite is empty; the 100% bar would be vacuous).
        ``PromotionVerdict.PROMOTED`` if every entry passed.
        ``PromotionVerdict.NOT_PROMOTED`` otherwise — including a single
        failing entry among many passing ones. No partial-percentage bar
        exists; see this module's docstring.
    """
    if not case_passes:
        return PromotionVerdict.INSUFFICIENT_EVIDENCE
    if all(case_passes):
        return PromotionVerdict.PROMOTED
    return PromotionVerdict.NOT_PROMOTED
