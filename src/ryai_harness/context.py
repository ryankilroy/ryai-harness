"""Context assembly: fixed preamble, then Slice-specific input.

Every request to the Model Backend is a **fixed preamble** followed by
**Slice-specific content**, in that order, never interleaved (issue #15,
ADR 0004, CONTEXT.md). The preamble is the glossary in ``CONTEXT.md`` plus
every ADR under ``docs/adr/``, read from the repo at assembly time — never
a copy pasted into this module, which could drift from the source of
truth. It is byte-identical across every Slice and every Backend.

Everything that varies per Slice — Blast Radius, Plan, Trajectory-so-far,
and this Slice's tool schemas — is carried on :class:`SliceContext` and
rendered strictly after the preamble.

Why the order is load-bearing (ADR 0004): SGLang's RadixAttention
prefix-caches a request by its longest shared byte prefix across requests.
The preamble only earns that cache if it is the same bytes, in the same
position, on every request; Blast Radius is deliberately *excluded* from
it because it varies per Slice by definition — including it would
invalidate the cache on the first token of every request. CI cannot
observe an actual cache hit against a live Pod; what it can check, and
what this module exists to make checkable, is the assembly-order property
that caching depends on.

Hard error, not convention (the subtlest acceptance criterion): nothing
here lets Slice-varying content land in the preamble region by construction,
not merely by discipline.

- :func:`assemble_request` takes a single content parameter, ``slice_context:
  SliceContext`` — there is no second parameter through which arbitrary
  preamble text could be supplied. The preamble is always sourced fresh
  from :func:`assemble_preamble`, internally, on every call.
- :class:`SliceContext` cannot hold a :class:`Preamble` — its fields are
  exactly the Slice-varying pieces (``blast_radius``, ``plan``,
  ``trajectory``, ``tool_schemas``); there is no field shaped to carry
  preamble text.
- :class:`AssembledRequest` stores exactly two ``bytes`` fields,
  ``preamble_bytes`` and ``slice_bytes``. ``boundary`` and ``full_bytes``
  are *computed* from them by this module, not independently settable and
  not left for a later body to get wrong (see the note on those two
  properties below) — ``full_bytes`` is defined as
  ``preamble_bytes + slice_bytes`` and nothing else, so "preamble then
  Slice, in that order" is a property of the type, not a convention a
  caller — or the implementation agent — has to uphold.

Encoding: every ``bytes`` value in this module is UTF-8 of the
corresponding ``str``/text content. "Byte-identical" claims (ADR 0004,
issue #15) are claims about UTF-8-encoded output, since RadixAttention
caches on the wire bytes SGLang actually receives.

Issue #15 lays down this structure; the implementation agent fills in
:func:`assemble_preamble` (reading ``CONTEXT.md`` and ``docs/adr/*.md``)
and :func:`assemble_request` (rendering a ``SliceContext`` and combining it
with the preamble). Everything else in this module — the dataclass shapes,
and the ``boundary``/``full_bytes`` computed properties on
``AssembledRequest`` — is already load-bearing on the type shape and is
implemented here, not left as a stub.

Note: this module keeps ``from __future__ import annotations`` at the
top, matching ``tool_result.py``. ``tests/test_context.py`` inspects
``dataclasses.fields(...)[i].type`` as a string for some of its structural
assertions; that only works while annotations are stringified.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ryai_harness.tool_call import ToolCall
from ryai_harness.tool_result import ToolResult

#: This repo's root, computed from this file's own location
#: (src/ryai_harness/context.py -> repo root is two parents up), so
#: assembly works the same from a checkout or a worktree without a caller
#: having to pass it. Tests override it via ``assemble_preamble``'s and
#: ``assemble_request``'s ``repo_root`` parameter to point at a synthetic
#: fixture repo instead.
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Preamble:
    """The fixed preamble: ``CONTEXT.md``'s glossary followed by every ADR
    under ``docs/adr/``, byte-identical across all Slices and Backends.

    The only supported way to obtain one is :func:`assemble_preamble`,
    which reads those files from the repo at assembly time. Constructing
    this directly with hand-written text is possible in Python (nothing
    stops a dataclass constructor call), but it is not how this type is
    meant to be produced: the drift test in ``tests/test_context.py``
    asserts the preamble actually came from the files on disk, which a
    hand-written value cannot satisfy except by accident.

    Attributes:
        text: The assembled preamble text, UTF-8-encodable, read from
            ``CONTEXT.md`` and ``docs/adr/*.md``.
    """

    text: str


@dataclass(frozen=True, slots=True)
class BlastRadius:
    """The files and concepts a Slice is expected to touch (CONTEXT.md),
    named by the Plan before work begins. Slice-varying by definition —
    this is the piece ADR 0004 is explicit about excluding from the
    preamble, even though CONTEXT.md's Seed definition lists it first.

    Attributes:
        files: Paths the Slice is expected to touch.
        concepts: Named concepts (not necessarily files) the Slice is
            expected to touch.
    """

    files: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    """A decomposition of intent into Slices (CONTEXT.md), as it bears on
    the Slice this context is being assembled for. Slice-specific.

    Attributes:
        text: The Plan content relevant to this Slice.
    """

    text: str


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    """One Tool Call / Tool Result pair from the Trajectory so far, in the
    Slice currently being attempted. Reuses issue #11's canonical types —
    a Trajectory is a record of Tool Calls and Tool Results (CONTEXT.md),
    not a parallel shape invented here.

    Attributes:
        call: The Tool Call as it was made.
        result: The Tool Result it produced.
    """

    call: ToolCall
    result: ToolResult


@dataclass(frozen=True, slots=True)
class ToolSchema:
    """One tool schema offered to the model for this Slice. Distinct from
    the fixed preamble because the set of tools on offer can differ by
    Slice.

    Attributes:
        name: The tool's canonical name (matches ``ToolCall.name``).
        schema: The tool's schema, already in canonical form.
    """

    name: str
    schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SliceContext:
    """Everything that varies per Slice: Blast Radius, Plan,
    Trajectory-so-far, and this Slice's tool schemas.

    This is the *only* content type :func:`assemble_request` accepts.
    There is no field here shaped to carry preamble text, and no
    other parameter on :func:`assemble_request` through which
    Slice-varying content could reach the preamble region instead of this
    one — that omission, not a runtime check, is what makes interleaving
    a hard error rather than a convention.

    Attributes:
        blast_radius: This Slice's Blast Radius.
        plan: The Plan content bearing on this Slice.
        trajectory: The Trajectory so far, in order, empty at the start of
            a Slice.
        tool_schemas: The tool schemas on offer for this Slice.
    """

    blast_radius: BlastRadius
    plan: Plan
    trajectory: tuple[TrajectoryStep, ...] = ()
    tool_schemas: tuple[ToolSchema, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AssembledRequest:
    """A fully assembled request: the preamble region, then the
    Slice-specific region, in that fixed order — never interleaved.

    ``boundary`` and ``full_bytes`` are computed from ``preamble_bytes``
    and ``slice_bytes``, not independently settable fields: there is
    exactly one concatenation site (``full_bytes``, below), and it is
    always preamble-then-slice. A caller cannot construct an
    ``AssembledRequest`` whose ``full_bytes`` puts Slice content before
    the preamble, or interleaves the two, because there is no field or
    parameter that lets ``full_bytes`` be anything other than that one
    concatenation.

    Attributes:
        preamble_bytes: The preamble region, UTF-8-encoded.
        slice_bytes: The Slice-specific region, UTF-8-encoded.
    """

    preamble_bytes: bytes
    slice_bytes: bytes

    @property
    def boundary(self) -> int:
        """Byte offset in :attr:`full_bytes` where the Slice-specific
        region begins — i.e. where the preamble region ends."""
        return len(self.preamble_bytes)

    @property
    def full_bytes(self) -> bytes:
        """The preamble region immediately followed by the Slice-specific
        region. The only concatenation this type performs, and always in
        this order."""
        return self.preamble_bytes + self.slice_bytes


def assemble_preamble(repo_root: Path | None = None) -> Preamble:
    """Assemble the fixed preamble by reading ``CONTEXT.md`` and every
    ``docs/adr/*.md`` file from ``repo_root`` (defaults to :data:`REPO_ROOT`,
    this repo's own root).

    Must read those files from disk on every call — not return a value
    copied from them at some earlier point — so that the assembled
    preamble can never drift from the source of truth: CONTEXT.md's
    glossary and the ADR texts. ``repo_root`` exists so tests can point
    this at a synthetic fixture repo and assert the result reflects
    exactly what is on disk there, which a hardcoded copy of this repo's
    real text could not do.

    Args:
        repo_root: Root directory containing ``CONTEXT.md`` and
            ``docs/adr/``. Defaults to this repo's own root.

    Returns:
        The assembled :class:`Preamble`.
    """
    root = repo_root if repo_root is not None else REPO_ROOT

    context_md = (root / "CONTEXT.md").read_text(encoding="utf-8")
    adr_paths = sorted((root / "docs" / "adr").glob("*.md"))
    adr_texts = [path.read_text(encoding="utf-8") for path in adr_paths]

    return Preamble(text="\n\n".join([context_md, *adr_texts]))


def _render_slice_context(slice_context: SliceContext) -> str:
    """Render ``slice_context`` to text for the Slice-specific region.

    Total over any ``SliceContext`` value — never raises on the content
    it renders (e.g. ``call.arguments``/``schema.schema`` are rendered
    with ``str()``, not ``json.dumps``, since a ``Mapping[str, object]``
    is not guaranteed JSON-serializable).
    """
    parts: list[str] = []

    parts.append("# Blast Radius")
    parts.append(f"Files: {', '.join(slice_context.blast_radius.files)}")
    parts.append(f"Concepts: {', '.join(slice_context.blast_radius.concepts)}")

    parts.append("# Plan")
    parts.append(slice_context.plan.text)

    parts.append("# Trajectory so far")
    for step in slice_context.trajectory:
        call = step.call
        result = step.result
        parts.append(f"Call: name={call.name} call_id={call.call_id} arguments={call.arguments}")
        parts.append(
            f"Result: outcome={result.outcome.value} content={result.content} "
            f"kind={result.kind} reason={result.reason}"
        )

    parts.append("# Tool schemas")
    for schema in slice_context.tool_schemas:
        parts.append(f"Tool: name={schema.name} schema={schema.schema}")

    return "\n".join(parts) + "\n"


def assemble_request(
    slice_context: SliceContext, *, repo_root: Path | None = None
) -> AssembledRequest:
    """Assemble a full request for ``slice_context``: the fixed preamble
    (sourced fresh from :func:`assemble_preamble`; see that function for
    ``repo_root``) followed by everything in ``slice_context``, rendered
    strictly after it.

    Note what this function does *not* accept: there is no parameter here
    for raw preamble text, and no way to place any part of
    ``slice_context`` before or inside the preamble region. The preamble
    always comes from :func:`assemble_preamble`; the only variable input
    is ``slice_context``, and it always renders after the preamble in the
    returned :class:`AssembledRequest`.

    Args:
        slice_context: Everything Slice-specific for this request: Blast
            Radius, Plan, Trajectory-so-far, and tool schemas.
        repo_root: Forwarded to :func:`assemble_preamble`.

    Returns:
        The assembled :class:`AssembledRequest`, preamble region then
        Slice-specific region.
    """
    preamble = assemble_preamble(repo_root=repo_root)
    slice_text = _render_slice_context(slice_context)

    return AssembledRequest(
        preamble_bytes=preamble.text.encode("utf-8"),
        slice_bytes=slice_text.encode("utf-8"),
    )
