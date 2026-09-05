# 5. Local Docker Sandbox, open by default

## Status

Accepted

## Context

The Sandbox is where a Tool Call with side effects (running tests, shell
commands) actually runs — distinct from the Harness and from the Model
Backend (CONTEXT.md, ADR 0001). Nothing forces the Sandbox onto RunPod: it
can live wherever is convenient.

This project has a single developer running the Harness on a machine they
control, and every Slice passes a human Review Gate — reading the diff and
the Trajectory — before it merges. That changes the shape of the isolation
question: the realistic failure mode is a buggy Slice doing something
unexpected, not an adversarial or shared-tenant actor. A cloud sandboxing
service (Modal was considered) buys isolation this project doesn't yet need,
at the cost of a new vendor dependency and slower iteration.

## Decision

The Sandbox is a local Docker container, on the developer's own machine.

- **Filesystem**: the whole repo is mounted read-write. No mount boundary
  scoped to the Slice's declared Blast Radius. A Slice that writes outside
  its Blast Radius is a signal the Review Gate catches via diff — evidence
  the Plan was wrong (CONTEXT.md), not damage the Sandbox needs to prevent.
- **Network**: open by default, same as the developer's own shell. No
  allowlist, no offline-by-default. An unexpected outbound call is caught by
  the Review Gate and the Trajectory log, not by a network boundary.
- **Resource limits**: a generous per-Slice wall-clock timeout (killed past
  N minutes, recorded as a failed Trajectory) and a memory cap. Tuned by
  observation once real Slices have run, not guessed up front. This exists
  to protect the developer's own machine from a hung or runaway Slice — it
  is a stability control, not an isolation boundary.
- **Lifecycle**: a fresh container per Slice. No state carries over between
  Slices, matching a Slice's own contract of ending at a known-good state.
  If dependency-install caching is ever needed, it comes from a Docker
  volume mount, not from keeping a container alive across Slices.
- **Privilege**: the Sandbox process runs as a non-root user inside the
  container. The container has no access to the host's Docker socket.

## Consequences

- v1 ships without a new vendor dependency (Modal, or any cloud sandboxing
  service) and without isolation machinery (Blast-Radius-scoped mounts,
  network allowlisting) this project doesn't yet have a concrete need for.
- The Review Gate and Trajectory log carry weight that a stricter Sandbox
  would otherwise take on: an unexpected file write or network call is
  caught by a human reading the diff, not prevented by the container.
- Non-root and no Docker-socket access cost nothing today and hold the line
  against the most well-known trivial container-escape vector, without
  requiring any isolation design this ADR doesn't otherwise call for.
- This is a deferral, not a rejection. Stronger isolation — Blast-Radius-
  scoped mounts, network allowlisting, a cloud sandboxing service — is
  worth revisiting if the Sandbox ever runs untrusted code, many parallel
  Sandboxes, or anything beyond a single developer's own Harness running its
  own Tool Calls on its own machine.
