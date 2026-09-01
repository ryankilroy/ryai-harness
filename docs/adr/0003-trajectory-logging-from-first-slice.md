# 3. Trajectory logging from the first Slice

## Status

Accepted

## Context

The architecture treats a Model Backend as a configuration value. That claim
needs a falsifier: a way to tell whether a swap made the system worse.

A Regression Suite that reflects real work can only be assembled from
Trajectories that were recorded. Recording cannot be applied retroactively. The
natural instinct — build the system first, add evaluation once it works — would
force the Suite to be authored synthetically, and a synthetic suite measures a
distribution that is not this project's work.

Public benchmarks are available immediately but are contaminated for models
trained after their release, and measure a codebase that is not ours.

## Decision

Every Slice attempt writes a full Trajectory from the first Slice onward.
Failed Slices are promoted into the Regression Suite as regression cases.
Public benchmarks determine the Shortlist only; adoption of a Backend requires
Regression Suite evidence.

## Consequences

- Evaluation quality compounds with usage instead of requiring a dedicated
  build-out.
- Storage grows with source excerpts in it. Trajectories stay local, consistent
  with ADR 0001.
- Early Backend decisions are made on thin evidence, since the Suite starts
  empty. This is accepted: the alternative is no evidence ever.
