# 7. Test Gate fails a Slice on an unexplained no-diff or an unresolved denial

## Status

Accepted

## Context

A predecessor project's harness had a live incident where a Cycle's every
mutating Tool Call was silently denied by a permission layer before any hook
saw it. The Cycle reported success and produced zero commits, four times.
The report was internally consistent and entirely wrong — nothing in the
Trajectory distinguished "nothing needed to change" from "nothing was
allowed to happen."

ADR 0002 makes a denied or failed Tool Call structurally distinct from a
successful one (`Tool Result.outcome`). That fixes the representation but
not the Test Gate: without a rule tying `outcome` and diff shape to pass/fail,
a Trajectory full of `denied` results could still reach the Gate looking
like ordinary work.

The Harness already has a term for what a Slice was expected to touch: the
Blast Radius, named by the Plan before work begins. A Slice's own glossary
entry already treats a wrong Blast Radius as a defect in the Plan, not the
Slice — the same split this decision needs between a legitimate no-op and a
silent failure.

## Decision

The Test Gate fails a Slice on either of the following, independent of
whatever else the Slice did:

- **No diff, unplanned.** The Slice produced no diff, and the Plan did not
  declare an empty Blast Radius for it. A no-op Slice is only legitimate
  when the Plan named it as one in advance; discovering after the fact that
  nothing needed to change is a defect in the Plan, to be re-planned, not a
  passing Slice.
- **A denial, by kind.** A `rejected` Tool Result anywhere in the Trajectory
  always fails the Gate — it is a permanent policy stance, not something a
  Slice can route around. A `needs-revision` Tool Result fails the Gate only
  if it is **unresolved**: no later `ok` Tool Result exists in the same
  Slice attempt. A `needs-revision` denial that the model corrected and
  retried successfully is ordinary iteration, not a failure.

## Consequences

- The four-zero-commit-Cycles failure mode is caught mechanically: an
  unplanned no-diff Slice, or a Trajectory containing a `rejected` or
  unresolved `needs-revision` result, cannot reach the Test Gate as a pass.
- A Plan that declares an empty Blast Radius can still produce a passing
  no-op Slice — the rule targets silent failure, not intentional no-ops.
- "Resolved" is checked at the level of `outcome`, not intent-matching: any
  later `ok` Tool Result in the Slice clears an unresolved `needs-revision`,
  without the Harness needing to prove the retry addressed the same request.
  This is deliberately weaker than tracking intent, and is accepted as
  sufficient for v1.
- A `rejected` result always fails the Gate even if the Slice otherwise
  produced a correct diff by another route — a permanent policy stance is
  treated as a defect in the Plan or Harness configuration, not something a
  Slice's other progress can offset.
