"""Tests for Test Gate layer 2: the ADR 0007 rules (issue #18; ADR 0007).

External behaviour only, mirroring test_gate.py's and test_trajectory.py's
conventions: a fixture ``SliceRecord`` (see gate_rules.py's module
docstring for why the narrower type, not ``Trajectory``, is the input) and
a ``BlastRadius`` in, a ``Verdict`` out. Nothing here inspects
``evaluate_gate``'s internal structure beyond its public signature (AC 6).
Before ``evaluate_gate``/``_is_retry_of`` are implemented, every test that
calls ``evaluate_gate`` fails fast on ``NotImplementedError``; the shape
tests (dataclass fields, invariants, purity, signature) are real code
already and pass from this commit.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

import ryai_harness.gate_rules
from ryai_harness.gate_rules import (
    BlastRadius,
    Rule,
    SliceRecord,
    Verdict,
    evaluate_gate,
)
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import DeniedKind, Outcome, ToolResult
from ryai_harness.trajectory import GateVerdict, TerminationReason, Trajectory

_PASSING_DIFF = "diff --git a/x.py b/x.py\n@@ -1 +1 @@\n-old\n+new\n"

_NOT_EMPTY = BlastRadius(empty=False)
_DECLARED_EMPTY = BlastRadius(empty=True)


def _record(
    *,
    tool_calls: tuple[ToolCall, ...] = (),
    tool_results: tuple[ToolResult, ...] = (),
    diff: str = _PASSING_DIFF,
    gate_command_result: ToolResult | None = None,
    termination_reason: TerminationReason = TerminationReason.MODEL_FINISHED,
) -> SliceRecord:
    """A SliceRecord that passes every rule unless a test deliberately
    overrides a field to trip one -- mirrors test_trajectory.py's
    ``_full_trajectory`` helper."""
    if gate_command_result is None:
        gate_command_result = ToolResult(outcome=Outcome.OK, content=("2 passed",))
    return SliceRecord(
        tool_calls=tool_calls,
        tool_results=tool_results,
        diff=diff,
        gate_command_result=gate_command_result,
        termination_reason=termination_reason,
    )


def _call(call_id: str, command: str = "echo hi") -> ToolCall:
    return ToolCall(call_id=call_id, name="shell", arguments={"command": command})


class TestSliceRecordMatchesTrajectoryShape:
    """Structural pin for gate_rules.py's module-docstring claim:
    SliceRecord's five fields agree with Trajectory's in name and type --
    a documented correspondence, not a coincidence a later edit could
    silently break."""

    _SHARED_FIELDS = (
        "tool_calls",
        "tool_results",
        "diff",
        "gate_command_result",
        "termination_reason",
    )

    def test_shared_field_names_and_types_agree_with_trajectory(self) -> None:
        record_fields = {f.name: f.type for f in dataclasses.fields(SliceRecord)}
        trajectory_fields = {f.name: f.type for f in dataclasses.fields(Trajectory)}

        assert set(record_fields) == set(self._SHARED_FIELDS)
        for name in self._SHARED_FIELDS:
            assert record_fields[name] == trajectory_fields[name], (
                f"SliceRecord.{name}'s type must match Trajectory.{name}'s"
            )

    def test_slice_record_has_no_verdict_cost_or_duration_fields(self) -> None:
        # These belong only to a *graded* Trajectory -- gate_verdict is
        # this module's own output, and no rule consults cost/duration.
        names = {f.name for f in dataclasses.fields(SliceRecord)}
        assert "gate_verdict" not in names
        assert "cost" not in names
        assert "duration_seconds" not in names


class TestBlastRadiusShape:
    def test_holds_the_empty_flag(self) -> None:
        assert BlastRadius(empty=True).empty is True
        assert BlastRadius(empty=False).empty is False

    def test_is_frozen(self) -> None:
        br = BlastRadius(empty=False)
        with pytest.raises(dataclasses.FrozenInstanceError):
            br.empty = True  # type: ignore[misc]

    def test_empty_field_has_no_default(self) -> None:
        with pytest.raises(TypeError):
            BlastRadius()  # type: ignore[call-arg]


class TestVerdictShape:
    """Cross-field invariant, same pattern as ToolResult's (tool_result.py):
    rule is None iff the verdict is PASS."""

    def test_pass_verdict_names_no_rule(self) -> None:
        v = Verdict(gate_verdict=GateVerdict.PASS, rule=None)
        assert v.rule is None

    def test_fail_verdict_must_name_a_rule(self) -> None:
        with pytest.raises(ValueError):
            Verdict(gate_verdict=GateVerdict.FAIL, rule=None)

    def test_pass_verdict_must_not_name_a_rule(self) -> None:
        with pytest.raises(ValueError):
            Verdict(gate_verdict=GateVerdict.PASS, rule=Rule.NONZERO_EXIT)

    def test_is_frozen(self) -> None:
        v = Verdict(gate_verdict=GateVerdict.PASS, rule=None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            v.rule = Rule.NONZERO_EXIT  # type: ignore[misc]


class TestPurity:
    """AC 5: no I/O, no Sandbox, no Backend, and no dependency on layer 1
    (gate.py) -- this module takes an already-decoded exit_code, never a
    GateRun (see gate_rules.py's module docstring)."""

    _FORBIDDEN_MODULES = frozenset(
        {
            "socket",
            "urllib",
            "http",
            "ftplib",
            "smtplib",
            "requests",
            "httpx",
            "aiohttp",
            "docker",
            "subprocess",
        }
    )

    def test_module_imports_nothing_networked_or_process_spawning(self) -> None:
        module_path = Path(ryai_harness.gate_rules.__file__)
        tree = ast.parse(module_path.read_text())

        imported_top_levels: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_top_levels.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_top_levels.add(node.module.split(".")[0])

        offenders = imported_top_levels & self._FORBIDDEN_MODULES
        assert not offenders, f"gate_rules.py imports {offenders} -- must stay pure, no I/O"

    def test_module_does_not_import_layer_one_or_sandbox(self) -> None:
        module_path = Path(ryai_harness.gate_rules.__file__)
        tree = ast.parse(module_path.read_text())

        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

        assert "ryai_harness.gate" not in imported_modules, (
            "layer 2 must not depend on layer 1 -- it takes an already-decoded "
            "exit_code, never a GateRun"
        )
        assert "ryai_harness.sandbox" not in imported_modules

    def test_module_never_opens_or_reads_a_file(self) -> None:
        source = inspect.getsource(ryai_harness.gate_rules)
        tree = ast.parse(source)

        file_reading_names = {"open", "read_text", "read_bytes", "read", "readlines"}
        offenders = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id in file_reading_names)
                or (isinstance(node.func, ast.Attribute) and node.func.attr in file_reading_names)
            )
        ]
        assert offenders == [], "gate_rules.py must never read a file -- it is a pure function"

    def test_evaluate_gate_signature_admits_only_its_three_declared_inputs(self) -> None:
        params = list(inspect.signature(evaluate_gate).parameters)
        assert params == ["record", "blast_radius", "exit_code"]


class TestNonzeroExitFails:
    def test_nonzero_exit_fails(self) -> None:
        verdict = evaluate_gate(_record(), _NOT_EMPTY, exit_code=1)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.NONZERO_EXIT

    def test_gate_command_that_never_completed_fails_the_same_rule(self) -> None:
        # exit_code is None -- the Gate Command never completed (Sandbox
        # cap trip, gate.py). Not a special case: None != 0 fails the same
        # rule as any other non-zero exit.
        verdict = evaluate_gate(_record(), _NOT_EMPTY, exit_code=None)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.NONZERO_EXIT


class TestUnplannedEmptyDiffFails:
    def test_empty_diff_without_a_declared_empty_blast_radius_fails(self) -> None:
        verdict = evaluate_gate(_record(diff=""), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.UNPLANNED_EMPTY_DIFF

    def test_empty_diff_with_a_declared_empty_blast_radius_passes(self) -> None:
        verdict = evaluate_gate(_record(diff=""), _DECLARED_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.PASS
        assert verdict.rule is None


class TestRejectedFails:
    def test_rejected_result_fails(self) -> None:
        results = (
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED, reason="policy"),
        )
        verdict = evaluate_gate(_record(tool_results=results), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.REJECTED

    def test_rejected_fails_regardless_of_other_progress(self) -> None:
        # AC 3: everything else about this attempt looks like a pass --
        # zero exit, non-empty diff, model-initiated finish -- but the
        # rejected result still fails it unconditionally.
        results = (
            ToolResult(outcome=Outcome.OK, content=("did some work",)),
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED, reason="policy"),
            ToolResult(outcome=Outcome.OK, content=("more work",)),
        )
        verdict = evaluate_gate(_record(tool_results=results), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.REJECTED


class TestNeedsRevisionRule:
    def test_unresolved_needs_revision_fails(self) -> None:
        results = (
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.NEEDS_REVISION, reason="fix args"),
        )
        verdict = evaluate_gate(_record(tool_results=results), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.UNRESOLVED_NEEDS_REVISION

    def test_needs_revision_resolved_by_any_later_ok_result_passes(self) -> None:
        # ADR 0007: clearing is not tied to the same call -- any later ok
        # result anywhere in the attempt clears it.
        results = (
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.NEEDS_REVISION, reason="fix args"),
            ToolResult(outcome=Outcome.OK, content=("unrelated work",)),
        )
        verdict = evaluate_gate(_record(tool_results=results), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.PASS
        assert verdict.rule is None

    def test_needs_revision_followed_by_an_earlier_ok_is_not_resolved(self) -> None:
        # The clearing ok must come *later* -- an ok result that merely
        # precedes the denial does not resolve it.
        results = (
            ToolResult(outcome=Outcome.OK, content=("earlier work",)),
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.NEEDS_REVISION, reason="fix args"),
        )
        verdict = evaluate_gate(_record(tool_results=results), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.UNRESOLVED_NEEDS_REVISION


class TestErrorRule:
    def test_unrecovered_error_fails(self) -> None:
        calls = (_call("c1"),)
        results = (ToolResult(outcome=Outcome.ERROR, content=("boom",)),)
        verdict = evaluate_gate(
            _record(tool_calls=calls, tool_results=results), _NOT_EMPTY, exit_code=0
        )
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.UNRECOVERED_ERROR

    def test_error_recovered_by_a_later_retry_of_the_same_call_passes(self) -> None:
        failing_call = _call("c1", command="flaky-thing")
        retry_call = _call("c2", command="flaky-thing")  # same name+arguments, new call_id
        calls = (failing_call, retry_call)
        results = (
            ToolResult(outcome=Outcome.ERROR, content=("boom",)),
            ToolResult(outcome=Outcome.OK, content=("worked this time",)),
        )
        verdict = evaluate_gate(
            _record(tool_calls=calls, tool_results=results), _NOT_EMPTY, exit_code=0
        )
        assert verdict.gate_verdict is GateVerdict.PASS
        assert verdict.rule is None

    def test_error_is_not_resolved_by_an_ok_result_for_a_different_call(self) -> None:
        # The discriminating case: an ok result exists later in the
        # attempt, but for a *different* Tool Call -- proves this rule
        # checks retry-of-the-same-call, not "any later ok" (that looser
        # check belongs to the needs-revision rule, not this one).
        failing_call = _call("c1", command="flaky-thing")
        other_call = _call("c2", command="something-else")
        calls = (failing_call, other_call)
        results = (
            ToolResult(outcome=Outcome.ERROR, content=("boom",)),
            ToolResult(outcome=Outcome.OK, content=("unrelated success",)),
        )
        verdict = evaluate_gate(
            _record(tool_calls=calls, tool_results=results), _NOT_EMPTY, exit_code=0
        )
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.UNRECOVERED_ERROR

    def test_all_error_trajectory_with_diff_and_passing_gate_still_fails(self) -> None:
        # AC 2: closes the gap ADR 0007 left open -- without the error
        # rule, an all-error attempt would pass as long as some diff
        # exists and the gate command is green.
        calls = (_call("c1"), _call("c2"))
        results = (
            ToolResult(outcome=Outcome.ERROR, content=("boom 1",)),
            ToolResult(outcome=Outcome.ERROR, content=("boom 2",)),
        )
        verdict = evaluate_gate(
            _record(tool_calls=calls, tool_results=results, diff=_PASSING_DIFF),
            _NOT_EMPTY,
            exit_code=0,
        )
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.UNRECOVERED_ERROR


class TestStopConditionRule:
    @pytest.mark.parametrize(
        "reason",
        [
            TerminationReason.ITERATION_CAP,
            TerminationReason.COST_CAP,
            TerminationReason.WALL_CLOCK_CAP,
        ],
    )
    def test_each_stop_condition_fails(self, reason: TerminationReason) -> None:
        verdict = evaluate_gate(_record(termination_reason=reason), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.STOP_CONDITION

    def test_model_finished_does_not_trigger_the_stop_condition_rule(self) -> None:
        verdict = evaluate_gate(
            _record(termination_reason=TerminationReason.MODEL_FINISHED), _NOT_EMPTY, exit_code=0
        )
        assert verdict.gate_verdict is GateVerdict.PASS
        assert verdict.rule is None

    def test_harness_error_falls_through_the_nonzero_exit_rule_first(self) -> None:
        # HARNESS_ERROR is deliberately not in the stop-condition set: a
        # HARNESS_ERROR attempt's gate command never ran, so exit_code is
        # already None, and rule 1 fires before rule 6 is ever checked.
        # Pinned directly rather than left implicit -- see gate_rules.py's
        # module docstring.
        verdict = evaluate_gate(
            _record(termination_reason=TerminationReason.HARNESS_ERROR),
            _NOT_EMPTY,
            exit_code=None,
        )
        assert verdict.gate_verdict is GateVerdict.FAIL
        assert verdict.rule is Rule.NONZERO_EXIT


class TestPassingConjunction:
    def test_a_clean_attempt_passes_with_no_rule_named(self) -> None:
        verdict = evaluate_gate(_record(), _NOT_EMPTY, exit_code=0)
        assert verdict.gate_verdict is GateVerdict.PASS
        assert verdict.rule is None


class TestRuleOrder:
    """AC 4: rules apply in the specified order; the first to fire is the
    one the Verdict names, even when a fixture would also trip a later
    rule."""

    def test_nonzero_exit_outranks_a_rejected_result(self) -> None:
        results = (ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED, reason="x"),)
        verdict = evaluate_gate(_record(tool_results=results, diff=""), _NOT_EMPTY, exit_code=1)
        assert verdict.rule is Rule.NONZERO_EXIT

    def test_unplanned_empty_diff_outranks_a_rejected_result(self) -> None:
        results = (ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED, reason="x"),)
        verdict = evaluate_gate(_record(tool_results=results, diff=""), _NOT_EMPTY, exit_code=0)
        assert verdict.rule is Rule.UNPLANNED_EMPTY_DIFF

    def test_rejected_outranks_unresolved_needs_revision(self) -> None:
        results = (
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED, reason="x"),
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.NEEDS_REVISION, reason="y"),
        )
        verdict = evaluate_gate(_record(tool_results=results), _NOT_EMPTY, exit_code=0)
        assert verdict.rule is Rule.REJECTED

    def test_unresolved_needs_revision_outranks_unrecovered_error(self) -> None:
        calls = (_call("c1", command="a"), _call("c2", command="b"))
        results = (
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.NEEDS_REVISION, reason="y"),
            ToolResult(outcome=Outcome.ERROR, content=("boom",)),
        )
        verdict = evaluate_gate(
            _record(tool_calls=calls, tool_results=results), _NOT_EMPTY, exit_code=0
        )
        assert verdict.rule is Rule.UNRESOLVED_NEEDS_REVISION

    def test_unrecovered_error_outranks_a_stop_condition(self) -> None:
        calls = (_call("c1"),)
        results = (ToolResult(outcome=Outcome.ERROR, content=("boom",)),)
        verdict = evaluate_gate(
            _record(
                tool_calls=calls,
                tool_results=results,
                termination_reason=TerminationReason.ITERATION_CAP,
            ),
            _NOT_EMPTY,
            exit_code=0,
        )
        assert verdict.rule is Rule.UNRECOVERED_ERROR
