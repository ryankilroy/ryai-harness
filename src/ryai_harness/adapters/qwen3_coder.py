"""Qwen3-Coder-30B-A3B Adapter (issue #13, ADR 0002, ADR 0006).

The entire integration surface for this Backend. Per CONTEXT.md's Adapter
definition: "The translation between a Tool Call and the dialect a
particular Model Backend was trained on, in both directions: rendering a
Tool Call into that dialect, and parsing what comes back into a canonical
Tool Result." No other module may know this Backend's wire shapes —
enforced by tests/test_qwen3_coder_adapter_boundary.py.

This module is a TDD-stage stub: signatures and types are fixed by this
ticket; ``render`` and ``parse`` bodies are left for the implementation
stage (``NotImplementedError``). What follows records the design this
ticket committed to and why, so the implementer isn't guessing either.

Wire format
-----------
Qwen3-Coder's native tool-call dialect, as emitted inside a chat
completion's ``message.content`` when the server is *not* asked to
pre-parse tool calls (ADR 0002 explicitly rejects depending on a serving
stack's own per-model parser being correct — this Adapter parses the raw
text itself rather than trusting SGLang's ``--tool-call-parser`` output):

    <tool_call>
    <function=FUNCTION_NAME>
    <parameter=PARAM_NAME>VALUE</parameter>
    <parameter=PARAM_NAME>VALUE</parameter>
    </function>
    </tool_call>

Source: ``sgl-project/sglang``,
``python/sglang/srt/function_call/qwen3_coder_detector.py`` (``Qwen3CoderDetector``),
read at
https://raw.githubusercontent.com/sgl-project/sglang/main/python/sglang/srt/function_call/qwen3_coder_detector.py
on an UNPINNED ``main`` commit — flagged, not verified against a pinned
SGLang release. Confirm against the SGLang version actually deployed
before trusting this shape in production; a related open issue
(sgl-project/sglang#27336 / PR #27337) documents closing-tag format drift
across newer Qwen3.x checkpoint variants, so "the wire format" is not
static even within one model family.

Two confirmed parser caveats (issue #8's verification, carried into this
ticket's acceptance criteria):

- sgl-project/sglang#35565 (open): 13 tool-call parsers, ``qwen3_coder``
  among them, silently return an *empty* message when generation
  truncates immediately after the ``<tool_call>`` open marker (e.g. hits
  ``max_tokens``), rather than erroring or surfacing the partial content.
  Nothing here may let that reach a caller looking like ``Outcome.OK``
  with empty content — ``content=()`` is a legitimate value for a
  genuinely empty *successful* result (ADR 0002: "a search with no
  matches"), so this is exactly the value a truncation bug could
  masquerade as. See tests/test_qwen3_coder_adapter.py for the paired
  tests that pin both sides of this: a truncated fixture must not read as
  ``ok``, and a structurally-complete empty-payload fixture must.
- sgl-project/sglang#9838: unrelated to tool-call parsing (an AWQ
  quantization load failure); noted for completeness, not load-bearing
  here.

``render`` / ``parse`` design note — an open tension, deliberately not
resolved by fiat
-----------------
``ToolCall`` (tool_call.py) is documented as "a request from a model" —
elsewhere in this codebase, an *output* of parsing, not naturally an
input to a request-building function. ``ToolResult.outcome is OK`` is
documented (ADR 0002) as "the call executed and succeeded" — but no
execution/Sandbox component exists anywhere in this ticket's scope (#10's
agent loop, Sandbox, and Trajectory writer are explicitly out of blast
radius here). Both CONTEXT.md's Adapter definition and issue #13's
acceptance criteria are nonetheless explicit and literal:
``render(ToolCall) -> dialect request``, ``parse(response) -> ToolResult``.
This module takes that literal reading rather than inventing a
parallel type. Concretely, within this ticket's scope: ``parse``'s
``Outcome.OK`` denotes "a well-formed Tool Call envelope was extracted
from the wire" — not "a tool executed" — and its ``content`` is left
empty (deferred to whatever later component actually executes a Tool
Call). This is a real gap between this Adapter and ADR 0002's literal
``ok`` definition; it is recorded here rather than silently papered over,
for whoever builds the execution path to reconcile.

Constrained decoding
---------------------
``render``'s request must carry a constraint scoped to the Tool Call
envelope only (SGLang's Structural Tag, ADR 0002) — reasoning/scratchpad
text outside the envelope stays unconstrained, and there is no parameter
anywhere in this module for turning that constraint off: "there is no
separate unconstrained 'first attempt' or backstop-on-failure mode; the
scoped constraint is always active" (ADR 0002). The exact SGLang
request-body schema for expressing a structural tag
(``response_format``/``extra_body`` key path) was NOT independently
verified against a pinned SGLang version in this ticket's research pass —
flagged for the implementer to confirm rather than copy blind from a
guess.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import DeniedKind, Outcome, ToolResult

#: The literal marker opening a Qwen3-Coder tool-call envelope. Used both
#: to scope the render-side structural-tag constraint and to recognise,
#: on the parse side, the truncation-after-open-marker failure mode
#: (sgl-project/sglang#35565).
TOOL_CALL_OPEN_MARKER = "<tool_call>"

#: The literal marker closing a Qwen3-Coder tool-call envelope.
TOOL_CALL_CLOSE_MARKER = "</tool_call>"

# A complete `<function=NAME>...</function>` envelope body, anchored so a
# trailing partial/duplicate fragment (which would indicate malformed
# input, not a clean envelope) cannot slip through via a partial match.
_FUNCTION_PATTERN = re.compile(r"\s*<function=([^>]*)>(.*)</function>\s*\Z", re.DOTALL)

# One `<parameter=NAME>VALUE</parameter>` pair. Non-greedy so adjacent
# parameters don't get merged into one match.
_PARAMETER_PATTERN = re.compile(r"<parameter=([^>]*)>(.*?)</parameter>", re.DOTALL)


def render(tool_call: ToolCall) -> dict[str, object]:
    """Render a canonical Tool Call into a Qwen3-Coder chat-completion request.

    Returns a JSON-serialisable request body for ``POST
    /v1/chat/completions`` against an OpenAI-compatible endpoint (ADR
    0001). The body must carry a Structural-Tag-style constraint scoped
    to the ``<tool_call>...</tool_call>`` envelope only — see the module
    docstring — active unconditionally, with no argument on this function
    able to disable it.

    Args:
        tool_call: The canonical Tool Call to render.

    Returns:
        The request body to send to the Backend.
    """
    envelope_lines = [TOOL_CALL_OPEN_MARKER, f"<function={tool_call.name}>"]
    for name, value in tool_call.arguments.items():
        envelope_lines.append(f"<parameter={name}>{value}</parameter>")
    envelope_lines.append("</function>")
    envelope_lines.append(TOOL_CALL_CLOSE_MARKER)
    envelope_text = "\n".join(envelope_lines)

    return {
        "model": "Qwen/Qwen3-Coder-30B-A3B-Instruct",
        # Placeholder message shape carrying the rendered envelope for
        # this Tool Call -- a direct consequence of the render/parse
        # design tension recorded in the module docstring (ToolCall as
        # render()'s input rather than parse()'s output), not re-litigated
        # here.
        "messages": [
            {"role": "assistant", "content": envelope_text},
        ],
        # GUESS: SGLang's actual structural-tag request-body schema was
        # NOT independently verified against a pinned release (see module
        # docstring). This shape only needs to satisfy this ticket's
        # tested properties -- the open/close markers appear somewhere in
        # the serialised request, and no ``type`` field anywhere names a
        # blanket ``json_object``/``json_schema`` mode -- not to match
        # SGLang's real wire schema. Confirm against the deployed SGLang
        # version before relying on this key path in production.
        "response_format": {
            "type": "structural_tag",
            "structures": [
                {
                    "begin": TOOL_CALL_OPEN_MARKER,
                    "end": TOOL_CALL_CLOSE_MARKER,
                    "name": tool_call.name,
                }
            ],
            "triggers": [TOOL_CALL_OPEN_MARKER],
        },
    }


def parse(response: Mapping[str, object]) -> ToolResult:
    """Parse a raw Backend response into a canonical Tool Result.

    ``response`` is the decoded JSON body received from the Backend's
    OpenAI-compatible endpoint (e.g. ``json.loads`` of the HTTP response
    this Adapter's own request produced) — either an ordinary chat
    completion (``choices[0].message.content`` carrying the raw dialect
    text described in the module docstring, ``choices[0].finish_reason``
    distinguishing a normal stop from a truncation), or an error/denial
    envelope originating on the wire below this Adapter (a policy or
    gateway layer refusing the request before generation happened; ADR
    0002's ``denied`` outcome). This function never trusts SGLang's own
    ``--tool-call-parser`` output (``choices[0].message.tool_calls``) —
    it parses the raw text itself.

    Must never let a truncated-after-open-marker response (see module
    docstring) read back as ``Outcome.OK`` with empty content, and must
    never let a below-the-Adapter denial read back as ``Outcome.OK``.

    Args:
        response: The decoded response body.

    Returns:
        The canonical Tool Result.
    """
    error = response.get("error")
    if error is not None:
        return _parse_denial(error)

    content = _extract_message_content(response)
    if content is None:
        return ToolResult(outcome=Outcome.ERROR)

    finish_reason = _extract_finish_reason(response)
    if finish_reason == "length" and TOOL_CALL_OPEN_MARKER in content:
        # Belt-and-suspenders alongside the marker-completeness check
        # below: a "length" finish_reason on a response that opened a
        # tool-call envelope is exactly sgl-project/sglang#35565's
        # truncation scenario. The marker check below already catches
        # this fixture on its own (no close marker present); this branch
        # documents the finish_reason signal explicitly rather than
        # leaving it unread, per the module docstring's own description
        # of it.
        if TOOL_CALL_CLOSE_MARKER not in content[content.find(TOOL_CALL_OPEN_MARKER) :]:
            return ToolResult(outcome=Outcome.ERROR)

    if not _has_well_formed_envelope(content):
        return ToolResult(outcome=Outcome.ERROR)

    return ToolResult(outcome=Outcome.OK)


def _parse_denial(error: object) -> ToolResult:
    """Build a ``DENIED`` Tool Result from a below-the-Adapter error envelope.

    The envelope shape (``{"error": {"type", "kind", "reason"}}``) is
    INVENTED for this ticket -- no SGLang precedent, no permission layer
    exists yet in this codebase (see the fixtures under
    tests/fixtures/qwen3_coder/). Treated here as a placeholder contract
    pinned only by the test fixtures, not a confirmed wire format.

    Raises ``ValueError`` (rather than returning ``Outcome.ERROR``) if the
    envelope doesn't decode -- ADR 0007 treats a `rejected` denial as
    always failing the gate; silently downgrading an undecodable denial
    to a generic error would lose that signal. An exception can't
    masquerade as a result the caller might treat as a routine failure.
    """
    if not isinstance(error, Mapping):
        raise ValueError(f"malformed denial envelope: 'error' is not a mapping: {error!r}")

    kind_value = error.get("kind")
    reason_value = error.get("reason")
    if not isinstance(kind_value, str) or not isinstance(reason_value, str):
        raise ValueError(f"malformed denial envelope: {error!r}")

    kind = DeniedKind(kind_value)
    return ToolResult(outcome=Outcome.DENIED, kind=kind, reason=reason_value)


def _extract_message_content(response: Mapping[str, object]) -> str | None:
    """Return ``choices[0].message.content``, or ``None`` if it's absent/malshaped."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return None
    message = choice.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    if not isinstance(content, str):
        return None
    return content


def _extract_finish_reason(response: Mapping[str, object]) -> str | None:
    """Return ``choices[0].finish_reason``, or ``None`` if it's absent/malshaped."""
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return None
    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str):
        return None
    return finish_reason


def _has_well_formed_envelope(content: str) -> bool:
    """Whether `content` carries one complete, well-formed ``<tool_call>`` envelope.

    False for all three failure modes this Adapter must never let through
    as ``ok``: no envelope at all, a truncated one (open marker present,
    no matching close marker -- sgl-project/sglang#35565), and a
    malformed one (empty function name, or a parameter/function tag left
    unclosed).
    """
    open_idx = content.find(TOOL_CALL_OPEN_MARKER)
    if open_idx == -1:
        return False

    close_idx = content.find(TOOL_CALL_CLOSE_MARKER, open_idx)
    if close_idx == -1:
        return False  # truncated after the open marker

    inner = content[open_idx + len(TOOL_CALL_OPEN_MARKER) : close_idx]
    match = _FUNCTION_PATTERN.match(inner)
    if match is None:
        return False

    name = match.group(1).strip()
    if not name:
        return False

    body = match.group(2)
    consumed_spans: list[tuple[int, int]] = [m.span() for m in _PARAMETER_PATTERN.finditer(body)]
    leftover = body
    for start, end in reversed(consumed_spans):
        leftover = leftover[:start] + leftover[end:]

    # Anything left over outside the matched <parameter=...>...</parameter>
    # pairs (an unclosed parameter tag, stray text, ...) means the
    # envelope didn't fully parse -- not well-formed.
    return not leftover.strip()
