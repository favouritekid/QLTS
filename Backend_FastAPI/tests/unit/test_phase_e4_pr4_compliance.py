"""Regression tests for Q9 #07 Phase E.4 PR-4 compliance gaps.

Closes spec gaps surfaced post PR-3 review:

1. ``_populate_priority_evidence_projections`` correctly computes 3 transient
   attrs (display projection, missing_priority_evidence_codes, priority_
   evidence_documents) — projection logic pure-function testable.

2. ``submit_and_evaluate`` inserts ``priority_audit_log`` row với
   ``action_type='ut_evidence_warning_dismissed'`` khi profile có codes
   ghi nhận nhưng thiếu file (Decision #2 audit trail — NOT eligibility
   gate, just post-hoc thanh tra track).

Mock pattern mirrors tests/unit/test_phase_e4_pr2_priority_evidence.py.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    id: int = 42,
    academic_year: int = 2026,
    codes: list = None,
    evidence: dict = None,
    documents: list = None,
):
    """SimpleNamespace mimicking AdmissionProfile + transient attrs."""
    profile = SimpleNamespace(
        id=id,
        lead_id=100,
        academic_year=academic_year,
        priority_object_codes=codes or [],
        priority_object_evidence=evidence or {},
        documents=documents or [],
        # Transient attrs set by _populate; pre-init None để assert sets them.
        priority_object_evidence_display=None,
        missing_priority_evidence_codes=None,
        priority_evidence_documents=None,
    )
    return profile


def _make_doc(
    *,
    id: int,
    sub_code: str,
    file_path: str = None,
    category: str = "priority_evidence",
):
    return SimpleNamespace(
        id=id,
        category=category,
        priority_sub_code=sub_code,
        file_path=file_path or f"uploads/admissions/42/priority_{sub_code}.pdf",
    )


def _make_db(catalog_rows=None):
    """Mock DB returning catalog rows cho PriorityObjectConfig query."""
    catalog_result = MagicMock()
    catalog_result.__iter__ = lambda self: iter(catalog_rows or [])

    async def _execute(stmt, *args, **kwargs):
        return catalog_result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


# ---------------------------------------------------------------------------
# Projection helper tests — G2 + G4 regression
# ---------------------------------------------------------------------------


async def test_populate_priority_evidence_projections_missing_codes_transient() -> None:
    """G4 regression: missing_priority_evidence_codes set as transient attr —
    correctly computed from priority_object_codes minus uploaded documents."""
    from app.services.admission_service import (
        _populate_priority_evidence_projections,
    )

    profile = _make_profile(
        codes=["04", "07", "08"],
        documents=[
            # Only UT04 has uploaded doc
            _make_doc(id=99, sub_code="04"),
        ],
    )
    catalog_rows = [
        SimpleNamespace(sub_code="04", bonus_points=Decimal("1.00"),
                        evidence_doc_type="Giấy chứng nhận con thương binh"),
        SimpleNamespace(sub_code="07", bonus_points=Decimal("0.50"),
                        evidence_doc_type="Giấy chứng nhận hộ nghèo"),
        SimpleNamespace(sub_code="08", bonus_points=Decimal("0.50"),
                        evidence_doc_type="Giấy xác nhận chất độc hóa học"),
    ]
    db = _make_db(catalog_rows=catalog_rows)

    await _populate_priority_evidence_projections(db, profile, profile.documents)

    # UT07 + UT08 missing files (only UT04 uploaded)
    assert profile.missing_priority_evidence_codes == ["07", "08"]


async def test_populate_priority_evidence_projections_no_codes_empty_lists() -> None:
    """Empty priority_object_codes → empty projections (defensive)."""
    from app.services.admission_service import (
        _populate_priority_evidence_projections,
    )

    profile = _make_profile(codes=[])
    db = _make_db()

    await _populate_priority_evidence_projections(db, profile, [])

    assert profile.missing_priority_evidence_codes == []
    assert profile.priority_evidence_documents == []


async def test_populate_priority_evidence_documents_projection_shape() -> None:
    """G0a: priority_evidence_documents per-UT item correctly populated
    với label, bonus, document_id, file_path, status, verification_status."""
    from app.services.admission_service import (
        _populate_priority_evidence_projections,
    )

    profile = _make_profile(
        codes=["04", "07"],
        evidence={
            "04": {"status": "verified", "verified_by": 7},
            "07": {"status": "pending"},
        },
        documents=[
            _make_doc(
                id=99, sub_code="04",
                file_path="uploads/admissions/42/priority_04.pdf",
            ),
        ],
    )
    catalog_rows = [
        SimpleNamespace(sub_code="04", bonus_points=Decimal("1.00"),
                        evidence_doc_type="Con thương binh"),
        SimpleNamespace(sub_code="07", bonus_points=Decimal("0.50"),
                        evidence_doc_type="Hộ nghèo"),
    ]
    db = _make_db(catalog_rows=catalog_rows)

    await _populate_priority_evidence_projections(db, profile, profile.documents)

    items = profile.priority_evidence_documents
    assert len(items) == 2

    # UT04 — uploaded + verified
    ut04 = next(i for i in items if i["sub_code"] == "04")
    assert ut04["bonus_points"] == 1.0
    assert ut04["label"] == "Con thương binh"
    assert ut04["document_id"] == 99
    assert ut04["document_file_path"] == "uploads/admissions/42/priority_04.pdf"
    assert ut04["status"] == "uploaded"
    assert ut04["verification_status"] == "verified"

    # UT07 — no doc, pending
    ut07 = next(i for i in items if i["sub_code"] == "07")
    assert ut07["bonus_points"] == 0.5
    assert ut07["label"] == "Hộ nghèo"
    assert ut07["document_id"] is None
    assert ut07["document_file_path"] is None
    assert ut07["status"] == "missing"
    assert ut07["verification_status"] == "pending"


async def test_populate_priority_evidence_missing_codes_sorted() -> None:
    """Sort contract — missing_priority_evidence_codes sorted ascending
    (consistent FE rendering order)."""
    from app.services.admission_service import (
        _populate_priority_evidence_projections,
    )

    profile = _make_profile(
        codes=["08", "04", "07", "01"],
        documents=[],  # all missing
    )
    catalog_rows = [
        SimpleNamespace(sub_code=c, bonus_points=Decimal("0.50"),
                        evidence_doc_type=f"UT{c}")
        for c in ["01", "04", "07", "08"]
    ]
    db = _make_db(catalog_rows=catalog_rows)

    await _populate_priority_evidence_projections(db, profile, [])

    # All 4 missing, returned sorted
    assert profile.missing_priority_evidence_codes == ["01", "04", "07", "08"]


async def test_populate_priority_evidence_filters_non_priority_evidence_docs() -> None:
    """Documents với category='path' (NOT priority_evidence) MUST NOT
    count toward uploaded codes set. Defensive filter check."""
    from app.services.admission_service import (
        _populate_priority_evidence_projections,
    )

    profile = _make_profile(
        codes=["04"],
        documents=[
            # Path doc (CCCD) với same sub_code-like accident — must skip
            _make_doc(
                id=11, sub_code="04",
                category="path",
                file_path="uploads/admissions/42/cccd.pdf",
            ),
        ],
    )
    db = _make_db()

    await _populate_priority_evidence_projections(db, profile, profile.documents)

    # UT04 missing because the only doc was category='path'
    assert profile.missing_priority_evidence_codes == ["04"]


# ---------------------------------------------------------------------------
# G3 cleaner regression (already in test_phase_e4_audit_fixes; light dup OK)
# ---------------------------------------------------------------------------


def test_strip_display_fields_preserves_paper_only_verification() -> None:
    """Decision #3 persisted field must survive strip cleaner (only
    verified_by_name + document_file_path are display-only)."""
    from app.services.admission_service import _strip_display_fields_from_evidence

    enriched = {
        "04": {
            "status": "verified",
            "verified_by": 7,
            "verified_by_name": "Trịnh Tố Uyên",  # display only
            "document_file_path": "uploads/.../x.pdf",  # display only
            "paper_only_verification": True,  # persisted
        }
    }
    cleaned = _strip_display_fields_from_evidence(enriched)
    assert cleaned["04"]["paper_only_verification"] is True
    assert "verified_by_name" not in cleaned["04"]
    assert "document_file_path" not in cleaned["04"]
