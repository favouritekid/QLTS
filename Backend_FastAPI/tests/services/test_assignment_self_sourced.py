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
from app.security import get_password_hash
from app.services.assignment_reason import build_assignment_reason
from app.services.assignment_service import (
    _non_final_status_filter,
    _self_sourced_subquery,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

# Seed reason officer-self qua CHÍNH build_assignment_reason (real producer, User
# THẬT role=String 'officer') ⇒ integration exercise đúng path prod (User.role str
# → token), KHÔNG hardcode shape. Admin negative case giữ literal (chỉ cần KHÔNG
# chứa token). Coupling ghim thêm bởi test_self_sourced_reason_token_contract.
_REASON_ADMIN_ASSIGN = "Manually assigned by admin {u}"


def _self_reason(officer):
    """reason officer tự tạo — qua CHÍNH builder production (User thật, role=str)."""
    return build_assignment_reason("Assigned during lead creation", officer)


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
    """officer1: 8 lead non-final, 8 tình huống latest-log ⇒ tự-tuyển = A+E+G+H
    (latest-ASSIGNMENT là manual 'by officer') = 4. officer2: 1 lead (I) chứng minh
    correlation officer_id — log 'by officer' của officer1 KHÔNG lọt sang officer2.
    self_cnt ≤ workload. Kiểm CẢ subquery-WHERE LẪN COUNT-FILTER gộp."""
    deps = seeded_dependencies
    officer = await _mk_officer(db, deps["unit_id"], "clf")
    officer2 = await _mk_officer(db, deps["unit_id"], "clf2")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # A: manual by officer (TỰ TUYỂN) ✓
    a = await _mk_lead(db, deps, officer, "0940000001")
    await _log(db, a, officer, "manual",
               _self_reason(officer), t0)

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
               _self_reason(officer), t0 + timedelta(days=1))

    # F: manual by officer (cũ) → reassignment (mới) ⇒ latest = đã-chia ✗
    f = await _mk_lead(db, deps, officer, "0940000006")
    await _log(db, f, officer, "manual",
               _self_reason(officer), t0)
    await _log(
        db, f, officer, "manual_reassignment", "reassigned", t0 + timedelta(days=1)
    )

    # G: manual by officer (cũ) → officer_reject (mới, GIỮ officer + non-final) ⇒
    # officer_reject KHÔNG phải assignment-source ⇒ latest-assignment = manual by
    # officer ⇒ VẪN tự tuyển ✓ (khử P2: reject self-sourced lead không hoá đã-chia).
    g = await _mk_lead(db, deps, officer, "0940000007")
    await _log(db, g, officer, "manual",
               _self_reason(officer), t0)
    await _log(
        db, g, officer, "officer_reject", "Officer từ chối", t0 + timedelta(days=1)
    )

    # H: manual by officer (cũ) → offering_change_unit_synced (mới, keep-sync đổi
    # ngành, GIỮ officer + non-final) ⇒ KHÔNG phải assignment-source ⇒ latest-
    # assignment = manual by officer ⇒ VẪN tự tuyển ✓ (nửa còn lại của fix P2 —
    # case LUÔN load-bearing).
    h = await _mk_lead(db, deps, officer, "0940000008")
    await _log(db, h, officer, "manual",
               _self_reason(officer), t0)
    await _log(
        db, h, officer, "offering_change_unit_synced", "Đổi ngành",
        t0 + timedelta(days=1)
    )

    # I (CROSS-OFFICER): lead nay gán OFFICER2 nhưng có log 'by officer' của
    # OFFICER1 (t0) rồi manual_reassignment sang officer2 (t1). Subquery của officer2
    # (correlate al.officer_id==assigned=officer2) chỉ thấy log officer2 = reassign ⇒
    # KHÔNG tự tuyển; log 'by officer' của officer1 KHÔNG lọt (chứng minh correlation
    # officer_id không bị đếm nhầm sang officer khác).
    i_lead = await _mk_lead(db, deps, officer2, "0940000009")
    await _log(db, i_lead, officer, "manual",
               _self_reason(officer), t0)
    await _log(
        db, i_lead, officer2, "manual_reassignment", "reassign→officer2",
        t0 + timedelta(days=1)
    )

    ids = [officer.id, officer2.id]
    # (1) subquery làm WHERE — đếm số dòng tự tuyển, theo officer
    workload = {r[0]: r[1] for r in (await db.execute(_count_stmt(ids))).all()}
    self_where = {
        r[0]: r[1]
        for r in (await db.execute(_count_stmt(ids, _self_sourced_subquery()))).all()
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
            models.Lead.assigned_officer_id.in_(ids),
            models.Lead.deleted_at.is_(None),
            _non_final_status_filter(),
        )
        .group_by(models.Lead.assigned_officer_id)
    )
    frows = {r.assigned_officer_id: r for r in (await db.execute(filter_stmt)).all()}

    # officer1: 8 lead, tự tuyển A+E+G+H = 4 (officer_reject + offering-sync ko reset)
    assert workload[officer.id] == 8
    assert self_where.get(officer.id, 0) == 4
    assert frows[officer.id].workload == 8 and frows[officer.id].self_cnt == 4
    # officer2: 1 lead (I) — correlation officer_id ⇒ log 'by officer' của officer1
    # KHÔNG lọt sang officer2 ⇒ self_cnt = 0
    assert workload[officer2.id] == 1
    assert self_where.get(officer2.id, 0) == 0
    assert frows[officer2.id].workload == 1 and frows[officer2.id].self_cnt == 0
    # bất biến subset cấu trúc
    assert all(fr.self_cnt <= fr.workload for fr in frows.values())
