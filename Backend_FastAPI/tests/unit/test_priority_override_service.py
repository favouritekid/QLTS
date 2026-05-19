"""Unit tests for ``priority_override_service.override_kv``.

Q9 #07 Phase E.2 — service-layer behaviour contract. Covers:

1. Version guard FIRST (memory `version-guard-before-state-machine`).
2. Reason length validation (20-500 char).
3. KV value validation (4 codes only).
4. Status whitelist enforcement per role:
   * Officer: {submitted, reviewing, revision_requested} ALLOW
   * Admin: same + bypass via acknowledge_post_publish for post-publish.
   * Hard-deny {draft, withdrawn, dropped, rejected} for both.
5. Snapshot mutation correctness (Decision D1 — LAST override wins).
6. Audit log INSERT (action_type='kv_manual_override').
7. Version bump (optimistic lock).
8. post_commit callback closure (dispatch wiring).

Tests mock the AsyncSession + profile so they stay independent of
alembic + DB seed (pure-logic unit tests).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.priority_override_service import override_kv
from app.utils.exceptions import BusinessRuleViolation, ConflictError


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_profile(
    *,
    status: str = "submitted",
    version: int = 5,
    snapshot: dict | None = None,
):
    """Build a SimpleNamespace profile stub with the fields override_kv reads."""
    return SimpleNamespace(
        id=42,
        lead_id=100,
        status=status,
        version=version,
        priority_resolution_snapshot=snapshot
        if snapshot is not None
        else {
            "kv_resolved": "KV3",
            "rule_applied": "thpt_multi_school_longest",
            "pathway": "thpt_multi_school",
            "frozen_at": "2026-05-19T00:00:00Z",
        },
        area_resolution_basis="school_history",
    )


def _make_actor(role: str = "officer", user_id: int = 7):
    return SimpleNamespace(
        id=user_id,
        role=role,
        full_name=f"User {user_id}",
        email=f"user{user_id}@example.com",
    )


def _make_db():
    """AsyncMock session — captures db.add() calls + db.flush() awaits."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


REASON_VALID = "Lý do override 20+ ký tự cho test smoke happy path"


# ---------------------------------------------------------------------------
# Version guard — FIRST per memory
# ---------------------------------------------------------------------------


async def test_version_conflict_raises_before_other_checks() -> None:
    """Version mismatch must raise ConflictError BEFORE status / reason
    validation — guarantees fast-fail trên concurrent writes.
    """
    profile = _make_profile(version=5)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(ConflictError) as exc:
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=99,  # mismatch
        )
    assert "version" in str(exc.value).lower()
    db.add.assert_not_called()
    db.flush.assert_not_awaited()


# ---------------------------------------------------------------------------
# Reason validation
# ---------------------------------------------------------------------------


async def test_reason_too_short_raises() -> None:
    profile = _make_profile()
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="20 characters"):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason="too short",  # 9 chars
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


async def test_reason_too_long_raises() -> None:
    profile = _make_profile()
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="500 characters"):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason="x" * 501,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


# ---------------------------------------------------------------------------
# KV value validation
# ---------------------------------------------------------------------------


async def test_invalid_kv_value_raises() -> None:
    profile = _make_profile()
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="Invalid kv_resolved"):
        await override_kv(
            db,
            profile,
            kv_resolved="KV99",  # invalid
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


# ---------------------------------------------------------------------------
# Status whitelist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status", ["draft", "withdrawn", "dropped", "rejected"]
)
async def test_hard_denied_status_raises_for_officer(status: str) -> None:
    profile = _make_profile(status=status)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match=status):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


@pytest.mark.parametrize(
    "status", ["draft", "withdrawn", "dropped", "rejected"]
)
async def test_hard_denied_status_raises_for_admin_too(status: str) -> None:
    """Admin also refused for hard-denied states (data integrity)."""
    profile = _make_profile(status=status)
    actor = _make_actor("admin")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match=status):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
            acknowledge_post_publish=True,
        )


@pytest.mark.parametrize(
    "status", ["enrolled", "approved", "confirmed", "result_published"]
)
async def test_officer_refused_post_publish_raises_permission_error(
    status: str,
) -> None:
    """Officer hits PermissionError for post-publish; router maps to 403."""
    profile = _make_profile(status=status)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(PermissionError):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


async def test_admin_post_publish_without_ack_raises() -> None:
    """Admin requires acknowledge_post_publish=true for post-publish states."""
    profile = _make_profile(status="enrolled")
    actor = _make_actor("admin")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="acknowledge_post_publish"):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
            acknowledge_post_publish=False,
        )


# ---------------------------------------------------------------------------
# Happy path — officer
# ---------------------------------------------------------------------------


async def test_officer_happy_path_mutates_snapshot_and_audit_log() -> None:
    profile = _make_profile(status="submitted", version=5)
    actor = _make_actor("officer", user_id=7)
    db = _make_db()

    updated, post_commit = await override_kv(
        db,
        profile,
        kv_resolved="KV1",
        reason=REASON_VALID,
        evidence_file_id=42,
        actor=actor,
        expected_version=5,
    )

    # Returned profile = same object mutated in-place
    assert updated is profile

    # Snapshot fully overwritten với manual override metadata
    snap = profile.priority_resolution_snapshot
    assert snap["kv_resolved"] == "KV1"
    assert snap["pathway"] == "manual"
    assert snap["rule_applied"] == "manual_override"
    assert snap["manual_override_by"] == 7
    assert snap["manual_override_at"]  # ISO timestamp set
    assert snap["manual_override_reason"] == REASON_VALID
    assert snap["evidence_file_id"] == 42
    assert snap["frozen_at_status"] == "manual_override"
    assert snap["resolved_by"] == "officer"

    # Engine-state keys dropped post-override
    assert "requires_manual_override" not in snap or not snap["requires_manual_override"]

    # area_resolution_basis flipped to manual
    assert profile.area_resolution_basis == "manual_override"

    # Version bumped
    assert profile.version == 6

    # Audit log row queued for INSERT
    assert db.add.call_count == 1
    audit_row = db.add.call_args[0][0]
    assert audit_row.profile_id == 42
    assert audit_row.action_type == "kv_manual_override"
    assert audit_row.actor_id == 7
    assert audit_row.old_value["kv_resolved"] == "KV3"
    assert audit_row.new_value["kv_resolved"] == "KV1"
    assert audit_row.new_value["reason"] == REASON_VALID
    assert audit_row.audit_metadata["actor_role"] == "officer"

    # Flushed but NOT committed (router responsibility)
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()

    # post_commit callable returned
    assert callable(post_commit)


# ---------------------------------------------------------------------------
# Happy path — admin post-publish với ack
# ---------------------------------------------------------------------------


async def test_admin_post_publish_with_ack_succeeds() -> None:
    profile = _make_profile(status="enrolled", version=10)
    actor = _make_actor("admin", user_id=1)
    db = _make_db()

    updated, _ = await override_kv(
        db,
        profile,
        kv_resolved="KV2-NT",
        reason=REASON_VALID,
        evidence_file_id=None,
        actor=actor,
        expected_version=10,
        acknowledge_post_publish=True,
    )

    assert updated.priority_resolution_snapshot["kv_resolved"] == "KV2-NT"
    assert updated.priority_resolution_snapshot["resolved_by"] == "admin"
    assert updated.version == 11

    audit_row = db.add.call_args[0][0]
    assert audit_row.audit_metadata["acknowledged_post_publish"] is True


# ---------------------------------------------------------------------------
# Chain-of-override semantics (Decision D1)
# ---------------------------------------------------------------------------


async def test_second_override_overwrites_manual_keys() -> None:
    """First override sets manual_override_*; second overwrites with new
    actor + reason (snapshot LAST wins, audit log preserves chain).
    """
    # Profile already had one override (e.g., from officer)
    profile = _make_profile(
        status="submitted",
        version=6,
        snapshot={
            "kv_resolved": "KV1",
            "pathway": "manual",
            "rule_applied": "manual_override",
            "manual_override_by": 7,
            "manual_override_at": "2026-05-19T01:00:00Z",
            "manual_override_reason": "Officer first pass override reason 20 chars+",
            "evidence_file_id": 11,
            "frozen_at": "2026-05-19T01:00:00Z",
            "frozen_at_status": "manual_override",
            "resolved_by": "officer",
        },
    )
    admin = _make_actor("admin", user_id=99)
    db = _make_db()

    new_reason = "Admin re-override second pass with longer justification"

    updated, _ = await override_kv(
        db,
        profile,
        kv_resolved="KV2-NT",
        reason=new_reason,
        evidence_file_id=22,
        actor=admin,
        expected_version=6,
    )

    snap = updated.priority_resolution_snapshot
    # New override metadata wins
    assert snap["kv_resolved"] == "KV2-NT"
    assert snap["manual_override_by"] == 99
    assert snap["manual_override_reason"] == new_reason
    assert snap["evidence_file_id"] == 22
    assert snap["resolved_by"] == "admin"

    # Audit log captures OLD = officer's last state, NEW = admin's
    audit_row = db.add.call_args[0][0]
    assert audit_row.old_value["kv_resolved"] == "KV1"
    assert audit_row.new_value["kv_resolved"] == "KV2-NT"
