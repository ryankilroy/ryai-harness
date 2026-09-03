# 4. RunPod Pod, custom SGLang container, and a leased lifecycle

## Status

Accepted

## Context

The Model Backend must run on RunPod under a $100/mo ceiling, for a single
developer working in bursty sessions (active work, then long idle gaps).
Three sub-decisions are coupled: deployment shape (Pod vs serverless),
serving engine (SGLang vs vLLM), and whether a stock RunPod template
suffices.

ADR 0002 requires constrained decoding at the sampling layer. RunPod's stock
`worker-vllm` serverless template does not expose per-request guided/
structured-decoding parameters in its documented request body — confirmed
against current docs, not a documentation gap. It cannot satisfy ADR 0002 at
any tuning, so it is eliminated outright rather than traded off.

Serverless cold starts for large model weights are unreliable (7s–7min
documented spread; the marketed "sub-second" figure applies only to
already-warm snapshots). A Slice is a bounded, latency-sensitive unit of
work; a cold start landing mid-Slice is worse than the discipline cost of
remembering to tear a Pod down.

Both SGLang and vLLM ship `structural_tag` and the guided-decoding
parameters ADR 0002 needs — this is not a capability gap between them.
CONTEXT.md's Seed is deliberately generous: the same long glossary/ADR
preamble is sent on every Slice. SGLang's RadixAttention is purpose-built for
exactly this long-shared-prefix, many-requests shape; a cross-project
measurement (sundial, different harness and provider) saw a 10–20:1
cache-read-to-cache-creation ratio on a similarly-sized fixed preamble,
real evidence the win is structural rather than marginal. Against this,
vLLM's tool-call-parser table is more independently verified per-model than
SGLang's; SGLang's parser names for this project's candidate models are an
open, closeable gap.

## Decision

Run a custom container on a persistent RunPod Pod, started at the beginning
of an active work session and torn down at the end — not the stock
`worker-vllm` template, not serverless. The container runs SGLang.

The Pod's "stay up" state is a **Lease** (see CONTEXT.md): renewed by
activity (a Slice starting, a tool call), not held open for a fixed
duration. On any failure to renew — expired, absent, or corrupt Lease
state — the default is to tear the Pod down, never to keep it running
silently. A deliberate stand-down (an intentional extended idle period) is
always recorded, so an idle stretch always has a reason on file.

## Consequences

- Billing is per-second while the Pod is up, with no cold-start risk once a
  session has started; the tradeoff is trusting the Lease mechanism rather
  than trusting scale-to-zero.
- SGLang's tool-call parser names for the eventual starting model are
  unconfirmed and must be verified before ticket #6 (starting Working
  Backend) locks a model — carried forward as an open gap, not blocking this
  decision.
- If usage shifts from session-bursty toward truly sporadic single calls,
  this decision should be revisited — the case for a persistent Pod is
  specifically about protecting a bounded Slice from cold-start whiplash,
  not a blanket preference over serverless.
- The Lease discipline (expire-by-default, activity-renewed, recorded
  stand-downs) is scoped here to Pod lifecycle, but the concept is written
  generally in CONTEXT.md and may apply to other running-cost resources
  later (e.g. the Sandbox).
