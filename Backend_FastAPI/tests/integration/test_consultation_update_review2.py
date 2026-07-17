"""Integration tests — review lần 2 (delta vá) cho update_consultation.

Bao 2 fix của review#2:

  • #1 — TÁCH 2 nghĩa "latest" khi GHI pipeline lead:
        Sửa status của cuộc THẬT cũ KHI có cuộc method='system' MỚI HƠN (reopen/
        milestone mang trạng thái pipeline thật) → CHỈ đổi row consultation, KHÔNG
        ghi đè lead.consultation_status_id (is_latest_for_pipeline dùng
        get_latest_consultation(exclude_system=False)). Nếu cuộc thật LÀ mới nhất
        kể cả tính system → vẫn ghi pipeline như cũ (control).

  • #5 — hard-terminal (enrolled) chặn MỌI sửa đổi cuộc (kể cả note-only /
        dời-lịch), không chỉ nhánh đổi status. Đối xứng delete_consultation +
        khớp cờ FE compute_...(is_hard_terminal). Non-terminal → sửa note OK.

Xem plan spicy-rolling-whistle.md §review#2 (#1, #5).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models, schemas
from app.services import lead_service
from app.utils.exceptions import BusinessRuleViolation

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)


async def _ensure_stage(db, stage_id, order, is_final_stage=False):
    if await db.get(models.PipelineStage, stage_id) is None:
        db.add(models.PipelineStage(
            id=stage_id, name=stage_id, order=order,
            is_final_stage=is_final_stage,
        ))
        await db.flush()


async def _ensure_status(db, status_id, stage_id, *, is_final=False, phase="consultation"):
    if await db.get(models.ConsultationStatus, status_id) is None:
        db.add(models.ConsultationStatus(
            id=status_id, name=status_id, color_code="#123456",
            stage_id=stage_id, is_final=is_final, updates_pipeline=True,
            phase=phase,
        ))
        await db.flush()


@pytest_asyncio.fixture
async def r2_statuses(db: AsyncSession, seeded_dependencies: dict):
    """Seed qua session `db` của test (conftest seed sts0x ở session RIÊNG, KHÔNG
    hiện trong session test). Dùng ID THẬT sts00/sts05/sts06 để qua phase-guard
    (PHASE_STATUSES[CONSULTATION]); R2_ENR = enrolled-terminal cho hard-block."""
    # Stage riêng (phase-guard chỉ soi status id, không soi stage id).
    await _ensure_stage(db, "R2_STG_C", 4101)
    await _ensure_stage(db, "R2_STG_E", 4106, is_final_stage=True)
    # Consultation-phase pipeline statuses (updates_pipeline mặc định True).
    await _ensure_status(db, "sts00", "R2_STG_C")
    await _ensure_status(db, "sts05", "R2_STG_C")
    await _ensure_status(db, "sts06", "R2_STG_C")
    # Enrolled-terminal → check_terminal_status_guard hard_block.
    await _ensure_status(db, "R2_ENR", "R2_STG_E", is_final=True, phase="enrolled")


async def _make_lead(db, deps, officer_id, status_id, stage_id="R2_STG_C"):
    lead = models.Lead(
        full_name="R2 Lead", phone="0900333222", email="r2_lead@test.com",
        source="website", unit_id=deps["unit_id"], assigned_officer_id=officer_id,
        consultation_status_id=status_id, pipeline_stage_id=stage_id,
        consultation_count=0, status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, method, minutes, status_id):
    c = models.Consultation(
        lead_id=lead_id, officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method=method, consultation_status_id=status_id,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


# ===========================================================================
# #1 — GHI pipeline dùng "latest incl system", KHÔNG phải "latest real"
# ===========================================================================


async def test_update_real_status_does_not_overwrite_pipeline_when_system_newer(
    db, seeded_dependencies, r2_statuses, admin_user, officer_user
):
    """Cuộc system MỚI HƠN (reopen sts06) đang giữ pipeline lead. Admin sửa status
    của cuộc THẬT cũ (sts05→sts00) → row đổi nhưng LEAD giữ nguyên sts06 (reopen
    KHÔNG bị ghi đè). Đây là bug #1: trước dùng 'latest real' → cuộc thật cũ bị coi
    là latest → ghi đè pipeline reopen."""
    off = officer_user.id
    # Lead đang ở sts06 do cuộc system reopen (mới nhất tính-cả-system).
    lead = await _make_lead(db, seeded_dependencies, off, "sts06")
    c_real = await _add_consult(db, lead.id, off, "phone", 10, "sts05")   # cũ, THẬT
    await _add_consult(db, lead.id, off, "system", 20, "sts06")           # mới, system

    await lead_service.update_consultation(
        db=db, lead_id=lead.id, consultation_id=c_real.id,
        consultation_in=schemas.ConsultationUpdate(status_id="sts00"),
        current_user=admin_user,
    )

    reloaded_c = await db.get(models.Consultation, c_real.id)
    reloaded_lead = await db.get(models.Lead, lead.id)
    # Row cuộc thật ĐÃ đổi status.
    assert reloaded_c.consultation_status_id == "sts00"
    # Nhưng LEAD giữ nguyên sts06 — cuộc system reopen mới hơn nắm pipeline.
    assert reloaded_lead.consultation_status_id == "sts06"


async def test_update_real_status_writes_pipeline_when_it_is_latest(
    db, seeded_dependencies, r2_statuses, admin_user, officer_user
):
    """Control #1: KHÔNG có cuộc system → cuộc thật LÀ latest-incl-system → sửa
    status của nó VẪN ghi pipeline lead như cũ (không hồi quy)."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "sts05")
    c_real = await _add_consult(db, lead.id, off, "phone", 10, "sts05")

    await lead_service.update_consultation(
        db=db, lead_id=lead.id, consultation_id=c_real.id,
        consultation_in=schemas.ConsultationUpdate(status_id="sts00"),
        current_user=admin_user,
    )

    reloaded_lead = await db.get(models.Lead, lead.id)
    assert reloaded_lead.consultation_status_id == "sts00"  # pipeline được ghi


# ===========================================================================
# #5 — hard-terminal (enrolled) chặn MỌI sửa đổi cuộc (kể cả note-only)
# ===========================================================================


async def test_update_note_only_on_enrolled_lead_hard_blocked(
    db, seeded_dependencies, r2_statuses, admin_user, officer_user
):
    """Lead enrolled → note-only edit (KHÔNG đổi status) vẫn BusinessRuleViolation.
    Trước fix#5: hard-block chỉ ở nhánh status_id → note-edit / dời-lịch lọt qua
    dù cờ FE đã ẩn nút = drift."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "R2_ENR", stage_id="R2_STG_E")
    c = await _add_consult(db, lead.id, off, "phone", 10, "sts05")

    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.update_consultation(
            db=db, lead_id=lead.id, consultation_id=c.id,
            consultation_in=schemas.ConsultationUpdate(notes="cố sửa note"),
            current_user=admin_user,
        )
    assert "nhập học" in str(exc.value.detail).lower()

    # Note KHÔNG bị đổi.
    reloaded = await db.get(models.Consultation, c.id)
    assert reloaded.notes != "cố sửa note"


async def test_update_note_only_on_non_terminal_lead_ok(
    db, seeded_dependencies, r2_statuses, admin_user, officer_user
):
    """Control #5: lead KHÔNG terminal → note-only edit thành công (không chặn oan)."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off, "sts05")
    c = await _add_consult(db, lead.id, off, "phone", 10, "sts05")

    await lead_service.update_consultation(
        db=db, lead_id=lead.id, consultation_id=c.id,
        consultation_in=schemas.ConsultationUpdate(notes="ghi chú mới"),
        current_user=admin_user,
    )

    reloaded = await db.get(models.Consultation, c.id)
    assert reloaded.notes == "ghi chú mới"
