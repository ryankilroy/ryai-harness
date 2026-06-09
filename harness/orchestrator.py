"""Phase 2 loop: plan -> OPERATOR APPROVAL -> implement -> run gates -> capped retry
-> open PR or escalate. The two — and only two — places your attention is spent are
the plan approval and an escalation. Everything green flows to the gates automatically."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Callable

from .config import Config
from .providers.base import Provider
from .roles.planner import make_plan, Plan
from .roles.implementer import implement
from .gate_runner import run_gates, GateResult
from . import patch


@dataclass
class Outcome:
    status: str                      # "merged_ready" | "escalated" | "rejected_plan"
    plan: Plan | None = None
    detail: str = ""
    gate_log: str = ""
    attempts: int = 0
    events: list[str] = field(default_factory=list)


# approval/escalation are injected so the loop is testable and UI-agnostic
ApprovalFn = Callable[[Plan], bool]


def _cli_approval(plan: Plan) -> bool:
    print("\n=== PLAN FOR YOUR APPROVAL ===")
    print(f"spec: {plan.spec_filename}")
    print(plan.spec_markdown)
    print("tasks:")
    for i, t in enumerate(plan.tasks, 1):
        print(f"  {i}. {t}")
    return input("\nApprove this plan? [y/N] ").strip().lower() == "y"


def run_feature(
    cfg: Config,
    planner_provider: Provider,
    executor_provider: Provider,
    feature_request: str,
    approval: ApprovalFn = _cli_approval,
    branch: str = "harness/feature",
) -> Outcome:
    events: list[str] = []

    # 1. Plan (proprietary model) — judgment-heavy step
    plan = make_plan(planner_provider, feature_request)
    events.append(f"planned: {plan.spec_filename}, {len(plan.tasks)} task(s)")

    # 2. Operator approval — supervision point #1
    if not approval(plan):
        return Outcome(status="rejected_plan", plan=plan,
                       detail="operator declined the plan", events=events)

    # 3. Write the spec into the product repo and branch
    patch.start_branch(cfg.product_repo, branch)
    spec_path = os.path.join(cfg.product_repo, plan.spec_filename)
    os.makedirs(os.path.dirname(spec_path), exist_ok=True)
    with open(spec_path, "w") as f:
        f.write(plan.spec_markdown)
    events.append(f"spec written to {plan.spec_filename}")

    # 4. Implement tasks; gates are the only judge; capped retry on failure
    last_gate: GateResult | None = None
    attempts = 0
    for task in plan.tasks:
        last_failure = None
        for attempt in range(cfg.max_retries + 1):
            attempts += 1
            diff = implement(executor_provider, plan.spec_markdown, task, last_failure)
            ok, msg = patch.apply_diff(cfg.product_repo, diff)
            if not ok:
                last_failure = f"diff did not apply: {msg}"
                events.append(f"task '{task}' attempt {attempt+1}: {last_failure}")
                continue
            last_gate = run_gates(cfg.product_repo, cfg.gate_command)
            events.append(f"task '{task}' attempt {attempt+1}: gates {last_gate.summary}")
            if last_gate.passed:
                break
            last_failure = last_gate.output
        else:
            # exhausted retries on this task -> escalate (supervision point #2)
            return Outcome(status="escalated", plan=plan, attempts=attempts,
                           detail=f"stuck on task: {task}",
                           gate_log=last_gate.output if last_gate else "",
                           events=events)

    # 5. All tasks green -> commit; PR opening left to CI/gh in the operator's hands
    patch.commit_all(cfg.product_repo, f"feat: {feature_request[:60]}")
    events.append("all tasks passed gates; branch committed")
    return Outcome(status="merged_ready", plan=plan, attempts=attempts,
                   detail="branch ready for PR + merge queue",
                   gate_log=last_gate.output if last_gate else "", events=events)
