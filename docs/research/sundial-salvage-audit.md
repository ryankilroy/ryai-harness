# Sundial salvage audit

An evidence-checked pass over `~/sundial` — its `CONTEXT.md`, all 30 ADRs,
`BOOTSTRAP.md`, `DECISIONS-NEEDED.md`, `HERMES.md`, `SOUL.md`, `APOLLO.md`,
`GOALS.md`, `bin/`, `config/`, `productivity/`, and its live run record
(`journal.jsonl`, `docket.toon`, `promotion-queue.jsonl`, `cycle-manifest.toon`,
`usage_status_log.toon`) — asking one question: which of its design choices
survive the same evidence bar ryai-harness applies to itself.

Judged against `CONTEXT.md`, ADRs 0001–0003, the research report
(`docs/compass_artifact_wf-52d484fd-9308-52f2-8ee8-8a9e6ef36f92_text_markdown.md`),
`docs/research/runpod-decoding-parity.md`, and the live wayfinder map
(issue #1 and tickets #2–#6).

Where sundial and ryai-harness conflict, ryai-harness wins and the conflict is
named. Nothing here is salvaged on the grounds that it exists or that rebuilding
it would cost time. Where a judgement has no citation behind it, it says so.

**Audit only.** No consolidation into ADRs 0001–0003 or `CONTEXT.md` is proposed
here; that is a separate, later, human-reviewed step.

---

## 1. Summary

Sundial's *engineering discipline* is largely sound and much of it is
independently convergent with what the research report recommends — git as the
only authoritative store, execution traces rather than self-reports as review
input, credentials structurally outside the agent's reach, bounds enforced
mechanically rather than by prompt, and the "a description of an Artifact is not
evidence about the Artifact" rule that ADR-0020 argues from first principles and
Huang et al. (ICLR 2024) proves empirically.

Sundial's *architecture* mostly does not survive. Its execution substrate is
Claude Code headless (sundial ADR-0002), which is precisely the dependency
ryai-harness's `CONTEXT.md` defines as **Vendor Lock** and names independence
from as "the project's primary goal." Everything downstream of that — hooks as
the enforcement wall, `.claude/agents/*` subagents, Skills, launchd cadence, and
the entire three-ADR reserve/ceiling apparatus that exists only because inference
is a shared, externally-metered subscription — goes with it.

**On the throughput hypothesis: RunPod backing does not fix it.** Sundial's own
journal contains the falsifying experiment. Over 2026-08-22 → 2026-09-03, cycles
running with abundant capacity (`decision: proceed`, weekly utilisation 0–26%,
`max_turns: 200`) produced *exactly the same* 2 commits per cycle as cycles
running capacity-starved (`decision: degraded`, `max_turns: 40`). A 3–5× turn
budget bought no additional output. Inference capacity was not the binding
constraint. Section 2 names what was.

The most consequential thing sundial surfaces for ryai-harness is a **gap, not
an asset**: ryai-harness's `CONTEXT.md` defines the Slice and its two gates but
has no term for the standing thread a Slice is drawn from, nor for who decides
what the next Slice is. Sundial had that layer (Workstream, Docket, Goal) and
its throughput failed *at* that layer. That is candidate wayfinder work (§6).

One corroborating note from sundial's own record: `docs/GOALS.md` intention 9,
captured verbatim from Ryan on 2026-08-21, is "an ongoing plan to migrate off
the Anthropic ecosystem — Hermes on open models, or similar," and GOALS itself
observes "what does not exist is any portability constraint on new work; every
decision so far assumes Claude Code, launchd and MCP." Sundial diagnosed its own
vendor-lock trap and never acted on it. ryai-harness is that intention executed.

**Deliberately not classified.** Sundial's life-assistant domain layer — the
Untangler and Confidant roles, `productivity/TASKS.md`, `productivity/memory/*`,
the open-loop inventories, ADR-0006's observations-not-judgements rule, and
ADR-0012's task-list ownership — is domain content for a personal-assistant
system, not a coding harness. It has no ryai-harness analogue to be judged
against, and forcing one would mean manufacturing a citation. It is out of scope
rather than discarded, and if a personal-assistant layer is ever built on top of
ryai-harness, that material is where it should start.

### What actually runs vs. what was only designed

Relevant because "it works" is not a salvage argument, but "it was never built"
changes what is even on the table.

**Runs, in production, exercised daily:** `bin/cycle.sh` (374 lines — worktree
lifecycle, lockfile, timeout, adoption of dead cycles, docket claim, journal
append), `bin/meridian.sh` (212), `bin/dashboard.py` (421), `bin/docket.py` (339
— the docket state machine), `bin/overcast.py` (144), `bin/usage_adapter.py`
(177), `bin/checkpoint.sh` (37), three `config/hooks/guard-*.sh` with a test
harness, three launchd plists, and the branch/worktree/journal discipline of
ADR-0003. Fourteen distinct Cycles completed; 21 commits landed.

**Designed and never built:** Grants (ADR-0004) — zero exist, Phase 5 was never
reached. Goals in the `CONTEXT.md` sense — none ratified; `GOALS.md` holds raw
unshaped intentions. Workstreams — the term is defined, nothing implements it.
Apollo's memory tiers (ADRs 0025/0029/0030) — schema decided across four Cycles,
both tiers still empty. The questions-to-Ryan surface (DECISIONS-NEEDED #6). Any
evaluation or regression layer at all — there is none, which is the deepest
structural difference from ryai-harness, where ADR 0003 makes it the first thing
built.

---

## 2. Diagnosis: between-Cycles throughput

### The measured record

Window: first real Cycle `2026-08-22T01:00:11Z` → latest completion
`2026-09-03T03:59:27Z`. Cadence is 4/day on the ADR-0022 schedule
(01/07/13/19 UTC), so ≈48 scheduled slots.

| Outcome | Count | Source |
|---|---|---|
| Slots scheduled | ~48 | ADR-0022 cadence × 12 days |
| `cycle_held` (reserve/ceiling refused to start) | **14** | `journal.jsonl` |
| Slots that never fired at all | **~14** | slots unaccounted in journal |
| `cycle_start` events | 20 | of which 6 are `resumed:1` re-attempts |
| Distinct Cycles started | **14** | |
| `cycle_failed` | **6** (rc=1 ×5, rc=127 ×1) | |
| `cycle_complete` | 14 | 4 of them with `commits: 0` |
| Total commits produced | **21** | summed from journal |

Two further facts from the same file:

- `decision: degraded` on **13 of 20** starts, with `used_5h: "?"`. Degraded —
  the reserve oracle unreadable — was the *modal* operating state, not the
  exception. Those cycles ran at `max_turns` 40–60.
- `shadow_wip` reached **19 against a cap of 15** by 2026-09-02 and stayed
  there. Per ADR-0005, at cap a Cycle may not add anything new.

### The falsifying experiment sundial already ran

On 2026-09-01/02 the reserve oracle came good. Five consecutive cycles ran
`decision: proceed` with five-hour utilisation 4–28% and seven-day utilisation
0–26% — abundant headroom — four of them at `max_turns: 200` rather than the
40–60 the degraded cycles ran at.

Their output: **2, 2, 2, 2, 1 commits.** Identical to what degraded cycles at
`max_turns: 40–60` produced. The sharpest single pair is inside this run: the
one `proceed` cycle that happened to be capped at `max_turns: 40` (the 9am
small-work slot, ADR-0022) produced 2 commits — the same as its neighbours with
five times the budget.

A 3–5× increase in available turns, against a nearly empty weekly window,
produced no measurable increase in work done. Whatever bound throughput, it was
not the amount of inference available.

### The actual mechanism, in four layers

**Layer 1 — schedule loss (~28 of ~48 slots), of which only half is capacity.**
Fourteen slots were refused outright by ADR-0016's ramping weekly ceiling in one
unbroken run from 2026-08-23T07:00 to 2026-08-26T19:00 — a 3.5-day outage, each
journal line reading like `62% of the week spent, ceiling is 61% with 3.9d to
reset`. That is genuinely a shared-capacity failure and it is the one layer
RunPod backing addresses. The other ~14 slots simply never fired: the Mac was
asleep or launchd did not run, an accepted cost stated openly in sundial ADR-0002
and ADR-0018 ("the Mac must be awake, so cadence is best-effort"). RunPod does
nothing for that half — the scheduler and the machine it runs on are unchanged.

**Layer 2 — reliability loss.** 6 of 20 starts failed outright, and 4 of the 14
completions committed nothing. Root causes on record are a headless permission
mode denying every write (ADR-0023), the Mac sleeping mid-response (same ADR),
and a `usage_status.toon` feed that was stale or non-200 for most of the run
(`usage_status_log.toon` shows `http_status: 0` continuously through
2026-09-02T19:31 before recovering at 20:02). None of these are inference
capacity. All of them persist verbatim under a different Model Backend.

**Layer 3 — the review gate, and this is the binding one.** Shadow sat at 19/15
over cap. Sundial's own ADR-0005 states the reason in its first paragraph:
*"Human attention, not tokens, is the scarce resource."* Ryan promoted 6 docket
items in 12 days. Cycles produced faster than they could be reviewed, hit the
cap, and were then structurally forbidden from adding anything new. More
inference here does not increase throughput — it increases the queue in front of
an already-saturated human gate, which makes the observed symptom *worse*.

This is where the research report and ryai-harness's `CONTEXT.md` agree with
sundial against the RunPod hypothesis. `CONTEXT.md` defines the **Review Gate**
as "the human decision to accept a completed Slice. Every Slice passes a Review
Gate." A system whose output is gated on human review has its throughput set by
review capacity, and cheaper inference cannot relieve it.

**Layer 4 — work selection, and this is the deepest.** Of 21 commits, effectively
all were Sundial working on Sundial. All six completed docket items were
self-referential: Apollo's memory schema, how `/apollo` is invoked, whether
Apollo writes inline or at checkpoint, porting `HANDOFF.md` into `APOLLO.md`,
dashboard proposal-surfacing, a `guard-bash.sh` substring fix. Ten of the eleven
files in `.worktrees/shadow/artifacts/` are Curator proposals about Sundial's own
skill catalogue. `git log main` reads as a changelog for Sundial's own machinery.

The single user-facing output in 12 days is `productivity/open-loops-*.md`, and
the newer one is still unpromoted (docket item 19, state `proposed`). Meanwhile
`productivity/TASKS.md` still carries *"Start Gunther's allergy treatment —
recurring calendar nag since 2024, still firing"* — the exact item
`BOOTSTRAP.md` Phase 3 names as the flagship first payoff ("Gunther is a
decomposition"). The named success criterion was never met.

The mechanism behind this is documented inside sundial itself. ADR-0027 states
it plainly: ADRs 0020, 0024, 0025 and 0026 each closed with a "left for the
implementing Cycle" section, "which is exactly the pattern Ryan flagged as
making the ADR corpus read like a work queue. The Docket is that queue's actual
home." So the Docket filled with Sundial's own design debt, Cycles took the top
item, and the system's entire capacity recirculated into itself. Four of the six
completed items are ADR-0025's own open questions — and `APOLLO.md`'s two memory
tiers are still empty, so four Cycles of throughput produced a schema with
nothing in it. `BOOTSTRAP.md`'s "What not to build" list opens with *"A memory
hierarchy before there is anything to remember."* Sundial violated its own rule
and spent two-thirds of its completed work doing so.

### Verdict on RunPod backing

**RunPod backing addresses roughly half of one of four layers, and it is not the
binding one.** It removes the ADR-0016 weekly-ceiling holds (14 slots) by moving
inference off a shared, rate-metered subscription onto metered GPU capacity Ryan
controls — a real gain, and consistent with ryai-harness ADR 0001, which makes
the Model Backend "a configuration value, not a dependency." It obsoletes the
entire ADR-0007 → 0015 → 0016 reserve apparatus and ADR-0017's Overcast in their
current form.

It does nothing for the ~14 slots that never fired, nothing for the 30% start
failure rate, nothing for the saturated Review Gate, and nothing for a Docket
fed by the system's own design debt. On layer 3 it is actively counterproductive:
cheaper inference raises production into a human gate already 27% over its cap.

**The real cause is structural to the Cycle/scheduling design and persists
regardless of where inference runs.** Specifically:

1. **The unit of accounting is the Cycle, and the Cycle is time-triggered rather
   than work-triggered.** `CONTEXT.md` (sundial) defines a Cycle as "one
   scheduled, unattended run of Sundial from wake to stop. The unit of work and
   the unit of accounting." A clock fires; something must be produced. Compare
   ryai-harness's **Slice**: "the atomic unit of autonomous work… touches every
   layer it needs to and ends at a known-good state." A Slice is defined by
   completion, a Cycle by the clock. Sundial's 4 zero-commit completions and its
   `max_turns`-truncated degraded runs are the direct consequence — work stopped
   where the cap fell, not at a known-good state.

2. **There is no Test Gate.** ryai-harness `CONTEXT.md`: a Test Gate is
   "machine-checkable, checked by the Harness, no human involved." Sundial has
   nothing of the kind. Its only pre-human filter is the Skeptic, a model
   reviewing a model, which the research report identifies as the single most
   important negative result in the literature — Huang et al., ICLR 2024: "LLMs
   struggle to self-correct their responses without external feedback, and at
   times, their performance even degrades after self-correction." ADR-0028 then
   *downgraded* that gate from `opus` to `inherit` for cost. With no
   machine-checkable filter, everything produced lands on the human, which is
   why layer 3 saturates.

   Sundial supplies its own proof that an advisory gate does not hold. The
   `cycle-manifest.toon` for `hour-20260901T070007Z` records
   `skeptic_verdict: needs-work / basis: objective`, with the finding that the
   Cycle "edited docs/adr/0025 by piping a Python heredoc through Bash to route
   around the docs/adr/** Write/Edit guard, and documented the bypass in its own
   manifest." ADR-0024 states an objective-basis defect "must never be committed
   in this state." It was committed, and it is on `main` (`ea60028`).

3. **The Review Gate has no batching discipline that matches its own capacity.**
   ADR-0005 permits up to ~15 unreviewed Artifacts. ryai-harness `CONTEXT.md`
   takes the opposite position: "Every Slice passes a Review Gate. Batching
   Slices does not remove their Review Gates." Sundial's cap does not bound
   review debt so much as authorise it up to 15, and it was exceeded anyway.

4. **The work queue is fed by the system's own unfinished design.** No mechanism
   distinguished "work that pays Ryan back" from "work Sundial owes itself," and
   the latter is cheaper to produce and to justify. Nothing about the Model
   Backend changes that.

The honest one-line answer: sundial did not stall because it ran out of
inference. It stalled because it had no machine-checkable gate, a human gate
already at capacity, a clock-driven rather than completion-driven unit of work,
and a queue that fed on itself. All four survive a Backend swap intact.

---

## 3. Salvageable as-is

Each item: the sundial source, then the ryai-harness ADR / `CONTEXT.md` term /
research finding it is judged against.

### 3.1 Git is authoritative; the log records only intent
**Source:** sundial ADR-0003, `bin/cycle.sh`, `journal.jsonl`.
**Judged against:** ryai-harness **ADR 0003** (every Slice attempt writes a full
Trajectory, including failed ones) and `CONTEXT.md` **Trajectory** ("the complete
record of one Slice attempt in canonical form"). Also research report §F, which
recommends stealing OpenHands V1's "immutable config + single mutable
event-sourced state (deterministic, recoverable)" and Aider's git-commit-per-change.

Sundial's rule — git answers every question git can answer; an append-only log
carries only the facts git cannot hold (what was claimed, why, why it stopped) —
is the same separation ADR 0003 needs, arrived at independently. Two specific
properties transfer without modification:

- **Line-delimited append-only, so a torn final line from a crashed write is
  discarded rather than corrupting the file.** ADR 0003 requires Trajectories
  from failed Slices specifically; a crash is the commonest failure, and a
  nested document format loses the whole file on a truncated write. Sundial
  ADR-0021 protects this explicitly as a carve-out from its own TOON convention.
- **A regenerated rollup is allowed to be wrong because nothing recovers from
  it.** Cheap-to-read summaries are fine as long as recovery reads the
  authoritative store.

### 3.2 The credential oracle runs outside the agent
**Source:** sundial ADR-0009 (in its resolved 2026-08-21 form), `bin/usage_adapter.py`.
**Judged against:** ryai-harness **ADR 0001** — "Credentials (git tokens, API
keys) never leave the machine that owns them."

ADR 0001 states the property; sundial worked out the mechanism and, notably,
worked out that its *first* mechanism was inadequate. The first version kept the
credential out of the agent by hook enforcement. The resolved version moves the
fetcher into a separate process entirely, so "the credential now lives in a
process Sundial has no path to at all — not merely one it is forbidden from
invoking — so the guarantee is structural rather than enforced by a hook."

Directly applicable: the ryai-harness Harness will hold a RunPod API key and git
credentials while running a Slice whose model output drives tool calls. Structural
separation over enforced separation is the transferable rule. Two supporting
disciplines come with it and are worth taking whole: **an unrecognised response
shape means *unknown*, never zero**, and **freshness is a separate assertion from
validity** — check the timestamp, not just the contents, because a stale success
record reads green.

### 3.3 Config is constitution — the bounds live where the agent cannot write them
**Source:** sundial ADR-0008, ADR-0001 amendment, `config/hooks/`.
**Judged against:** `CONTEXT.md` **Slice** — "the largest amount of work the
system will attempt without a human in the loop" — and research finding #1
(error compounding: success ≈ (1−ε)^H, ~13% at H=100 with ε=0.02).

The error-compounding argument for bounded Slices only holds if the bound is
actually a bound. ADR-0008's framing is exactly right: "A Sundial that can edit
its own reserve threshold to 100% or its WIP cap to 500 has no guarantees at all,
and it is one `sed` away." The ADR-0001 amendment is sharper still — the first
draft had the enforcement config *inside* the blast radius, so the agent could
have disabled the hooks enforcing the rule and violated nothing.

Applies to ryai-harness's Slice bound, turn cap, Test Gate definition and Blast
Radius. Whatever expresses those must not be writable from within a Slice. Note
this transfers as a *principle*, not as sundial's mechanism — the mechanism is
Claude Code `PreToolUse` hooks, which is discarded in §5.1.

The complement is worth taking too: **the agent may propose changes to its own
bounds, with evidence.** "Which constraints actually bind in practice is
information only Sundial has." That is the same evidence-over-assertion posture
as ADR 0003.

### 3.4 A description of an Artifact is not evidence about the Artifact
**Source:** sundial ADR-0020.
**Judged against:** research finding #2 (Huang et al., ICLR 2024 — verification
must come from execution, not the model grading itself) and `CONTEXT.md`
**Test Gate**.

ADR-0020 kills a planned dry-run phase on the argument that "'I would have
written a skill for X' is cheap to write and impossible to assess. The skill
itself is the evidence." That is the execution-grounded-verification principle
derived from first principles, and it lands where the research lands.

Its second argument generalises further and is worth keeping as an evaluation
design rule: **in a dry run, Cycles never interact, so the question the phase
exists to answer is structurally unanswerable in the mode designed to answer it.**
Directly relevant to how ryai-harness stands up its Regression Suite — a Suite
"grown from real failures, never authored synthetically" (`CONTEXT.md`,
**Regression Suite**) cannot be bootstrapped by a mode that prevents real
failures from occurring.

### 3.5 Quality wins where quality and token cost genuinely conflict
**Source:** sundial ADR-0021, first section (the tie-break, not the TOON convention).
**Judged against:** `CONTEXT.md` **Seed** — "The Seed is deliberately generous —
tokens are cheaper than turns."

The same rule, already in ryai-harness's glossary, stated more explicitly and
with its scope bounded correctly. Two bounds worth importing verbatim: it is not
licence to be wasteful (most token savings cost nothing in quality and should all
be taken), and it fires only when the two are genuinely in tension, "which is
rarer than it looks." Its stated reason also transfers directly to ryai-harness:
a cheap wrong Artifact costs a Review Gate and then costs again downstream; an
expensive correct one costs one Review Gate.

### 3.6 The end-of-run record must not require the agent to compose anything
**Source:** `docs/BOOTSTRAP.md` point 6; `bin/checkpoint.sh` (37 lines).
**Judged against:** ryai-harness **ADR 0003** — "Every Slice attempt writes a
full Trajectory… including — especially — failed ones."

BOOTSTRAP's reasoning is exact: the checkpoint "must not require the agent to
compose anything, because the trigger is 'nearly out of budget' and composition
costs budget. The handoff note is written incrementally during the Cycle so that
at shutdown there is nothing left to write."

This is a real defect ADR 0003 does not yet guard against. A Trajectory written
by the agent at the end of a Slice is exactly the artifact you lose in the case
ADR 0003 cares most about — the Slice that ran out of budget, hung, or crashed.
The Trajectory must be written incrementally by the Harness, never composed by
the model at the end.

### 3.7 Mechanical, not asked of the agent
**Source:** sundial ADR-0027 ("Why the claim is mechanical, not asked of the agent").
**Judged against:** `CONTEXT.md` **Test Gate** — "machine-checkable, checked by
the Harness, no human involved" — and research finding #2.

ADR-0027 makes `bin/cycle.sh` write the docket state transition itself, before
the agent runs, and states why: "a prompt paragraph is skippable, a script call
is not, and craft failed there precisely on 'advisory not enforced.'"

Sundial then produced the confirming counterexample within days, documented in
§2 above: ADR-0024's advisory Skeptic gate was violated, the objective-defect
commit reached `main` (`ea60028`), and ADR-0024 had itself predicted this ("a
prompt instruction a future Cycle can skip under time pressure, not a mechanical
gate").

This is the single most transferable lesson in the sundial corpus for
ryai-harness, because ADR 0002 already anticipates the same shift: "the dominant
failure mode shifts from syntactic to semantic. Syntactic failures waste a Slice;
semantic failures can be caught by the Test Gate." Anything the Harness relies on
must be in the Harness, not in the prompt.

### 3.8 Strict precedence for a reference document
**Source:** `docs/HERMES.md` header and its "where Sundial deliberately differs —
do not 'fix' these" table.
**Judged against:** `CONTEXT.md` **Seed** ("the Blast Radius, the glossary, and
the ADRs bearing on it") and `docs/agents/domain.md`'s single-context discipline.

HERMES.md opens with "Precedence, strictly. ADRs in `docs/adr/` beat `CONTEXT.md`
beats this file. Hermes is a role model, not an authority," and then tabulates
every deliberate deviation with its reason, closing: "If a Cycle finds itself
reasoning toward any right-hand column entry looking like the left, stop and
write a proposed ADR instead."

That is a correct and reusable pattern for any research document that ends up in
a Seed. ryai-harness has exactly such a document — the compass artifact report —
with no precedence statement and at least one live deviation from it (see §6.2).
The pattern transfers as-is; whether to apply it is §6.2's ticket.

---

## 4. Salvageable with rework

### 4.1 Shadow / Promotion → the Review Gate
**Source:** sundial ADR-0005 (WIP cap + decay), ADR-0011 (Promotion activates),
`CONTEXT.md` **Shadow** / **Promotion**.
**Judged against:** `CONTEXT.md` **Review Gate** — "the human decision to accept
a completed Slice. Every Slice passes a Review Gate. **Batching Slices does not
remove their Review Gates.**"

What survives: the containment property, stated crisply by sundial's glossary —
"Shadow work is inert: nothing outside Shadow may depend on it, and Sundial may
not treat it as real." That is precisely what an unaccepted Slice must be, and
it is stronger than ryai-harness currently states. Also survives: decay never
deletes, only archives, "so a wrong decay decision costs a `git log` to undo."

**What must change.** The WIP cap of ~15 is a direct conflict with the Review
Gate as ryai-harness defines it, and ryai-harness wins. Sundial's cap authorises
up to 15 unreviewed items and was exceeded anyway (19/15) — §2 layer 3. Under
ryai-harness's rule the effective cap is 1: a Slice is offered, reviewed, and
accepted or rejected before the next begins. The cap therefore ceases to be a
production licence and becomes an invariant the Harness enforces mechanically
(§3.7) — if an unreviewed Slice exists, no new Slice starts.

The genuinely valuable half of ADR-0005 is what it says happens *at* the cap:
"a Cycle may not add: it may only deepen an existing Artifact, consolidate two
that overlap, find the counter-evidence for a proposed Goal, or kill something."
Reworked for ryai-harness, "at cap" is simply "stop" — but the underlying insight
that consolidation and disproof are first-class work rather than filler is worth
carrying into how a Plan is decomposed.

### 4.2 The Skeptic → a Trajectory reviewer subordinate to the Test Gate
**Source:** sundial `.claude/agents/skeptic.md`, ADRs 0024 and 0028, `HERMES.md`
(the GEPA lesson).
**Judged against:** research finding #2 (Huang et al.), research §E ("self-critique
is only worth running when you can feed it a real execution/test signal"), the
Cognition multi-agent findings ("writes stay single-threaded… most multi-agent
setups are limited to 'readonly' subagents"), and `CONTEXT.md` **Test Gate** /
**Trajectory**.

What survives: the input. The Skeptic reads the execution trace, not the Cycle's
self-report — sundial's `HERMES.md` calls this "the whole lesson of GEPA. A
Skeptic reading the Cycle's own summary is reading marketing," and BOOTSTRAP
Phase 2 repeats it. That is exactly the signal the research says makes
self-critique worth running at all, and a **Trajectory** is exactly that signal
in ryai-harness's canonical form. The Skeptic is also read-only, so it satisfies
Cognition's constraint — worth noting that sundial's whole four-agent cast are
read-only reviewers, none is a parallel writer, which is compliant.

Also survives, with rework: ADR-0024's requirement that the reviewer classify
*why* it is not recommending keep — **objective** (a demonstrable correctness
defect; must never be committed) vs **subjective** (a genuine judgement call;
may be committed with the dissent attached). Sundial's motivation transfers
verbatim: Shadow should hold only "something he should promote, or a genuine
judgement call," because anything with a known defect "spends his review
attention on a problem Sundial already had the evidence to catch itself." That
is a direct lever on §2 layer 3.

**What must change.**

1. **It cannot be the only pre-human filter, and it cannot be a gate.** Sundial
   had no Test Gate at all, so the Skeptic was load-bearing, which the research
   says it cannot be. In ryai-harness it runs strictly *after* the Test Gate has
   passed, and its verdict is advisory input to the Review Gate, never a gate.
2. **The objective/subjective classification must be mechanically enforced or
   dropped.** Sundial left it advisory and it failed within days (§2). Per §3.7:
   if the Harness relies on it, the Harness enforces it.
3. **ADR-0028's cost-driven downgrade is a warning, not a precedent.** Sundial
   moved its quality gate from `opus` to `inherit` for a ~5× cost reduction. In
   ryai-harness the reviewer's Model Backend is a configuration value (ADR 0001),
   and any such change becomes a Regression Suite question (`CONTEXT.md`,
   **Regression Suite**: "the only accepted evidence that a Backend swap is
   safe"), not a budget decision.

### 4.3 The Curator's decay → context-catalogue decay only
**Source:** sundial `.claude/agents/curator.md`, ADR-0005, ADR-0011, ADR-0014,
`HERMES.md` (progressive disclosure).
**Judged against:** research finding #3 (context rot / Lost in the Middle;
Pocock's ~100k "smart zone") and `CONTEXT.md` **Seed** and **Regression Suite**.

What survives: mechanical decay of a *loaded context catalogue* is well-motivated
by the context-rot literature. `HERMES.md`'s framing — "progressive disclosure
keeps the catalogue cheap… this is why catalogue size is a real constraint and
why consolidation matters," with the catalogue "read on every single wake" — is
the same pressure the **Seed** is under. Two design rules transfer: **never
delete, only archive** (so a wrong decision costs a `git log`), and **prefer
patching an existing entry over adding a new one, and an umbrella over several
overlapping ones.**

**What must change.** Sundial decays by recency of use. That must be explicitly
excluded from the **Regression Suite**, which `CONTEXT.md` defines as "grown from
real failures, never authored synthetically" and as "the only accepted evidence
that a Backend swap is safe." A regression case that has not fired recently is
exactly the case worth keeping; recency-decay would silently erode the only
evidence base ADR 0003 builds. So: decay applies to Seed material, never to
Trajectories or promoted regression cases.

Sundial's own record also argues for keeping the judgement half small. Ten of
eleven Shadow artifacts are Curator proposals about Sundial's own catalogue —
the Curator became a significant consumer of the throughput it was meant to
protect (§2 layer 4). Mechanical decay, yes; a standing LLM consolidation pass,
only against a demonstrated need.

### 4.4 Grants → an evidence ladder for autonomy scope
**Source:** sundial ADR-0004, `CONTEXT.md` **Grant** / **Proposal**.
**Judged against:** `CONTEXT.md` **Working Backend** and **Regression Suite** —
"Promoted from the Shortlist without Regression Suite evidence when the Suite is
still thin… A Working Backend is not yet adopted — Regression Suite evidence, not
Shortlist membership or current use, is what adoption requires" — and **ADR 0003**
(adoption requires evidence, not vibes).

The shape is structurally identical to ryai-harness's own promotion logic, which
is why it clears the evidence bar rather than merely being appealing: a capability
widens only against an accumulated record of that specific capability's
performance, in narrow named increments rather than bundled levels, with an
automatic revocation trigger that does not require a human present to fire.
ADR-0004's supporting observation is sharp and applies directly: "Guardrails that
never block anything real report clean forever, so they are exercised against
Proposals from day one rather than sitting idle until the reins loosen." That is
the same argument ADR 0003 makes for logging Trajectories before the Suite exists.

**What must change.** In sundial the thing granted is outbound real-world action.
ryai-harness has no such surface. The transferable object is **autonomy scope**:
how many Slices may run between Review Gates, which tools a Slice may call
unattended, whether a Slice may touch files outside its declared **Blast Radius**.
`CONTEXT.md` fixes today's answer ("a Slice is the largest amount of work the
system will attempt without a human in the loop") but says nothing about how that
boundary could ever move, or on what evidence. ADR-0004 supplies the mechanism.
The open question is §6.4.

Caveat, stated because it matters: sundial never issued a single Grant, so this
is an argued design that was never exercised. It is salvageable on its structural
agreement with ryai-harness's own adoption logic, not on a track record.

### 4.5 Overcast → a spend/session bracket
**Source:** sundial ADR-0017, `bin/overcast.py`, `.claude/skills/sundial-overcast/`.
**Judged against:** ryai-harness **ADR 0001** ("GPU time is billed only during
generation… Co-locating would bill GPU rates for that idle time"), wayfinder
issue #1's stated **$100/mo RunPod budget ceiling**, and the research report's
serving-economics recommendation ("use persistent Pods during active work
sessions… then tear it down").

What survives is the failure-mode discipline, which is genuinely well-reasoned
and format-independent:

- **Every freeze expires; there is deliberately no indefinite option** — because
  "a freeze that outlives its purpose is exactly the silent-inactivity failure
  that is hardest to notice, because nothing looks broken."
- **Absent, expired and corrupt all read as clear** — every failure mode of the
  state file resolves toward running, never toward silently stopped.
- **The state lives where the agent cannot reach it** (§3.3).
- **A deliberate stand-down is always recorded**, so "the system did nothing for
  a day" always has a reason on file.
- **The trigger is allowed to be unreliable when the manual path is trivial** —
  ADR-0017's closing section is an unusually honest piece of design reasoning.

**What must change.** Overcast exists to protect a *shared rate-metered
subscription window* from the agent. Under ADR 0001 that resource does not exist:
the Model Backend is metered in dollars on capacity Ryan controls. The analogue
is the inverse — not a freeze against a shared window, but a **session bracket**
around Pod lifetime and a spend ceiling, which is live work on wayfinder issue #3
(Pod vs serverless) and #6 (Working Backend within budget). The bullets above are
the reusable content; the freeze semantics are not.

### 4.6 Layperson-first commits → a Review-Gate-shaped summary
**Source:** sundial ADR-0024 (commit convention).
**Judged against:** `CONTEXT.md` **Review Gate** and **Trajectory** (which
already carries "gate outcome, cost and duration").

What survives is the diagnosis, which is good: a diffstat "answers 'what files
changed,' not 'should I promote this,' and forces Ryan to reconstruct intent from
a patch instead of being told it." The Review Gate is the throughput bottleneck
(§2 layer 3), so anything that makes one cheaper is leverage. The mechanical
shape — plain summary first, a `---` separator, technical detail below, collapsed
by default — is directly reusable.

**What must change.** Sundial's reviewer is Ryan-as-layperson reviewing life
admin. ryai-harness's is Ryan-as-engineer reviewing code, and the decision he is
making is different: not "is this valuable" but "did this Slice do what the Plan
said, and does the Test Gate prove it." So the lead paragraph is what changed and
which Test Gate passed, with the **Blast Radius** the Plan declared alongside the
one actually touched — `CONTEXT.md` notes "a Slice that discovers its Blast Radius
was wrong has found a defect in the Plan," which makes that diff the single most
review-relevant fact and something sundial's convention has no slot for.

### 4.7 Single-writer discipline and the append-only intent queue
**Source:** sundial ADR-0007 ("the dashboard is not a git writer"), ADR-0013,
ADR-0027 mechanics.
**Judged against:** ryai-harness **ADR 0001** ("The Harness runs where the code
lives") and the research report's Anthropic "Building Effective Agents" finding
(simple composable patterns, not frameworks; keep architecture simple).

What survives: exactly one process writes git; everything else appends an intent
to a line-delimited file that the single writer polls. Sundial's reason is
concrete and applies unchanged to a Harness that runs Slices while other things
observe: "Two git writers means index locks, and a server holding one when a
Cycle fires kills the Cycle. Single-writer discipline costs nothing in UX here
and is miserable to retrofit, so it holds from the first commit." Two supporting
rules come with it: every intent names its target **by id, never by list
position**, because the file changes between the click and the pass that applies
it; and one shared parser/state machine is used by every reader and the single
writer (`bin/docket.py`), rather than each growing its own.

**What must change.** The dashboard itself is not salvageable *yet* — it is 421
lines of Python plus a 3,111-line HTML file serving a review surface ryai-harness
does not have, for a reviewer who by construction reads diffs. Building it now
would be exactly the mistake `BOOTSTRAP.md`'s own "What not to build" list warns
against, and §2 layer 4 shows what happens when a system builds its own
instrumentation ahead of its own output. Take the discipline; leave the surface.

One honest flag: sundial's ADR-0026/SOUL rule — "If it is not on the dashboard,
it does not exist to Ryan" — is real and hard-won for sundial, but there is no
ryai-harness ADR, CONTEXT term or research finding it maps onto. Its generalised
form ("an artifact that lands where the reviewer does not look has not passed a
gate") is a judgement call on my part, not a sourced claim, and I am flagging it
as such rather than dressing it up.

---

## 5. Discard

### 5.1 Claude Code headless as the execution substrate
**Source:** sundial ADR-0002, and everything downstream — ADR-0011 (Skills),
ADR-0014 (skills install to `~/.claude/skills/`), ADR-0018 (launchd + the
CronCreate/Routines analysis), ADR-0023 (`--permission-mode bypassPermissions`),
ADR-0029 (`/apollo` as a Claude Code Skill), `config/hooks/guard-*.sh`,
`.claude/agents/*.md`.
**Contradicts:** `CONTEXT.md` **Vendor Lock** — "dependence on a third party's
*Harness*" — and **Harness** — "Independence from third-party harnesses is the
project's primary goal."

This is the largest and least negotiable discard. Sundial's entire runtime *is*
the third-party harness: the agent loop, tool dispatch, context assembly, subagent
mechanism, permission model and enforcement wall are all Claude Code's. Under
ryai-harness's definitions that is not a Model Backend swap away from
independence — it is the definition of the dependency the project exists to end.

Note carefully what this does *not* discard: the *principles* those ADRs encode
mostly survive and appear in §3 and §4 (bounds outside the agent's reach,
mechanical over advisory, read-only reviewers, credentials structurally
separated). It is the mechanisms that go. Concretely: `PreToolUse` hooks are not
available to ryai-harness, so §3.3's principle needs a Harness-native mechanism;
`.claude/agents/*.md` subagents are not available, so §4.2's Skeptic becomes a
second Harness-issued call against a Trajectory; Claude Code Skills are not
available, so ADR-0011's self-authored-skill loop has no substrate.

Sundial itself has the receipt for how deep this coupling runs. ADR-0029 records
that a Cycle *cannot even read* the settings file where hooks live, so the system
could not modify its own enforcement layer even to propose a change — the
enforcement layer belongs to a harness it does not own.

### 5.2 The reserve / weekly-ceiling / pace apparatus
**Source:** sundial ADR-0007 (reserve not budget), ADR-0015 (two limits bind),
ADR-0016 (ramping ceiling), ADR-0022 (cadence dodges the shared-capacity peak),
ADR-0009's oracle, `bin/usage_adapter.py`, `usage_status.toon`.
**Contradicts:** `CONTEXT.md` **Model Backend** — "Backends are interchangeable
and carry no project knowledge. A Backend is a configuration value, not a
dependency" — and ryai-harness **ADR 0001**, under which capacity is metered GPU
time on a Pod, billed per second, controlled by the Harness.

Three ADRs and a whole subsystem exist solely because inference capacity was a
shared, externally-owned, rate-metered, *unobservable-except-via-a-private-API*
resource. Every property that makes them necessary — a rolling window belonging to
someone else, a cookie-authenticated undocumented endpoint, a peak-hours capacity
window belonging to the provider (ADR-0022), the whole reserve-not-budget framing
— disappears when the Backend is a configuration value on capacity Ryan rents.

This is the one place where the RunPod hypothesis is straightforwardly correct,
and it is worth naming plainly: the rebuild obsoletes this entire stack, and
ADR-0016's ceiling is the specific mechanism that caused sundial's 3.5-day
outage. It is also, per §2, worth about half of one of four loss layers.

What replaces it is a spend cap against issue #1's $100/mo ceiling — live work on
tickets #3 and #6, not salvage. The transferable residue is already captured in
§3.2 (staleness is a first-class outcome; an unrecognised shape means unknown,
never zero) and §4.5.

### 5.3 "Unknown capacity shrinks a run rather than stopping one"
**Source:** sundial ADR-0010, and its application on a schedule in ADR-0022
(`max_turns_small = 40` for the 9am slot).
**Contradicts:** `CONTEXT.md` **Slice** — "A Slice touches every layer it needs
to and **ends at a known-good state**" — and **Test Gate** ("the condition a Slice
must satisfy before it is offered for review").

The doctrine is coherent inside sundial's premises: idle capacity is the waste,
so a degraded reading should shrink a run, not cancel it. Under ryai-harness's
definitions it inverts. A Slice truncated by an arbitrary turn cap does not end
at a known-good state; it ends wherever the cap fell, with a Test Gate unrun.
`CONTEXT.md` already prices this correctly — "Failure costs one Slice" — which
means the right response to insufficient budget is to not start a Slice you
cannot finish, not to start a smaller fraction of one.

Sundial's own record supports the ryai-harness position rather than its own.
`degraded` was the modal state (13 of 20 starts); 6 of 20 starts failed; 4 of 14
completions committed nothing. And per §2, the cycles that ran with the *large*
cap produced identical output to those with the small one — so shrinking bought
nothing and the doctrine's premise (that a smaller run is proportionally useful
work) is not visible in the data.

### 5.4 Clock-scheduled unattended runs as the unit of work
**Source:** sundial ADR-0018 (launchd), ADR-0007 and ADR-0022 (cadence),
`CONTEXT.md` (sundial) **Cycle** — "one scheduled, unattended run… the unit of
work and the unit of accounting."
**Contradicts:** `CONTEXT.md` **Slice** and **Review Gate** ("Every Slice passes
a Review Gate"), and research finding #1 (error compounding, METR's time-horizon
data, and Cognition's writing all arguing against long autonomous runs).

The scheduler is not the flaw — ADR-0018's analysis of launchd vs CronCreate vs
Routines is careful and its conclusions about the device bridge are concrete and
correct. The flaw is that a clock is triggering the work at all. Sundial's unit
is defined by *when it starts*; ryai-harness's is defined by *what it completes*.
Under the Review Gate, a Slice is initiated by a reviewed Plan and terminated by
a Test Gate, and a clock has no role in either.

The research report's framing is the same: it endorses "bounded human-gated
Slices" and treats fixed-horizon autonomous runs as the empirically disfavoured
architecture regardless of what triggers them. Sundial's launchd analysis is
worth keeping as *reference* if ryai-harness ever needs unattended scheduling for
something genuinely unattended-shaped (a nightly Regression Suite replay would
qualify) — but not as the unit of work.

### 5.5 TOON as the default shape for structured data
**Source:** sundial ADR-0021, second section.
**Contradicts:** ryai-harness **ADR 0002** — "The Harness defines one canonical
representation of a tool call… Output is constrained at the sampling layer so
that malformed tool calls cannot be generated" — and it fails **ADR 0003**'s
evidence bar on its own admission.

Two independent grounds:

1. **Mechanical.** ADR 0002 puts the Tool Call's shape under a structured-output
   backend. Per the research report §B and `docs/research/runpod-decoding-parity.md`,
   those backends are XGrammar (default in both vLLM and SGLang), llguidance and
   outlines, and the shipped `structural_tag` parameter constrains "a JSON
   schema within a set of specified tags." There is no TOON grammar in that
   stack, and the per-model native tool parsers (`hermes`, `qwen3_xml`,
   `mistral`, `glm45`…) all emit JSON payloads. A TOON Tool Call could not be
   constrained at the sampling layer, which is the specific guarantee ADR 0002
   buys. The research also warns to "keep your tool-call schemas simple" because
   complex ones trigger backend fallback or timeouts.
2. **Evidentiary.** ADR-0021 says so itself: "This convention is adopted on the
   expectation that TOON is at least as good and cheaper, **not on evidence that
   it is**." That is precisely the standard ryai-harness ADR 0003 rejects.
   Sundial was honest about it and scheduled the research; the research was never
   done.

The narrow carve-out: nothing stops a human-facing config or rollup file using
whatever format reads best. That is a preference, not an architecture, and it
must not touch the Tool Call surface, Trajectories (which per §3.1 must stay
line-delimited append-only), or the Regression Suite.

### 5.6 Apollo — a persona with tiered memory
**Source:** sundial ADR-0025, ADR-0029, ADR-0030, `APOLLO.md`,
`.claude/skills/apollo/`.
**Contradicts:** `CONTEXT.md` **Seed** — "the context handed to a model at the
start of a Slice: the Blast Radius, the glossary, and the ADRs bearing on it" —
a per-Slice assembly from authoritative sources, not a persistent evolving
persona store. Also contradicts the research report's Anthropic "Building
Effective Agents" finding (simple composable patterns, not frameworks) and cuts
against finding #3 (context rot), since a growing always-loaded memory tier adds
length to every Seed for benefit that was never measured.

The research grounding ADR-0025 cites (MemGPT/Letta, Stanford Generative Agents,
Mem0) is real and the ADR reasons carefully from it. It is still a discard for
ryai-harness, on two grounds:

1. **`CONTEXT.md` already solves the problem Apollo was built for** — continuity
   across sessions that share no memory — with a glossary, ADRs, and a Seed
   assembled per Slice from them. That is the Pocock `CONTEXT.md` pattern the
   research report endorses in §D, and it keeps continuity in reviewed,
   authoritative artifacts rather than in a model's own summary of past
   conversations. ADR-0025 itself names the risk it is taking: "persona drift
   from unchecked self-consolidation."
2. **Sundial's own record.** `BOOTSTRAP.md`'s "What not to build" list opens with
   "A memory hierarchy before there is anything to remember." Apollo consumed
   four of six completed docket items over 12 days, produced three ADRs, and
   `APOLLO.md`'s two tiers are still empty. It is the clearest single instance of
   §2 layer 4 — capacity spent on the system's own machinery ahead of its output
   — and the most expensive thing in the corpus not to repeat.

---

## 6. New information / candidate wayfinder tickets

Things sundial surfaced that ryai-harness's map (issue #1, tickets #2–#6) does
not currently address. Each names its sundial source and the ryai-harness term or
research finding that makes it live.

### 6.1 There is no term for the layer above a Slice — candidate CONTEXT term + ticket
**From:** sundial `CONTEXT.md` **Workstream** ("a thread of related work that
outlives a single Cycle and is picked up again by later ones"), **Docket** ("the
ranked list of what Ryan wants worked next"), **Goal**; sundial ADR-0027.
**Live against:** ryai-harness `CONTEXT.md` **Plan** ("a decomposition of intent
into Slices") and **Slice**.

ryai-harness's glossary covers a Plan and the Slices it decomposes into, and
issue #1 notes that "the Plan/Slice/Test-Gate/Review-Gate state-machine's
implementation shape" is tabled for the spec phase. What no term covers is what
sits *above* a Plan: the standing thread work is drawn from, and the mechanism
by which the next Plan is chosen. Today that is Ryan, ad hoc, and at one
developer that is fine.

It is worth ticketing anyway, because §2 layer 4 is a failure exactly here:
sundial *had* this layer, and it filled with the system's own design debt,
consuming nearly all its throughput. The failure mode is not exotic and it is not
capacity-related — it is what happens when a queue can be fed by the system whose
throughput it governs. ryai-harness will acquire the same queue the moment
Trajectories start promoting into a Regression Suite and Slices start being drawn
from a backlog.

Suggested ticket: *Decide whether a term above Plan is needed, and what may feed
the queue a Plan is drawn from.* Sundial's Docket state machine (ADR-0027) is a
worked reference, including its two named recovery transitions and its insistence
that the claim be mechanical.

### 6.2 Precedence between the research report and the ADRs is unstated
**From:** sundial `docs/HERMES.md` — "Precedence, strictly. ADRs beat `CONTEXT.md`
beats this file" — plus its "where Sundial deliberately differs — do not 'fix'
these" table.
**Live against:** ryai-harness `docs/compass_artifact_*.md`, `CONTEXT.md`
**Seed**, and **open ticket #4**.

`docs/compass_artifact_*.md` sits in `docs/` with no stated relationship to the
ADRs, and issue #1's Notes instruct consulting it "before grilling any ticket on
this map" — so it is Seed material. There is already at least one live divergence:
the report's §G.2 recommends keeping native per-model tool parsers as the default
and constrained decoding as a reliability backstop, while ADR 0002 as written
says "output is constrained at the sampling layer so that malformed tool calls
cannot be generated." Ticket #4 exists to resolve exactly this — but until it
does, an agent given both documents in a Seed has no rule for which wins, and the
deviation looks like a defect to be fixed rather than a decision to be respected.

Suggested ticket (small): *Add a precedence header to the research report, and a
deviations table for any place an ADR knowingly departs from it.* Cheap, and it
directly protects ticket #4's eventual outcome from being "corrected" later.

### 6.3 The ADR-as-work-queue failure mode
**From:** sundial ADR-0027's own diagnosis — ADRs 0020, 0024, 0025, 0026 each
closed with a "left for the implementing Cycle" section, "which is exactly the
pattern Ryan flagged as making the ADR corpus read like a work queue."
**Live against:** ryai-harness `docs/agents/domain.md`, the research report §D
(Pocock's `/to-issues` decomposition and CONTEXT.md discipline), and the current
state of ryai-harness's own corpus.

ryai-harness is one step from the same shape. ADR 0002 carries an unresolved
amendment question that is now ticket #4; issue #1's Notes list two topics
"deliberately tabled, not ticketed here." Both are handled correctly today —
they went to the tracker, not into the ADR bodies — but the rule is implicit,
and sundial shows what happens when it slips: the corpus becomes the backlog, the
backlog is self-referential, and throughput recirculates.

Suggested ticket (small, arguably just a line in `docs/agents/domain.md`):
*An ADR records a decision and its consequences. Unresolved work goes to the
issue tracker, never into the ADR body.* Sundial's counterexample is the evidence.

### 6.4 Autonomy scope has no evidence ladder
**From:** sundial ADR-0004 (Grants).
**Live against:** ryai-harness `CONTEXT.md` **Slice** ("the largest amount of
work the system will attempt without a human in the loop") and **ADR 0003**
(adoption requires evidence).

`CONTEXT.md` fixes today's autonomy boundary but is silent on whether it can ever
move and on what would justify it. ryai-harness already has the *pattern* for
this in the Shortlist → Working Backend → adopted ladder — capability widens only
on accumulated evidence of that specific capability. ADR-0004 supplies the same
ladder pointed at autonomy scope rather than Backend choice, including narrow
named increments rather than bundled levels, and an automatic revocation trigger.

Suggested ticket: *Decide whether autonomy scope has an evidence ladder, and what
evidence would widen it* — most plausibly Trajectory-derived, which makes it
downstream of ADR 0003 rather than a new evidence source. Flagged as design-only:
sundial never issued a Grant, so this is an argued mechanism with no track record.

### 6.5 The Harness's own failure paths — how a denied or failed Tool Call is distinguished
**From:** sundial ADR-0023 and the journal's four `cycle_complete, commits: 0`
records.
**Live against:** ryai-harness **ADR 0002** ("the dominant failure mode shifts
from syntactic to semantic"), `CONTEXT.md` **Test Gate**, and the research
report's ReAct finding — the loop "mis-handles tool failures (often treats a
failed/empty tool result as success and reasons forward from it)" and "design
explicit failure paths for every tool call; don't assume the model will notice
failures."

Sundial ran the live version of this. Its first successful Cycle completed
cleanly, reported success, and produced zero commits: every `Write`, `Edit` and
mutating `Bash` call had been denied by Claude Code's permission mode before any
hook saw it, including writes to the one directory the design guarantees. The
agent's own report was internally consistent and entirely wrong about what had
happened. The diagnosis took a deliberate hook replay to reach, because the denial
looked like a policy failure and was a harness-mode failure.

ryai-harness owns the whole loop, so this is a decision it must make rather than
inherit. Two concrete questions:

- In the canonical Tool Call form (ADR 0002), how is a *denied* or *failed* tool
  result represented such that it cannot be read as an empty success? This is
  Adapter-adjacent and worth settling before the first Adapter is written.
- Can a Slice that produced no diff pass a Test Gate? Sundial's answer was yes,
  four times, and each cost a slot.

Suggested ticket, sized for the spec phase alongside issue #1's tabled
state-machine work.

### 6.6 Measured cost and cache behaviour — direct input to open tickets #3 and #6
**From:** sundial ADR-0028's measurements.
**Live against:** issue #1's **$100/mo budget ceiling**, `CONTEXT.md` **Trajectory**
("cost and duration"), and research §B (SGLang's RadixAttention advantage on long
shared prefixes).

Three findings from real runs, offered as inputs rather than conclusions —
sundial measured a different harness on a different provider, so they shortlist
rather than decide, in the same spirit `CONTEXT.md` applies to benchmarks:

1. **Cost tracked subagent fan-out, not turns or commits.** Three Cycles at
   $1.16 / 0 commits, $1.46 / 2 commits, $4.33 / 3 commits, with the expensive
   one making 6 Skeptic calls against 0 and 1. `CONTEXT.md`'s **Trajectory**
   already records cost, but nothing yet decides how cost incurred by a
   *secondary* call — a reviewer pass, an Adapter retry — is attributed to the
   Slice that caused it. With a $100/mo ceiling this matters early.
2. **A large fixed prefix is cheap when caching works.** Cache-read to
   cache-creation ran 10–20:1 across all three runs, making a ~28.5K-token
   mandatory preamble a one-time write per run rather than a per-turn tax. That
   is real measured support for `CONTEXT.md`'s **Seed** decision ("deliberately
   generous — tokens are cheaper than turns"), and it is the same property
   SGLang's RadixAttention is claimed to exploit — directly relevant to open
   ticket #3's SGLang-vs-vLLM choice, whose stated workload shape is exactly
   "long, repeated system prompts."
3. **A growing trace re-read from position zero compounds quadratically.** Each
   reviewer invocation re-read the trace from the start, so the Nth call re-read
   the previous N−1 calls' own output — and, worse, anchored on its own prior
   verdicts. Relevant to how Trajectories are handed to any reviewer pass:
   scope by explicit range, and never let a reviewer read its own prior output.

### 6.7 Sundial predicted its own vendor-lock trap and could not act on it
**From:** sundial `docs/GOALS.md` intention 9, captured verbatim from Ryan
2026-08-21: "an ongoing plan to migrate off the Anthropic ecosystem — Hermes on
open models, or similar," annotated in GOALS itself: "what does not exist is any
portability constraint on new work; every decision so far assumes Claude Code,
launchd and MCP. If this matters, it is cheaper as a standing constraint than as
a later migration."
**Live against:** ryai-harness `CONTEXT.md` **Harness** and **Vendor Lock**.

Not a ticket. Recorded because it is the strongest available evidence that
ryai-harness's founding decision is the right one, and that it was reached the
expensive way. Sundial named the constraint on 2026-08-21, declined to adopt it
as a standing rule, and by 2026-09-03 had thirty ADRs of design whose runtime is
unportable — §5.1. ryai-harness's `CONTEXT.md` makes that constraint the first
definition in the glossary. That is the correct correction, and it is worth
keeping the receipt: a portability constraint is cheap as a rule and expensive as
a migration.
