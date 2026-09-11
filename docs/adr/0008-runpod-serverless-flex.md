# 8. RunPod Serverless (Flex, scale-to-zero), custom SGLang image

## Status

Accepted — supersedes ADR 0004's deployment-shape decision (Pod vs
serverless). ADR 0004's other decisions (SGLang over vLLM, RadixAttention,
prefix ordering) are unaffected and stay in force.

## Context

ADR 0004 eliminated serverless for two reasons: the stock `worker-vllm`
template doesn't expose guided-decoding parameters, and a cold start landing
mid-Slice was judged worse than the discipline cost of a persistent Pod
managed by a custom Lease.

Both premises narrow on inspection:

- The guided-decoding gap belongs to the *stock template*, not to serverless
  as a deployment shape. RunPod Serverless runs any custom Docker image with
  a custom handler — the same SGLang container ADR 0004 already committed to
  building for the Pod runs unmodified behind a Serverless endpoint.
- A cold start is only a mid-Slice risk if it can land *inside* a Slice.
  RunPod's idle-timeout keeps a worker warm for a configurable window after
  its last request; set that window generously relative to the gap between
  calls within one Slice, and every call after the first in a session lands
  warm. The cold start narrows to "the first request of a new session,"
  which is a session-boundary cost, not a Slice-interior one.

Usage is single-developer, bursty-session (ADR 0004's own framing): long
idle stretches between sessions, activity clustered once a session starts.
That shape is what Flex Workers (scale-to-zero between sessions, per-second
billing only while a request is in flight or a worker is draining its idle
window) are built for — and it means the Pod's core cost objection ADR 0004
was managing (billing that continues through an idle stretch unless a
custom Lease tears it down) is now structurally impossible rather than
merely policed: zero workers running is zero cost, enforced by the
platform, not by Harness-side discipline.

## Decision

Run the same custom SGLang container as a RunPod Serverless endpoint —
`worker-vllm` and every other stock template are still out — using Flex
Workers with scale-to-zero, not Active (always-on) Workers.

Set the endpoint's idle-timeout to a value longer than the typical gap
between tool calls within one Slice, so a warm worker survives the pauses
inside a running Slice. A cold start is tolerated only as a session-opening
cost: the first Slice after an idle gap may see one; no Slice after it,
within the same session, should.

The Lease concept (CONTEXT.md, ADR 0004) is retired. It existed to prevent
a Pod from silently billing through an idle stretch by policing renewal and
teardown in Harness code. Flex Workers make that failure mode structurally
unreachable — no worker, no charge — so there is nothing left for a Lease
to police. Ticket #21's scope (a Lease record, a second control-API stub,
activity-based renewal, teardown-by-default, recorded stand-downs) is
folded into #20 as one configuration concern: choose and document the
idle-timeout value, and prove empirically that it survives one Slice's
worth of inter-call gaps without a cold start.

## Consequences

- No custom teardown/renewal code, no Lease state machine, no second
  control-API stub — a class of bugs (the OOM-latch-style state-tracking
  defects already seen elsewhere in this build) is avoided by not building
  the stateful thing at all.
- A cold start at the start of a session is an accepted, expected cost, not
  a failure mode to design around. The Harness should not fail or retry a
  Slice merely because its first call was slow; #24 must state this
  explicitly rather than leave it to be discovered against the live
  endpoint.
- GPU tier availability for Serverless must be reverified independently of
  the Pod tier ADR 0004 assumed (A40) — Serverless and Pod inventories are
  not guaranteed to match. This is a build-time check for #20, not a
  blocking decision here.
- If usage shifts from bursty-session toward high-frequency/always-on
  calling, Active Workers (or a return to a persistent Pod) should be
  revisited — the case for Flex is specifically the idle-heavy, single-
  developer usage shape, not a blanket preference over always-on serving.
- "Deliberate stand-down," the recorded-reason concept ADR 0004 introduced
  for an operator choosing to leave a Pod up through idle time, has no
  referent under scale-to-zero and is dropped with the Lease. Any future
  need to force a specific worker warm (e.g. for a benchmark run) is Active
  Workers' concern if it arises, not the Harness's.
