# 6. Starting Working Backend: Qwen3-Coder-30B-A3B on an A40

## Status

Accepted

## Context

The research report's starting-model recommendation was Devstral Small 2507
(24B, FP8) — the cheapest strong agentic coder built for this scaffold, at
the time it was written. But ADR 0002's central guarantee (no malformed tool
call is ever generated) depends on SGLang, the locked serving engine (ADR
0004), correctly parsing and constraining that model's tool-call format.

SGLang ships no parser named for Devstral. The closest option is its generic
`mistral` parser, documented against base Mistral-7B/Nemo checkpoints, not
Devstral. A live user report (SGLang v0.5.10) found Devstral tool calls
coming back as plain text instead of structured calls, and Mistral's own
Devstral-Small-2507 model card doesn't list SGLang as a supported engine at
all — it recommends vLLM. By contrast, SGLang's parser list explicitly
includes `qwen3_coder` and `glm`: this ticket's own two named promotion
targets, Qwen3-Coder-30B-A3B and GLM-4.5-Air, both have first-party SGLang
tool-call support today.

Starting on a backend whose tool-calling is unconfirmed on the locked engine
risks burning the first Slices on parser bugs rather than real work — the
exact syntactic-failure mode ADR 0002 exists to eliminate.

Separately, the sundial salvage audit (§6.6) flagged a real gap: nothing had
decided how cost incurred by a secondary call caused by a Slice — a
reviewer pass, an Adapter retry after a malformed tool call — gets
attributed against the $100/mo RunPod budget ceiling.

## Decision

**Starting Working Backend**: Qwen3-Coder-30B-A3B (30B total / 3B active
MoE), not Devstral Small 2507. Devstral is not ruled out permanently — it's
worth a fresh research ticket if SGLang's Devstral support matures — but it
is not the starting pick under a serving stack that cannot confirm it works
today.

**GPU tier**: RunPod A40 (48GB), on-demand at $0.44/hr — the cheapest
48GB-class tier, roughly half the L40/L40S rate, with room for a 30B MoE at
FP8/quantized precision plus KV cache and RadixAttention's prefix cache
(ADR 0004). At the Pod's activity-renewed Lease lifecycle (not 24/7), $100/mo
affords roughly 227 active hours.

**Budget scope**: the $100/mo ceiling is all-in — every cost RunPod bills
(compute, storage, egress) counts against it as one number, tracked against
RunPod's own invoice.

**Promotion threshold**: a candidate Model Backend must pass 100% of the
current Regression Suite before it is promoted to Working Backend. No
partial-percentage bar. Every Suite entry is a documented real failure
(CONTEXT.md: "grown from real failures, never authored synthetically"); a
candidate that still fails even one is repeating a known mistake, not
progressing past it.

**Dwell time**: none. Promotion is purely evidence-triggered — the moment a
candidate clears the 100%-Suite bar, it is promoted, however soon that
happens.

**Cost attribution** (CONTEXT.md's `Trajectory` term amended alongside this
ADR): all cost incurred producing a Slice's outcome — including retries and
internal reviewer passes — rolls into that Slice's Trajectory as one total.
There is no separate cost record for secondary calls.

## Consequences

- The starting Working Backend is chosen for confirmed compatibility with
  the locked serving engine, not solely for benchmark strength — a
  deliberate reordering of the research report's original ranking, made
  necessary by the ADR 0002 guarantee this project already committed to.
- A Slice's Trajectory cost figure reflects the true cost of reaching that
  Slice's outcome, including any retries it needed — a Slice that required
  three retries will not look artificially cheap next to one that needed
  none, at the cost of secondary-call cost never being visible on its own.
- Promotion has a simple, binary bar (100% of Suite) rather than a tunable
  threshold — cheap to state and check, but also means a single flaky or
  ill-specified Suite entry can block an otherwise-ready promotion; fixing
  that is a Regression Suite quality problem, not a reason to soften this
  bar.
- Devstral Small 2507 remains a live candidate to revisit — its SGLang
  support gap is a fact about today's tooling, not a permanent architectural
  exclusion.
