# 2. Canonical tool calls with per-model adapters

## Status

Accepted

## Context

Open-weight models do not share a tool-calling surface. Hermes, Qwen and Llama
each emit a different format for the same concept. The Harness must treat the
Model Backend as a configuration value, which is impossible if the tool
contract changes shape with every swap.

Serving stacks expose an OpenAI-compatible `tools` parameter with per-model
parsers, which appears to solve this — but it makes correctness depend on a
third party shipping a parser for each model, and on that parser being correct.

Constraining an entire model turn at the sampling layer measurably degrades
reasoning (Tam et al., EMNLP 2024): stricter format restrictions correlate
with greater reasoning-task degradation, because JSON-mode can force answer
fields to be emitted before chain-of-thought completes. The tax is
capacity-dependent — models with headroom absorb it better — which matters
here because this project's likely starting models (24B–30B class) sit
closer to the end of that spectrum where the tax bites. SGLang (the locked
serving engine, ADR 0004) ships Structural Tag support today: a tagged
region of the output can be grammar-constrained while the rest of the turn,
including reasoning, stays free.

## Decision

The Harness defines one canonical representation of a tool call, and it
travels in exactly one direction: a **Tool Call** is parsed model output.
An adapter's `parse` produces one by reading what a Model Backend
returned; nothing in the Harness constructs one to describe a call the
Backend has not yet made. Symmetrically, an adapter's `render` never
takes a bare Tool Call as input — a not-yet-produced call is not a
canonical value this ADR defines at all, so there is no `ToolCall` for
`render` to be handed. `render` instead takes a **Turn**: the system
prompt, prior conversation, and the Trajectory so far (Tool Calls this
Backend already made, each paired with the Tool Result it produced — see
`ryai_harness/turn.py`, issue #26). A Turn cannot hold a Tool Call with
no Tool Result yet, so a call still awaiting production can never be
rendered into a request as if the model had already said it. Output is
constrained at the sampling layer only within the pending Tool Call's
envelope — via SGLang's Structural Tag, applied on every generation — so
that malformed tool calls cannot be generated, while reasoning and
scratchpad text outside that envelope, and every message drawn from the
Turn's history and Trajectory, remain unconstrained.

(This direction was ambiguous through issue #13: an earlier `render`
took a bare `ToolCall`, which had nowhere to go in a chat-style request
except an assistant-role message falsely claiming the model had already
produced the call it was in fact being asked for. Issue #26 resolved it
as stated above — a Tool Call out of `parse`, never into `render` — by
introducing the Turn type rather than loosening `ToolCall` itself.)

The adapter is the entire cost of adding a Backend.

The canonical form also covers what comes back: a **Tool Result**, one per
Tool Call, in the same canonical shape regardless of Backend. A Tool Result
carries a mandatory `outcome` with no default — nothing is ever `ok` by
absence. `outcome` is one of:

- `ok` — the call executed and succeeded. A legitimately empty result (a
  search with no matches, a no-op edit) is `ok` with empty content; it is
  never represented by an absent or missing result.
- `error` — the call executed and failed.
- `denied` — the call never executed; something upstream of execution
  refused it (a permission layer, a policy check) before the Model Backend's
  intended action could run. A `denied` result carries a mandatory `kind`:
  - `rejected` — a permanent policy stance; this action is not permitted,
    retrying it will not change that.
  - `needs-revision` — actionable feedback; the call as issued was refused,
    but a corrected call may succeed.

  Either `kind` also carries a free-text `reason` naming why.

A `denied` outcome is structurally distinct from `ok`: an Adapter has
nothing to omit that would let a denial parse back to the model, a log, or
the Test Gate as a quiet success.

## Consequences

- Tools, logs and evaluations speak the canonical form only. None of them change
  when a Backend is swapped.
- No format is imposed on a model against its training. Each model is addressed
  in its native dialect.
- The dominant failure mode shifts from syntactic to semantic. Syntactic
  failures waste a Slice; semantic failures can be caught by the Test Gate.
- The serving stack becomes part of the architecture rather than an
  interchangeable detail, because constrained decoding requires control of
  sampling. Portability across model providers is traded for portability
  across models. This is the correct direction given the project's goal.
- Scoping the grammar to the envelope keeps the original guarantee (no
  malformed tool call is ever generated) while avoiding the reasoning tax
  measured on full-turn constraints — there is no separate unconstrained
  "first attempt" or backstop-on-failure mode; the scoped constraint is
  always active.
- A denial and a failure are no longer conflatable with each other or with
  success. The Adapter's contract now runs in both directions: it must
  render every Tool Result's `outcome`, not just parse a well-formed one.
  A permission layer or Sandbox boundary that silently drops a mutating
  call — the failure mode a predecessor project hit — can no longer produce
  a result that reads as `ok`.
