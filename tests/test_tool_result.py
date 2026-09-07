"""Tests for the canonical Tool Result schema (issue #11, ADR 0002).

External behaviour only: given a construction, expect this value or this
failure. See tests/test_mypy_strict_rejects_missing_outcome.py for the
static-typing half of the "outcome is mandatory" requirement.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

import ryai_harness.tool_result
from ryai_harness.tool_result import DeniedKind, Outcome, ToolResult


class TestOkOutcome:
    def test_ok_with_content(self) -> None:
        result = ToolResult(outcome=Outcome.OK, content=("42",))

        assert result.outcome is Outcome.OK
        assert result.content == ("42",)

    def test_ok_with_empty_content_is_a_valid_value(self) -> None:
        # "A search with no matches" — legitimately empty, not absent.
        result = ToolResult(outcome=Outcome.OK, content=())

        assert result.outcome is Outcome.OK
        assert result.content == ()

    def test_ok_empty_content_is_distinct_from_an_absent_result(self) -> None:
        empty_ok = ToolResult(outcome=Outcome.OK, content=())

        # A second, independently-constructed "found nothing" result is
        # equal to the first -- "empty" is one well-defined value, not a
        # stand-in for "we don't know" or "there is no result". See
        # test_content_field_type_never_admits_none and
        # test_no_optional_tool_result_anywhere_in_source below for the
        # structural half of this: there is no nullable type an absent
        # result could hide behind in the first place.
        assert empty_ok == ToolResult(outcome=Outcome.OK, content=())

    def test_content_field_type_never_admits_none(self) -> None:
        # Structural half of "empty is distinct from absent": `content`'s
        # annotation is `tuple[str, ...]`, never `tuple[str, ...] | None`,
        # so there is no nullable field an absent result could hide behind.
        content_field = next(f for f in dataclasses.fields(ToolResult) if f.name == "content")

        assert "None" not in content_field.type
        assert "Optional" not in content_field.type


class TestErrorOutcome:
    def test_error_result(self) -> None:
        result = ToolResult(outcome=Outcome.ERROR, content=("boom: file not found",))

        assert result.outcome is Outcome.ERROR
        assert result.content == ("boom: file not found",)


class TestDeniedOutcome:
    def test_denied_with_kind_rejected_and_reason(self) -> None:
        result = ToolResult(
            outcome=Outcome.DENIED,
            kind=DeniedKind.REJECTED,
            reason="writes outside the workspace are not permitted",
        )

        assert result.outcome is Outcome.DENIED
        assert result.kind is DeniedKind.REJECTED
        assert result.reason == "writes outside the workspace are not permitted"

    def test_denied_with_kind_needs_revision_and_reason(self) -> None:
        result = ToolResult(
            outcome=Outcome.DENIED,
            kind=DeniedKind.NEEDS_REVISION,
            reason="path must be relative to the repo root",
        )

        assert result.kind is DeniedKind.NEEDS_REVISION

    def test_denied_without_kind_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolResult(outcome=Outcome.DENIED, reason="no kind given")

    def test_denied_without_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED)

    def test_denied_without_kind_or_reason_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolResult(outcome=Outcome.DENIED)


class TestOutcomeIsMandatory:
    def test_outcome_field_has_no_default(self) -> None:
        outcome_field = next(f for f in dataclasses.fields(ToolResult) if f.name == "outcome")

        assert outcome_field.default is dataclasses.MISSING
        assert outcome_field.default_factory is dataclasses.MISSING  # type: ignore[comparison-overlap]

    def test_missing_outcome_fails_loudly_at_runtime(self) -> None:
        # Simulates a caller that bypassed the type checker (e.g. building
        # the call from an untyped dict) rather than typing it out
        # directly, so a static check alone would not catch this one.
        untyped_kwargs: dict[str, object] = {"content": ()}

        with pytest.raises(TypeError):
            ToolResult(**untyped_kwargs)  # type: ignore[arg-type]


class TestAbsenceIsStructurallyUnrepresentable:
    # "No result for a completed Tool Call" must never become expressible
    # by wrapping ToolResult in an optional. This is a decision about the
    # module's shape, not just this one type's fields, so it is checked
    # against the source of every module in the package -- not only
    # tool_result.py -- so nothing elsewhere in ryai_harness can reintroduce
    # it either.
    _FORBIDDEN = (
        re.compile(r"Optional\[\s*ToolResult\s*\]"),
        re.compile(r"ToolResult\s*\|\s*None"),
        re.compile(r"None\s*\|\s*ToolResult"),
    )

    def test_no_optional_tool_result_anywhere_in_source(self) -> None:
        package_dir = Path(ryai_harness.tool_result.__file__).resolve().parent

        offenders = []
        for path in sorted(package_dir.glob("*.py")):
            text = path.read_text()
            for pattern in self._FORBIDDEN:
                if pattern.search(text):
                    offenders.append(f"{path.name}: matched {pattern.pattern!r}")

        assert not offenders, (
            "ToolResult must never appear behind Optional/`| None` -- "
            "an absent result has to be a different type, not this one "
            "wrapped in a nullable:\n" + "\n".join(offenders)
        )


class TestReviewFollowUps:
    """Gaps found by the issue #11 code review, closed before later Slices
    build denial-handling logic on this schema."""

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_denied_rejects_a_reason_that_names_nothing(self, blank: str) -> None:
        with pytest.raises(ValueError, match="names nothing"):
            ToolResult(outcome=Outcome.DENIED, kind=DeniedKind.REJECTED, reason=blank)

    def test_an_explicit_none_outcome_is_rejected_at_runtime(self) -> None:
        """The dataclass __init__ catches an *omitted* outcome; this covers an
        outcome explicitly present but None, as untyped external data yields."""
        with pytest.raises(TypeError, match="must be an Outcome"):
            ToolResult(outcome=None)  # type: ignore[arg-type]

    def test_tool_result_is_immutable(self) -> None:
        result = ToolResult(outcome=Outcome.OK)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.outcome = Outcome.ERROR  # type: ignore[misc]
