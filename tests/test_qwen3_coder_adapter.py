"""Tests for the Qwen3-Coder Adapter (issue #13, ADR 0002, ADR 0006).

Render and parse are exercised as real integrated code wherever the HTTP
boundary is involved -- the round-trip test at the bottom sends render()'s
actual output over a real loopback socket to the stub server (tests/
conftest.py's ``stub_backend`` fixture) and feeds parse() the stub's
actual response bytes; nothing Harness-side of that boundary is
separately mocked. Every HTTP-touching test carries a hard timeout
(``urlopen(..., timeout=2)``); none may block on a socket.

Fixture response bodies live at tests/fixtures/qwen3_coder/ -- see that
directory and this Adapter module's own docstring for what each shape
represents and why (in particular sgl-project/sglang#35565, the
truncation-after-open-marker bug this ticket carries forward from issue
#8's verification pass).
"""

from __future__ import annotations

import inspect
import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from ryai_harness.adapters import qwen3_coder
from ryai_harness.adapters.qwen3_coder import TOOL_CALL_CLOSE_MARKER, TOOL_CALL_OPEN_MARKER
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import DeniedKind, Outcome

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "qwen3_coder"


def _load(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    return result


def _find_values(obj: object, key: str) -> Any:
    """Yield every value found anywhere under a matching key, recursively.

    Used to check properties of render()'s output (e.g. "no ``type``
    field anywhere names a blanket JSON mode") without assuming an exact,
    unverified SGLang request-body key path -- see the Adapter module's
    docstring on the structural-tag schema not being independently
    confirmed.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _find_values(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _find_values(item, key)


SAMPLE_CALLS = [
    ToolCall(call_id="call-1", name="read_file", arguments={"path": "src/app.py"}),
    ToolCall(call_id="call-2", name="list_open_prs", arguments={}),
    ToolCall(
        call_id="call-3",
        name="write_file",
        arguments={"path": "a.py", "content": "x = 1\n"},
    ),
]


class TestRenderProducesTheDialectRequestShape:
    @pytest.mark.parametrize("tool_call", SAMPLE_CALLS, ids=lambda c: c.name)
    def test_returns_a_json_serialisable_request_body(self, tool_call: ToolCall) -> None:
        request = qwen3_coder.render(tool_call)

        # Must round-trip through JSON as-is -- this is exactly the body
        # the round-trip test below hands to ``json.dumps`` for a real
        # POST; a value that only *looks* JSON-shaped (a set, a non-str
        # dict key, ...) would fail there.
        json.loads(json.dumps(request))


class TestStructuralTagScopedToTheEnvelopeOnly:
    @pytest.mark.parametrize("tool_call", SAMPLE_CALLS, ids=lambda c: c.name)
    def test_a_constraint_referencing_the_tool_call_envelope_is_always_present(
        self, tool_call: ToolCall
    ) -> None:
        # "the scoped constraint is always active" (ADR 0002) -- checked
        # across several different Tool Calls, not just one, so a
        # render() that only sometimes attaches the constraint cannot
        # pass by accident.
        request = qwen3_coder.render(tool_call)
        serialised = json.dumps(request)

        assert TOOL_CALL_OPEN_MARKER in serialised
        assert TOOL_CALL_CLOSE_MARKER in serialised

    @pytest.mark.parametrize("tool_call", SAMPLE_CALLS, ids=lambda c: c.name)
    def test_the_constraint_is_not_a_blanket_json_mode_over_the_whole_turn(
        self, tool_call: ToolCall
    ) -> None:
        # A blanket ``json_object``/``json_schema`` response_format
        # constrains the entire completion, including reasoning -- the
        # full-turn-constraint tax ADR 0002 exists specifically to avoid.
        # Whatever exact key path SGLang uses for its structural tag
        # (unverified -- see the Adapter module docstring), no ``type``
        # field anywhere in the request may name one of these two
        # blanket modes.
        request = qwen3_coder.render(tool_call)

        for type_value in _find_values(request, "type"):
            assert type_value not in ("json_object", "json_schema"), (
                f"render() applied blanket JSON mode ({type_value!r}) -- the "
                "constraint must be scoped to the tool-call envelope only, "
                "not the whole turn"
            )


class TestNoUnconstrainedFirstAttemptFallback:
    def test_render_has_no_parameter_that_could_disable_the_constraint(self) -> None:
        # ADR 0002: "there is no separate unconstrained 'first attempt'
        # or backstop-on-failure mode; the scoped constraint is always
        # active." Operationalised as: render's signature gives a caller
        # nothing to turn it off with.
        params = set(inspect.signature(qwen3_coder.render).parameters)
        disabling_names = {
            "unconstrained",
            "constrain",
            "strict",
            "fallback",
            "allow_unconstrained",
            "disable_structural_tag",
            "backstop",
        }

        assert params == {"tool_call"}
        assert params.isdisjoint(disabling_names)


class TestParseWellFormedResponse:
    def test_parses_into_an_ok_result(self) -> None:
        response = _load("well_formed.json")

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.OK

    def test_a_structurally_complete_empty_payload_call_is_ok_with_empty_content(self) -> None:
        # Paired with test_truncated_response_is_not_ok_with_empty_content
        # below: this proves Outcome.OK + content=() is reachable through
        # the *legitimate* path (a complete envelope, finish_reason
        # "stop"). Without this test, a parse() that rejects all empty
        # content to dodge the truncation-bug test would pass here by
        # accident -- ADR 0002 requires "a search with no matches" to
        # still read as ok.
        response = _load("legitimately_empty_success.json")

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.OK
        assert result.content == ()


class TestParseNeverSilentlyOk:
    def test_malformed_tool_call_is_not_ok(self) -> None:
        response = _load("malformed.json")

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.ERROR

    def test_model_text_with_no_tool_call_is_not_ok(self) -> None:
        response = _load("no_tool_call.json")

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.ERROR

    def test_unclosed_parameter_tag_is_not_ok(self) -> None:
        # malformed.json's envelope also has an empty function name, so it
        # short-circuits on that check without ever exercising the
        # "leftover content after consuming <parameter> pairs" path. Pin
        # that path directly, inline: a valid function name, one
        # <parameter> tag that is never closed.
        response = {
            "id": "chatcmpl-fixture-unclosed-parameter",
            "object": "chat.completion",
            "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": (
                            "<tool_call>\n<function=read_file>\n"
                            "<parameter=path>src/app.py\n</function>\n</tool_call>"
                        ),
                    },
                }
            ],
        }

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.ERROR


class TestTruncationAfterOpenMarkerNeverMasqueradesAsOk:
    def test_truncated_response_is_not_ok_with_empty_content(self) -> None:
        # sgl-project/sglang#35565 (open, confirmed in issue #8's
        # verification pass): several tool-call parsers, qwen3_coder
        # among them, silently return an empty message when generation
        # truncates right after the <tool_call> open marker (finish_reason
        # "length" here) rather than erroring or surfacing partial
        # content. content=() is a *legitimate* ok value elsewhere (see
        # the paired test above) -- which is exactly why this must not
        # read as ok: an ok-with-empty-content is precisely the value a
        # truncation bug could masquerade as.
        response = _load("truncated_after_open_marker.json")

        result = qwen3_coder.parse(response)

        assert not (result.outcome is Outcome.OK and result.content == ())
        assert result.outcome is Outcome.ERROR


class TestDenialBelowTheAdapterNeverMasqueradesAsOk:
    def test_rejected_denial_maps_to_denied_not_ok(self) -> None:
        response = _load("denied_below_adapter.json")

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.DENIED
        assert result.kind is DeniedKind.REJECTED
        # Must be *derived* from the fixture, not hardcoded -- otherwise
        # an implementer could pass this by hardcoding reason="denied".
        assert result.reason == response["error"]["reason"]

    def test_needs_revision_denial_maps_to_denied_not_ok(self) -> None:
        response = _load("denied_below_adapter_needs_revision.json")

        result = qwen3_coder.parse(response)

        assert result.outcome is Outcome.DENIED
        assert result.kind is DeniedKind.NEEDS_REVISION
        assert result.reason == response["error"]["reason"]

    def test_undecodable_denial_raises_rather_than_masquerading_as_error(self) -> None:
        # ADR 0007: a `rejected` denial always fails the Gate. Silently
        # downgrading an undecodable denial envelope to a generic
        # Outcome.ERROR would erase that signal -- a raised exception
        # can't be mistaken downstream for a routine, swallowable
        # failure. An unrecognised `kind` is the realistic way this
        # fires (a permission layer's vocabulary drifting from
        # DeniedKind's own), and it raises from DeniedKind construction
        # itself, not from an explicit guard in this module.
        response = {
            "error": {
                "type": "denied",
                "kind": "blocked",
                "reason": "policy: unrecognised denial kind",
            }
        }

        with pytest.raises(ValueError):
            qwen3_coder.parse(response)


class TestFullRoundTripAgainstTheStub:
    def test_render_post_parse_round_trip(self, stub_backend: Any) -> None:
        # Real integrated code against the stub server, not a mocked
        # unit: render()'s actual output is JSON-encoded and POSTed over
        # a real loopback socket; parse() sees the stub's actual response
        # bytes, decoded the same way a real caller would decode them.
        stub_backend.set_response(_load("well_formed.json"))
        tool_call = ToolCall(call_id="call-1", name="read_file", arguments={"path": "src/app.py"})

        request_body = qwen3_coder.render(tool_call)
        http_request = urllib.request.Request(
            f"{stub_backend.url}/v1/chat/completions",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=2) as response:
            response_body = json.loads(response.read().decode("utf-8"))

        result = qwen3_coder.parse(response_body)

        assert result.outcome is Outcome.OK
        assert stub_backend.last_request_body == request_body
