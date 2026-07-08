# tests/services/test_lead_offering_keep_officer.py
"""
FIX đổi ngành (offering) — chỉ reassign khi officer hiện tại KHÔNG còn đủ điều
kiện nhận lead ở đơn vị đích. GIỮ officer (chỉ đồng bộ unit_id) khi officer vẫn
ELIGIBLE: role=officer + active + available + đúng đơn vị đích + không trong
blacklist `rejected_by_officer_ids` (khớp pool auto-assign, assignment_service).
Thiếu bất kỳ điều kiện nào → reassign (không để lead kẹt trên người auto-assign
không với tới, không dán ngược người vừa từ chối).

Chạy one-off container (CLAUDE.md). Không gọi post_commit callback → không đụng
celery/notification broker. `get_target_unit_for_offering` mock để chốt đơn vị
đích; offering là bản ghi THẬT để qua FK lead_offering_id_fkey.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.schemas import LeadCreate, LeadUpdate
from app.security import get_password_hash
from app.services import lead_service
from app.utils.exceptions import BusinessRuleViolation, DuplicateResourceError

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_DIST = (
    "app.services.lead_service.distribution_service."
    "get_target_unit_for_offering"
)


async def _mk_officer(
    db, unit_id, tag, status="active", availability="available"
):
    u = models.User(
        username=f"kofc_{tag}",
        email=f"kofc_{tag}@test.com",
        password_hash=get_password_hash("OfficerPass123!"),
        role="officer",
        status=status,
        availability_status=availability,
        full_name=f"Keep Officer {tag}",
        unit_id=unit_id,
    )
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_offering(db, unit_id, tag) -> int:
    """MajorProgram + ProgramOffering thật (qua FK lead.offering_id). Đơn vị của
    ngành KHÔNG ảnh hưởng — routing đã mock qua get_target_unit_for_offering."""
    major = models.MajorProgram(
        name=f"Test Major {tag}",
        degree_level="Cao đẳng",
        code=f"TESTMJ{tag}",
        unit_id=unit_id,
    )
    db.add(major)
    await db.flush()
    offering = models.ProgramOffering(
        offering_type="Chính quy",
        program_id=major.id,
        is_active=True,
    )
    db.add(offering)
    await db.flush()
    return offering.id


async def _mk_lead(db, deps, officer, phone, rejected=None, email=None,
                   unit_id=None):
    lead = models.Lead(
        full_name="Keep-Officer Lead",
        phone=phone,
        email=email,
        source="website",
        unit_id=unit_id or deps["unit_id"],
        status=deps["initial_status_id"],
        consultation_status_id=deps["initial_status_id"],
        pipeline_stage_id=deps["stage_id"],
        assigned_officer_id=officer.id if officer else None,
        assigned_at=datetime.now(timezone.utc) if officer else None,
        rejected_by_officer_ids=rejected or [],
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _log_methods(db, lead_id):
    rows = await db.execute(
        select(models.AssignmentLog.method).where(
            models.AssignmentLog.lead_id == lead_id
        )
    )
    return set(rows.scalars().all())


async def _run_offering_change(db, lead_id, offering_id, target_unit, admin):
    with patch(_DIST, new_callable=AsyncMock, return_value=target_unit):
        await lead_service.update_lead(
            db, lead_id, LeadUpdate(offering_id=offering_id), updated_by=admin
        )


# --- GIỮ officer ---------------------------------------------------------

async def test_keep_officer_when_offering_stays_in_officer_unit(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Officer eligible ở đơn vị đích → GIỮ officer, đồng bộ unit + log sync."""
    officer = await _mk_officer(db, second_unit.id, "keep")
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "keep")
    lead = await _mk_lead(db, seeded_dependencies, officer, "0909555001")
    await _run_offering_change(
        db, lead.id, offering_id, second_unit.id, admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id == officer.id  # GIỮ officer
    assert lead.unit_id == second_unit.id          # đồng bộ unit đích
    _logs = await _log_methods(db, lead.id)
    assert "offering_change_unit_synced" in _logs
    assert "system_auto_reassign" not in _logs  # nhánh reassign KHÔNG chạy


# --- REASSIGN (từng lý do) -----------------------------------------------

async def test_reassign_when_officer_not_in_target_unit(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Officer khác đơn vị đích → reassign."""
    officer = await _mk_officer(db, seeded_dependencies["unit_id"], "reasgn")
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "reasgn")
    lead = await _mk_lead(db, seeded_dependencies, officer, "0909555002")
    await _run_offering_change(
        db, lead.id, offering_id, second_unit.id, admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id is None
    assert lead.unit_id == second_unit.id
    assert "system_auto_reassign" in await _log_methods(db, lead.id)


async def test_reassign_when_officer_in_target_unit_but_blacklisted(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Officer ở đơn vị đích NHƯNG đã từ chối lead → vẫn reassign."""
    officer = await _mk_officer(db, second_unit.id, "black")
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "black")
    lead = await _mk_lead(
        db, seeded_dependencies, officer, "0909555003", rejected=[officer.id]
    )
    await _run_offering_change(
        db, lead.id, offering_id, second_unit.id, admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id is None  # KHÔNG dán ngược người đã từ chối


async def test_reassign_when_officer_in_target_unit_but_inactive(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Officer ở đơn vị đích NHƯNG status=inactive → reassign (regression fix:
    không kẹt lead trên officer bị vô hiệu hoá mà auto-assign không với tới)."""
    officer = await _mk_officer(
        db, second_unit.id, "inact", status="inactive"
    )
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "inact")
    lead = await _mk_lead(db, seeded_dependencies, officer, "0909555004")
    await _run_offering_change(
        db, lead.id, offering_id, second_unit.id, admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id is None  # KHÔNG giữ officer inactive


async def test_reassign_when_officer_in_target_unit_but_unavailable(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Officer ở đơn vị đích NHƯNG availability=on_leave → reassign."""
    officer = await _mk_officer(
        db, second_unit.id, "leave", availability="on_leave"
    )
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "leave")
    lead = await _mk_lead(db, seeded_dependencies, officer, "0909555005")
    await _run_offering_change(
        db, lead.id, offering_id, second_unit.id, admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id is None  # KHÔNG giữ officer đang nghỉ


async def test_reassign_when_lead_unassigned(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Lead CHƯA gán officer + đổi ngành đổi đơn vị → reassign (ghi log)."""
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "noofc")
    lead = await _mk_lead(db, seeded_dependencies, None, "0909555006")
    await _run_offering_change(
        db, lead.id, offering_id, second_unit.id, admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id is None
    assert lead.unit_id == second_unit.id
    assert "system_auto_reassign" in await _log_methods(db, lead.id)


# --- Email-check chạy cả nhánh KEEP --------------------------------------

async def test_keep_path_still_rechecks_email_conflict(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Nhánh GIỮ officer vẫn kiểm email trùng trong đơn vị đích (email-check dời
    ra chạy cả 2 nhánh)."""
    officer = await _mk_officer(db, second_unit.id, "mail")
    offering_id = await _mk_offering(db, seeded_dependencies["unit_id"], "mail")
    # Lead khác cùng email đã ở đơn vị đích
    conflict = models.Lead(
        full_name="Conflict Target",
        phone="0909555008",
        email="dup_keep@test.com",
        source="website",
        unit_id=second_unit.id,
        status=seeded_dependencies["initial_status_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(conflict)
    await db.flush()
    lead = await _mk_lead(
        db, seeded_dependencies, officer, "0909555007", email="dup_keep@test.com"
    )
    with patch(_DIST, new_callable=AsyncMock, return_value=second_unit.id):
        with pytest.raises(DuplicateResourceError):
            await lead_service.update_lead(
                db, lead.id, LeadUpdate(offering_id=offering_id),
                updated_by=admin_user,
            )


# --- (b) gán tay: officer PHẢI cùng đơn vị lead --------------------------

async def test_manual_assign_rejects_cross_unit_officer(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Gán tay officer KHÁC đơn vị lead → BusinessRuleViolation (invariant b)."""
    officer = await _mk_officer(db, second_unit.id, "xunit")  # unit đích 2001
    lead = await _mk_lead(db, seeded_dependencies, None, "0909555010")  # unit 1001
    with pytest.raises(BusinessRuleViolation):
        await lead_service.assign_lead_manually(
            db, lead.id, officer.id, assigner=admin_user
        )


async def test_manual_assign_accepts_same_unit_officer(
    db: AsyncSession, seeded_dependencies, admin_user
):
    """Gán tay officer CÙNG đơn vị lead → OK, lead.unit KHÔNG đổi."""
    officer = await _mk_officer(db, seeded_dependencies["unit_id"], "sunit")
    lead = await _mk_lead(db, seeded_dependencies, None, "0909555011")
    await lead_service.assign_lead_manually(
        db, lead.id, officer.id, assigner=admin_user
    )
    await db.refresh(lead)
    assert lead.assigned_officer_id == officer.id
    assert lead.unit_id == seeded_dependencies["unit_id"]  # lead.unit GIỮ NGUYÊN
    assert "manual" in await _log_methods(db, lead.id)  # AssignmentLog ghi


async def test_bulk_assign_leads_reports_cross_unit_per_lead(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """bulk_assign_leads: lead lệch đơn vị officer → báo lỗi PER-LEAD (không
    abort cả batch) nhờ except bắt BusinessRuleViolation."""
    officer = await _mk_officer(db, second_unit.id, "bulk")  # unit đích 2001
    lead_ok = await _mk_lead(
        db, seeded_dependencies, None, "0909555020", unit_id=second_unit.id
    )  # cùng đơn vị officer
    lead_bad = await _mk_lead(
        db, seeded_dependencies, None, "0909555021"
    )  # unit 1001, lệch
    result, _cb = await lead_service.bulk_assign_leads(
        db, [lead_ok.id, lead_bad.id], officer.id, assigner=admin_user
    )
    assert result["successful"] == 1
    assert result["failed"] == 1  # batch KHÔNG abort — lead lệch báo riêng
    assert any(e["lead_id"] == lead_bad.id for e in result["errors"])
    await db.refresh(lead_ok)
    await db.refresh(lead_bad)
    assert lead_ok.assigned_officer_id == officer.id  # cùng đơn vị → gán
    assert lead_bad.assigned_officer_id is None        # lệch → KHÔNG gán


async def test_create_lead_rejects_cross_unit_direct_assign(
    db: AsyncSession, seeded_dependencies, second_unit, admin_user
):
    """Admin tạo lead unit A + gán TRỰC TIẾP officer unit B → BusinessRuleViolation."""
    officer_b = await _mk_officer(db, second_unit.id, "crt")  # unit 2001
    lead_in = LeadCreate(
        full_name="Cross Create",
        phone="0909555022",
        source="website",
        unit_id=seeded_dependencies["unit_id"],  # unit 1001
        assigned_officer_id=officer_b.id,          # officer unit 2001 (lệch)
    )
    with pytest.raises(BusinessRuleViolation):
        await lead_service.create_lead(db, lead_in, created_by=admin_user)
