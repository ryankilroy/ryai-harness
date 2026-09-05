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

The Harness defines one canonical representation of a tool call. Per-model
adapters render it into the format the model was trained on and parse the
result back. Output is constrained at the sampling layer only within the
Tool Call envelope — via SGLang's Structural Tag, applied on every
generation — so that malformed tool calls cannot be generated, while
reasoning and scratchpad text outside that envelope remain unconstrained.

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
