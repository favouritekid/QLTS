# tests/services/test_assignment_self_sourced.py
# -*- coding: utf-8 -*-
"""Real-DB test cho ``_self_sourced_subquery`` + query GỘP COUNT-FILTER (BƯỚC 3).

Mock-suite (test_assignment.py) inject self_cnt trực tiếp nên KHÔNG chạy subquery
tương quan / FILTER thật. File này seed lead + assignment_log THẬT rồi execute cả
subquery (làm WHERE) LẪN production path ``COUNT(id) FILTER(_self_sourced_subquery)``
để chốt: chỉ lead 'manual' + reason 'by officer' (bản ghi MỚI NHẤT của officer
hiện tại) mới bị loại; admin-manual / automatic / không-log / reassign-mới-nhất
đều tính đã-chia.

Chạy one-off container (CLAUDE.md) — seed DB thật.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app import models
from app.core.constants import UserRole
from app.security import get_password_hash
from app.services.assignment_service import (
    _non_final_status_filter,
    _self_sourced_subquery,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# ⚠️ COUPLING: reason phải khớp cái lead_service.py sinh (create+direct-assign
# ~1179 + assign_lead_to_officer ~2350) và pattern ILIKE '%by officer %' của
# _self_sourced_subquery. Role token DERIVE từ UserRole.OFFICER (StrEnum→'officer')
# ⇒ ĐỔI GIÁ TRỊ enum mà quên pattern subquery → reason không chứa 'by officer ' →
# self_cnt=0 ≠ 2 → TEST ĐỎ (ghim role-value drift). ⚠️ Giới hạn: template prefix
# "Assigned during lead creation by" hardcode ở đây → KHÔNG bắt nếu lead_service đổi
# RIÊNG câu prefix (hướng no-op an toàn). Ghim đủ cần extract prefix ra hằng chung —
# hoãn (out of scope flag-OFF).
_REASON_SELF_CREATE = f"Assigned during lead creation by {UserRole.OFFICER} " + "{u}"
_REASON_ADMIN_ASSIGN = "Manually assigned by admin {u}"


async def _mk_officer(db, unit_id, tag):
    u = models.User(
        username=f"ss_{tag}",
        email=f"ss_{tag}@test.com",
        password_hash=get_password_hash("OfficerPass123!"),
        role="officer",
        status="active",
        availability_status="available",
        full_name=f"SelfSourced Officer {tag}",
        unit_id=unit_id,
        max_capacity=100,
    )
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_lead(db, deps, officer, phone):
    lead = models.Lead(
        full_name="SS Lead",
        phone=phone,
        source="website",
        unit_id=deps["unit_id"],
        status=deps["initial_status_id"],
        consultation_status_id=deps["initial_status_id"],  # non-final
        pipeline_stage_id=deps["stage_id"],
        assigned_officer_id=officer.id,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _log(db, lead, officer, method, reason, ts):
    db.add(
        models.AssignmentLog(
            lead_id=lead.id,
            officer_id=officer.id,
            method=method,
            reason=reason,
            timestamp=ts,
        )
    )
    await db.flush()


def _count_stmt(officer_ids, *extra_where):
    stmt = (
        select(
            models.Lead.assigned_officer_id,
            func.count(models.Lead.id),
        )
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,
        )
        .where(
            models.Lead.assigned_officer_id.in_(officer_ids),
            models.Lead.deleted_at.is_(None),
            _non_final_status_filter(),
            *extra_where,
        )
        .group_by(models.Lead.assigned_officer_id)
    )
    return stmt


async def test_self_sourced_subquery_classification(db, seeded_dependencies):
    """7 lead non-final gán cho 1 officer, đủ 7 tình huống latest-log. Đếm tự-tuyển
    = A + E + G (latest-ASSIGNMENT là manual 'by officer') = 3; self_cnt ≤ workload
    (bất biến ⇒ balance_load ≥ 0). Kiểm CẢ subquery-WHERE LẪN COUNT-FILTER gộp."""
    deps = seeded_dependencies
    officer = await _mk_officer(db, deps["unit_id"], "clf")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # A: manual by officer (TỰ TUYỂN) ✓
    a = await _mk_lead(db, deps, officer, "0940000001")
    await _log(db, a, officer, "manual",
               _REASON_SELF_CREATE.format(u=officer.username), t0)

    # B: manual by admin (đã-chia — admin gán tay) ✗
    b = await _mk_lead(db, deps, officer, "0940000002")
    await _log(db, b, officer, "manual",
               _REASON_ADMIN_ASSIGN.format(u="admin1"), t0)

    # C: automatic (đã-chia) ✗
    c = await _mk_lead(db, deps, officer, "0940000003")
    await _log(db, c, officer, "automatic", "Hệ thống phân công tự động", t0)

    # D: KHÔNG có log (đã-chia — subquery NULL, fail-safe) ✗
    await _mk_lead(db, deps, officer, "0940000004")

    # E: automatic (cũ) → manual by officer (mới) ⇒ LATEST = self ✓
    e = await _mk_lead(db, deps, officer, "0940000005")
    await _log(db, e, officer, "automatic", "auto cũ", t0)
    await _log(db, e, officer, "manual",
               _REASON_SELF_CREATE.format(u=officer.username), t0 + timedelta(days=1))

    # F: manual by officer (cũ) → reassignment (mới) ⇒ latest = đã-chia ✗
    f = await _mk_lead(db, deps, officer, "0940000006")
    await _log(db, f, officer, "manual",
               _REASON_SELF_CREATE.format(u=officer.username), t0)
    await _log(
        db, f, officer, "manual_reassignment", "reassigned", t0 + timedelta(days=1)
    )

    # G: manual by officer (cũ) → officer_reject (mới, GIỮ officer + non-final) ⇒
    # officer_reject KHÔNG phải assignment-source ⇒ latest-assignment = manual by
    # officer ⇒ VẪN tự tuyển ✓ (khử P2: reject self-sourced lead không hoá đã-chia).
    g = await _mk_lead(db, deps, officer, "0940000007")
    await _log(db, g, officer, "manual",
               _REASON_SELF_CREATE.format(u=officer.username), t0)
    await _log(
        db, g, officer, "officer_reject", "Officer từ chối", t0 + timedelta(days=1)
    )

    # (1) subquery làm WHERE — đếm số dòng tự tuyển
    workload = {
        r[0]: r[1] for r in (await db.execute(_count_stmt([officer.id]))).all()
    }
    self_where = {
        r[0]: r[1]
        for r in (
            await db.execute(_count_stmt([officer.id], _self_sourced_subquery()))
        ).all()
    }
    # (2) PRODUCTION path: COUNT(id) FILTER(_self_sourced_subquery()) GỘP 1 query
    filter_stmt = (
        select(
            models.Lead.assigned_officer_id,
            func.count(models.Lead.id).label("workload"),
            func.count(models.Lead.id)
            .filter(_self_sourced_subquery())
            .label("self_cnt"),
        )
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,
        )
        .where(
            models.Lead.assigned_officer_id == officer.id,
            models.Lead.deleted_at.is_(None),
            _non_final_status_filter(),
        )
        .group_by(models.Lead.assigned_officer_id)
    )
    frow = (await db.execute(filter_stmt)).one()

    assert workload[officer.id] == 7                   # tất cả 7 lead non-final
    assert self_where.get(officer.id, 0) == 3          # subquery-WHERE: A + E + G
    assert frow.workload == 7 and frow.self_cnt == 3   # FILTER gộp khớp
    assert frow.self_cnt <= frow.workload              # bất biến subset (cấu trúc)
