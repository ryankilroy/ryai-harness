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

Both are schemas only (issue #11): no agent loop, Adapters, Sandbox, or
Test Gate live here yet (see spec #10 and its child issues).
