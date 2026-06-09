"""The harness's own gate: prove the loop's control flow end-to-end with a mock
provider, no keys, no network. Covers the green path, the escalation path, and the
operator-rejects-plan path."""

import json
import os
import subprocess
import tempfile

from harness.config import Config
from harness.orchestrator import run_feature
from harness.providers.mock import MockProvider


def _repo(d):
    subprocess.run(["git", "-C", d, "init", "-q"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", d, "config", "user.name", "t"], check=True)
    open(os.path.join(d, "seed.txt"), "w").write("seed\n")
    subprocess.run(["git", "-C", d, "add", "-A"], check=True)
    subprocess.run(["git", "-C", d, "commit", "-qm", "seed"], check=True)


def _cfg(d, gate="true", retries=2):
    return Config(
        anthropic_api_key="x",
        planning_model="m",
        openrouter_api_key="x",
        executor_model="m",
        product_repo=d,
        gate_command=gate,
        max_retries=retries,
        max_cad_per_feature=2.0,
    )


_PLAN = json.dumps(
    {
        "spec_filename": "specs/0002-demo.md",
        "spec_markdown": "---\nid: 0002\nstatus: ready\n---\n# demo\n- [ ] do the thing\n",
        "tasks": ["create hello.txt"],
    }
)

_DIFF = (
    "diff --git a/hello.txt b/hello.txt\nnew file mode 100644\n"
    "--- /dev/null\n+++ b/hello.txt\n@@ -0,0 +1 @@\n+hi\n"
)


def test_green_path_reaches_merge_ready():
    with tempfile.TemporaryDirectory() as d:
        _repo(d)
        planner = MockProvider(lambda s, u: _PLAN)
        executor = MockProvider(lambda s, u: _DIFF)
        out = run_feature(
            _cfg(d, gate="true"),
            planner,
            executor,
            "demo feature",
            approval=lambda plan: True,
        )
        assert out.status == "merged_ready", out.detail
        assert os.path.exists(os.path.join(d, "hello.txt"))


def test_red_gates_escalate_after_retries():
    with tempfile.TemporaryDirectory() as d:
        _repo(d)
        planner = MockProvider(lambda s, u: _PLAN)
        executor = MockProvider(lambda s, u: _DIFF)
        out = run_feature(
            _cfg(d, gate="false", retries=1),
            planner,
            executor,
            "demo feature",
            approval=lambda plan: True,
        )
        assert out.status == "escalated"
        assert out.attempts == 2  # initial + 1 retry


def test_operator_can_reject_plan():
    with tempfile.TemporaryDirectory() as d:
        _repo(d)
        planner = MockProvider(lambda s, u: _PLAN)
        executor = MockProvider(lambda s, u: _DIFF)
        out = run_feature(
            _cfg(d), planner, executor, "demo feature", approval=lambda plan: False
        )
        assert out.status == "rejected_plan"
