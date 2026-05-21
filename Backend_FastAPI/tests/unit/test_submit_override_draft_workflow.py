"""Regression test cho full workflow:
   submit unresolved → snapshot persists with signal → override draft succeeds.

Reviewer P0 2026-05-21 v4 — deadlock identification:
   1. Officer submit draft → freeze runs → snapshot stays in object (in-memory)
   2. ``_assert_kv_resolved_for_submit`` raise ``BadRequest`` (pre-fix-up v4)
   3. Router ``admissions.py`` chỉ commit success path
   4. ``except BadRequest`` raise HTTP 400, KHÔNG commit
   5. Snapshot unresolved bị rollback / never persists
   6. Manager/admin go to override draft → ``override_kv()`` reads
      ``profile.priority_resolution_snapshot.requires_manual_override`` → False
      (snapshot không persist) → refuse

Fix v4: submit returns ``(result_dict, None)`` với ``status='draft'`` +
``validation_errors`` thay vì raise. ``db.flush()`` trong errors branch persist
snapshot. Router commit → snapshot lưu vào DB → override draft thấy signal.

Pure-logic regression test (KHÔNG cần real DB):
  - Helper ``_kv_unresolved_error_message()`` trả message non-None
  - Helper ``override_kv()`` draft + snapshot signal → allow
  - End-to-end: snapshot trước submit + signal-after-submit match
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.admission_service import _kv_unresolved_error_message
from app.services.priority_override_service import override_kv


pytestmark = pytest.mark.unit


# ===========================================================================
# Workflow test — submit unresolved leaves signal, override draft picks it up
# ===========================================================================


def _make_actor(role: str = "manager", user_id: int = 7):
    return SimpleNamespace(id=user_id, role=role, full_name=f"Test {role}")


async def test_submit_then_override_draft_no_deadlock() -> None:
    """End-to-end: submit unresolved emits snapshot signal, override_kv on
    draft consumes signal and succeeds."""
    # Step 1: Simulate submit produces snapshot với engine fail-closed signal
    # (vd address_not_normalized cho THUONG_TRU + missing commune_code).
    submit_snapshot = {
        "kv_resolved": None,
        "rule_applied": "address_not_normalized",
        "pathway": "thuong_tru",
        "basis": "THUONG_TRU",
        "basis_reason": "tc_chinh_quy_post_thcs_uses_commune",
        "requires_manual_override": True,
        "reason": "profile_missing_permanent_commune_code",
        "frozen_at": "2026-05-21T03:00:00+00:00",
        "frozen_at_status": "submitted_T1",
        "resolved_by": "system",
        "target_level": "trung_cap",
        "admission_type": "chinh_quy",
    }

    # Submit helper trả error message (KHÔNG raise) cho submit append vào
    # validation_errors. Snapshot stays in profile, sẽ flush+commit ở router.
    submit_error = _kv_unresolved_error_message(submit_snapshot, profile_id=1)
    assert submit_error is not None
    assert "KV_UNRESOLVED" in submit_error
    assert "address_not_normalized" in submit_error

    # Step 2: Router commit → snapshot persists vào DB (simulated bằng cách
    # gán snapshot vào profile object — KV ngữ nghĩa: snapshot persisted).
    profile_after_submit = SimpleNamespace(
        id=1,
        lead_id=100,
        status="draft",  # Submit returns status=draft (errors flow)
        version=5,
        priority_resolution_snapshot=submit_snapshot,  # PERSISTED — signal có
        area_resolution_basis="school_history",
    )

    # Step 3: Manager attempts override_kv on draft profile.
    # Gate check: status="draft" + role="manager" + snapshot signal True → allow.
    actor = _make_actor(role="manager")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    updated_profile, callback = await override_kv(
        db,
        profile_after_submit,
        kv_resolved="KV2-NT",
        reason="Lớp tạo nguồn theo QĐ Bộ → KV2-NT (override draft sau submit fail)",
        evidence_file_id=None,
        actor=actor,
        expected_version=5,
    )

    # Verify override succeeded — snapshot overwritten với manual_override.
    new_snap = updated_profile.priority_resolution_snapshot
    assert new_snap["kv_resolved"] == "KV2-NT"
    assert new_snap["rule_applied"] == "manual_override"
    assert new_snap["manual_override_by"] == actor.id
    assert "Lớp tạo nguồn" in new_snap["manual_override_reason"]
    # Engine signal dropped post-override (deadlock state cleared)
    assert "requires_manual_override" not in new_snap

    # Step 4: Officer re-submit. Snapshot rule_applied="manual_override" +
    # kv_resolved="KV2-NT" → success whitelist + kv_resolved set → submit pass.
    resubmit_error = _kv_unresolved_error_message(new_snap, profile_id=1)
    assert resubmit_error is None  # Pass — no error


async def test_admin_can_also_override_draft_after_submit_unresolved() -> None:
    """Verify admin role cũng được override draft (mirror manager case)."""
    submit_snapshot = {
        "kv_resolved": None,
        "rule_applied": "catalog_gap_school",
        "requires_manual_override": True,
        "reason": "all_school_lookups_failed",
    }
    profile = SimpleNamespace(
        id=2, lead_id=101, status="draft", version=3,
        priority_resolution_snapshot=submit_snapshot,
        area_resolution_basis="school_history",
    )
    actor = _make_actor(role="admin")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())
    db.add = MagicMock()
    db.flush = AsyncMock()

    updated, _cb = await override_kv(
        db, profile,
        kv_resolved="KV1",
        reason="THPT trong catalog gap; xác minh thủ công bằng giấy → KV1",
        evidence_file_id=None,
        actor=actor,
        expected_version=3,
    )
    assert updated.priority_resolution_snapshot["kv_resolved"] == "KV1"
    assert updated.priority_resolution_snapshot["rule_applied"] == "manual_override"


async def test_officer_still_blocked_from_draft_override() -> None:
    """Officer KHÔNG bypass deadlock — phải nhờ manager/admin (đúng nghiệp vụ #10)."""
    from app.utils.exceptions import BusinessRuleViolation

    submit_snapshot = {
        "kv_resolved": None,
        "rule_applied": "address_not_normalized",
        "requires_manual_override": True,
    }
    profile = SimpleNamespace(
        id=3, lead_id=102, status="draft", version=4,
        priority_resolution_snapshot=submit_snapshot,
        area_resolution_basis="school_history",
    )
    officer = _make_actor(role="officer")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())

    with pytest.raises(BusinessRuleViolation, match="Officer không được override"):
        await override_kv(
            db, profile,
            kv_resolved="KV1",
            reason="Officer trying to override — should be refused per nghiệp vụ #10",
            evidence_file_id=None,
            actor=officer,
            expected_version=4,
        )


async def test_manager_cannot_override_draft_without_engine_signal() -> None:
    """Manager cũng KHÔNG bypass khi snapshot không có signal — engine resolve OK
    nhưng manager muốn override draft → refuse (avoid free-form override)."""
    from app.utils.exceptions import BusinessRuleViolation

    happy_snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "longest_duration",
        # KHÔNG có requires_manual_override
    }
    profile = SimpleNamespace(
        id=4, lead_id=103, status="draft", version=2,
        priority_resolution_snapshot=happy_snapshot,
        area_resolution_basis="school_history",
    )
    actor = _make_actor(role="manager")
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock())

    with pytest.raises(BusinessRuleViolation, match="draft chỉ được override"):
        await override_kv(
            db, profile,
            kv_resolved="KV2",
            reason="Manager wants to override even though engine resolved fine",
            evidence_file_id=None,
            actor=actor,
            expected_version=2,
        )
