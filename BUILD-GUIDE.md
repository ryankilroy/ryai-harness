# Guided rebuild: the ryai harness, one piece at a time

The goal of this rebuild is **understanding, not speed**. An autonomous agent already
built a working Phase 2 harness — it lives, complete with its tests, on the
`reference/autonomous-build` branch. You're going to rebuild it yourself on `main`,
milestone by milestone, so that every line on `main` is something you understand and
chose. Peek at the reference whenever you want:

```bash
git show reference/autonomous-build:harness/orchestrator.py
# or check the whole thing out side-by-side:
git worktree add ../ryai-harness-reference reference/autonomous-build
```

## The big picture (from solo-consultancy-plan.html)

The paradigm: **stochastic agents inside a deterministic harness**. Models write
code; they are never trusted. The only judge of correctness is a deterministic gate
command (lint + typecheck + tests + spec-conformance) in the *product* repo. The
harness's job is to run the loop:

```
feature request
  → Planner (Claude, pay-per-use)        produces spec + ordered task list
  → YOU approve the plan                  ← supervision point #1
  → Implementer (cheap OSS model)         writes a unified diff per task
  → Gate command runs                     the ONLY judge of correctness
  → red? feed the failure back, capped retry
  → still red? ESCALATE to you            ← supervision point #2
  → all green? commit the branch — a human PR + merge queue decides what lands
```

Your attention is spent in exactly two places. Everything else is automated and
gated. The harness **never merges**.

## Rules for the rebuild

1. **Gates first, every time.** Each milestone ends with a runnable test. A component
   without a test that you've watched fail is not done. This is the plan's "single
   biggest risk" callout applied to the harness itself.
2. **Write the code yourself.** Ask Claude to explain, review, or pair — but type the
   implementation. The reference branch is your answer key, not your source.
3. **Stdlib only** (no SDKs, HTTP via `urllib`). This was a deliberate decision in the
   reference build: no vendor lock-in while the shape is still moving, and nothing to
   install means the harness runs anywhere Python 3.10+ runs.
4. One milestone per sitting is plenty. Each is sized to be understood, not just finished.

---

## Milestone 0 — Verify the floor you're standing on

**Why first:** the plan's biggest-risk callout says building orchestration on top of
an aspirational gate burns all your time debugging agent behavior instead of trusting
the harness. The autonomous build *assumed* `../i-am-grem` has a working
`npm run gate` — it never checked. You check.

**Do:**
1. In the product repo (`../i-am-grem`), run the gate command by hand. Confirm it
   exits 0 when the repo is healthy.
2. Break something on purpose (a failing test, a type error). Confirm the gate exits
   nonzero and the failure output is readable. *A gate you haven't watched fail is
   not a gate.*
3. Revert the breakage.

**Exit:** you can state the exact gate command, and you've seen it both pass and fail.

---

## Milestone 1 — Project skeleton + config

**Concepts:** `pyproject.toml` entry points; frozen dataclasses; 12-factor config
(everything tunable comes from env vars, so the same code runs on any machine —
this directly serves the plan's Phase 4 "no local state that matters" goal).

**Do:**
1. Create `pyproject.toml` with the project metadata, an empty dependency list, a
   `ryai-harness` console script, and pytest config.
2. Create `harness/config.py`: a frozen `Config` dataclass with a `from_env()`
   constructor. Fields: the two API keys, the two model names, `product_repo`,
   `gate_command`, `max_retries`, `max_cad_per_feature`.
3. Create `.env.example` documenting every variable and *why you'd change it*.
4. `pip install -e .` and confirm `python -c "from harness.config import Config"` works.

**Decide as you go** (the reference got this wrong — three files disagree):
pick ONE default planning model and use it consistently everywhere.

**Reference:** `harness/config.py`, `.env.example`, `pyproject.toml`.

---

## Milestone 2 — The gate runner

**Concepts:** `subprocess.run` with `shell=True` and `cwd`; exit codes as the
universal pass/fail contract; capturing stdout+stderr so failures can be fed back to
a model verbatim.

**Why this is the heart:** this ~20-line module is the entire trust model. The
harness never evaluates code quality itself — it runs this and believes the exit code.

**Do:**
1. `harness/gate_runner.py`: a `GateResult(passed, output)` dataclass and a
   `run_gates(repo_path, gate_command) -> GateResult` function.
2. `tests/test_gate_runner.py`: one test where the command is `true` (passes), one
   where it's `echo boom >&2; false` (fails AND the output contains "boom").
3. `python -m pytest -q` — watch them pass. Then break the implementation on purpose
   and watch them fail. Fix it.

**Exit:** tests green, and you can explain why combined stdout+stderr matters
(the retry loop feeds it back to the implementer model).

**Reference:** `harness/gate_runner.py`, `tests/test_gate_runner.py`.

---

## Milestone 3 — Patch application (git plumbing)

**Concepts:** unified diff format; `git apply`; `git checkout -B` for disposable
branches; why the harness applies diffs instead of letting a model write files
directly (a diff is reviewable, bounded, and rejectable as a unit).

**Do:**
1. `harness/patch.py` with three functions:
   - `start_branch(repo, branch)` — `git checkout -B`
   - `apply_diff(repo, diff_text) -> (ok, message)` — write the diff to a temp file,
     `git apply` it, reject empty diffs before touching git
   - `commit_all(repo, message)`
2. `tests/test_patch.py`: build a throwaway git repo in a `tempfile.TemporaryDirectory`
   (init, config user, seed commit — you'll reuse this helper in milestone 6), then
   test a new-file diff applies and an empty/whitespace diff is rejected.
3. Hand-write a small unified diff yourself at least once so the format isn't magic.

**Known reference flaw to think about now:** the reference never *resets* the working
tree between retry attempts, so a failed attempt's changes stay on disk and the next
diff is applied on top — "every attempt is isolated" was claimed but not implemented.
Add a `reset_branch(repo)` (e.g. `git checkout -- .` + `git clean -fd`) so milestone 6
can use it.

**Reference:** `harness/patch.py`, `tests/test_patch.py`.

---

## Milestone 4 — The provider abstraction + mock

**Concepts:** `typing.Protocol` (structural typing — the orchestrator depends on a
shape, not a class); why the *mock* is the most important provider (it makes the
whole loop testable offline, no keys, no network, no flakiness).

**Do:**
1. `harness/providers/base.py`: a `Completion(text, usd_cost)` dataclass and a
   `Provider` protocol with one method: `complete(system, user) -> Completion`.
2. `harness/providers/mock.py`: `MockProvider(responder)` — calls a function you
   supply, records every call in a `.calls` list so tests can assert on prompts.

**Exit:** you can explain why `usd_cost` lives on `Completion` (it's how the
per-feature spend cap gets its data) and why the orchestrator will never import
`ClaudeProvider` directly.

**Reference:** `harness/providers/base.py`, `harness/providers/mock.py`.

---

## Milestone 5 — The two roles (planner, implementer)

**Concepts:** role = prompt + output contract, nothing more; the two-tier model
split (judgment-heavy planning on the proprietary model, high-frequency well-scoped
implementation on the cheap per-token model — this is the plan's core cost posture);
structured output via "return ONLY JSON" + `json.loads`.

**Do:**
1. `harness/roles/planner.py`: a `Plan(spec_filename, spec_markdown, tasks)`
   dataclass and `make_plan(provider, feature_request) -> Plan`. The system prompt
   demands strict JSON with those three keys; the spec follows the product repo's
   spec template; tasks are atomic and ordered.
2. `harness/roles/implementer.py`: `implement(provider, spec_markdown, task,
   last_failure) -> str`. System prompt: return ONLY a `git apply`-compatible unified
   diff. On retries, the previous gate failure is appended to the user message —
   that's the entire feedback mechanism.

**Improve on the reference:** `make_plan` does a bare `json.loads` — if the model
adds prose or code fences, the harness crashes with a traceback instead of failing
gracefully. Strip fences / extract the JSON object defensively, and decide what a
parse failure should do (it shouldn't be an uncaught exception).

**Reference:** `harness/roles/planner.py`, `harness/roles/implementer.py`.

---

## Milestone 6 — The orchestrator (the loop itself)

**Concepts:** the whole Phase 2/3 control flow in one function; dependency injection
of the approval prompt (an `ApprovalFn` callable, so tests pass `lambda p: True` and
the CLI passes an `input()` prompt); `for/else` for "retries exhausted"; the three
terminal states.

**Do:**
1. `harness/orchestrator.py`: `run_feature(cfg, planner_provider, executor_provider,
   feature_request, approval, branch) -> Outcome` where `Outcome` carries
   `status` (`merged_ready` | `escalated` | `rejected_plan`), the plan, attempt
   count, last gate log, and an `events` list (your audit trail).
   The sequence: plan → approval gate → branch + write spec → per task: capped
   attempts of (reset tree → implement → apply diff → run gates) → all green:
   commit; any task exhausts retries: escalate.
2. **Enforce the spend cap here** — the reference never did, despite the README
   claiming it. Accumulate `usd_cost` across every completion; if it crosses
   `max_cad_per_feature`, stop and escalate with a clear reason. (Note the currency
   mismatch you'll need to resolve: providers report USD, the cap is named CAD.)
3. `tests/test_orchestrator_dryrun.py` — the harness's own gate floor, all with
   `MockProvider` and gate commands of `true`/`false`:
   - green path → `merged_ready`, the new file exists in the temp repo
   - failing gates → `escalated` with exactly `max_retries + 1` attempts
   - approval returns False → `rejected_plan`
   - *(beyond the reference)* a diff that fails to apply consumes a retry
   - *(beyond the reference)* spend cap exceeded → escalates

**Exit:** all tests green offline. This is the milestone where the whole paradigm
clicks — take your time.

**Reference:** `harness/orchestrator.py`, `tests/test_orchestrator_dryrun.py`.

---

## Milestone 7 — Real providers (Claude + OpenRouter)

**Concepts:** the Anthropic Messages API and the OpenAI-compatible chat-completions
shape, raw over `urllib.request` (headers, JSON bodies, timeouts); reading `usage`
from responses to compute real cost.

**Do:**
1. `harness/providers/claude.py`: POST to `/v1/messages` with `x-api-key` +
   `anthropic-version` headers; join the text blocks; compute `usd_cost` from
   `usage` — and **look up the current per-MTok rates for the model you actually
   chose in milestone 1** (the reference hardcoded Sonnet-ish rates under an Opus
   default, understating cost ~5×).
2. `harness/providers/openrouter.py`: same shape, `Authorization: Bearer` header.
   The reference returns `usd_cost=0.0` here, which silently exempts the executor
   from the spend cap — OpenRouter returns usage (and supports cost in the
   response); wire up a real best-effort number.
3. Handle HTTP errors deliberately: a 429/500 should surface as a clean failure,
   not an uncaught traceback (the plan budgets your attention for two interrupts,
   not "Python died").
4. Smoke-test each provider with a tiny real call (this is the one step that costs
   actual cents).

**Reference:** `harness/providers/claude.py`, `harness/providers/openrouter.py`.

---

## Milestone 8 — CLI, CI, and the first real run

**Do:**
1. `harness/cli.py`: parse the feature request, check keys, build the two real
   providers, call `run_feature` with an interactive approval prompt, print the
   outcome + event log. Exit 0 for `merged_ready`/`rejected_plan`, 1 for `escalated`.
   *(Improve on the reference: derive a unique branch name per feature —
   the reference hardcodes `harness/feature` and clobbers the previous run.)*
2. `.github/workflows/harness-gates.yml`: run `pytest -q` on PR, merge_group, and
   push to main. The harness gates itself.
3. Write your own `README.md` — in your words, and *consistent with the code*
   (the reference README oversold safety features that weren't wired up; don't
   document what doesn't exist).
4. Run one real feature end-to-end against the practice repo:
   `ryai-harness "Add a small, real thing"`. Watch the plan arrive, approve it,
   watch the gates run, review the branch it commits. Per the plan's Phase 2
   attention budget: review *everything* — you're buying calibration data.

**Exit:** one merged, gate-passing feature went through the loop, and you understood
every step it took.

---

## After the rebuild: where this sits in the 5-phase plan

You'll have completed **Phase 2** (one agent behind the gates) with several of the
reference build's gaps fixed. What comes next, each with its trigger from the plan:

| Phase | What | Trigger — don't build before it fires |
|---|---|---|
| 3 | Split executor into decomposer / implementer / verifier; tier models; escalation tier | Several merged features + per-task-type gate-pass-rate data showing where the cheap model fails |
| 4 | Always-on VPS control plane + Tailscale; laptop becomes a dumb terminal | Phase 3 loop reliably lands-or-escalates and you want it off your laptop |
| 5 | Intake template + parallel multi-project orchestration | A second project is ready |
| — | Auto-PR via `gh`, agent frameworks, GPU rental, dashboards | See the defer table in solo-consultancy-plan.html |

Track from your very first real run: **what fraction of tasks clear the gates on the
cheap model alone**. That single number is the trigger for nearly everything in Phase 3.
