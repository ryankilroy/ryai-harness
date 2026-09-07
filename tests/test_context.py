"""Tests for context assembly (issue #15, ADR 0004, CONTEXT.md).

External behaviour only: given a construction or an assembled request,
expect this value, this failure, or this API shape. No test here reaches
into the implementation's internals or asserts on how assembly is done
internally — only on the preamble/Slice boundary property RadixAttention
actually depends on, and on the type shapes that make interleaving
inexpressible.

This suite is written as a stub-plus-tests seam (per issue #15), not the
usual TDD vertical slice: the module stub in src/ryai_harness/context.py
defines signatures and types with bodies raising NotImplementedError,
and a separate implementation agent fills them in. Structural tests below
(dataclass shape / signature introspection, and AssembledRequest's
computed properties, which are implemented in the stub itself) pass now;
behavioural tests that call assemble_preamble/assemble_request currently
fail on NotImplementedError, which is the expected red.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

from ryai_harness.context import (
    AssembledRequest,
    BlastRadius,
    Plan,
    SliceContext,
    ToolSchema,
    TrajectoryStep,
    assemble_preamble,
    assemble_request,
)
from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import Outcome, ToolResult

REPO_ROOT = Path(__file__).resolve().parents[1]


def _slice_context(
    *,
    blast_radius_files: tuple[str, ...] = ("src/example.py",),
    plan_text: str = "Slice 1 of 3: do the thing.",
    trajectory: tuple[TrajectoryStep, ...] = (),
    tool_schemas: tuple[ToolSchema, ...] = (),
) -> SliceContext:
    return SliceContext(
        blast_radius=BlastRadius(files=blast_radius_files),
        plan=Plan(text=plan_text),
        trajectory=trajectory,
        tool_schemas=tool_schemas,
    )


# --- AssembledRequest: boundary/full_bytes are computed, not stored -------
# These pass now: the stub implements this concatenation itself (per the
# ticket, "encode it in the stub you lay down"), so this is not waiting on
# the implementation agent.


def test_boundary_is_the_length_of_the_preamble_region() -> None:
    request = AssembledRequest(preamble_bytes=b"abc", slice_bytes=b"defgh")

    assert request.boundary == 3


def test_full_bytes_is_preamble_then_slice_and_nothing_else() -> None:
    request = AssembledRequest(preamble_bytes=b"abc", slice_bytes=b"defgh")

    assert request.full_bytes == b"abcdefgh"
    assert request.full_bytes[: request.boundary] == b"abc"
    assert request.full_bytes[request.boundary :] == b"defgh"


def test_assembled_request_has_no_field_to_reorder_or_interleave() -> None:
    # AssembledRequest carries exactly the two regions, nothing that could
    # parameterise concatenation order (no "order", "interleaved", etc.).
    field_names = {f.name for f in dataclasses.fields(AssembledRequest)}

    assert field_names == {"preamble_bytes", "slice_bytes"}


# --- Hard error by API shape, not convention -------------------------------


def test_assemble_request_has_no_parameter_for_raw_preamble_content() -> None:
    # The only content parameter is `slice_context: SliceContext`; there is
    # no second parameter (str/bytes/Preamble) a caller could use to place
    # Slice-varying text into the preamble region.
    signature = inspect.signature(assemble_request)
    params = signature.parameters

    assert "slice_context" in params
    non_repo_root_params = [name for name in params if name != "repo_root"]

    assert non_repo_root_params == ["slice_context"]


def test_slice_context_has_no_field_shaped_to_carry_a_preamble() -> None:
    # Nominal separation: checked as a substring on every field's type
    # string (not set-membership against the whole type string, which
    # would pass even if a field really were typed Preamble) — this is
    # what rules out a SliceContext smuggling a Preamble value into the
    # Slice region via a type-compatible field.
    field_names = {f.name for f in dataclasses.fields(SliceContext)}

    assert field_names == {"blast_radius", "plan", "trajectory", "tool_schemas"}
    assert "preamble" not in field_names

    field_types = {f.name: f.type for f in dataclasses.fields(SliceContext)}
    for name, type_str in field_types.items():
        assert "Preamble" not in type_str, f"{name} field type {type_str!r} names Preamble"


# --- Preamble/Slice boundary is well-defined --------------------------------


def test_assembled_request_exposes_a_well_defined_boundary() -> None:
    request = assemble_request(_slice_context())

    assert isinstance(request.boundary, int)
    assert request.boundary == len(request.preamble_bytes)
    assert request.full_bytes[: request.boundary] == request.preamble_bytes
    assert request.full_bytes[request.boundary :] == request.slice_bytes

    # A real property of assemble_request, not implied by AssembledRequest's
    # construction: for a non-empty SliceContext, the Slice region actually
    # landed in slice_bytes rather than being silently dropped (which would
    # also satisfy the boundary/full_bytes assertions above, vacuously, by
    # putting the boundary at the very end).
    assert len(request.preamble_bytes) > 0
    assert len(request.slice_bytes) > 0


# --- The preamble is byte-identical across Slices with different Blast Radii


def test_preamble_is_byte_identical_across_two_slices_with_different_blast_radii() -> None:
    request_a = assemble_request(_slice_context(blast_radius_files=("src/a.py",)))
    request_b = assemble_request(
        _slice_context(blast_radius_files=("src/completely_different_b.py", "docs/x.md"))
    )

    assert request_a.preamble_bytes == request_b.preamble_bytes


# --- The first differing byte falls at or after the end of the preamble ----


def test_first_differing_byte_between_two_slices_is_at_or_after_the_boundary() -> None:
    request_a = assemble_request(
        _slice_context(blast_radius_files=("src/a.py",), plan_text="Plan A: touch a.py.")
    )
    request_b = assemble_request(
        _slice_context(
            blast_radius_files=("src/b.py", "src/c.py"),
            plan_text="Plan B: touch b.py and c.py, an entirely different plan.",
        )
    )

    assert request_a.boundary == request_b.boundary
    boundary = request_a.boundary

    a_bytes, b_bytes = request_a.full_bytes, request_b.full_bytes
    assert a_bytes != b_bytes  # otherwise the assertion below is vacuous

    first_diff = next(
        (i for i, (x, y) in enumerate(zip(a_bytes, b_bytes, strict=False)) if x != y),
        min(len(a_bytes), len(b_bytes)),  # one is a strict prefix of the other
    )

    assert first_diff >= boundary


# --- Blast Radius, Plan, Trajectory-so-far appear strictly in the Slice region
#
# Each test below asserts a pair: marker present in slice_bytes, and marker
# absent from preamble_bytes. Keep both halves together — the "absent from
# preamble_bytes" half alone is satisfiable vacuously (e.g. by an
# implementation that drops the Slice content entirely, landing it nowhere);
# the "present in slice_bytes" half is what rules that out.


def test_blast_radius_appears_strictly_in_the_slice_region() -> None:
    marker = "BLAST-RADIUS-MARKER-b7e1c9"
    request = assemble_request(_slice_context(blast_radius_files=(f"src/{marker}.py",)))

    assert marker.encode("utf-8") in request.slice_bytes
    assert marker.encode("utf-8") not in request.preamble_bytes


def test_plan_appears_strictly_in_the_slice_region() -> None:
    marker = "PLAN-MARKER-4f2a90"
    request = assemble_request(_slice_context(plan_text=f"Do the thing. {marker}"))

    assert marker.encode("utf-8") in request.slice_bytes
    assert marker.encode("utf-8") not in request.preamble_bytes


def test_trajectory_so_far_appears_strictly_in_the_slice_region() -> None:
    marker = "TRAJECTORY-MARKER-9d1e33"
    step = TrajectoryStep(
        call=ToolCall(call_id="call-1", name=marker, arguments={}),
        result=ToolResult(outcome=Outcome.OK, content=("done",)),
    )
    request = assemble_request(_slice_context(trajectory=(step,)))

    assert marker.encode("utf-8") in request.slice_bytes
    assert marker.encode("utf-8") not in request.preamble_bytes


def test_tool_schemas_appear_strictly_in_the_slice_region() -> None:
    marker = "TOOL-SCHEMA-MARKER-71ab5c"
    schema = ToolSchema(name=marker, schema={"type": "object", "properties": {}})
    request = assemble_request(_slice_context(tool_schemas=(schema,)))

    assert marker.encode("utf-8") in request.slice_bytes
    assert marker.encode("utf-8") not in request.preamble_bytes


# --- The preamble is assembled from the real glossary and ADR texts --------
# ("not from a copy that can drift")


def test_preamble_contains_the_current_context_md_glossary_verbatim() -> None:
    context_md = (REPO_ROOT / "CONTEXT.md").read_text(encoding="utf-8")

    preamble = assemble_preamble()

    assert context_md in preamble.text


def test_preamble_contains_every_current_adr_verbatim() -> None:
    adr_dir = REPO_ROOT / "docs" / "adr"
    adr_paths = sorted(adr_dir.glob("*.md"))
    assert adr_paths, "expected at least one ADR file under docs/adr/ to test against"

    preamble = assemble_preamble()

    for adr_path in adr_paths:
        adr_text = adr_path.read_text(encoding="utf-8")
        message = f"{adr_path.name} not found verbatim in the assembled preamble"
        assert adr_text in preamble.text, message


def test_preamble_reflects_a_synthetic_repos_actual_files_not_a_hardcoded_copy(
    tmp_path: Path,
) -> None:
    # A hardcoded copy of *this* repo's real CONTEXT.md/ADR text would pass
    # the two tests above by coincidence (it would match, today). What it
    # cannot do is match arbitrary, never-seen-before synthetic content
    # supplied only at test time — so this is the test that actually
    # distinguishes "reads the repo at assembly time" from "ships a copy".
    glossary_marker = "SYNTHETIC-GLOSSARY-e13f0a"
    (tmp_path / "CONTEXT.md").write_text(
        f"# Context\n\n## Widget\n\nA thing that does widgetry. {glossary_marker}\n",
        encoding="utf-8",
    )
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    # A filename nothing could have hardcoded in advance, so picking up its
    # body also proves the ADR *list* isn't hardcoded, only re-read.
    (adr_dir / "0099-synthetic-adr.md").write_text(
        "# 99. Synthetic ADR\n\nSYNTHETIC-ADR-MARKER-9c44de\n",
        encoding="utf-8",
    )
    (adr_dir / "0100-second-synthetic-adr.md").write_text(
        "# 100. Second Synthetic ADR\n\nSYNTHETIC-ADR-MARKER-2b6a71\n",
        encoding="utf-8",
    )

    preamble = assemble_preamble(repo_root=tmp_path)

    assert glossary_marker in preamble.text
    assert "SYNTHETIC-ADR-MARKER-9c44de" in preamble.text
    assert "SYNTHETIC-ADR-MARKER-2b6a71" in preamble.text


def test_preamble_changes_when_the_underlying_files_change(tmp_path: Path) -> None:
    (tmp_path / "CONTEXT.md").write_text("# Context\n\nfirst-version-9f1a\n", encoding="utf-8")
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-x.md").write_text("# 1. X\n\nirrelevant\n", encoding="utf-8")

    first = assemble_preamble(repo_root=tmp_path)
    assert "first-version-9f1a" in first.text
    assert "second-version-7c2b" not in first.text

    (tmp_path / "CONTEXT.md").write_text("# Context\n\nsecond-version-7c2b\n", encoding="utf-8")

    second = assemble_preamble(repo_root=tmp_path)
    assert "second-version-7c2b" in second.text
    assert "first-version-9f1a" not in second.text
