"""Static-typing half of "ToolResult.outcome is mandatory" (issue #11,
ADR 0002).

Whether `mypy --strict` rejects a particular construction is not
observable through an ordinary pytest assertion -- there is no runtime
value to inspect, only a compile-time diagnostic. So this test shells out
to mypy itself (stdlib subprocess; no test dependency beyond mypy, which
the project already depends on for its own strict run) against a small
fixture file containing the deliberately-bad construction, and asserts
that mypy rejects it for the expected reason.

The fixture lives at tests/fixtures/tool_result_missing_outcome.py and is
excluded from the project's own `mypy --strict src` run (see
pyproject.toml's `[tool.mypy] exclude`) precisely so this one deliberate
error doesn't make that run permanently red.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "tool_result_missing_outcome.py"


def test_mypy_strict_rejects_tool_result_missing_outcome() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(FIXTURE)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert proc.returncode != 0, (
        "mypy --strict accepted a ToolResult construction with `outcome` "
        f"omitted (it must not):\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "[call-arg]" in proc.stdout, (
        "expected mypy's missing-argument diagnostic (call-arg); got:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "outcome" in proc.stdout, (
        f"expected the diagnostic to name `outcome`; got:\n{proc.stdout}"
    )
