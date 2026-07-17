"""Integration tests (PR-2 Nhóm 4) — get_lead_timeline gắn cờ quyền per-cuộc.

Khoá hợp đồng thin-client: mỗi consultation trong timeline mang can_edit /
can_delete / can_reschedule + blocker để FE gate nút KHÔNG đọc user.role.
Trọng tâm: **can_reschedule chỉ bật trên lịch hẹn ĐANG HIỆU LỰC** (cuộc-có-hẹn
mới nhất), áp MỌI vai trò kể cả admin → vá bug nút Dời/Hủy hiện trên cuộc CŨ.

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 4.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import lead_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
_APPT = _BASE + timedelta(days=7)  # giá trị scheduled_at (future/past không quan trọng)


@pytest_asyncio.fixture
async def tl_status(db: AsyncSession, seeded_dependencies: dict):
    stage = models.PipelineStage(id="TL_STG", name="TL Stage", order=51)
    db.add(stage)
    await db.flush()
    st = models.ConsultationStatus(
        id="TL_PIPE", name="TL Pipe", color_code="#161616",
        stage_id="TL_STG", is_final=False, updates_pipeline=True,
        phase="consultation",
    )
    db.add(st)
    await db.flush()
    return st


async def _make_lead(db, deps, officer_id):
    lead = models.Lead(
        full_name="TL Lead", phone="0900222111", email="tl_lead@test.com",
        source="website", unit_id=deps["unit_id"], assigned_officer_id=officer_id,
        consultation_status_id="TL_PIPE", pipeline_stage_id="TL_STG",
        status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, method, minutes, scheduled_at=None):
    c = models.Consultation(
        lead_id=lead_id, officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method=method, consultation_status_id="TL_PIPE",
        scheduled_at=scheduled_at,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


def _by_id(timeline):
    return {
        it["data"]["id"]: it["data"]
        for it in timeline if it["type"] == "consultation"
    }


async def test_timeline_admin_flags_and_active_appointment(
    db, seeded_dependencies, tl_status, admin_user, officer_user
):
    """Admin sửa/xóa mọi cuộc non-system; nhưng can_reschedule CHỈ bật trên
    lịch hẹn đang hiệu lực (c_new), KHÔNG bật trên hẹn cũ (c_old) — vá bug 17-07.
    Cuộc system → mọi cờ False."""
    off = officer_user.id
    lead = await _make_lead(db, seeded_dependencies, off)
    c_old = await _add_consult(db, lead.id, off, "phone", 10, scheduled_at=_APPT)
    c_new = await _add_consult(db, lead.id, off, "phone", 20, scheduled_at=_APPT)
    c_sys = await _add_consult(db, lead.id, off, "system", 5)  # older, no appt

    tl = await lead_service.get_lead_timeline(db, lead.id, current_user=admin_user)
    d = _by_id(tl)

    # Admin edit/delete mọi cuộc non-system (không cần latest).
    assert d[c_old.id]["can_edit"] and d[c_old.id]["can_delete"]
    assert d[c_new.id]["can_edit"] and d[c_new.id]["can_delete"]
    # System → bất biến.
    assert not d[c_sys.id]["can_edit"] and d[c_sys.id]["edit_blocker"] == "system"
    assert not d[c_sys.id]["can_reschedule"]
    # 🎯 Active appointment = c_new (cuộc-có-hẹn mới nhất) → CHỈ nó reschedule được.
    assert d[c_new.id]["can_reschedule"] is True
    assert d[c_old.id]["can_reschedule"] is False  # hẹn CŨ không dời/hủy được


async def test_timeline_officer_latest_only(
    db, seeded_dependencies, tl_status, officer_user
):
    """Officer chỉ sửa/xóa/dời cuộc MỚI NHẤT của mình; cuộc cũ → not_latest."""
    off = officer_user
    lead = await _make_lead(db, seeded_dependencies, off.id)
    c_old = await _add_consult(db, lead.id, off.id, "phone", 10, scheduled_at=_APPT)
    c_new = await _add_consult(db, lead.id, off.id, "phone", 20, scheduled_at=_APPT)

    tl = await lead_service.get_lead_timeline(db, lead.id, current_user=off)
    d = _by_id(tl)

    assert d[c_new.id]["can_edit"] and d[c_new.id]["can_delete"]
    assert d[c_new.id]["can_reschedule"]  # latest + active + own + recent
    assert not d[c_old.id]["can_edit"] and d[c_old.id]["edit_blocker"] == "not_latest"
    assert not d[c_old.id]["can_reschedule"]


async def test_timeline_no_current_user_flags_default_false(
    db, seeded_dependencies, tl_status, officer_user
):
    """current_user=None (vd callsite /insights) → cờ giữ mặc định False."""
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    await _add_consult(db, lead.id, officer_user.id, "phone", 10, scheduled_at=_APPT)

    tl = await lead_service.get_lead_timeline(db, lead.id)  # KHÔNG truyền user
    items = [it for it in tl if it["type"] == "consultation"]
    assert items
    assert all(
        not it["data"]["can_edit"]
        and not it["data"]["can_delete"]
        and not it["data"]["can_reschedule"]
        for it in items
    )
