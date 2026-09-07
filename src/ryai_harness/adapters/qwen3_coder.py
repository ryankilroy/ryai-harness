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

from collections.abc import Mapping

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import ToolResult

#: The literal marker opening a Qwen3-Coder tool-call envelope. Used both
#: to scope the render-side structural-tag constraint and to recognise,
#: on the parse side, the truncation-after-open-marker failure mode
#: (sgl-project/sglang#35565).
TOOL_CALL_OPEN_MARKER = "<tool_call>"

#: The literal marker closing a Qwen3-Coder tool-call envelope.
TOOL_CALL_CLOSE_MARKER = "</tool_call>"


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
    raise NotImplementedError


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
    raise NotImplementedError
