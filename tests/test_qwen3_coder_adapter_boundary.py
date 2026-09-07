"""Boundary test (issue #13, CONTEXT.md's Adapter definition): nothing
outside the Qwen3-Coder Adapter may reference this Backend's wire shapes.
An actual grep over the source tree, run as a test, so this keeps holding
as the codebase grows rather than being a one-off audit that rots.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "ryai_harness"
ADAPTER_FILE = SRC / "adapters" / "qwen3_coder.py"

# Case-insensitive tokens that only the Qwen3-Coder Adapter is allowed to
# know about: the dialect's literal markers, the model/parser family
# name, and the SGLang structural-tag mechanism name this Adapter uses to
# scope constrained decoding.
BANNED_TOKENS = [
    "<tool_call>",
    "<function=",
    "<parameter=",
    "qwen3_coder",
    "qwen",
    "structural_tag",
]


def _source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p != ADAPTER_FILE)


def test_adapter_file_itself_uses_a_banned_token() -> None:
    # Proves the scan below is actually looking at live content and isn't
    # vacuously true forever -- if this ever fails, the token list or the
    # adapter's own path has drifted and the boundary test needs updating,
    # not silently passing.
    text = ADAPTER_FILE.read_text().lower()

    assert any(token.lower() in text for token in BANNED_TOKENS)


def test_no_module_outside_the_adapter_references_the_qwen3_coder_dialect() -> None:
    offenders = []
    for path in _source_files():
        text = path.read_text().lower()
        for token in BANNED_TOKENS:
            if token.lower() in text:
                offenders.append((str(path.relative_to(REPO_ROOT)), token))

    assert not offenders, (
        "a Qwen3-Coder-specific shape leaked outside its Adapter "
        f"(src/ryai_harness/adapters/qwen3_coder.py): {offenders}"
    )
