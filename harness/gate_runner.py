"""Runs the product repo's deterministic gate command. This is the harness's only
source of truth about correctness — it never trusts model output, only the gates."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass


@dataclass
class GateResult:
    passed: bool
    output: str

    @property
    def summary(self) -> str:
        return "PASS" if self.passed else "FAIL"


def run_gates(repo_path: str, gate_command: str) -> GateResult:
    proc = subprocess.run(
        gate_command, shell=True, cwd=repo_path,
        capture_output=True, text=True,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    return GateResult(passed=proc.returncode == 0, output=combined.strip())
