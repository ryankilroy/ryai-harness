# 1. The Harness runs outside the GPU host

## Status

Accepted

## Context

The system runs open-weight models on RunPod to avoid dependence on
third-party agent providers. The obvious deployment is to place the agent loop
on the same pod as the weights: one machine, no network hop, the agent has a
filesystem it can freely modify.

## Decision

The Harness runs where the code lives — a local machine or CI container. The
Model Backend is reached only as an OpenAI-compatible HTTP endpoint. The pod
hosts weights and nothing else.

## Consequences

- GPU time is billed only during generation. An agent loop is mostly not
  generating: it is running tests, reading files, and waiting. Co-locating
  would bill GPU rates for that idle time.
- The Model Backend stays a configuration value. If the Harness were coupled to
  the pod's filesystem and lifecycle, swapping backends would mean redeploying
  the Harness — reintroducing lock-in from the other direction.
- Credentials (git tokens, API keys) never leave the machine that owns them.
- Cost: every tool result crosses the network. Context assembly must be
  deliberate rather than bulk-loading the repository.
- If a disposable execution environment is later needed, it is a separate
  concern from model hosting and must not be solved by moving the loop.
