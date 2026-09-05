# Context

Glossary for the agent system. Terms only — no implementation details, no specs.

## Harness

The parts of the system we own and that accumulate project knowledge: the agent
loop, tool definitions and dispatch, context assembly, memory, and evaluation.
The Harness is the asset. Independence from third-party harnesses is the
project's primary goal.

## Model Backend

Any inference endpoint the Harness can call. Backends are interchangeable and
carry no project knowledge. A Backend is a configuration value, not a
dependency. Open-weight Backends are the default; proprietary Backends are
permitted where a task demands one.

## Vendor Lock

Dependence on a third party's *Harness*. Dependence on a particular Model
Backend is explicitly **not** vendor lock under this definition.

## Slice

The atomic unit of autonomous work. A Slice touches every layer it needs to and
ends at a known-good state. A Slice is the largest amount of work the system
will attempt without a human in the loop. Failure costs one Slice.

## Test Gate

The condition a Slice must satisfy before it is offered for review. Machine-
checkable, checked by the Harness, no human involved.

## Review Gate

The human decision to accept a completed Slice. Every Slice passes a Review
Gate. Batching Slices does not remove their Review Gates.

## Plan

A decomposition of intent into Slices. A Plan is itself produced by the system
and passes its own Review Gate before any Slice derived from it begins.

## Tool Call

A request from a model to perform an action, expressed in the Harness's own
canonical form. Tools, logs and evaluations speak only this form. The dialect a
given model emits is not a Tool Call until an Adapter has translated it.

## Adapter

The translation between a Tool Call and the dialect a particular Model Backend
was trained on. One Adapter per Backend. An Adapter holds no project knowledge
and is the entire cost of adopting a new Backend.

## Trajectory

The complete record of one Slice attempt in canonical form: Tool Calls, tool
results, gate outcome, cost and duration. Every Slice produces a Trajectory,
including — especially — failed ones. Cost is attributed wholly to the
Slice that caused it: a retry or a reviewer pass triggered while producing
the Slice's outcome is part of that Slice's cost, not a cost tracked apart
from any Trajectory.

## Regression Suite

Trajectories promoted to test cases, replayed against a candidate Model Backend.
The Suite is grown from real failures, never authored synthetically. It is the
only accepted evidence that a Backend swap is safe.

## Shortlist

The set of candidate Backends worth standing up, drawn from public benchmarks.
A benchmark score qualifies a Backend for the Shortlist and never for adoption;
adoption evidence comes only from the Regression Suite.

## Working Backend

The Model Backend currently wired into the Harness and used to run Slices.
Promoted from the Shortlist without Regression Suite evidence when the Suite
is still thin or empty. A Working Backend is not yet adopted — Regression
Suite evidence, not Shortlist membership or current use, is what adoption
requires.

## Sandbox

Where a Tool Call with side effects (running tests, executing shell commands)
actually runs. Distinct from where the Harness runs (see ADR 0001) and from
the Model Backend that decided to make the call.

## Blast Radius

The set of files and concepts a Slice is expected to touch, named by the Plan
before work begins. A Slice that discovers its Blast Radius was wrong has found
a defect in the Plan, not merely an obstacle.

## Seed

The context handed to a model at the start of a Slice: the Blast Radius, the
glossary, and the ADRs bearing on it. The Seed is deliberately generous —
tokens are cheaper than turns.

## Lease

A time-bound hold that keeps a resource with a running cost (a RunPod Pod,
for example) alive. A Lease always expires — no indefinite Lease exists — and
is renewed by activity rather than held open for a fixed duration. Absent,
expired, or corrupt Lease state resolves toward stopping the resource, never
toward silently continuing it.
