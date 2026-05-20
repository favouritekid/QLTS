"""Regression tests for Q9 #07 Phase E.4 audit fix contracts.

Covers the 4 audit-flagged contracts shipped sau Hour 0-3 + G0 commit
checkpoint. Each test pins a single contract — failure shows up immediately
at the contract boundary, not deep downstream.

Contracts:
1. ``paper_only_verification`` persisted when ``document_id=None`` (Decision #3)
2. ``paper_only_verification=False`` when document_id provided (positive case)
3. ``priority_service.resolve_law_citation()`` map alignment (Phase E.4 G0a)
4. ``PreviewPriorityKvResponse.rule_law_citation`` field exists trên schema
5. ``_strip_display_fields_from_evidence()`` removes display fields, preserves persisted
6. ``_strip_display_fields_from_evidence()`` handles non-dict entry edge case
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers — mirror tests/unit/test_priority_evidence_service.py style
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    status: str = "submitted",
    version: int = 5,
    codes: list = None,
    evidence: dict = None,
):
    return SimpleNamespace(
        id=42,
        lead_id=100,
        status=status,
        version=version,
        academic_year=2026,
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


def _make_db(catalog_rows=None, doc_row=None):
    """Mock DB. Phase E.4 PR-2 P1: verify_object_evidence now does server-side
    ProfileDocument lookup. Smart dispatch by SQL target — ProfileDocument
    select → doc_row, others → catalog (bucket recompute)."""
    catalog_result = MagicMock()
    catalog_result.all = MagicMock(return_value=catalog_rows or [])

    doc_result = MagicMock()
    doc_result.scalar_one_or_none = MagicMock(return_value=doc_row)

    async def _execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        if "profile_document" in stmt_str:
            return doc_result
        return catalog_result

    db = MagicMock()
    db.add = MagicMock()
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
# Test 1+2: paper_only_verification flag (audit fix P0)
# ---------------------------------------------------------------------------


async def test_verify_paper_only_when_document_id_none() -> None:
    """Decision #3: officer verify UT cho hồ sơ giấy → paper_only_verification=True
    persist trong evidence entry + audit log new_value + audit_metadata.

    Default case trong nghiệp vụ VN — KHÔNG phải bypass. Tone neutral.
    """
    from app.services.priority_override_service import verify_object_evidence

    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    db = _make_db(catalog_rows=[("04", Decimal("1.00"))])

    updated, _ = await verify_object_evidence(
        db, profile, sub_code="04", document_id=None,
        actor=actor, expected_version=5,
    )

    # Contract: paper_only_verification=True khi không có file
    entry = updated.priority_object_evidence["04"]
    assert entry["status"] == "verified"
    assert entry["document_id"] is None
    assert entry["paper_only_verification"] is True, (
        "Decision #3: hồ sơ giấy verify phải persist paper_only_verification=True"
    )

    # Contract: audit log capture flag để thanh tra truy được
    audit = _find_audit_rows(db)[0]
    assert audit.new_value["paper_only_verification"] is True
    assert audit.audit_metadata["paper_only_verification"] is True


async def test_verify_paper_only_false_when_document_id_provided() -> None:
    """Positive case: officer verify với scan file → paper_only_verification=False.

    Audit log ghi flag=False để analytics post-launch quantify ratio
    paper-only vs file-backed verify.

    Phase E.4 PR-2 P1: server-side doc lookup — client document_id=42
    matches doc_row.id=42 → bind successful, paper_only=False.
    """
    from app.services.priority_override_service import verify_object_evidence
    from types import SimpleNamespace

    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    doc_row = SimpleNamespace(
        id=42, category="priority_evidence", priority_sub_code="04",
        file_path="uploads/admissions/42/priority_04_xyz.pdf",
    )
    db = _make_db(catalog_rows=[("04", Decimal("1.00"))], doc_row=doc_row)

    updated, _ = await verify_object_evidence(
        db, profile, sub_code="04", document_id=42,
        actor=actor, expected_version=5,
    )

    entry = updated.priority_object_evidence["04"]
    assert entry["document_id"] == 42
    assert entry["paper_only_verification"] is False

    audit = _find_audit_rows(db)[0]
    assert audit.new_value["paper_only_verification"] is False
    assert audit.audit_metadata["paper_only_verification"] is False


# ---------------------------------------------------------------------------
# Test P1 fix audit cycle: verify server-side document binding
# ---------------------------------------------------------------------------


async def test_verify_auto_binds_doc_when_payload_null_and_row_exists() -> None:
    """P1 fix contract: FE hardcodes document_id=null trong verify request.
    Nếu profile has uploaded priority_evidence file → server auto-bind doc.id
    + paper_only_verification=False (NOT paper-only, file IS attached).

    Without server-side lookup: FE null → paper_only=True dù file đã scan.
    Officer workflow đúng nhưng audit log sai → thanh tra không truy được file.
    """
    from app.services.priority_override_service import verify_object_evidence
    from types import SimpleNamespace

    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    # Server-side row exists từ prior upload
    doc_row = SimpleNamespace(
        id=99, category="priority_evidence", priority_sub_code="04",
        file_path="uploads/admissions/42/priority_04_uploaded.pdf",
    )
    db = _make_db(catalog_rows=[("04", Decimal("1.00"))], doc_row=doc_row)

    # Client gửi null (FE chưa kịp re-fetch profile after upload)
    updated, _ = await verify_object_evidence(
        db, profile, sub_code="04", document_id=None,
        actor=actor, expected_version=5,
    )

    entry = updated.priority_object_evidence["04"]
    # Auto-bound to server doc row
    assert entry["document_id"] == 99, (
        "P1 server-side bind: client null + row exists → auto-bind doc.id"
    )
    # NOT paper-only — file actually attached
    assert entry["paper_only_verification"] is False, (
        "P1 contract: row exists → paper_only=False dù client gửi null"
    )

    # Audit reflects server truth, not client claim
    audit = _find_audit_rows(db)[0]
    assert audit.new_value["document_id"] == 99
    assert audit.new_value["paper_only_verification"] is False


async def test_verify_rejects_mismatched_document_id() -> None:
    """P1 fix contract: client gửi document_id KHÔNG match server row → refuse.

    Defense vs (a) client stale state sending old doc_id; (b) malicious client
    trying to bind cross-profile document_id; (c) FE bug sending wrong id.
    Server-side ownership truth wins.
    """
    from app.services.priority_override_service import verify_object_evidence
    from app.utils.exceptions import BusinessRuleViolation
    from types import SimpleNamespace

    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    # Server has row id=99 for UT04
    doc_row = SimpleNamespace(
        id=99, category="priority_evidence", priority_sub_code="04",
        file_path="uploads/admissions/42/priority_04.pdf",
    )
    db = _make_db(catalog_rows=[("04", Decimal("1.00"))], doc_row=doc_row)

    # Client gửi id=999 (lie / stale / cross-profile)
    with pytest.raises(BusinessRuleViolation, match="không match"):
        await verify_object_evidence(
            db, profile, sub_code="04", document_id=999,
            actor=actor, expected_version=5,
        )


async def test_verify_rejects_client_doc_id_when_no_server_row() -> None:
    """P1 edge case: client gửi document_id nhưng server có NO row →
    refuse (case 4 — mismatch, no doc row to bind).

    Officer phải verify với null nếu muốn paper-only, hoặc upload file trước.
    """
    from app.services.priority_override_service import verify_object_evidence
    from app.utils.exceptions import BusinessRuleViolation

    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    db = _make_db(catalog_rows=[("04", Decimal("1.00"))], doc_row=None)

    with pytest.raises(BusinessRuleViolation, match="không match"):
        await verify_object_evidence(
            db, profile, sub_code="04", document_id=42,
            actor=actor, expected_version=5,
        )


# ---------------------------------------------------------------------------
# Test 3+4: rule_law_citation (audit fix P1)
# ---------------------------------------------------------------------------


def test_resolve_law_citation_map_alignment() -> None:
    """RULE_LAW_CITATION keys MUST align with engine resolve_kv_for_profile
    rule_applied emit values. Mismatch = silent None law citation cho FE.
    """
    from app.services.priority_service import resolve_law_citation

    # 4 keys với citation
    assert resolve_law_citation("longest_duration") == "TT 05/2021 Phụ lục 01 Mục 5.b"
    assert resolve_law_citation("tiebreak_graduation_school") == "TT 05/2021 Phụ lục 01 Mục 5.a"
    assert resolve_law_citation("commune_lookup") == "TT 05/2021 Phụ lục 01 Mục 4"
    assert resolve_law_citation("manual_override") == "TT 05/2021 Phụ lục 01 Mục 6 (admin override)"

    # ambiguous → None (no clear citation)
    assert resolve_law_citation("ambiguous_requires_manual") is None

    # None input → None output (defensive)
    assert resolve_law_citation(None) is None
    assert resolve_law_citation("") is None

    # Unknown rule_applied → None (defensive — không crash)
    assert resolve_law_citation("unknown_future_rule") is None


def test_preview_priority_kv_response_schema_has_rule_law_citation() -> None:
    """Schema field contract: FE Zod schema mirror sẽ break nếu BE field rename."""
    from app.schemas.admission import PreviewPriorityKvResponse

    assert "rule_law_citation" in PreviewPriorityKvResponse.model_fields, (
        "Phase E.4 G0a: rule_law_citation field missing trên response schema"
    )

    # Default None (Optional) — không required cho old preview consumers
    instance = PreviewPriorityKvResponse(
        kv_resolved="KV1",
        pathway="thpt_multi_school",
        rule_applied="longest_duration",
        requires_manual_override=False,
    )
    assert instance.rule_law_citation is None


# ---------------------------------------------------------------------------
# Test 5+6: _strip_display_fields_from_evidence (audit fix P1 — G3 cleaner)
# ---------------------------------------------------------------------------


def test_strip_display_fields_removes_denormalized() -> None:
    """G3 cleaner contract: display-only fields (verified_by_name +
    document_file_path) MUST be removed before writing JSONB column.

    Persisted fields (status, verified_by, document_id, paper_only_verification,
    reject_reason, verified_at, rejected_*) MUST be preserved unchanged.
    """
    from app.services.admission_service import _strip_display_fields_from_evidence

    enriched = {
        "04": {
            "status": "verified",
            "verified_by": 15,
            "verified_by_name": "Trịnh Tố Uyên",  # display only
            "verified_at": "2026-05-20T10:00:00+00:00",
            "document_id": 42,
            "document_file_path": "uploads/admissions/17/x.pdf",  # display only
            "paper_only_verification": False,  # persisted
        },
        "07": {
            "status": "rejected",
            "reject_reason": "Giấy chứng nhận hết hạn",
            "rejected_by": 15,
            "rejected_at": "2026-05-20T10:00:00+00:00",
        },
    }

    cleaned = _strip_display_fields_from_evidence(enriched)

    # Display fields removed
    assert "verified_by_name" not in cleaned["04"]
    assert "document_file_path" not in cleaned["04"]

    # Persisted fields preserved on verified entry
    assert cleaned["04"]["status"] == "verified"
    assert cleaned["04"]["verified_by"] == 15
    assert cleaned["04"]["verified_at"] == "2026-05-20T10:00:00+00:00"
    assert cleaned["04"]["document_id"] == 42
    assert cleaned["04"]["paper_only_verification"] is False

    # Rejected entry unchanged (no display fields to strip)
    assert cleaned["07"] == enriched["07"]

    # Idempotent — running twice same as once
    cleaned_twice = _strip_display_fields_from_evidence(cleaned)
    assert cleaned_twice == cleaned


def test_strip_display_fields_handles_non_dict_entry() -> None:
    """Edge case: malformed evidence entry (vd legacy string value). Helper
    must pass through without raising — defensive guard."""
    from app.services.admission_service import _strip_display_fields_from_evidence

    weird = {
        "04": "legacy_string_value",  # not a dict
        "07": None,
        "08": {"status": "pending"},  # valid dict
    }

    cleaned = _strip_display_fields_from_evidence(weird)

    # Non-dict entries pass through
    assert cleaned["04"] == "legacy_string_value"
    assert cleaned["07"] is None
    # Dict entries cleaned normally
    assert cleaned["08"] == {"status": "pending"}
