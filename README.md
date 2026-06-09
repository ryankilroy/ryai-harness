# ryai-harness

The **system** that builds I Am Grem — not the product. Phase 2 of the build plan:
one stochastic agent running behind the deterministic gate floor in `../i-am-grem`.

Your attention is spent in exactly two places: **approving the plan** and **handling
an escalation**. Everything else is the gates' job.

## The loop
```
feature request
  → Planner   (Claude API, proprietary)   spec + ordered task list
  → YOU approve the plan                   ← supervision point #1
  → Implementer (OpenRouter, OSS per-token) writes a diff per task
  → Gate floor runs (npm run gate)         the ONLY judge of correctness
  → fails? capped retry with the failure fed back
  → still stuck? ESCALATE to you           ← supervision point #2
  → all green? commit branch → your PR + merge queue
```

## Run it
```bash
cp .env.example .env        # fill in keys + point PRODUCT_REPO at the a local git-repo
pip install -e .
ryai-harness "Add a blah to the blah"
```

## Stack & cost (Phase 2)
| Role | Service | Model (default) | Cost posture |
|------|---------|-----------------|--------------|
| Planning | Anthropic Claude API | `claude-sonnet-4-6` | the one assumed fixed cost; ~CAD $20–50/mo at practice volume |
| Execution | OpenRouter (per-token) | `deepseek/deepseek-chat` | pay-per-use, ~CAD $1–2/feature |

**Triggers (don't change a model without one):**
- Downgrade planning → skip the Claude call for trivial/templated features.
- Upgrade planning → only if specs repeatedly produce diffs the executor can't satisfy.
- Upgrade execution → only when gate-pass rate is too low; that's the Phase 3 escalation tier, not a Phase 2 change.

## Safety caps
`MAX_RETRIES` and `MAX_CAD_PER_FEATURE` bound how far the loop runs before it must
escalate. The harness never merges on its own — it commits a branch; your gates +
merge queue decide what lands.

## Self-gates
The harness has its own gate floor so it's as trustworthy as what it builds:
```bash
python -m pytest -q
```
Covers the gate runner, diff application, and the full loop (green / escalate /
plan-rejected) via a mock provider — no keys or network needed.

## NOT built yet (Phase 3+, each with its trigger)
- **Separate decomposer + verifier roles / model tiering** — add when the single
  executor's gate-pass rate data justifies splitting the work.
- **Always-on control plane + ephemeral execution (VPS, Tailscale)** — Phase 4, when
  you want the loop running off your laptop and drivable from any machine.
- **Parallel multi-project orchestration** — Phase 5, when a second project is ready.
- **Auto PR creation / merge-queue integration via `gh`** — add once you've watched
  the branch-handoff work by hand a few times.
