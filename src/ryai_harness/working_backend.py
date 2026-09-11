"""Working Backend: wiring in vs promoting (issue #23, ADR 0006,
CONTEXT.md).

CONTEXT.md's ``Working Backend`` entry names two different acts that
both end with a Model Backend wired into the Harness:

- **Wiring in**: "Promoted from the Shortlist without Regression Suite
  evidence when the Suite is still thin or empty." This is how
  Qwen3-Coder-30B-A3B became the starting Working Backend (ADR 0006) —
  wiring in and promoting are different acts, and a Working Backend
  produced by wiring in is explicitly "not yet adopted."
- **Promoting**: ADR 0006's evidence-gated act — a candidate clears
  ``regression_suite.check_promotion`` at ``PromotionVerdict.PROMOTED``
  (100% of a non-empty Regression Suite) before it becomes the Working
  Backend.

The word "promoted" is used for *both* acts across the two documents
(CONTEXT.md's Working Backend entry uses it for wiring in; ADR 0006
uses it for the evidence-gated act), which reads as a contradiction
until the acts are named separately. This module resolves that by
giving each its own function and recording, on the resulting
:class:`WorkingBackend`, which basis produced it
(:class:`PromotionBasis`) — not an ``adopted: bool``. CONTEXT.md states
flatly that "a Working Backend is not yet adopted" at all, full stop;
adoption is a distinct concept this ticket does not model, gated on
Regression Suite evidence accumulating over time, not on a single
promotion event. Recording ``adopted=True`` on the object a single
``promote_backend`` call returns would assert exactly what CONTEXT.md
denies.

:func:`wire_in_working_backend` takes no Regression Suite input at all
— not "promote with an empty suite" but a structurally different
operation, proven by its signature carrying no ``case_passes``
parameter. :func:`promote_backend` requires suite evidence and refuses
(raises) unless :func:`regression_suite.check_promotion` returns
``PromotionVerdict.PROMOTED``; the declined verdict is embedded in the
raised message. Callers that need the verdict itself as a value (to
decide what to do next, or to test the "reports insufficient evidence"
half of the promotion check) should call
:func:`ryai_harness.regression_suite.check_promotion` directly — that
is the reporting function this module builds on, not something this
module's exception replaces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class PromotionBasis(Enum):
    """Which of the two distinct acts produced a :class:`WorkingBackend`.

    ``WIRED_IN``: wired in without Regression Suite evidence (CONTEXT.md
    Working Backend entry; ADR 0006's starting pick). ``SUITE_EVIDENCE``:
    promoted after passing 100% of a non-empty Regression Suite (ADR
    0006's promotion threshold). Never both, never neither — a
    ``WorkingBackend`` always names exactly which act produced it.
    """

    WIRED_IN = "wired-in"
    SUITE_EVIDENCE = "suite-evidence"


@dataclass(frozen=True, slots=True)
class WorkingBackend:
    """A Model Backend currently wired into the Harness (CONTEXT.md).

    Attributes:
        name: The Backend's identifier. This module does not interpret
            its shape or validate it against a Shortlist.
        basis: Which act produced this value — see
            :class:`PromotionBasis`. Deliberately not an
            ``adopted: bool``: CONTEXT.md's Working Backend entry states
            a Working Backend is not yet adopted, full stop, so no field
            on this type claims otherwise.
    """

    name: str
    basis: PromotionBasis


def wire_in_working_backend(name: str) -> WorkingBackend:
    """Wire ``name`` in as the Working Backend without Regression Suite
    evidence (CONTEXT.md; ADR 0006's starting pick). Distinct from
    :func:`promote_backend`: this function consults no Suite at all —
    see this module's docstring and its signature (no ``case_passes``
    parameter).
    """
    raise NotImplementedError


def promote_backend(name: str, case_passes: Sequence[bool]) -> WorkingBackend:
    """Promote ``name`` to Working Backend on Regression Suite evidence
    (ADR 0006).

    ``case_passes`` is forwarded verbatim to
    :func:`ryai_harness.regression_suite.check_promotion`. Raises
    ``ValueError`` naming the declined :class:`~ryai_harness.regression_suite.PromotionVerdict`
    unless that check returns ``PromotionVerdict.PROMOTED`` — an empty
    Suite or anything short of a 100% pass never yields a
    ``WorkingBackend`` built on suite evidence.
    """
    raise NotImplementedError
