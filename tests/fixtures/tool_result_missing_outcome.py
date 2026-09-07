"""Deliberately-invalid construction, used only by the subprocess-driven
mypy test in tests/test_mypy_strict_rejects_missing_outcome.py.

This file is NOT a pytest test module (pytest's default `test_*.py`
collection pattern skips it) and is excluded from the project's own
`mypy --strict src` run via pyproject.toml's `[tool.mypy] exclude`, so this
one deliberate type error never breaks the clean strict run over the real
package. `mypy --strict` is instead pointed at this file directly, as an
explicit argument, by the test that asserts it fails.
"""

from ryai_harness.tool_result import DeniedKind, ToolResult

# `outcome` is the one required field with no default (ADR 0002) --
# omitting it here is exactly what mypy --strict must reject.
bad_result = ToolResult(kind=DeniedKind.REJECTED, reason="missing outcome")
