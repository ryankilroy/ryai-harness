"""Qwen3-Coder-30B-A3B Adapter (issue #13, ADR 0002, ADR 0006).

The entire integration surface for this Backend. Per CONTEXT.md's Adapter
definition: "The translation between a Tool Call and the dialect a
particular Model Backend was trained on, in both directions: rendering a
Tool Call into that dialect, and parsing what comes back into a canonical
Tool Result." No other module may know this Backend's wire shapes —
enforced by tests/test_qwen3_coder_adapter_boundary.py.

Signatures and types were fixed by this ticket's TDD stage; ``render``
and ``parse`` bodies were filled in by the implementation stage. What
follows records the design this ticket committed to and why, so the
implementer isn't guessing either.

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

``render`` direction (issue #26, resolved)
-------------------------------------------
Earlier revisions of this module took ``render(tool_call: ToolCall)`` —
a bare canonical Tool Call, the same type ``parse`` produces. That is
backwards: ``ToolCall`` (tool_call.py) is documented as parsed model
output, and rendering one meant fabricating an assistant-role message
claiming the model had already produced a call it was, in fact, being
asked for. ADR 0002 now states the direction unambiguously: a Tool Call
travels in exactly one direction, out of ``parse``, never into
``render``.

``render`` instead takes a :class:`~ryai_harness.turn.Turn`
(``ryai_harness/turn.py``, issue #26) — the system prompt, prior plain
conversation, and the Trajectory so far (Tool Calls this Backend already
made, each paired with its Tool Result). A ``Turn`` cannot hold a Tool
Call with no result yet — see that module's docstring — so there is no
value ``render`` could be handed that would put a not-yet-produced call
in an assistant-role message. Any Tool Call envelope this function
places in an assistant-role message is therefore always one drawn from
``turn.trajectory``: something this Backend already did, being shown
back to it as history, which is exactly what a chat-style request's
assistant-role messages are for.

Concretely, within this ticket's scope: ``parse``'s ``Outcome.OK``
denotes "a well-formed Tool Call envelope was extracted from the wire" —
not "a tool executed" — and its ``content`` is left empty (deferred to
whatever later component actually executes a Tool Call; #10's agent
loop, Sandbox, and Trajectory writer remain out of blast radius here).
This is a real gap between this Adapter and ADR 0002's literal ``ok``
definition; it is recorded here rather than silently papered over, for
whoever builds the execution path to reconcile.

Constrained decoding
---------------------
``render``'s request must carry a constraint scoped to the pending Tool
Call's envelope only (SGLang's Structural Tag, ADR 0002) — reasoning/
scratchpad text outside the envelope, and every message drawn from
``turn.history``/``turn.trajectory``, stays unconstrained, and there is
no parameter anywhere in this module for turning that constraint off:
"there is no separate unconstrained 'first attempt' or
backstop-on-failure mode; the scoped constraint is always active" (ADR
0002). One consequence of Resolution A: since ``render`` no longer
receives a pending Tool Call, the constraint can no longer pin *which*
function name gets called the way an earlier revision's structural tag
did -- only that the envelope, whichever function it names, is
well-formed. Narrowing *which* function is on offer is tool-schema
territory (#15), not this Adapter's structural tag.

The exact SGLang request-body schema for expressing a structural
tag (``response_format``/``extra_body`` key path) was NOT independently
verified against a pinned SGLang version in this ticket's research pass —
flagged for the implementer to confirm rather than copy blind from a
guess.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import DeniedKind, Outcome, ToolResult
from ryai_harness.turn import Turn

#: The literal marker opening a Qwen3-Coder tool-call envelope. Used both
#: to scope the render-side structural-tag constraint and to recognise,
#: on the parse side, the truncation-after-open-marker failure mode
#: (sgl-project/sglang#35565).
TOOL_CALL_OPEN_MARKER = "<tool_call>"

#: The literal marker closing a Qwen3-Coder tool-call envelope.
TOOL_CALL_CLOSE_MARKER = "</tool_call>"

#: The model id this Adapter renders requests for (ADR 0006's model
#: choice, spelled the way the fixtures under tests/fixtures/qwen3_coder/
#: echo it back). GUESS, same caveat as the structural-tag schema below:
#: the endpoint's actual ``--served-model-name`` was NOT independently
#: verified against a live SGLang deployment. A request needs a ``model``
#: field to be functional and render() has nowhere else for it to come
#: from, so it stays -- confirm the exact string before trusting it in
#: production.
_MODEL = "Qwen/Qwen3-Coder-30B-A3B-Instruct"

# A complete `<function=NAME>...</function>` envelope body, anchored so a
# trailing partial/duplicate fragment (which would indicate malformed
# input, not a clean envelope) cannot slip through via a partial match.
_FUNCTION_PATTERN = re.compile(r"\s*<function=([^>]*)>(.*)</function>\s*\Z", re.DOTALL)

# One `<parameter=NAME>VALUE</parameter>` pair. Non-greedy so adjacent
# parameters don't get merged into one match.
_PARAMETER_PATTERN = re.compile(r"<parameter=([^>]*)>(.*?)</parameter>", re.DOTALL)

#: Literal dialect markers that corrupt or forge envelope structure if
#: they appear verbatim, unescaped, inside a rendered parameter *value*.
#: This dialect has no escaping mechanism (module docstring), so a value
#: containing one of these -- e.g. a ``write_file`` call whose own
#: ``content`` happens to contain the text ``</parameter>`` -- would
#: otherwise close the current parameter (or ``<function>``/
#: ``<tool_call>``) early and let whatever follows be read as new
#: envelope structure, up to and including a wholly forged second
#: ``<tool_call>`` naming an unrelated function. See
#: ``_reject_if_value_forges_envelope_structure``.
_ENVELOPE_STRUCTURAL_MARKERS = (
    TOOL_CALL_OPEN_MARKER,
    TOOL_CALL_CLOSE_MARKER,
    "<function=",
    "</function>",
    "<parameter=",
    "</parameter>",
)

#: Longest value text echoed into a raised exception's message. A tool
#: argument (e.g. ``write_file``'s ``content``) can be arbitrarily large;
#: the exception must not dump it whole.
_VALUE_PREVIEW_LIMIT = 80


def render(turn: Turn) -> dict[str, object]:
    """Render a Turn into a Qwen3-Coder chat-completion request soliciting
    its next Tool Call.

    Returns a JSON-serialisable request body for ``POST
    /v1/chat/completions`` against an OpenAI-compatible endpoint (ADR
    0001). ``turn.system_prompt`` and ``turn.history`` become the leading
    messages; each ``turn.trajectory`` step becomes, at minimum, an
    assistant-role message carrying that already-made call's rendered
    ``<tool_call>...</tool_call>`` envelope (paired, per ADR 0002, with
    however its ``ToolResult`` is surfaced back to the model). The
    request must also carry a Structural-Tag-style constraint scoped to
    the *pending* call's envelope only — see the module docstring —
    active unconditionally, with no argument on this function able to
    disable it. Implemented by this ticket's implementation stage; this
    stage fixes the signature and the design record above only.

    Args:
        turn: The system prompt, prior conversation, and Trajectory so
            far to render a next-Tool-Call request from.

    Returns:
        The request body to send to the Backend.
    """
    messages: list[dict[str, object]] = [{"role": "system", "content": turn.system_prompt}]

    for message in turn.history:
        messages.append({"role": message.role.value, "content": message.content})

    for step in turn.trajectory:
        # An already-made call is exactly what a chat-style request's
        # assistant-role messages are for -- see the module docstring and
        # ADR 0002. Its Tool Result is surfaced back as a paired
        # tool-role message so the model can see what its own prior call
        # produced.
        messages.append({"role": "assistant", "content": _render_call_envelope(step.call)})
        messages.append(_render_result_message(step.call, step.result))

    request: dict[str, object] = {
        "model": _MODEL,
        "messages": messages,
    }
    request.update(_structural_tag_constraint())
    return request


def _render_call_envelope(call: ToolCall) -> str:
    """Render a Tool Call the Backend already made back into this dialect's
    ``<tool_call>...</tool_call>`` envelope, for display in an
    assistant-role history message.

    Mirrors the wire shape ``_envelope_failure_reason``/``parse`` read on
    the way in (module docstring), so a call rendered here and later fed
    back through ``parse`` round-trips.

    Raises ``ValueError`` if any argument *value* contains a literal
    dialect marker (see ``_reject_if_value_forges_envelope_structure``)
    rather than interpolating it unescaped -- this dialect has no
    escaping mechanism to fall back on, so failing loudly here is
    preferred over silently emitting a corrupted or forged envelope into
    an assistant-role history message. Scoped to values only: a
    parameter *name* containing a bare ``>`` can shift the same envelope
    boundary and is NOT caught here. This is not because names are any
    more trusted than values -- ``ToolCall.arguments`` is model-produced
    either way -- but because the six-marker set below is not sufficient
    to catch name-side injection (a bare ``>`` isn't one of the markers),
    and guarding names with an insufficient check would read as a
    guarantee this function does not make. Known, unaddressed gap.
    """
    for name, value in call.arguments.items():
        _reject_if_value_forges_envelope_structure(name, value)
    parameters = "".join(
        f"\n<parameter={name}>{value}</parameter>" for name, value in call.arguments.items()
    )
    return (
        f"{TOOL_CALL_OPEN_MARKER}\n<function={call.name}>{parameters}\n</function>\n"
        f"{TOOL_CALL_CLOSE_MARKER}"
    )


def _reject_if_value_forges_envelope_structure(parameter_name: str, value: object) -> None:
    """Raise ``ValueError`` if ``value`` contains a literal envelope
    marker that would corrupt or forge ``<tool_call>`` structure if
    rendered verbatim.

    Not a contrived-attack-only concern: any argument value an Adapter
    doesn't control the contents of -- a file's own text, a shell
    command's output -- can legitimately contain these characters
    sequences. Qwen3-Coder's dialect has no quoting/escaping mechanism to
    encode them safely (module docstring), so the only correct response
    is to refuse rather than emit ambiguous or forged envelope text.
    """
    text = str(value)
    for marker in _ENVELOPE_STRUCTURAL_MARKERS:
        if marker in text:
            preview = (
                text
                if len(text) <= _VALUE_PREVIEW_LIMIT
                else (f"{text[:_VALUE_PREVIEW_LIMIT]}...({len(text)} chars total)")
            )
            raise ValueError(
                f"tool argument {parameter_name!r} contains the literal dialect marker "
                f"{marker!r}; rendering it verbatim would corrupt or forge a "
                f"<tool_call> envelope in the assistant-role history message, and this "
                f"dialect has no escaping mechanism to encode it safely "
                f"(value preview: {preview!r})"
            )


def _render_result_message(call: ToolCall, result: ToolResult) -> dict[str, object]:
    """Render a Trajectory step's Tool Result as the tool-role message
    that follows its call's assistant-role envelope.

    ``"tool"`` and ``tool_call_id`` are this Adapter's own wire spelling
    for surfacing a result back to the model -- not a canonical concept
    from ``ryai_harness.turn`` or ``ryai_harness.tool_result`` (see the
    Turn module docstring: wire-format detail is entirely the rendering
    Adapter's business).

    GUESS, unverified: this mirrors the OpenAI-compatible ``tool``-role
    message shape, but unlike the call side above (raw ``<tool_call>``
    text this Adapter controls end-to-end) this side leans on Qwen3-
    Coder's chat template to render a ``tool``-role message into
    something the model was trained to read, and on the endpoint
    accepting a ``tool``-role message with no preceding assistant
    ``tool_calls`` array (this Adapter never populates one -- #12).
    Neither was checked against a live SGLang endpoint or the model's
    actual chat template; confirm before trusting it in production.
    """
    return {
        "role": "tool",
        "tool_call_id": call.call_id,
        "content": _render_result_content(result),
    }


def _render_result_content(result: ToolResult) -> str:
    """The text placed in a tool-role message for one Tool Result."""
    if result.outcome is Outcome.DENIED:
        kind = result.kind.value if result.kind is not None else "unknown"
        return f"denied ({kind}): {result.reason}"
    if result.content:
        return "\n".join(result.content)
    return f"({result.outcome.value}, no output)"


def _structural_tag_constraint() -> dict[str, object]:
    """The request-body fragment constraining generation to a well-formed
    ``<tool_call>...</tool_call>`` envelope, scoped to that span only.

    GUESS: SGLang's exact ``response_format``/structural-tag request-body
    schema was NOT independently verified against a pinned SGLang release
    (module docstring) -- this shape follows the vendor's public
    structural-tag proposal (a list of begin/end-delimited regions, each
    with its own grammar) closely enough to scope the constraint to the
    envelope, but the precise key names are not to be trusted as an exact
    wire contract. Confirm against the deployed SGLang version before
    relying on this in production.

    Deliberately carries no reference to *which* function name is called
    (issue #26: under Resolution A, render() no longer receives a pending
    Tool Call to read a name from) -- only that whichever envelope the
    model emits is well-formed. Narrowing which function is on offer is
    tool-schema territory (#15), not this Adapter's structural tag.
    """
    return {
        "response_format": {
            "type": "structural_tag",
            "structures": [
                {
                    "begin": TOOL_CALL_OPEN_MARKER,
                    "end": TOOL_CALL_CLOSE_MARKER,
                    # GUESS: a permissive placeholder grammar for the
                    # envelope's inner text, not a schema for any
                    # specific function's arguments (see above).
                    "schema": {"type": "string"},
                }
            ],
            "triggers": [TOOL_CALL_OPEN_MARKER],
        }
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
        return ToolResult(
            outcome=Outcome.ERROR,
            content=("no usable choices[0].message.content in response",),
        )

    finish_reason = _extract_finish_reason(response)
    failure = _envelope_failure_reason(content, finish_reason)
    if failure is not None:
        return ToolResult(outcome=Outcome.ERROR, content=(failure,))

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


def _envelope_failure_reason(content: str, finish_reason: str | None) -> str | None:
    """Why `content` fails to carry one complete, well-formed ``<tool_call>``
    envelope, or ``None`` if it carries one.

    Distinguishes the three failure modes this Adapter must never collapse
    into one undifferentiated ``Outcome.ERROR`` with no detail -- issue
    #12's research on sgl-project/sglang#35565 turns on exactly this: "the
    model was truncated mid-envelope" and "the model said nothing" are
    different facts a developer debugging a Trajectory needs told apart,
    not merged into one silent failure.

    - No envelope at all: the open marker never appears.
    - Truncated: an open marker with no matching close marker.
      ``finish_reason == "length"`` on this shape is the #35565 signature
      specifically; any other ``finish_reason`` here means the *model*
      stopped mid-envelope on its own, a different failure worth saying
      so about.
    - Malformed: a complete envelope that doesn't parse -- an empty
      function name, or a ``<parameter>``/``<function>`` tag left
      unclosed.
    """
    open_idx = content.find(TOOL_CALL_OPEN_MARKER)
    if open_idx == -1:
        return "no <tool_call> envelope found in response content"

    close_idx = content.find(TOOL_CALL_CLOSE_MARKER, open_idx)
    if close_idx == -1:
        if finish_reason == "length":
            return (
                "truncated after the <tool_call> open marker with "
                "finish_reason='length' (sgl-project/sglang#35565)"
            )
        return (
            "truncated after the <tool_call> open marker "
            f"(finish_reason={finish_reason!r}): no matching close marker found"
        )

    inner = content[open_idx + len(TOOL_CALL_OPEN_MARKER) : close_idx]
    match = _FUNCTION_PATTERN.match(inner)
    if match is None:
        return "malformed <tool_call> envelope: could not parse a <function=...>...</function> body"

    name = match.group(1).strip()
    if not name:
        return "malformed <tool_call> envelope: empty function name"

    body = match.group(2)
    consumed_spans: list[tuple[int, int]] = [m.span() for m in _PARAMETER_PATTERN.finditer(body)]
    leftover = body
    for start, end in reversed(consumed_spans):
        leftover = leftover[:start] + leftover[end:]

    # Anything left over outside the matched <parameter=...>...</parameter>
    # pairs (an unclosed parameter tag, stray text, ...) means the
    # envelope didn't fully parse -- not well-formed.
    if leftover.strip():
        return (
            "malformed <tool_call> envelope: unparsed content inside the "
            "<function> body (e.g. an unclosed <parameter> tag)"
        )

    return None
