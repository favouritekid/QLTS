"""Integration tests (PR-2 Nhóm 1, slice 2) — restore_consultation B2 + B3.

Khoá hành vi khôi phục consultation:
- B2: revert pipeline qua `_resolve_revert_target` (KHÔNG exclude — cuộc restore
  giờ đã live → tính vào chuỗi). Restore cuộc universal-mới-nhất KHÔNG còn NULL-hoá
  stage của lead (helper dò về cuộc pipeline gần nhất). Restore cuộc non-latest
  không cướp pipeline của cuộc latest thật.
- B3: terminal guard đầu restore — hard-block 'enrolled' (raise). Soft-terminal
  (sts20-like) KHÔNG bị chặn và KHÔNG skip revert theo status hiện tại (bài học
  B5): helper tính lại từ chuỗi còn sống → lead thoát terminal nếu cuộc pipeline
  mới nhất non-terminal, hoặc giữ terminal nếu cuộc terminal vẫn latest.

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 1 (B2, B3).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import lead_service
from app.utils.exceptions import BusinessRuleViolation

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def restore_statuses(db: AsyncSession, seeded_dependencies: dict) -> dict:
    """Seed stages + consultation statuses cho các nhánh restore.

    - PIPE_A / PIPE_B: human pipeline (updates_pipeline=True, có stage, non-final).
    - UNIV: universal (updates_pipeline=False, stage_id=NULL).
    - TERM: terminal phase tư vấn (updates_pipeline=True, is_final=True,
      phase='consultation') — sts20-like SOFT terminal.
    - ENROLLED: terminal phase nhập học (is_final=True, phase='enrolled') — HARD
      terminal, kích hoạt hard_block của check_terminal_status_guard.
    """
    stages = [
        models.PipelineStage(id="RS_STG_A", name="RS Stage A", order=21),
        models.PipelineStage(id="RS_STG_B", name="RS Stage B", order=22),
        models.PipelineStage(id="RS_STG_TERM", name="RS Stage Term", order=98),
        models.PipelineStage(id="RS_STG_ENR", name="RS Stage Enrolled", order=97),
    ]
    for s in stages:
        db.add(s)
    await db.flush()

    statuses = {
        "PIPE_A": models.ConsultationStatus(
            id="RS_PIPE_A", name="RS Pipe A", color_code="#111111",
            stage_id="RS_STG_A", is_final=False, updates_pipeline=True,
            phase="consultation",
        ),
        "PIPE_B": models.ConsultationStatus(
            id="RS_PIPE_B", name="RS Pipe B", color_code="#222222",
            stage_id="RS_STG_B", is_final=False, updates_pipeline=True,
            phase="consultation",
        ),
        "UNIV": models.ConsultationStatus(
            id="RS_UNIV", name="RS Universal", color_code="#333333",
            stage_id=None, is_final=False, updates_pipeline=False,
            is_universal=True, phase="consultation",
        ),
        "TERM": models.ConsultationStatus(
            id="RS_TERM", name="RS Ngừng tư vấn", color_code="#CC0000",
            stage_id="RS_STG_TERM", is_final=True, updates_pipeline=True,
            phase="consultation",
        ),
        "ENROLLED": models.ConsultationStatus(
            id="RS_ENROLLED", name="RS Đã nhập học", color_code="#00AA00",
            stage_id="RS_STG_ENR", is_final=True, updates_pipeline=True,
            phase="enrolled",
        ),
    }
    for st in statuses.values():
        db.add(st)
    await db.flush()
    return statuses


async def _make_lead(db, seeded_dependencies, officer_id, cur_status, cur_stage):
    """Lead với status/stage HIỆN TẠI cho trước (mô phỏng add_consultation đã set)."""
    lead = models.Lead(
        full_name="Restore Lead",
        phone="0900777666",
        email="restore_lead@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=officer_id,
        consultation_status_id=cur_status,
        pipeline_stage_id=cur_stage,
        consultation_count=0,
        status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, status_id, minutes, deleted=False):
    """Consultation trực tiếp, date = _BASE + minutes (điều khiển order).

    deleted=True → set deleted_at (cuộc đang soft-deleted, sẵn sàng restore).
    """
    c = models.Consultation(
        lead_id=lead_id,
        officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method="phone",
        consultation_status_id=status_id,
        deleted_at=(_BASE + timedelta(minutes=minutes)) if deleted else None,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


async def _restore_and_reload(db, lead_id, consultation_id, actor):
    await lead_service.restore_consultation(
        db=db, lead_id=lead_id, consultation_id=consultation_id, current_user=actor
    )
    await db.commit()
    return await db.get(models.Lead, lead_id)


# ===========================================================================
# B2 — restore revert dùng _resolve_revert_target (không NULL-hoá stage)
# ===========================================================================


async def test_restore_universal_latest_does_not_null_stage(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """C1=PIPE_A (live). C2=UNIV (deleted, date mới hơn). Restore C2 → C2 thành
    cuộc mới nhất & universal. Bug cũ: gán lead.pipeline_stage_id = UNIV.stage_id
    = NULL. B2: helper dò về PIPE_A → stage KHÔNG bị NULL-hoá."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_PIPE_A", "RS_STG_A")
    await _add_consult(db, lead.id, off, "RS_PIPE_A", 10)
    c_univ = await _add_consult(db, lead.id, off, "RS_UNIV", 30, deleted=True)

    lead = await _restore_and_reload(db, lead.id, c_univ.id, manager_user)
    assert lead.consultation_status_id == "RS_PIPE_A"
    assert lead.pipeline_stage_id == "RS_STG_A"
    assert lead.pipeline_stage_id is not None


async def test_restore_pipeline_becomes_latest_reverts_to_it(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """C1=PIPE_A (live). C2=PIPE_B (deleted, date mới hơn). Restore C2 → C2 là
    cuộc pipeline mới nhất → lead revert về PIPE_B/STG_B."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_PIPE_A", "RS_STG_A")
    await _add_consult(db, lead.id, off, "RS_PIPE_A", 10)
    c_b = await _add_consult(db, lead.id, off, "RS_PIPE_B", 20, deleted=True)

    lead = await _restore_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.consultation_status_id == "RS_PIPE_B"
    assert lead.pipeline_stage_id == "RS_STG_B"


async def test_restore_non_latest_pipeline_keeps_current_latest(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """C1=PIPE_A (live, mới nhất). C2=PIPE_B (deleted, cũ hơn). Restore C2 → C2
    KHÔNG phải latest → lead giữ nguyên PIPE_A (không bị cuộc cũ cướp pipeline)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_PIPE_A", "RS_STG_A")
    await _add_consult(db, lead.id, off, "RS_PIPE_A", 30)
    c_b = await _add_consult(db, lead.id, off, "RS_PIPE_B", 10, deleted=True)

    lead = await _restore_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.consultation_status_id == "RS_PIPE_A"
    assert lead.pipeline_stage_id == "RS_STG_A"


async def test_restore_bumps_lead_version(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """Restore là data-change (deleted→live) → lead.version PHẢI tăng (đối xứng
    delete_consultation) cho optimistic-lock."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_PIPE_A", "RS_STG_A")
    await _add_consult(db, lead.id, off, "RS_PIPE_A", 10)
    c_b = await _add_consult(db, lead.id, off, "RS_PIPE_B", 20, deleted=True)
    before = lead.version or 1

    lead = await _restore_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.version > before


# ===========================================================================
# B3 — terminal guard đầu restore
# ===========================================================================


async def test_restore_on_enrolled_lead_hard_blocked(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """Lead 'enrolled' (hard terminal) → restore consultation bị chặn CỨNG
    (BusinessRuleViolation), KHÔNG khôi phục, KHÔNG đảo pipeline lệch
    AdmissionProfile."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_ENROLLED", "RS_STG_ENR")
    c_a = await _add_consult(db, lead.id, off, "RS_PIPE_A", 10, deleted=True)

    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.restore_consultation(
            db=db, lead_id=lead.id, consultation_id=c_a.id, current_user=manager_user
        )
    assert "enrolled" in str(exc.value.detail).lower()

    # Không mutation: lead vẫn enrolled, consultation vẫn soft-deleted.
    assert lead.consultation_status_id == "RS_ENROLLED"
    reloaded_c = await db.get(models.Consultation, c_a.id)
    assert reloaded_c.deleted_at is not None


async def test_restore_on_soft_terminal_not_blocked_and_escapes(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """Lead sts20-like (soft terminal). C1=PIPE_A (live). C2=PIPE_B (deleted, mới
    hơn). Restore C2 → KHÔNG bị chặn (soft), helper thấy PIPE_B là latest pipeline
    → lead THOÁT terminal về PIPE_B (bài học B5: không skip theo current-terminal)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_TERM", "RS_STG_TERM")
    await _add_consult(db, lead.id, off, "RS_PIPE_A", 10)
    c_b = await _add_consult(db, lead.id, off, "RS_PIPE_B", 20, deleted=True)

    lead = await _restore_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.consultation_status_id == "RS_PIPE_B"
    assert lead.pipeline_stage_id == "RS_STG_B"


async def test_restore_soft_terminal_still_latest_stays_terminal(
    db, seeded_dependencies, restore_statuses, manager_user
):
    """Lead soft terminal. C1=PIPE_A (live). C2=TERM (live, latest — cuộc gây
    terminal vẫn còn). C3=PIPE_B (deleted, cũ nhất). Restore C3 → không bị chặn
    nhưng helper thấy TERM vẫn latest pipeline → lead GIỮ terminal (guard chính
    xác: restore không mù quáng un-terminal)."""
    off = manager_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "RS_TERM", "RS_STG_TERM")
    await _add_consult(db, lead.id, off, "RS_PIPE_A", 10)
    await _add_consult(db, lead.id, off, "RS_TERM", 30)  # latest, live
    c_b = await _add_consult(db, lead.id, off, "RS_PIPE_B", 5, deleted=True)

    lead = await _restore_and_reload(db, lead.id, c_b.id, manager_user)
    assert lead.consultation_status_id == "RS_TERM"
    assert lead.pipeline_stage_id == "RS_STG_TERM"
