"""Tests for Working Backend wiring-in vs promotion (issue #23, ADR 0006,
CONTEXT.md).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

import ryai_harness.working_backend
from ryai_harness.regression_suite import PromotionVerdict
from ryai_harness.working_backend import (
    PromotionBasis,
    WorkingBackend,
    promote_backend,
    wire_in_working_backend,
)


class TestWiringInIsDistinctFromPromoting:
    """AC 7: wiring a Backend in as Working Backend is a distinct
    operation from promoting one, proven both structurally (different
    signatures) and behaviourally (different resulting basis)."""

    def test_wiring_in_never_consults_suite_evidence(self) -> None:
        # wire_in_working_backend takes no suite/case-results parameter
        # at all -- it is not "promote with an empty suite", it is a
        # different act (CONTEXT.md's Working Backend entry: "Promoted
        # from the Shortlist without Regression Suite evidence").
        params = set(inspect.signature(wire_in_working_backend).parameters)
        assert params == {"name"}

    def test_promoting_requires_suite_evidence(self) -> None:
        params = set(inspect.signature(promote_backend).parameters)
        assert "case_passes" in params

    def test_wiring_in_produces_wired_in_basis(self) -> None:
        backend = wire_in_working_backend("qwen3-coder-30b-a3b")
        assert backend == WorkingBackend(name="qwen3-coder-30b-a3b", basis=PromotionBasis.WIRED_IN)

    def test_promoting_produces_suite_evidence_basis(self) -> None:
        backend = promote_backend("glm-4.5-air", (True, True, True))
        assert backend == WorkingBackend(name="glm-4.5-air", basis=PromotionBasis.SUITE_EVIDENCE)

    def test_wiring_in_and_promoting_yield_different_basis_for_the_same_name(self) -> None:
        wired = wire_in_working_backend("same-name")
        promoted = promote_backend("same-name", (True,))

        assert wired.basis is not promoted.basis
        assert wired.basis is PromotionBasis.WIRED_IN
        assert promoted.basis is PromotionBasis.SUITE_EVIDENCE

    def test_wired_in_backend_is_not_adopted_by_construction(self) -> None:
        # CONTEXT.md: "A Working Backend is not yet adopted" -- there is
        # no `adopted` field on this type at all (see working_backend.py's
        # module docstring for why an adopted: bool would be wrong here).
        field_names = {f.name for f in dataclasses.fields(WorkingBackend)}
        assert "adopted" not in field_names


class TestPromoteDeclines:
    """AC 3, AC 5: promote_backend refuses when check_promotion would
    not return PROMOTED -- an empty Suite or a less-than-100% pass rate
    never yields a Working Backend built on suite evidence."""

    def test_promote_declines_on_empty_suite(self) -> None:
        with pytest.raises(ValueError, match=PromotionVerdict.INSUFFICIENT_EVIDENCE.value):
            promote_backend("candidate", ())

    def test_promote_declines_on_partial_pass(self) -> None:
        with pytest.raises(ValueError, match=PromotionVerdict.NOT_PROMOTED.value):
            promote_backend("candidate", (True, False))


class TestNoDwellTimer:
    """AC 6, extended to this module: no dwell timer gates promotion
    here either."""

    _FORBIDDEN_MODULES = frozenset({"time", "datetime"})

    def test_module_imports_no_time_machinery(self) -> None:
        module_path = Path(ryai_harness.working_backend.__file__)
        tree = ast.parse(module_path.read_text())

        imported_top_levels: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_top_levels.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_top_levels.add(node.module.split(".")[0])

        offenders = imported_top_levels & self._FORBIDDEN_MODULES
        assert not offenders, f"working_backend.py imports time machinery {offenders}"

    def test_promote_backend_signature_has_no_temporal_parameter(self) -> None:
        params = set(inspect.signature(promote_backend).parameters)
        assert params == {"name", "case_passes"}
