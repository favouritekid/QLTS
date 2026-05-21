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
    """AsyncMock session — captures db.add() calls + db.flush() awaits.

    Phase E.4 v5 — override_kv draft gate now calls db.execute() qua
    ``derive_profile_target_context`` + ``resolve_kv_for_profile``. Provide
    a permissive execute mock returning empty results; tests that need
    specific engine behavior patch the priority_service functions instead.
    """
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    # Defensive execute mock: returns a result object with scalar_one_or_none()
    # = None + scalar().all() = []. Tests patch priority_service functions để
    # bypass execute entirely.
    empty_result = MagicMock()
    empty_result.scalar_one_or_none = MagicMock(return_value=None)
    empty_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db.execute = AsyncMock(return_value=empty_result)
    return db


def _find_audit_rows(db):
    """Filter db.add() calls down to PriorityAuditLog instances only.

    Wave 2 dispatch_event() also adds a NotificationOutbox row inside
    the caller's transaction (per B2.3 wrapper). Tests inspecting the
    audit row must filter by type to skip the outbox sibling.
    """
    from app import models
    rows = []
    for call in db.add.call_args_list:
        instance = call[0][0]
        if isinstance(instance, models.PriorityAuditLog):
            rows.append(instance)
    return rows


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


# Phase E.4 commit 7 hardening: officer blocked at top — KHÔNG cần status-
# specific test cho officer vì role gate fire trước status gate.
# `test_officer_uniformly_blocked` (parametrized below) cover all states.


@pytest.mark.parametrize(
    "status",
    ["draft", "submitted", "reviewing", "revision_requested", "resubmitted",
     "withdrawn", "dropped", "rejected", "enrolled", "approved",
     "confirmed", "result_published"],
)
async def test_officer_uniformly_blocked_at_any_status(status: str) -> None:
    """Phase E.4 commit 7 (yêu cầu nghiệp vụ #10): officer KHÔNG được override
    KV bất kể profile status. Service-layer hard-deny role=='officer' ngay
    sau version + reason validate, trước status whitelist."""
    profile = _make_profile(status=status)
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="Officer không được override KV"):
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
    "status", ["withdrawn", "dropped", "rejected"]
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


# ---------------------------------------------------------------------------
# Phase E.4 commit 5 fix-up — draft gate (gỡ deadlock submit-guard fail-closed)
# ---------------------------------------------------------------------------


async def test_draft_override_refused_for_officer() -> None:
    """Officer KHÔNG được override KV ở draft — kể cả engine signal unresolved.
    Hardening đầy đủ ở commit 7."""
    snapshot_with_engine_signal = {
        "kv_resolved": None,
        "rule_applied": "address_not_normalized",
        "requires_manual_override": True,
        "reason": "profile_missing_permanent_commune_code",
    }
    profile = _make_profile(
        status="draft",
        snapshot=snapshot_with_engine_signal,
    )
    actor = _make_actor("officer")
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="Officer không được override KV"):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


# Phase E.4 v5 — Draft override now uses LIVE engine recompute (not snapshot
# stale). Helper monkeypatch để control resolve_kv_for_profile + derive
# context output for these tests.
async def _fake_derive_ctx(profile_arg, db_arg):
    return {
        "target_level": "trung_cap",
        "admission_type": "chinh_quy",
        "eligibility": {"passed": True, "reason": None},
        "path_bonus_rule": None,
        "source": "test_stub",
    }


def _fake_resolve_factory(returns_unresolved: bool, rule: str = "address_not_normalized"):
    """Factory: build resolve_kv_for_profile mock returning unresolved or success meta."""
    async def _fake_resolve(profile_arg, db_arg, target_level=None, admission_type=None):
        if returns_unresolved:
            return None, {
                "rule_applied": rule,
                "pathway": "thuong_tru",
                "basis": "THUONG_TRU",
                "basis_reason": "tc_chinh_quy_post_thcs_uses_commune",
                "requires_manual_override": True,
                "reason": "profile_missing_permanent_commune_code",
            }
        return "KV1", {
            "rule_applied": "commune_lookup",
            "pathway": "thuong_tru",
            "basis": "THUONG_TRU",
            "basis_reason": "tc_chinh_quy_post_thcs_uses_commune",
            "breakdown": {"commune_code_used": "66_22255"},
        }
    return _fake_resolve


@pytest.mark.parametrize("role", ["admin", "manager"])
async def test_draft_override_refused_when_engine_recompute_resolves_live(
    role: str, monkeypatch,
) -> None:
    """v5: Live engine recompute resolve OK với current profile data → refuse,
    bất kể snapshot stale có signal hay không. Tránh free-form override khi
    engine có đường tự xử."""
    # Snapshot có thể là stale signal (officer mới sửa data) hoặc resolved OK
    snapshot_any = {
        "kv_resolved": None,
        "rule_applied": "address_not_normalized",
        "requires_manual_override": True,  # STALE signal
        "reason": "profile_missing_permanent_commune_code",
    }
    profile = _make_profile(status="draft", snapshot=snapshot_any)
    actor = _make_actor(role)
    db = _make_db()

    # Patch live recompute → return success (engine resolve OK)
    import app.services.priority_service as priority_module
    monkeypatch.setattr(priority_module, "derive_profile_target_context", _fake_derive_ctx)
    monkeypatch.setattr(
        priority_module, "resolve_kv_for_profile",
        _fake_resolve_factory(returns_unresolved=False),
    )

    with pytest.raises(BusinessRuleViolation, match="Engine vừa tính lại và resolve thành công"):
        await override_kv(
            db, profile,
            kv_resolved="KV2",
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )


@pytest.mark.parametrize("role", ["admin", "manager"])
async def test_draft_override_allowed_when_engine_recompute_still_unresolved(
    role: str, monkeypatch,
) -> None:
    """v5: Live engine recompute vẫn emit unresolved → allow (matches submit
    guard fail-closed). Snapshot có thể đã có signal cũ hoặc không — không
    quan trọng, live engine là nguồn quyết định."""
    snapshot_with_engine_signal = {
        "kv_resolved": None,
        "rule_applied": "ambiguous_requires_manual",
        "requires_manual_override": True,
        "reason": "tied_graduation_year_and_grade",
    }
    profile = _make_profile(status="draft", snapshot=snapshot_with_engine_signal)
    actor = _make_actor(role)
    db = _make_db()

    # Patch live recompute → return unresolved (engine vẫn không xác định)
    import app.services.priority_service as priority_module
    monkeypatch.setattr(priority_module, "derive_profile_target_context", _fake_derive_ctx)
    monkeypatch.setattr(
        priority_module, "resolve_kv_for_profile",
        _fake_resolve_factory(returns_unresolved=True, rule="address_not_normalized"),
    )

    # Should not raise — override succeeds
    updated, _cb = await override_kv(
        db, profile,
        kv_resolved="KV1",
        reason=REASON_VALID,
        evidence_file_id=None,
        actor=actor,
        expected_version=5,
    )
    snap = updated.priority_resolution_snapshot
    assert snap["kv_resolved"] == "KV1"
    assert snap["rule_applied"] == "manual_override"
    assert snap["manual_override_reason"] == REASON_VALID
    # Engine signal flag dropped post-override
    assert "requires_manual_override" not in snap


async def test_draft_override_refused_with_stale_snapshot_signal_after_officer_fix(
    monkeypatch,
) -> None:
    """Reviewer P0 2026-05-21 v5 — STALE SIGNAL bug regression.

    Scenario:
      1. Officer submit thiếu commune_code → snapshot persist với rule
         address_not_normalized + requires_manual_override=True.
      2. Officer sửa permanent_commune_code='66_22255' (qua update_profile);
         snapshot KHÔNG được clear/recompute auto.
      3. Manager mở override_kv draft.
      4. Pre-fix v5: gate kiểm tra snapshot.requires_manual_override → True
         (stale) → pass → free-form override với KV bất kỳ. SAI nghiệp vụ.
      5. Post-fix v5: gate recompute live → engine giờ resolve OK (commune
         có catalog) → refuse. Officer cần submit lại để engine refreeze.
    """
    # Stale snapshot from old submit (commune empty)
    stale_snapshot = {
        "kv_resolved": None,
        "rule_applied": "address_not_normalized",
        "pathway": "thuong_tru",
        "basis": "THUONG_TRU",
        "requires_manual_override": True,  # STALE
        "reason": "profile_missing_permanent_commune_code",
    }
    profile = _make_profile(status="draft", snapshot=stale_snapshot)
    # Officer đã sửa commune_code; profile.permanent_commune_code có giá trị.
    # Trong test này SimpleNamespace stub không tracking field; quan trọng là
    # live recompute fake return success → simulate "engine giờ resolve OK".
    actor = _make_actor("manager")
    db = _make_db()

    import app.services.priority_service as priority_module
    monkeypatch.setattr(priority_module, "derive_profile_target_context", _fake_derive_ctx)
    monkeypatch.setattr(
        priority_module, "resolve_kv_for_profile",
        _fake_resolve_factory(returns_unresolved=False),  # Live = OK
    )

    with pytest.raises(BusinessRuleViolation) as exc:
        await override_kv(
            db, profile,
            kv_resolved="KV2",  # Manager intent override
            reason=REASON_VALID,
            evidence_file_id=None,
            actor=actor,
            expected_version=5,
        )
    # Message phải nói rõ "engine vừa tính lại" để officer hiểu sửa data → resolve OK
    assert "Engine vừa tính lại và resolve thành công" in str(exc.value)
    # Snapshot KHÔNG bị mutate (override refused)
    assert profile.priority_resolution_snapshot == stale_snapshot


# Phase E.4 commit 7: ``test_officer_refused_post_publish_raises_permission_error``
# REMOVED — officer giờ block ngay top với BusinessRuleViolation cho mọi status
# (covered by ``test_officer_uniformly_blocked_at_any_status``). PermissionError
# path còn lại chỉ cho manager attempting post-publish (treated as officer-path).


@pytest.mark.parametrize(
    "status", ["enrolled", "approved", "confirmed", "result_published"]
)
async def test_manager_refused_post_publish_raises_permission_error(
    status: str,
) -> None:
    """Manager refused post-publish via PermissionError (router maps to 403).
    Admin bypass với acknowledge_post_publish flag (separate test)."""
    profile = _make_profile(status=status)
    actor = _make_actor("manager")
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


async def test_manager_happy_path_mutates_snapshot_and_audit_log() -> None:
    """Phase E.4 commit 7: officer hard-blocked; happy path now belongs to
    manager (admin happy path covered separately with post-publish ack).
    Manager override pre-publish status (submitted) — same mechanics as
    pre-commit 7 officer flow."""
    profile = _make_profile(status="submitted", version=5)
    actor = _make_actor("manager", user_id=7)
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
    # Manager treated as officer-path (resolved_by="officer"); only admin emit
    # resolved_by="admin". Behavior preserved from pre-commit 7.
    assert snap["resolved_by"] == "officer"

    # Engine-state keys dropped post-override
    assert "requires_manual_override" not in snap or not snap["requires_manual_override"]

    # area_resolution_basis flipped to manual
    assert profile.area_resolution_basis == "manual_override"

    # Version bumped
    assert profile.version == 6

    # Audit log row queued for INSERT (also NotificationOutbox row from
    # dispatch_event — filter by type to avoid coupling).
    audit_rows = _find_audit_rows(db)
    assert len(audit_rows) == 1
    audit_row = audit_rows[0]
    assert audit_row.profile_id == 42
    assert audit_row.action_type == "kv_manual_override"
    assert audit_row.actor_id == 7
    assert audit_row.old_value["kv_resolved"] == "KV3"
    assert audit_row.new_value["kv_resolved"] == "KV1"
    assert audit_row.new_value["reason"] == REASON_VALID
    assert audit_row.audit_metadata["actor_role"] == "manager"

    # Flushed but NOT committed (router responsibility)
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()

    # post_commit callable returned
    assert callable(post_commit)


async def test_officer_blocked_even_with_valid_state_and_inputs() -> None:
    """Phase E.4 commit 7 negative regression — officer with completely valid
    submitted-state inputs STILL blocked. Confirms role gate is unconditional."""
    profile = _make_profile(status="submitted", version=5)
    actor = _make_actor("officer", user_id=7)
    db = _make_db()

    with pytest.raises(BusinessRuleViolation, match="Officer không được override KV"):
        await override_kv(
            db,
            profile,
            kv_resolved="KV1",
            reason=REASON_VALID,
            evidence_file_id=42,
            actor=actor,
            expected_version=5,
        )
    # Snapshot KHÔNG bị mutate
    assert profile.priority_resolution_snapshot.get("rule_applied") != "manual_override"
    # Version KHÔNG bump
    assert profile.version == 5
    # Audit log KHÔNG có row được add
    assert len(_find_audit_rows(db)) == 0


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

    audit_rows = _find_audit_rows(db)
    assert len(audit_rows) == 1
    assert audit_rows[0].audit_metadata["acknowledged_post_publish"] is True


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
    audit_rows = _find_audit_rows(db)
    assert len(audit_rows) == 1
    audit_row = audit_rows[0]
    assert audit_row.old_value["kv_resolved"] == "KV1"
    assert audit_row.new_value["kv_resolved"] == "KV2-NT"
