"""Unit tests for ``priority_override_service.verify_object_evidence`` +
``reject_object_evidence`` (Q9 #07 Phase E.3).

Stub AsyncSession + profile per ``test_priority_override_service`` style.
Coverage:
1. Version guard FIRST (per memory `version-guard-before-state-machine`).
2. sub_code-not-in-codes → BusinessRuleViolation.
3. Hard-denied status → BusinessRuleViolation.
4. Reject reason length validation.
5. Happy verify: evidence dict mutated, snapshot.ut_verified_bucket
   recomputed, audit log INSERT, version bump.
6. Happy reject: same shape + reject_reason persisted.
7. Reject after verify: bucket recomputes (chain).
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.priority_override_service import (
    reject_object_evidence,
    verify_object_evidence,
)
from app.utils.exceptions import BusinessRuleViolation, ConflictError


pytestmark = pytest.mark.unit


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


def _make_db(catalog_rows=None):
    """Mock DB session — execute() returns catalog rows for UT bucket recompute."""
    catalog_result = MagicMock()
    catalog_result.all = MagicMock(return_value=catalog_rows or [])

    async def _execute(stmt, *args, **kwargs):
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


REJECT_REASON_VALID = "Document không hợp lệ (10+ chars)"


# ---------------------------------------------------------------------------
# Version guard
# ---------------------------------------------------------------------------


async def test_verify_version_conflict_raises() -> None:
    profile = _make_profile(version=5)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(ConflictError):
        await verify_object_evidence(
            db, profile, sub_code="04", document_id=None,
            actor=actor, expected_version=99,
        )
    db.add.assert_not_called()


async def test_reject_version_conflict_raises() -> None:
    profile = _make_profile(version=5)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(ConflictError):
        await reject_object_evidence(
            db, profile, sub_code="04", reject_reason=REJECT_REASON_VALID,
            actor=actor, expected_version=99,
        )


# ---------------------------------------------------------------------------
# sub_code-not-in-codes
# ---------------------------------------------------------------------------


async def test_verify_sub_code_not_submitted_raises() -> None:
    profile = _make_profile(codes=["04"])
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="not in profile's submitted"):
        await verify_object_evidence(
            db, profile, sub_code="99", document_id=None,
            actor=actor, expected_version=5,
        )


async def test_reject_sub_code_not_submitted_raises() -> None:
    profile = _make_profile(codes=["04"])
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="not in profile's submitted"):
        await reject_object_evidence(
            db, profile, sub_code="99", reject_reason=REJECT_REASON_VALID,
            actor=actor, expected_version=5,
        )


# ---------------------------------------------------------------------------
# Hard-denied status (draft/withdrawn/dropped)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["draft", "withdrawn", "dropped"])
async def test_verify_hard_denied_status(status: str) -> None:
    profile = _make_profile(status=status)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match=status):
        await verify_object_evidence(
            db, profile, sub_code="04", document_id=None,
            actor=actor, expected_version=5,
        )


# ---------------------------------------------------------------------------
# Reject reason length
# ---------------------------------------------------------------------------


async def test_reject_reason_too_short_raises() -> None:
    profile = _make_profile()
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="10 characters"):
        await reject_object_evidence(
            db, profile, sub_code="04", reject_reason="short",
            actor=actor, expected_version=5,
        )


async def test_reject_reason_too_long_raises() -> None:
    profile = _make_profile()
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="500 characters"):
        await reject_object_evidence(
            db, profile, sub_code="04", reject_reason="x" * 501,
            actor=actor, expected_version=5,
        )


# ---------------------------------------------------------------------------
# Happy verify
# ---------------------------------------------------------------------------


async def test_verify_happy_path_mutates_evidence_and_audit() -> None:
    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    # Catalog returns UT04 bonus_points=1.00, UT07=0.50
    db = _make_db(catalog_rows=[("04", Decimal("1.00"))])

    updated, post_commit = await verify_object_evidence(
        db, profile, sub_code="04", document_id=42,
        actor=actor, expected_version=5,
    )

    # Evidence dict mutated
    assert updated.priority_object_evidence["04"]["status"] == "verified"
    assert updated.priority_object_evidence["04"]["verified_by"] == 7
    assert updated.priority_object_evidence["04"]["document_id"] == 42

    # Snapshot ut_verified_bucket recomputed
    bucket = updated.priority_resolution_snapshot["ut_verified_bucket"]
    assert bucket["applied_code"] == "04"
    assert bucket["applied_rate"] == 1.0

    # Version bumped
    assert updated.version == 6

    # Audit log row
    audit_rows = _find_audit_rows(db)
    assert len(audit_rows) == 1
    audit = audit_rows[0]
    assert audit.action_type == "ut_evidence_verified"
    assert audit.actor_id == 7
    assert audit.new_value["sub_code"] == "04"
    assert audit.new_value["status"] == "verified"
    assert audit.audit_metadata["ut_verified_bucket"]["applied_code"] == "04"

    # Flushed not committed
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert callable(post_commit)


# ---------------------------------------------------------------------------
# Happy reject
# ---------------------------------------------------------------------------


async def test_reject_happy_path_mutates_evidence() -> None:
    profile = _make_profile()
    actor = _make_actor("officer", user_id=7)
    db = _make_db()

    updated, _ = await reject_object_evidence(
        db, profile, sub_code="04",
        reject_reason="Minh chứng không khớp với hồ sơ",
        actor=actor, expected_version=5,
    )

    entry = updated.priority_object_evidence["04"]
    assert entry["status"] == "rejected"
    assert entry["reject_reason"] == "Minh chứng không khớp với hồ sơ"
    assert entry["rejected_by"] == 7

    assert updated.version == 6

    audit_rows = _find_audit_rows(db)
    assert len(audit_rows) == 1
    assert audit_rows[0].action_type == "ut_evidence_rejected"
    assert audit_rows[0].new_value["reject_reason"] == "Minh chứng không khớp với hồ sơ"


# ---------------------------------------------------------------------------
# Bucket recompute — verify after reject (chain)
# ---------------------------------------------------------------------------


async def test_reject_after_verify_recomputes_bucket() -> None:
    """If UT04 was verified (applied_code), then rejected, bucket falls
    back to next-highest verified (or null if none).
    """
    profile = _make_profile(
        codes=["04", "07"],
        evidence={
            "04": {"status": "verified", "verified_by": 7},
            "07": {"status": "verified", "verified_by": 7},
        },
    )
    actor = _make_actor("officer")
    # Before reject, catalog has both verified. After rejecting "04",
    # only "07" remains verified. Bucket recomputes to UT07=0.50.
    db = _make_db(catalog_rows=[("07", Decimal("0.50"))])

    updated, _ = await reject_object_evidence(
        db, profile, sub_code="04",
        reject_reason="Reject 04 to test bucket recompute",
        actor=actor, expected_version=5,
    )

    bucket = updated.priority_resolution_snapshot["ut_verified_bucket"]
    assert bucket["applied_code"] == "07"
    assert bucket["applied_rate"] == 0.5

    # 04 evidence now rejected
    assert updated.priority_object_evidence["04"]["status"] == "rejected"
