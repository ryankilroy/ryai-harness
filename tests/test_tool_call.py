"""Tests for the canonical Tool Call schema (issue #11, ADR 0002).

External behaviour only: given a construction, expect this value or this
failure. No test here reaches into ToolCall's internals or asserts on
call sequences.
"""

from __future__ import annotations

import dataclasses

import pytest

from ryai_harness.tool_call import ToolCall


def test_constructs_with_the_canonical_fields() -> None:
    call = ToolCall(call_id="call-1", name="read_file", arguments={"path": "a.py"})

    assert call.call_id == "call-1"
    assert call.name == "read_file"
    assert call.arguments == {"path": "a.py"}


def test_two_calls_with_equal_fields_are_equal() -> None:
    a = ToolCall(call_id="call-1", name="read_file", arguments={"path": "a.py"})
    b = ToolCall(call_id="call-1", name="read_file", arguments={"path": "a.py"})

    assert a == b


def test_is_immutable() -> None:
    call = ToolCall(call_id="call-1", name="read_file", arguments={})

    with pytest.raises(dataclasses.FrozenInstanceError):
        call.name = "write_file"  # type: ignore[misc]


def test_field_names_do_not_borrow_a_model_dialects_shape() -> None:
    # Backend-agnostic per ADR 0002: no OpenAI ("type", "function"),
    # Anthropic ("type", "input"), or ReAct ("action", "action_input")
    # vocabulary. This is a coarse proxy for "backend-agnostic", not a
    # substitute for the design review that keeps it that way.
    vendor_terms = {"type", "function", "input", "action", "action_input"}
    field_names = {f.name for f in dataclasses.fields(ToolCall)}

    assert field_names.isdisjoint(vendor_terms)


def test_arguments_field_type_is_a_mapping_not_a_string() -> None:
    # OpenAI's dialect carries `function.arguments` as a JSON-encoded
    # string; the canonical form must already be parsed, since decoding a
    # Backend's wire format is the Adapter's job, upstream of this type.
    # Structural, not a runtime isinstance check: passing a dict literal at
    # a call site would satisfy `isinstance(x, dict)` regardless of what
    # the field is actually typed to accept, so the field's own annotation
    # is the thing that has to rule out `str`.
    arguments_field = next(f for f in dataclasses.fields(ToolCall) if f.name == "arguments")

    assert "Mapping" in arguments_field.type
    assert arguments_field.type != "str"
