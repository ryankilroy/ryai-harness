# ryai-harness

The Harness — see `CONTEXT.md` for the glossary and `docs/adr/` for the
decisions behind it.

## Development

Requires Python 3.12+. From a fresh clone:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Four commands, all run clean on a fresh clone:

```sh
.venv/bin/pytest
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy --strict src
```

`mypy --strict` is scoped to `src` (the `ryai_harness` package). It does
not cover `tests/`, and it deliberately does not cover
`tests/fixtures/tool_result_missing_outcome.py` — that file is a
deliberately-invalid construction that `tests/test_mypy_strict_rejects_missing_outcome.py`
runs `mypy --strict` against directly, as a subprocess, to prove that
constructing a `ToolResult` without `outcome` is statically rejected.

## Package layout

- `src/ryai_harness/tool_call.py` — canonical Tool Call schema.
- `src/ryai_harness/tool_result.py` — canonical Tool Result schema
  (`Outcome`, `DeniedKind`, `ToolResult`).
- `src/ryai_harness/regression_suite.py` — Regression Suite eligibility
  (`is_eligible_for_promotion`, `eligible_trajectories`) and the ADR 0006
  promotion check (`check_promotion`, `PromotionVerdict`).
- `src/ryai_harness/working_backend.py` — Working Backend: wiring a
  Backend in (`wire_in_working_backend`) vs promoting one on Regression
  Suite evidence (`promote_backend`), as two distinct operations
  (`WorkingBackend`, `PromotionBasis`).

This list has fallen behind `src/ryai_harness/` before (`sandbox.py`
and `trajectory.py` from issues #14/#16 are not listed above either);
fixing that wholesale is outside this ticket's Blast Radius.
