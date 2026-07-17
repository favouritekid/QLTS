"""Integration tests (PR-2 Nhóm 2) — F1: consultation do hệ thống tạo
(method='system') là BẤT BIẾN.

update_consultation / delete_consultation / restore_consultation đều chặn CỨNG
consultation method='system' với BusinessRuleViolation — **mọi vai trò kể cả
admin** (guard chèn TRƯỚC nhánh role). Consultation thường (method != 'system')
KHÔNG bị F1 chặn (control).

Xem plan spicy-rolling-whistle.md §PR-2 Nhóm 2 (F1).
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


@pytest_asyncio.fixture
async def f1_status(
    db: AsyncSession, seeded_dependencies: dict
) -> models.ConsultationStatus:
    """Status pipeline đơn giản cho consultation trong test F1."""
    stage = models.PipelineStage(id="F1_STG", name="F1 Stage", order=41)
    db.add(stage)
    await db.flush()
    st = models.ConsultationStatus(
        id="F1_PIPE", name="F1 Pipe", color_code="#121212",
        stage_id="F1_STG", is_final=False, updates_pipeline=True,
        phase="consultation",
    )
    db.add(st)
    await db.flush()
    return st


async def _make_lead(db, seeded_dependencies, officer_id):
    lead = models.Lead(
        full_name="F1 Lead",
        phone="0900555444",
        email="f1_lead@test.com",
        source="website",
        unit_id=seeded_dependencies["unit_id"],
        assigned_officer_id=officer_id,
        consultation_status_id="F1_PIPE",
        pipeline_stage_id="F1_STG",
        consultation_count=0,
        status="contacted",
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _add_consult(db, lead_id, officer_id, method, minutes, deleted=False):
    c = models.Consultation(
        lead_id=lead_id,
        officer_id=officer_id,
        consultation_date=_BASE + timedelta(minutes=minutes),
        method=method,
        consultation_status_id="F1_PIPE",
        deleted_at=(_BASE + timedelta(minutes=minutes)) if deleted else None,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


# ===========================================================================
# F1 — chặn sửa/xóa/khôi phục consultation method='system' (kể cả admin)
# ===========================================================================


async def test_update_system_consultation_blocked_even_admin(
    db, seeded_dependencies, f1_status, admin_user, officer_user
):
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    c = await _add_consult(db, lead.id, officer_user.id, "system", 10)

    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.update_consultation(
            db=db,
            lead_id=lead.id,
            consultation_id=c.id,
            consultation_in=schemas.ConsultationUpdate(notes="cố sửa"),
            current_user=admin_user,
        )
    assert "hệ thống" in str(exc.value.detail).lower()


async def test_delete_system_consultation_blocked_even_admin(
    db, seeded_dependencies, f1_status, admin_user, officer_user
):
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    c = await _add_consult(db, lead.id, officer_user.id, "system", 10)

    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.delete_consultation(
            db=db, lead_id=lead.id, consultation_id=c.id, current_user=admin_user
        )
    assert "hệ thống" in str(exc.value.detail).lower()

    # Consultation KHÔNG bị xoá.
    reloaded = await db.get(models.Consultation, c.id)
    assert reloaded.deleted_at is None


async def test_delete_system_consultation_blocked_officer(
    db, seeded_dependencies, f1_status, officer_user
):
    """Officer cũng bị chặn (F1 trước cả nhánh role)."""
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    c = await _add_consult(db, lead.id, officer_user.id, "system", 10)

    with pytest.raises(BusinessRuleViolation):
        await lead_service.delete_consultation(
            db=db, lead_id=lead.id, consultation_id=c.id, current_user=officer_user
        )


async def test_restore_system_consultation_blocked_even_admin(
    db, seeded_dependencies, f1_status, admin_user, officer_user
):
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    c = await _add_consult(db, lead.id, officer_user.id, "system", 10, deleted=True)

    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.restore_consultation(
            db=db, lead_id=lead.id, consultation_id=c.id, current_user=admin_user
        )
    assert "hệ thống" in str(exc.value.detail).lower()

    # Vẫn soft-deleted.
    reloaded = await db.get(models.Consultation, c.id)
    assert reloaded.deleted_at is not None


# ===========================================================================
# Control — consultation thường KHÔNG bị F1 chặn
# ===========================================================================


async def test_delete_normal_consultation_not_blocked_by_f1(
    db, seeded_dependencies, f1_status, admin_user, officer_user
):
    """method='phone' → F1 không áp; admin xóa được bình thường."""
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    c = await _add_consult(db, lead.id, officer_user.id, "phone", 10)

    await lead_service.delete_consultation(
        db=db, lead_id=lead.id, consultation_id=c.id, current_user=admin_user
    )
    await db.commit()

    reloaded = await db.get(models.Consultation, c.id)
    assert reloaded.deleted_at is not None


# ===========================================================================
# Sentinel reservation — guard tầng SERVICE (defense-in-depth, bypass schema)
# ===========================================================================


async def test_add_consultation_service_rejects_system_method(
    db, seeded_dependencies, f1_status, officer_user
):
    """Dù bypass schema (model_construct), add_consultation vẫn chặn tạo cuộc
    method='system' → không spoof được row bất biến/ẩn KPI."""
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    data = schemas.ConsultationCreate.model_construct(
        status_id="F1_PIPE", method="system",
    )
    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.add_consultation(db, lead.id, officer_user.id, data)
    assert "hệ thống" in str(exc.value.detail).lower()


async def test_update_consultation_service_rejects_normal_to_system(
    db, seeded_dependencies, f1_status, admin_user, officer_user
):
    """Bypass schema (model_construct): đổi cuộc THƯỜNG → method='system' vẫn bị
    service chặn (F1 chỉ chặn row ĐÃ là system, không chặn spoof normal→system)."""
    lead = await _make_lead(db, seeded_dependencies, officer_user.id)
    c = await _add_consult(db, lead.id, officer_user.id, "phone", 10)
    data = schemas.ConsultationUpdate.model_construct(method="system")

    with pytest.raises(BusinessRuleViolation) as exc:
        await lead_service.update_consultation(
            db=db, lead_id=lead.id, consultation_id=c.id,
            consultation_in=data, current_user=admin_user,
        )
    assert "hệ thống" in str(exc.value.detail).lower()

    # Không bị đổi thành system.
    reloaded = await db.get(models.Consultation, c.id)
    assert reloaded.method == "phone"
