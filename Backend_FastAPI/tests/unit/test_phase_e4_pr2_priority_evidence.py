"""Unit tests for Q9 #07 Phase E.4 PR-2 priority evidence service contracts.

Covers:
* ``untick_priority_evidence`` (priority_override_service) — happy path,
  version conflict, sub_code-not-in-codes, finalize callback unlink semantics.
* ``upload_priority_evidence_document`` (admission_service) — guard checks
  fire BEFORE file IO (status whitelist + sub_code-in-codes + catalog
  lookup). Full filesystem happy-path defer to integration test.

Mock pattern mirrors tests/unit/test_priority_evidence_service.py to keep
test fixture style consistent across Phase E.3/E.4 unit suite.
"""
from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    status: str = "submitted",
    version: int = 5,
    codes: list = None,
    evidence: dict = None,
    academic_year: int = 2026,
):
    return SimpleNamespace(
        id=42,
        lead_id=100,
        status=status,
        version=version,
        academic_year=academic_year,
        priority_object_codes=codes or ["04", "07"],
        priority_object_evidence=evidence or {},
        priority_resolution_snapshot={},
    )


def _make_actor(role: str = "officer", user_id: int = 7):
    return SimpleNamespace(
        id=user_id,
        role=role,
        full_name=f"User {user_id}",
        email=f"user{user_id}@example.com",
    )


def _make_db_for_untick(
    doc_row=None,
    catalog_rows=None,
):
    """Mock DB for untick: db.execute() resolves ProfileDocument lookup +
    catalog query for bucket recompute.
    """
    profile_doc_result = MagicMock()
    profile_doc_result.scalar_one_or_none = MagicMock(return_value=doc_row)

    bucket_catalog_result = MagicMock()
    bucket_catalog_result.all = MagicMock(return_value=catalog_rows or [])

    call_state = {"count": 0}

    async def _execute(stmt, *args, **kwargs):
        # First call = ProfileDocument lookup. Subsequent = bucket recompute catalog.
        call_state["count"] += 1
        if call_state["count"] == 1:
            return profile_doc_result
        return bucket_catalog_result

    db = MagicMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _find_audit_rows(db):
    from app import models
    return [
        c[0][0]
        for c in db.add.call_args_list
        if isinstance(c[0][0], models.PriorityAuditLog)
    ]


# ---------------------------------------------------------------------------
# Untick — happy path
# ---------------------------------------------------------------------------


async def test_untick_happy_removes_codes_and_evidence_and_audits() -> None:
    """Untick UT04 (no file) → cleanup JSONB + INSERT audit row + bump version."""
    from app.services.priority_override_service import untick_priority_evidence

    profile = _make_profile(
        codes=["04", "07"],
        evidence={
            "04": {"status": "verified", "verified_by": 7, "document_id": None},
            "07": {"status": "pending"},
        },
    )
    actor = _make_actor("officer", user_id=7)
    db = _make_db_for_untick(doc_row=None)  # no file attached

    updated, finalize_cb = await untick_priority_evidence(
        db, profile, sub_code="04", actor=actor, expected_version=5,
    )

    # JSONB updates: codes + evidence both lose '04'
    assert updated.priority_object_codes == ["07"]
    assert "04" not in updated.priority_object_evidence

    # Audit row INSERTed
    audit_rows = _find_audit_rows(db)
    assert len(audit_rows) == 1
    audit = audit_rows[0]
    assert audit.action_type == "ut_evidence_untick"
    assert audit.actor_id == 7
    assert audit.old_value["sub_code"] == "04"
    assert audit.old_value["had_document"] is False
    assert audit.new_value["untick"] is True
    assert audit.audit_metadata["file_unlinked"] is False

    # Version bumped + flush (no commit)
    assert updated.version == 6
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    db.delete.assert_not_awaited()  # no doc row to delete
    assert callable(finalize_cb)


async def test_untick_with_file_calls_db_delete() -> None:
    """Untick UT07 với file đính kèm → db.delete(doc_row) called + audit
    flags file_unlinked=True."""
    from app.services.priority_override_service import untick_priority_evidence

    doc_row = SimpleNamespace(
        id=99,
        file_path="uploads/admissions/42/priority_07_abc123.pdf",
        priority_sub_code="07",
        category="priority_evidence",
    )
    profile = _make_profile(
        codes=["04", "07"],
        evidence={"07": {"status": "verified", "verified_by": 7, "document_id": 99}},
    )
    actor = _make_actor("officer")
    db = _make_db_for_untick(doc_row=doc_row)

    updated, _ = await untick_priority_evidence(
        db, profile, sub_code="07", actor=actor, expected_version=5,
    )

    # db.delete called với doc_row
    db.delete.assert_awaited_once_with(doc_row)

    # Audit captures file_unlinked + had_document
    audit = _find_audit_rows(db)[0]
    assert audit.old_value["had_document"] is True
    assert audit.audit_metadata["file_unlinked"] is True

    # Profile cleaned up
    assert "07" not in updated.priority_object_evidence
    assert "07" not in updated.priority_object_codes


# ---------------------------------------------------------------------------
# Untick — guards
# ---------------------------------------------------------------------------


async def test_untick_version_conflict_raises() -> None:
    """Version mismatch FIRST (per memory version-guard-before-state-machine)."""
    from app.services.priority_override_service import untick_priority_evidence
    from app.utils.exceptions import ConflictError

    profile = _make_profile(version=5)
    actor = _make_actor("officer")
    db = _make_db_for_untick()

    with pytest.raises(ConflictError):
        await untick_priority_evidence(
            db, profile, sub_code="04", actor=actor, expected_version=4,
        )


async def test_untick_sub_code_not_in_codes_raises() -> None:
    """sub_code MUST be in profile.priority_object_codes."""
    from app.services.priority_override_service import untick_priority_evidence
    from app.utils.exceptions import BusinessRuleViolation

    profile = _make_profile(codes=["04"])  # 07 NOT in codes
    actor = _make_actor("officer")
    db = _make_db_for_untick()

    with pytest.raises(BusinessRuleViolation):
        await untick_priority_evidence(
            db, profile, sub_code="07", actor=actor, expected_version=5,
        )


async def test_untick_hard_denied_status_raises() -> None:
    """draft/withdrawn/dropped status → BusinessRuleViolation."""
    from app.services.priority_override_service import untick_priority_evidence
    from app.utils.exceptions import BusinessRuleViolation

    profile = _make_profile(status="draft")
    actor = _make_actor("officer")
    db = _make_db_for_untick()

    with pytest.raises(BusinessRuleViolation):
        await untick_priority_evidence(
            db, profile, sub_code="04", actor=actor, expected_version=5,
        )


# ---------------------------------------------------------------------------
# Untick — finalize callback (ADM-007 file unlink)
# ---------------------------------------------------------------------------


async def test_untick_finalize_commit_false_keeps_file() -> None:
    """finalize(committed=False) MUST NOT delete file (DB rollback restores
    doc_row → file still referenced).
    """
    from app.services.priority_override_service import untick_priority_evidence

    # Create real tempfile so finalize callback có real path to NOT delete
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        doc_row = SimpleNamespace(
            id=99, file_path=tmp_path, priority_sub_code="07",
            category="priority_evidence",
        )
        profile = _make_profile(codes=["07"], evidence={"07": {"status": "pending"}})
        actor = _make_actor("officer")
        db = _make_db_for_untick(doc_row=doc_row)

        _, finalize_cb = await untick_priority_evidence(
            db, profile, sub_code="07", actor=actor, expected_version=5,
        )

        # Simulate commit failure → finalize(False)
        await finalize_cb(False)
        # File MUST still exist (no unlink on rollback)
        assert os.path.exists(tmp_path), (
            "ADM-007 contract: commit fail → finalize(False) must NOT unlink"
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def test_untick_finalize_commit_true_unlinks_file() -> None:
    """finalize(committed=True) MUST delete the staged file path."""
    from app.services.priority_override_service import untick_priority_evidence

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        doc_row = SimpleNamespace(
            id=99, file_path=tmp_path, priority_sub_code="07",
            category="priority_evidence",
        )
        profile = _make_profile(codes=["07"], evidence={"07": {"status": "pending"}})
        actor = _make_actor("officer")
        db = _make_db_for_untick(doc_row=doc_row)

        _, finalize_cb = await untick_priority_evidence(
            db, profile, sub_code="07", actor=actor, expected_version=5,
        )

        # Simulate commit success → finalize(True) unlinks
        await finalize_cb(True)
        assert not os.path.exists(tmp_path), (
            "ADM-007 contract: commit success → finalize(True) unlinks file"
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def test_untick_finalize_handles_missing_file_silent() -> None:
    """finalize(True) khi file đã missing (vd manual cleanup) → log warning,
    NOT raise. DB delete already settled."""
    from app.services.priority_override_service import untick_priority_evidence

    doc_row = SimpleNamespace(
        id=99,
        file_path="/nonexistent/path/that/never/existed.pdf",
        priority_sub_code="07",
        category="priority_evidence",
    )
    profile = _make_profile(codes=["07"], evidence={"07": {"status": "pending"}})
    actor = _make_actor("officer")
    db = _make_db_for_untick(doc_row=doc_row)

    _, finalize_cb = await untick_priority_evidence(
        db, profile, sub_code="07", actor=actor, expected_version=5,
    )

    # Should not raise even though file doesn't exist
    await finalize_cb(True)
    # If we reach here, contract held


# ---------------------------------------------------------------------------
# Upload — guard checks (fail BEFORE file IO)
# ---------------------------------------------------------------------------


def _make_upload_db(catalog_has_sub_code: bool = True):
    """Mock DB cho upload guard tests — catalog.scalar_one_or_none()
    returns either id (sub_code in catalog) or None."""
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none = MagicMock(
        return_value=1 if catalog_has_sub_code else None
    )

    async def _execute(stmt, *args, **kwargs):
        return catalog_result

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _make_mock_upload_file():
    """Minimal UploadFile mock — guards don't touch file IO."""
    f = MagicMock()
    f.content_type = "application/pdf"
    f.filename = "test.pdf"
    return f


async def test_upload_wrong_status_raises() -> None:
    """Upload trên profile status 'enrolled' → BusinessRuleViolation
    (not in APPLICANT_DOC_MUTATION_STATES)."""
    from app.services import admission_service
    from app.utils.exceptions import BusinessRuleViolation

    profile = _make_profile(status="enrolled", codes=["04"])
    actor = _make_actor("officer")
    db = _make_upload_db()

    # Patch get_profile to return our SimpleNamespace
    import app.services.admission_service as admission_service_mod
    original = admission_service_mod.get_profile

    async def mock_get_profile(db_, profile_id, current_user):
        return profile

    admission_service_mod.get_profile = mock_get_profile
    try:
        with pytest.raises(BusinessRuleViolation, match="enrolled"):
            await admission_service.upload_priority_evidence_document(
                db=db,
                profile_id=42,
                sub_code="04",
                file=_make_mock_upload_file(),
                current_user=actor,
            )
    finally:
        admission_service_mod.get_profile = original


async def test_upload_sub_code_not_in_codes_raises() -> None:
    """sub_code MUST be in profile.priority_object_codes (officer ghi nhận
    diện UT TRƯỚC khi upload)."""
    from app.services import admission_service
    from app.utils.exceptions import BusinessRuleViolation

    profile = _make_profile(status="draft", codes=["04"])  # 07 NOT in codes
    actor = _make_actor("officer")
    db = _make_upload_db()

    import app.services.admission_service as admission_service_mod
    original = admission_service_mod.get_profile

    async def mock_get_profile(db_, profile_id, current_user):
        return profile

    admission_service_mod.get_profile = mock_get_profile
    try:
        with pytest.raises(BusinessRuleViolation, match="priority_object_codes"):
            await admission_service.upload_priority_evidence_document(
                db=db,
                profile_id=42,
                sub_code="07",
                file=_make_mock_upload_file(),
                current_user=actor,
            )
    finally:
        admission_service_mod.get_profile = original


async def test_upload_sub_code_not_in_catalog_raises() -> None:
    """sub_code MUST exist trong PriorityObjectConfig catalog cho academic_year."""
    from app.services import admission_service
    from app.utils.exceptions import BusinessRuleViolation

    profile = _make_profile(status="draft", codes=["99"])  # 99 in codes but not catalog
    actor = _make_actor("officer")
    db = _make_upload_db(catalog_has_sub_code=False)  # catalog returns None

    import app.services.admission_service as admission_service_mod
    original = admission_service_mod.get_profile

    async def mock_get_profile(db_, profile_id, current_user):
        return profile

    admission_service_mod.get_profile = mock_get_profile
    try:
        with pytest.raises(BusinessRuleViolation, match="catalog"):
            await admission_service.upload_priority_evidence_document(
                db=db,
                profile_id=42,
                sub_code="99",
                file=_make_mock_upload_file(),
                current_user=actor,
            )
    finally:
        admission_service_mod.get_profile = original


# ---------------------------------------------------------------------------
# Upload — happy + re-upload (P1 contract) + finalize true/false
# ---------------------------------------------------------------------------

# Minimal valid PDF bytes — magic "%PDF" + padding để _sniff_document_signature
# recognize without large fixture.
_MINIMAL_PDF_BYTES = b"%PDF-1.4\n%\xff\xff\xff\xff\n" + b"x" * 200


class _MockUploadFile:
    """Minimal FastAPI UploadFile mock supporting .file.seek/.tell/.read +
    .content_type + .filename."""

    def __init__(self, content: bytes, content_type: str = "application/pdf",
                 filename: str = "test.pdf"):
        import io
        self.content_type = content_type
        self.filename = filename
        self.file = io.BytesIO(content)


def _make_upload_db_full(
    *,
    existing_doc=None,
    catalog_has_sub_code: bool = True,
    bucket_catalog_rows=None,
):
    """Multi-call DB mock. Order:
    1. Catalog lookup (PriorityObjectConfig.id) — guard check
    2. Existing ProfileDocument lookup
    3. (Re-upload only) bucket recompute catalog rows
    """
    catalog_result = MagicMock()
    catalog_result.scalar_one_or_none = MagicMock(
        return_value=1 if catalog_has_sub_code else None
    )
    existing_doc_result = MagicMock()
    existing_doc_result.scalar_one_or_none = MagicMock(return_value=existing_doc)
    bucket_result = MagicMock()
    bucket_result.all = MagicMock(return_value=bucket_catalog_rows or [])

    call_state = {"count": 0}

    async def _execute(stmt, *args, **kwargs):
        call_state["count"] += 1
        if call_state["count"] == 1:
            return catalog_result
        if call_state["count"] == 2:
            return existing_doc_result
        return bucket_result

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(side_effect=_execute)
    return db


def _setup_upload_mocks(monkeypatch, tmp_path, profile, documents=None):
    """Patch get_profile + _sniff_document_signature + repo +
    _populate_response_fields + cwd to tmp_path."""
    import app.services.admission_service as svc

    async def mock_get_profile(db_, pid, user):
        return profile

    def mock_sniff(file_obj):
        pos = file_obj.tell()
        file_obj.seek(0)
        head = file_obj.read(4)
        file_obj.seek(pos)
        return "pdf" if head == b"%PDF" else None

    async def mock_get_all_documents(self, pid):
        return documents or []

    async def mock_populate(db, p, u, documents=None):
        return None

    monkeypatch.setattr(svc, "get_profile", mock_get_profile)
    monkeypatch.setattr(svc, "_sniff_document_signature", mock_sniff)
    monkeypatch.setattr(svc, "_populate_response_fields", mock_populate)

    from app.repositories.admission_repository import AdmissionRepository
    monkeypatch.setattr(
        AdmissionRepository, "get_all_documents", mock_get_all_documents
    )

    monkeypatch.chdir(tmp_path)


async def test_upload_happy_creates_new_doc_row(monkeypatch, tmp_path) -> None:
    """Happy path: new sub_code upload → new ProfileDocument với
    category='priority_evidence' + priority_sub_code + status='uploaded' +
    document_type_id=None (critical: no FK to ConfigDocumentType)."""
    from app.services import admission_service
    from app import models

    profile = _make_profile(status="draft", codes=["04"], evidence={})
    actor = _make_actor("officer")
    db = _make_upload_db_full(existing_doc=None)

    _setup_upload_mocks(monkeypatch, tmp_path, profile)

    file = _MockUploadFile(_MINIMAL_PDF_BYTES)

    _, finalize = await admission_service.upload_priority_evidence_document(
        db=db, profile_id=42, sub_code="04", file=file, current_user=actor,
    )

    added = [c[0][0] for c in db.add.call_args_list]
    new_docs = [a for a in added if isinstance(a, models.ProfileDocument)]
    assert len(new_docs) == 1
    new_doc = new_docs[0]
    assert new_doc.category == "priority_evidence"
    assert new_doc.priority_sub_code == "04"
    assert new_doc.document_type_id is None
    assert new_doc.status == "uploaded"
    assert new_doc.file_path.endswith(".pdf")
    assert "priority_04_" in new_doc.file_path

    assert callable(finalize)
    db.flush.assert_awaited()


async def test_reupload_verified_resets_jsonb_and_recomputes_bucket(
    monkeypatch, tmp_path,
) -> None:
    """P1 fix contract: re-upload UT04 đang verified → evidence JSONB
    reset về 'pending' + ut_verified_bucket recomputed + version bumped.

    Without this fix engine reads stale status='verified' từ JSONB và
    tiếp tục tính bonus dù file mới upload cần re-verify.
    """
    from app.services import admission_service

    existing_doc = SimpleNamespace(
        id=99,
        category="priority_evidence",
        priority_sub_code="04",
        document_type_id=None,
        file_path="uploads/admissions/42/priority_04_old.pdf",
        status="verified",
        uploaded_at=None,
        verified_at="2026-05-20T08:00:00+00:00",
        verified_by=7,
        rejected_at=None,
        rejected_by=None,
        rejection_reason=None,
    )
    profile = _make_profile(
        status="submitted", version=10, codes=["04"],
        evidence={
            "04": {
                "status": "verified",
                "verified_by": 7,
                "verified_at": "2026-05-20T08:00:00+00:00",
                "document_id": 99,
                "paper_only_verification": False,
                "requested_at": "2026-05-20T07:00:00+00:00",
            }
        },
    )
    profile.priority_resolution_snapshot = {
        "kv_resolved": "KV1",
        "ut_verified_bucket": {"applied_code": "04", "applied_rate": 1.0},
    }
    actor = _make_actor("officer")
    # After reset → no verified codes → bucket falls back to None
    db = _make_upload_db_full(existing_doc=existing_doc, bucket_catalog_rows=[])

    _setup_upload_mocks(monkeypatch, tmp_path, profile, documents=[existing_doc])

    file = _MockUploadFile(_MINIMAL_PDF_BYTES)

    await admission_service.upload_priority_evidence_document(
        db=db, profile_id=42, sub_code="04", file=file, current_user=actor,
    )

    # P1: evidence JSONB reset
    entry = profile.priority_object_evidence["04"]
    assert entry["status"] == "pending", (
        "P1 fix: re-upload phải reset evidence status về pending — "
        "engine reads bonus eligibility từ JSONB, không phải document row"
    )
    assert entry["verified_by"] is None
    assert entry["verified_at"] is None
    assert entry["document_id"] is None
    assert entry["paper_only_verification"] is False
    # requested_at preserved
    assert entry["requested_at"] == "2026-05-20T07:00:00+00:00"

    # Bucket recomputed → no verified codes left
    bucket = profile.priority_resolution_snapshot["ut_verified_bucket"]
    assert bucket["applied_code"] is None
    assert bucket["applied_rate"] == 0

    # Version bumped (JSONB mutation = optimistic-lock advance)
    assert profile.version == 11

    # Document row also updated
    assert existing_doc.status == "uploaded"
    assert existing_doc.verified_by is None


async def test_reupload_pending_does_not_bump_version(
    monkeypatch, tmp_path,
) -> None:
    """Re-upload trên evidence status='pending' (chưa verify): KHÔNG cần
    reset JSONB (already pending) + KHÔNG bump version (chỉ document row
    changes; evidence unchanged)."""
    from app.services import admission_service

    existing_doc = SimpleNamespace(
        id=99, category="priority_evidence", priority_sub_code="04",
        document_type_id=None,
        file_path="uploads/admissions/42/priority_04_old.pdf",
        status="uploaded",
        uploaded_at=None, verified_at=None, verified_by=None,
        rejected_at=None, rejected_by=None, rejection_reason=None,
    )
    profile = _make_profile(
        status="submitted", version=5, codes=["04"],
        evidence={"04": {"status": "pending"}},
    )
    actor = _make_actor("officer")
    db = _make_upload_db_full(existing_doc=existing_doc)

    _setup_upload_mocks(monkeypatch, tmp_path, profile, documents=[existing_doc])

    file = _MockUploadFile(_MINIMAL_PDF_BYTES)

    await admission_service.upload_priority_evidence_document(
        db=db, profile_id=42, sub_code="04", file=file, current_user=actor,
    )

    assert profile.priority_object_evidence["04"]["status"] == "pending"
    assert profile.version == 5


async def test_upload_finalize_true_promotes_staging(
    monkeypatch, tmp_path,
) -> None:
    """finalize(True) MUST os.replace staging file to final path."""
    from app.services import admission_service

    profile = _make_profile(status="draft", codes=["04"], evidence={})
    actor = _make_actor("officer")
    db = _make_upload_db_full(existing_doc=None)

    _setup_upload_mocks(monkeypatch, tmp_path, profile)

    file = _MockUploadFile(_MINIMAL_PDF_BYTES)

    _, finalize = await admission_service.upload_priority_evidence_document(
        db=db, profile_id=42, sub_code="04", file=file, current_user=actor,
    )

    upload_dir = tmp_path / "uploads" / "admissions" / "42"
    staging_files = list(upload_dir.glob(".staging.*"))
    final_files = [
        f for f in upload_dir.glob("priority_04_*")
        if not f.name.startswith(".staging.")
    ]
    assert len(staging_files) == 1, "staging file MUST exist pre-finalize"
    assert len(final_files) == 0, "final file MUST NOT exist pre-finalize"

    await finalize(True)

    staging_files = list(upload_dir.glob(".staging.*"))
    final_files = [
        f for f in upload_dir.glob("priority_04_*")
        if not f.name.startswith(".staging.")
    ]
    assert len(staging_files) == 0, "staging file MUST be promoted"
    assert len(final_files) == 1, "final file MUST exist after finalize(True)"


async def test_upload_finalize_false_cleans_staging(
    monkeypatch, tmp_path,
) -> None:
    """finalize(False) MUST clean staging + NOT create final (rollback path)."""
    from app.services import admission_service

    profile = _make_profile(status="draft", codes=["04"], evidence={})
    actor = _make_actor("officer")
    db = _make_upload_db_full(existing_doc=None)

    _setup_upload_mocks(monkeypatch, tmp_path, profile)

    file = _MockUploadFile(_MINIMAL_PDF_BYTES)

    _, finalize = await admission_service.upload_priority_evidence_document(
        db=db, profile_id=42, sub_code="04", file=file, current_user=actor,
    )

    upload_dir = tmp_path / "uploads" / "admissions" / "42"
    assert len(list(upload_dir.glob(".staging.*"))) == 1

    await finalize(False)

    staging_files = list(upload_dir.glob(".staging.*"))
    final_files = [
        f for f in upload_dir.glob("priority_04_*")
        if not f.name.startswith(".staging.")
    ]
    assert len(staging_files) == 0, "staging cleaned on rollback"
    assert len(final_files) == 0, "no final file on rollback"
