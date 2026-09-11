"""Tests for Regression Suite eligibility + promotion check (issue #23,
ADR 0003, ADR 0006, CONTEXT.md).

External behaviour only, in the same style as tests/test_trajectory.py:
given a construction or a call, expect this value or this failure.
``TestNoPartialPercentageBarStructurally`` and ``TestNoDwellTimer``
mirror tests/test_trajectory.py's ``TestWriterNeverTransmits`` AST-based
idiom -- proving an absence structurally, not just that today's inputs
happen to produce the right verdict.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import ryai_harness.regression_suite
from ryai_harness.regression_suite import (
    PromotionVerdict,
    check_promotion,
    eligible_trajectories,
    is_eligible_for_promotion,
)
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult
from ryai_harness.trajectory import GateVerdict, TerminationReason, Trajectory


def _trajectory(gate_verdict: GateVerdict) -> Trajectory:
    return Trajectory(
        tool_calls=(ToolCall(call_id="c1", name="shell", arguments={"command": "pytest"}),),
        tool_results=(ToolResult(outcome=Outcome.OK, content=("output",)),),
        diff="diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+new\n",
        gate_command_result=ToolResult(outcome=Outcome.OK, content=("summary",)),
        gate_verdict=gate_verdict,
        termination_reason=TerminationReason.MODEL_FINISHED,
        cost=0.01,
        duration_seconds=1.0,
    )


class TestEligibility:
    """AC 1: a failed Slice's Trajectory is automatically eligible.
    Derived from gate_verdict alone -- no field is added to Trajectory
    to carry this (see regression_suite.py's module docstring)."""

    def test_a_failed_trajectory_is_eligible(self) -> None:
        assert is_eligible_for_promotion(_trajectory(GateVerdict.FAIL)) is True

    def test_a_passing_trajectory_is_not_eligible(self) -> None:
        assert is_eligible_for_promotion(_trajectory(GateVerdict.PASS)) is False

    def test_no_eligible_field_was_added_to_trajectory(self) -> None:
        # Eligibility is a derived property, not stored state -- so
        # "automatically marked eligible" can never be forgotten or set
        # wrong for a Trajectory that already exists.
        field_names = {f.name for f in dataclasses.fields(Trajectory)}
        assert "eligible" not in field_names
        assert "eligible_for_promotion" not in field_names


class TestEnumeration:
    """AC 2: eligible Trajectories can be enumerated from a collection."""

    def test_enumerates_only_failed_trajectories_preserving_order(self) -> None:
        passing = _trajectory(GateVerdict.PASS)
        failing_1 = _trajectory(GateVerdict.FAIL)
        failing_2 = _trajectory(GateVerdict.FAIL)

        result = eligible_trajectories([passing, failing_1, passing, failing_2])

        assert result == (failing_1, failing_2)

    def test_empty_input_enumerates_to_empty(self) -> None:
        assert eligible_trajectories([]) == ()

    def test_all_passing_enumerates_to_empty(self) -> None:
        result = eligible_trajectories(
            [_trajectory(GateVerdict.PASS), _trajectory(GateVerdict.PASS)]
        )
        assert result == ()


class TestPromotionCheck:
    """AC 3, AC 4, AC 5: check_promotion is a pure function over the
    candidate's per-case pass/fail results against the current
    Regression Suite."""

    def test_empty_suite_declines_with_insufficient_evidence(self) -> None:
        assert check_promotion(()) is PromotionVerdict.INSUFFICIENT_EVIDENCE
        assert PromotionVerdict.INSUFFICIENT_EVIDENCE.value == "insufficient-evidence"

    def test_100_percent_pass_of_non_empty_suite_promotes(self) -> None:
        assert check_promotion((True, True, True)) is PromotionVerdict.PROMOTED

    def test_single_case_suite_all_passing_promotes(self) -> None:
        assert check_promotion((True,)) is PromotionVerdict.PROMOTED

    def test_less_than_100_percent_does_not_promote(self) -> None:
        assert check_promotion((True, False)) is PromotionVerdict.NOT_PROMOTED

    def test_99_of_100_passing_does_not_promote(self) -> None:
        # No partial-percentage bar: 99% is still not 100%.
        case_passes = (True,) * 99 + (False,)
        assert check_promotion(case_passes) is PromotionVerdict.NOT_PROMOTED

    def test_all_failing_does_not_promote(self) -> None:
        assert check_promotion((False, False)) is PromotionVerdict.NOT_PROMOTED

    def test_three_distinct_verdict_members_only(self) -> None:
        assert {m.value for m in PromotionVerdict} == {
            "promoted",
            "not-promoted",
            "insufficient-evidence",
        }
        assert len(PromotionVerdict) == 3


class TestNoPartialPercentageBarStructurally:
    """AC 5's structural half: no percentage math anywhere in
    check_promotion's implementation -- not just tests happening to pass
    at today's boundary."""

    def test_check_promotion_body_contains_no_arithmetic(self) -> None:
        # Deliberately broader than "no division": a ratio/threshold bar
        # can just as easily be written with multiplication (e.g.
        # ``sum(case_passes) >= 0.9 * len(case_passes)``) or any other
        # BinOp, not only Div/FloorDiv. Banning every BinOp inside this
        # function's body is the only check that actually backs "no
        # partial-percentage bar anywhere in the code" (AC 5) rather than
        # one specific spelling of it. check_promotion's real
        # implementation needs none: ``not case_passes`` / ``all(...)``
        # are the whole decision.
        module_path = Path(ryai_harness.regression_suite.__file__)
        tree = ast.parse(module_path.read_text())

        fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "check_promotion"
        )
        arithmetic = [node for node in ast.walk(fn) if isinstance(node, ast.BinOp)]
        assert not arithmetic, "check_promotion must not compute a pass ratio/percentage"


class TestNoDwellTimer:
    """AC 6: no dwell timer gates promotion. Checked structurally: the
    module imports no time-related machinery, and check_promotion's
    signature carries no temporal parameter."""

    _FORBIDDEN_MODULES = frozenset({"time", "datetime"})

    def test_module_imports_no_time_machinery(self) -> None:
        module_path = Path(ryai_harness.regression_suite.__file__)
        tree = ast.parse(module_path.read_text())

        imported_top_levels: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_top_levels.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_top_levels.add(node.module.split(".")[0])

        offenders = imported_top_levels & self._FORBIDDEN_MODULES
        assert not offenders, f"regression_suite.py imports time machinery {offenders}"

    def test_check_promotion_signature_has_no_temporal_parameter(self) -> None:
        params = set(inspect.signature(check_promotion).parameters)
        assert params == {"case_passes"}
