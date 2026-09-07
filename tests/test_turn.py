"""Tests for the canonical Turn schema (issue #26, ADR 0002).

External behaviour only, mirroring tests/test_tool_call.py and tests/
test_tool_result.py's idiom: given a construction, expect this value or
this failure; where a property is structural (a field's own type
annotation ruling something out), inspect the dataclass field itself
rather than only trying one runtime value that happens to satisfy it.
"""

from __future__ import annotations

import dataclasses

import pytest

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult
from ryai_harness.turn import Message, Role, TrajectoryStep, Turn


def _make_call() -> ToolCall:
    return ToolCall(call_id="call-1", name="read_file", arguments={"path": "a.py"})


def _make_result() -> ToolResult:
    return ToolResult(outcome=Outcome.OK)


class TestRole:
    def test_has_exactly_user_and_assistant(self) -> None:
        # No SYSTEM (the system prompt is Turn.system_prompt, a distinct
        # field, not a role-tagged message) and no role naming a Tool
        # Call envelope.
        assert {member.name for member in Role} == {"USER", "ASSISTANT"}

    def test_a_system_role_does_not_exist(self) -> None:
        with pytest.raises(ValueError):
            Role("system")

    def test_a_tool_role_does_not_exist(self) -> None:
        with pytest.raises(ValueError):
            Role("tool")


class TestMessage:
    def test_constructs_with_role_and_content(self) -> None:
        message = Message(role=Role.USER, content="hello")

        assert message.role is Role.USER
        assert message.content == "hello"

    def test_is_immutable(self) -> None:
        message = Message(role=Role.USER, content="hello")

        with pytest.raises(dataclasses.FrozenInstanceError):
            message.content = "goodbye"  # type: ignore[misc]


class TestTrajectoryStep:
    def test_constructs_with_a_call_and_its_result(self) -> None:
        call = _make_call()
        result = _make_result()

        step = TrajectoryStep(call=call, result=result)

        assert step.call == call
        assert step.result == result

    def test_is_immutable(self) -> None:
        step = TrajectoryStep(call=_make_call(), result=_make_result())

        with pytest.raises(dataclasses.FrozenInstanceError):
            step.result = _make_result()  # type: ignore[misc]

    def test_result_is_required_not_defaulted(self) -> None:
        # A call with no result yet -- one still awaiting execution, or
        # one that has not even been produced yet -- cannot be wrapped in
        # a TrajectoryStep at all: there is no default to fall back on.
        with pytest.raises(TypeError):
            TrajectoryStep(call=_make_call())  # type: ignore[call-arg]

    def test_result_fields_type_admits_no_none(self) -> None:
        # Structural, not a runtime isinstance check (mirrors
        # test_tool_call.py's arguments-field check and tool_result.py's
        # own pattern): a caller handing an actual ToolResult at a call
        # site would satisfy isinstance regardless of what the field
        # claims to accept, so the field's own annotation is what has to
        # rule a bare-optional shape out.
        result_field = next(f for f in dataclasses.fields(TrajectoryStep) if f.name == "result")

        assert "None" not in result_field.type
        assert result_field.type == "ToolResult"


class TestTurn:
    def test_constructs_with_defaults_for_history_and_trajectory(self) -> None:
        turn = Turn(system_prompt="be careful")

        assert turn.system_prompt == "be careful"
        assert turn.history == ()
        assert turn.trajectory == ()

    def test_constructs_with_history_and_trajectory(self) -> None:
        message = Message(role=Role.USER, content="do the thing")
        step = TrajectoryStep(call=_make_call(), result=_make_result())

        turn = Turn(system_prompt="be careful", history=(message,), trajectory=(step,))

        assert turn.history == (message,)
        assert turn.trajectory == (step,)

    def test_is_immutable(self) -> None:
        turn = Turn(system_prompt="be careful")

        with pytest.raises(dataclasses.FrozenInstanceError):
            turn.system_prompt = "different"  # type: ignore[misc]

    def test_no_field_is_typed_as_a_bare_tool_call(self) -> None:
        # The structural claim this module exists to make: nowhere on
        # Turn can a caller hand a ToolCall directly. The only path a
        # ToolCall can take into a Turn is wrapped in a TrajectoryStep,
        # paired with a ToolResult that proves it already happened.
        field_types = {f.name: f.type for f in dataclasses.fields(Turn)}

        assert "ToolCall" not in field_types["system_prompt"]
        assert field_types["history"] == "tuple[Message, ...]"
        assert field_types["trajectory"] == "tuple[TrajectoryStep, ...]"
