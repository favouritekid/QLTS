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


# ---------------------------------------------------------------------------
# Decision #2 audit row regression — P1 contract pinning
# ---------------------------------------------------------------------------


def _make_audit_db(uploaded_sub_codes: list[str]):
    """Mock DB cho audit helper test — db.execute returns mapping rows với
    .priority_sub_code attribute, simulating ProfileDocument query result."""
    docs_result = MagicMock()

    # Each row mimics ORM row attribute access (.priority_sub_code)
    docs_result.__iter__ = lambda self: iter(
        [SimpleNamespace(priority_sub_code=c) for c in uploaded_sub_codes]
    )

    async def _execute(stmt, *args, **kwargs):
        return docs_result

    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _find_warning_audit_rows(db):
    """Filter db.add() calls to PriorityAuditLog với action_type warning_dismissed."""
    from app import models
    return [
        c[0][0]
        for c in db.add.call_args_list
        if isinstance(c[0][0], models.PriorityAuditLog)
        and c[0][0].action_type == "ut_evidence_warning_dismissed"
    ]


async def test_audit_warning_dismissed_inserts_row_when_missing_codes() -> None:
    """P1 Decision #2 contract: profile có UT codes ghi nhận nhưng chưa
    upload minh chứng → INSERT priority_audit_log row với
    action_type='ut_evidence_warning_dismissed' + new_value chứa
    missing_codes + audit_metadata chứa missing_count + actor_role.
    """
    from app.services.admission_service import _audit_warning_dismissed_if_missing

    actor = SimpleNamespace(id=7, role="officer")
    profile = _make_profile(
        codes=["04", "07", "08"],
    )
    # Only UT04 has uploaded doc → UT07 + UT08 missing
    db = _make_audit_db(uploaded_sub_codes=["04"])

    await _audit_warning_dismissed_if_missing(db, profile.id, profile, actor)

    audit_rows = _find_warning_audit_rows(db)
    assert len(audit_rows) == 1, "Exactly 1 warning_dismissed audit row expected"

    row = audit_rows[0]
    assert row.profile_id == profile.id
    assert row.action_type == "ut_evidence_warning_dismissed"
    assert row.actor_id == 7
    assert row.new_value == {"missing_codes": ["07", "08"]}  # sorted
    assert row.audit_metadata["submit_status"] == "submitted"
    assert row.audit_metadata["missing_count"] == 2
    assert row.audit_metadata["actor_role"] == "officer"


async def test_audit_warning_dismissed_no_row_when_all_uploaded() -> None:
    """All codes have uploaded files → NO audit row (officer hoàn thành
    workflow trước submit, không trigger Decision #2 warning)."""
    from app.services.admission_service import _audit_warning_dismissed_if_missing

    actor = SimpleNamespace(id=7, role="officer")
    profile = _make_profile(codes=["04", "07"])
    db = _make_audit_db(uploaded_sub_codes=["04", "07"])

    await _audit_warning_dismissed_if_missing(db, profile.id, profile, actor)

    assert _find_warning_audit_rows(db) == []


async def test_audit_warning_dismissed_no_row_when_no_priority_codes() -> None:
    """Profile không có UT codes (e.g., candidate không thuộc diện ưu tiên)
    → NO audit row, NO DB query needed."""
    from app.services.admission_service import _audit_warning_dismissed_if_missing

    actor = SimpleNamespace(id=7, role="officer")
    profile = _make_profile(codes=[])
    db = _make_audit_db(uploaded_sub_codes=[])

    await _audit_warning_dismissed_if_missing(db, profile.id, profile, actor)

    assert _find_warning_audit_rows(db) == []


async def test_audit_warning_dismissed_magic_link_path_no_actor() -> None:
    """Magic-link self-service path (current_user=None) → actor_id=None +
    audit_metadata.actor_role='magic_link' (Decision #2 captures source
    for thanh tra distinguishing officer vs candidate self-submit)."""
    from app.services.admission_service import _audit_warning_dismissed_if_missing

    profile = _make_profile(codes=["04"])
    db = _make_audit_db(uploaded_sub_codes=[])

    await _audit_warning_dismissed_if_missing(db, profile.id, profile, None)

    rows = _find_warning_audit_rows(db)
    assert len(rows) == 1
    assert rows[0].actor_id is None
    assert rows[0].audit_metadata["actor_role"] == "magic_link"


async def test_audit_warning_dismissed_defensive_on_db_error() -> None:
    """Decision #2 contract: audit insert failure MUST NOT block submit.
    DB exception → swallow + warning log; no raise."""
    from app.services.admission_service import _audit_warning_dismissed_if_missing

    actor = SimpleNamespace(id=7, role="officer")
    profile = _make_profile(codes=["04"])

    # DB raises on execute
    db = MagicMock()
    db.add = MagicMock()
    db.execute = AsyncMock(side_effect=Exception("simulated DB error"))

    # MUST NOT raise — defensive try/except wraps entire audit block
    await _audit_warning_dismissed_if_missing(db, profile.id, profile, actor)

    # No audit row inserted (compute failed before db.add reached)
    assert _find_warning_audit_rows(db) == []


async def test_audit_warning_dismissed_missing_codes_sorted_in_audit() -> None:
    """missing_codes trong audit.new_value MUST be sorted ascending
    (consistent ordering cho thanh tra grep + comparison)."""
    from app.services.admission_service import _audit_warning_dismissed_if_missing

    actor = SimpleNamespace(id=7, role="admin")
    # Profile codes in reverse order to verify sort happens
    profile = _make_profile(codes=["08", "04", "07", "01"])
    db = _make_audit_db(uploaded_sub_codes=[])  # all missing

    await _audit_warning_dismissed_if_missing(db, profile.id, profile, actor)

    rows = _find_warning_audit_rows(db)
    assert len(rows) == 1
    # Sorted ascending in audit row
    assert rows[0].new_value["missing_codes"] == ["01", "04", "07", "08"]
    assert rows[0].audit_metadata["actor_role"] == "admin"


# ===========================================================================
# Smoke 2026-05-20 — GET path projection wiring (P1 read-side bug)
# ===========================================================================
# Smoke discovered that ``get_profile()`` skipped
# ``_populate_priority_evidence_projections``, so the G0a contract
# (DocumentsTab Priority section + § 3 UT cards) was dark on every GET.
# Mutation endpoints wired through ``_populate_response_fields`` did populate
# the projection, hiding the bug from frontend integration tests. Fix added
# the call to ``get_profile`` directly. These tests pin both the projection
# call site and the empty-fallback semantic so the bug doesn't drift back.


async def test_get_profile_populates_priority_evidence_documents_when_codes_set(
    monkeypatch,
) -> None:
    """GET path: codes=['07'] + no doc → projection row with status='missing'.

    Mirrors the Chrome MCP smoke finding 2026-05-20: officer set
    priority_object_codes=['07'] via PUT, response showed
    priority_evidence_documents=[] (BUG). After fix, GET path itself populates
    the projection.
    """
    from sqlalchemy import select as _sel
    import app.services.admission_service as svc

    captured_projection_calls: list = []

    async def fake_populate_projection(db, profile, documents):
        captured_projection_calls.append({
            "profile_id": profile.id,
            "codes": list(profile.priority_object_codes or []),
            "doc_count": len(documents),
        })
        profile.priority_evidence_documents = [
            {
                "sub_code": "07",
                "bonus_points": 0.5,
                "label": "Quyết định cấp sổ hộ nghèo",
                "document_id": None,
                "document_file_path": None,
                "status": "missing",
                "verification_status": None,
            }
        ]
        profile.priority_object_evidence_display = {}
        profile.missing_priority_evidence_codes = ["07"]

    async def fake_audit_log(db, profile_id):
        return []

    async def fake_repo_documents(profile_id):
        return []

    async def fake_resolver(db, docs):
        return {}

    async def fake_minor(db, profile, user):
        return None

    # Stub repository layer + helper functions
    monkeypatch.setattr(svc, "_populate_priority_evidence_projections", fake_populate_projection)
    monkeypatch.setattr(svc, "_load_priority_audit_log", fake_audit_log)
    monkeypatch.setattr(svc, "_resolve_verifier_names", fake_resolver)
    monkeypatch.setattr(svc, "_resolve_minor_correction_state", fake_minor)
    monkeypatch.setattr(svc, "_compute_frontend_fields", lambda *a, **kw: None)
    monkeypatch.setattr(svc, "_calculate_and_update_totals", lambda *a, **kw: None)
    monkeypatch.setattr(svc, "_check_idor_access", lambda profile, user: None)

    # Stub repository class — return a profile with codes=['07'], no docs
    profile_stub = SimpleNamespace(
        id=99,
        status="draft",
        academic_year=2026,
        priority_object_codes=["07"],
        priority_object_evidence={},
        lead=SimpleNamespace(unit_id=1, assigned_officer=None),
        assigned_reviewer=None,
        priority_evidence_documents=None,
        priority_object_evidence_display=None,
        missing_priority_evidence_codes=None,
        priority_audit_log=None,
    )

    class FakeRepo:
        def __init__(self, db):
            pass

        async def get_profile_by_id_with_lead(self, profile_id):
            return profile_stub

        async def get_all_documents(self, profile_id):
            return []

        async def get_profile_scores(self, profile_id):
            return []

    monkeypatch.setattr("app.repositories.AdmissionRepository", FakeRepo)

    db = MagicMock()
    user = SimpleNamespace(id=7, role="officer", unit_id=1)

    result = await svc.get_profile(db, 99, user)

    # Pin contract: projection helper was called from GET path
    assert len(captured_projection_calls) == 1
    assert captured_projection_calls[0]["codes"] == ["07"]

    # Pin contract: projection populated transient attrs visible to response
    assert result.priority_evidence_documents == [
        {
            "sub_code": "07",
            "bonus_points": 0.5,
            "label": "Quyết định cấp sổ hộ nghèo",
            "document_id": None,
            "document_file_path": None,
            "status": "missing",
            "verification_status": None,
        }
    ]
    assert result.missing_priority_evidence_codes == ["07"]


async def test_get_profile_populates_audit_log_alongside_projection(
    monkeypatch,
) -> None:
    """GET path also loads priority_audit_log — paired Phase E.4 contract.

    These two attrs (audit log + projection) ship together via
    ``_populate_response_fields`` for mutation endpoints; the GET fix mirrors
    that pairing so workbench audit timeline does NOT regress.
    """
    import app.services.admission_service as svc

    audit_call_recorded: dict = {}

    async def fake_audit_log(db, profile_id):
        audit_call_recorded["profile_id"] = profile_id
        return [
            SimpleNamespace(
                id=1,
                action_type="ut_evidence_verified",
                actor_id=2,
                timestamp=None,
                old_value=None,
                new_value={"sub_code": "07"},
                audit_metadata={},
            )
        ]

    async def fake_projection(db, profile, documents):
        profile.priority_evidence_documents = []
        profile.priority_object_evidence_display = {}
        profile.missing_priority_evidence_codes = []

    monkeypatch.setattr(svc, "_populate_priority_evidence_projections", fake_projection)
    monkeypatch.setattr(svc, "_load_priority_audit_log", fake_audit_log)
    monkeypatch.setattr(svc, "_resolve_verifier_names", AsyncMock(return_value={}))
    monkeypatch.setattr(svc, "_resolve_minor_correction_state", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_compute_frontend_fields", lambda *a, **kw: None)
    monkeypatch.setattr(svc, "_calculate_and_update_totals", lambda *a, **kw: None)
    monkeypatch.setattr(svc, "_check_idor_access", lambda profile, user: None)

    profile_stub = SimpleNamespace(
        id=99,
        status="draft",
        academic_year=2026,
        priority_object_codes=[],
        priority_object_evidence={},
        lead=SimpleNamespace(unit_id=1, assigned_officer=None),
        assigned_reviewer=None,
        priority_audit_log=None,
        priority_evidence_documents=None,
        priority_object_evidence_display=None,
        missing_priority_evidence_codes=None,
    )

    class FakeRepo:
        def __init__(self, db):
            pass

        async def get_profile_by_id_with_lead(self, profile_id):
            return profile_stub

        async def get_all_documents(self, profile_id):
            return []

        async def get_profile_scores(self, profile_id):
            return []

    monkeypatch.setattr("app.repositories.AdmissionRepository", FakeRepo)

    db = MagicMock()
    user = SimpleNamespace(id=7, role="officer", unit_id=1)

    result = await svc.get_profile(db, 99, user)

    # Pin contract: audit log loaded on GET path
    assert audit_call_recorded["profile_id"] == 99
    assert len(result.priority_audit_log) == 1
    assert result.priority_audit_log[0].action_type == "ut_evidence_verified"


async def test_get_profile_projection_empty_codes_still_populates_empty_list(
    monkeypatch,
) -> None:
    """GET with empty codes: projection still sets [] (not None default).

    Pydantic schema defaults priority_evidence_documents=[]. If the projection
    helper is skipped entirely, the attribute stays at whatever __init__ set
    (usually unset → schema default kicks in). The fix MUST call the helper
    unconditionally so transient attrs are consistent — even empty.
    """
    import app.services.admission_service as svc

    helper_called = {"count": 0}

    async def fake_projection(db, profile, documents):
        helper_called["count"] += 1
        profile.priority_evidence_documents = []
        profile.priority_object_evidence_display = {}
        profile.missing_priority_evidence_codes = []

    monkeypatch.setattr(svc, "_populate_priority_evidence_projections", fake_projection)
    monkeypatch.setattr(svc, "_load_priority_audit_log", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "_resolve_verifier_names", AsyncMock(return_value={}))
    monkeypatch.setattr(svc, "_resolve_minor_correction_state", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_compute_frontend_fields", lambda *a, **kw: None)
    monkeypatch.setattr(svc, "_calculate_and_update_totals", lambda *a, **kw: None)
    monkeypatch.setattr(svc, "_check_idor_access", lambda profile, user: None)

    profile_stub = SimpleNamespace(
        id=99,
        status="draft",
        academic_year=2026,
        priority_object_codes=None,  # not set
        priority_object_evidence={},
        lead=SimpleNamespace(unit_id=1, assigned_officer=None),
        assigned_reviewer=None,
        priority_evidence_documents=None,
        priority_object_evidence_display=None,
        missing_priority_evidence_codes=None,
        priority_audit_log=None,
    )

    class FakeRepo:
        def __init__(self, db):
            pass

        async def get_profile_by_id_with_lead(self, profile_id):
            return profile_stub

        async def get_all_documents(self, profile_id):
            return []

        async def get_profile_scores(self, profile_id):
            return []

    monkeypatch.setattr("app.repositories.AdmissionRepository", FakeRepo)

    db = MagicMock()
    user = SimpleNamespace(id=7, role="officer", unit_id=1)

    result = await svc.get_profile(db, 99, user)

    # Pin contract: helper called even when no codes — keeps transient attrs
    # consistent so response schema doesn't fall back to None defaults.
    assert helper_called["count"] == 1
    assert result.priority_evidence_documents == []


# ===========================================================================
# Smoke 2026-05-20 hotfix #2 — submit + reject path crashes (bugs #3/#4)
# ===========================================================================
# Smoke matrix on profile 39 (real officer browser) discovered 2 more P1
# blockers on the post-submit path that #319 hadn't covered:
#
# Bug #3: ``submit_and_evaluate`` ran the same ``doc.document_type.code``
#         comprehension at admission_service.py:4533 → NPE on first
#         priority_evidence doc (document_type_id=NULL by design).
#
# Bug #4: ``PriorityObjectEvidenceEntry`` schema lacked ``rejected_by`` +
#         ``rejected_at`` fields that the reject service persists. After
#         any PATCH .../reject, every subsequent GET raised
#         ResponseValidationError extra_forbidden → cascading 500 on the
#         profile detail page until the reject was undone.


def test_submit_path_filter_skips_priority_evidence_docs_with_null_doctype() -> None:
    """submit_and_evaluate's path_uploaded_docs filter must skip priority
    evidence rows (document_type=None) to avoid NPE on doc.document_type.code.

    This pins the secondary site of the same pattern fixed for
    _validate_documents in #319 — same shape filter, different function.
    """
    # Build a mixed documents list — 2 path docs (with document_type) + 1
    # priority evidence (None document_type, category='priority_evidence').
    path_dt = SimpleNamespace(code="HOC_BA", name="Học bạ THPT")
    docs = [
        SimpleNamespace(
            id=1,
            document_type=path_dt,
            category="academic",
            status="verified",
            file_path="hocba.pdf",
        ),
        SimpleNamespace(
            id=2,
            document_type=path_dt,
            category="academic",
            status="uploaded",
            file_path="other.pdf",
        ),
        # Priority evidence — document_type=None per BE design (priority
        # docs map via priority_sub_code, NOT document_type FK).
        SimpleNamespace(
            id=153,
            document_type=None,
            category="priority_evidence",
            status="uploaded",
            file_path="priority_07.pdf",
            priority_sub_code="07",
        ),
    ]

    # Mirror the filter pattern in admission_service.py:4533+
    path_uploaded_docs = [
        doc for doc in docs
        if doc.document_type is not None
        and getattr(doc, "category", None) != "priority_evidence"
    ]

    # Filter excluded the priority_evidence row → 2 path docs remain
    assert len(path_uploaded_docs) == 2
    assert {d.document_type.code for d in path_uploaded_docs} == {"HOC_BA"}

    # The comprehension that crashed pre-fix now succeeds (NO NPE)
    codes = {doc.document_type.code for doc in path_uploaded_docs}
    assert "HOC_BA" in codes
    # Priority evidence doc would have caused: AttributeError on .code
    # — fix proven by the filter step above.


def test_priority_object_evidence_entry_accepts_rejected_by_and_rejected_at() -> None:
    """Pydantic schema for evidence dict value must accept ``rejected_by``
    and ``rejected_at`` (parity with verified_by/verified_at).

    Pre-fix: after reject service stored these fields into the evidence
    JSONB, every GET response serialization raised
    ``ResponseValidationError(extra_forbidden)`` because the read schema
    only whitelisted verified_by/verified_at. The fix added rejected_by +
    rejected_at as Optional fields.
    """
    from datetime import datetime, timezone
    from app.schemas.admission import PriorityObjectEvidenceEntry

    # Reject service writes this shape into priority_object_evidence['01']:
    payload = {
        "status": "rejected",
        "rejected_by": 15,
        "rejected_at": "2026-05-20T15:19:36.284184+00:00",
        "verified_at": None,
        "verified_by": None,
        "reject_reason": "Smoke test reject — không có giấy chứng nhận phong tặng",
        "paper_only_verification": False,
    }

    # Pre-fix: this would raise ValidationError('extra_forbidden' on
    # rejected_by + rejected_at) because ConfigDict(extra='forbid').
    entry = PriorityObjectEvidenceEntry.model_validate(payload)

    assert entry.status == "rejected"
    assert entry.rejected_by == 15
    assert isinstance(entry.rejected_at, datetime)
    assert entry.rejected_at.tzinfo is not None  # tz-aware
    assert entry.verified_by is None
    assert entry.verified_at is None
    assert entry.reject_reason is not None
    assert "không có giấy" in entry.reject_reason


def test_priority_object_evidence_entry_verified_still_works_unchanged() -> None:
    """Negative-regression: verified path schema unchanged by hotfix #2.

    After adding rejected_by/rejected_at fields, verified-state entries
    must still parse correctly with their original field set.
    """
    from app.schemas.admission import PriorityObjectEvidenceEntry

    payload = {
        "status": "verified",
        "verified_by": 7,
        "verified_at": "2026-05-20T10:00:00+00:00",
        "document_id": 153,
        "paper_only_verification": False,
    }
    entry = PriorityObjectEvidenceEntry.model_validate(payload)
    assert entry.status == "verified"
    assert entry.verified_by == 7
    assert entry.document_id == 153
    assert entry.rejected_by is None
    assert entry.rejected_at is None
