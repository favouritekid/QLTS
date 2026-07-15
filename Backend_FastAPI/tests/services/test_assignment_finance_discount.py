# tests/services/test_assignment_finance_discount.py
# -*- coding: utf-8 -*-
"""Real-DB test cho GIẢM TRỪ TẢI HỌC PHÍ (Option A, ENABLE_FINANCE_WORKLOAD_DISCOUNT).

Bọc sau cờ ``ENABLE_FINANCE_WORKLOAD_DISCOUNT`` (default OFF). Khi ON: lead ở
trạng thái học phí non-final (``TUITION_HOLD_STATUS_IDS`` = sts14/sts10) được
giảm trừ khỏi:
  - cơ sở sắp xếp ``dist_load`` (eff_util) — GỘP với self-tuyển, chống trừ 2 lần
    qua phần giao S∩T,
  - cổng ``overloaded`` = ((workload − tuition)/capacity) >= SAFETY_THRESHOLD,
  - ``is_officer_at_threshold`` (referral fast-path).
Trần cứng ``workload < capacity`` VẪN theo TỔNG workload (không test ở đây).

Seed lead + consultation_status THẬT rồi execute production path
(``COUNT(id) FILTER(_tuition_hold_filter())`` + union self∩tuition) và gọi thẳng
``is_officer_at_threshold``. Chạy one-off container (CLAUDE.md) — seed DB thật.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import and_, func, select

from app import models
from app.config import settings
from app.security import get_password_hash
from app.services.assignment_reason import build_assignment_reason
from app.services.assignment_service import (
    TUITION_HOLD_STATUS_IDS,
    _non_final_status_filter,
    _self_sourced_subquery,
    _tuition_hold_filter,
    is_officer_at_threshold,
)

# asyncio_mode=auto (pytest.ini) ⇒ async test tự chạy, KHÔNG cần mark asyncio
# (mark asyncio ở module-level sẽ dính nhầm vào test đồng bộ documented → warning).
pytestmark = pytest.mark.integration


async def _ensure_status(db, sid, is_final):
    """get-or-create ConsultationStatus (test DB không seed sẵn sts14/10/18/06;
    get-or-create để idempotent giữa các test cùng schema)."""
    st = await db.get(models.ConsultationStatus, sid)
    if st is None:
        db.add(
            models.ConsultationStatus(
                id=sid,
                name=f"FD {sid}",
                color_code="#123456",
                is_final=is_final,
            )
        )
    else:
        st.is_final = is_final
    await db.flush()


async def _mk_officer(db, unit_id, tag, cap=100):
    u = models.User(
        username=f"fd_{tag}",
        email=f"fd_{tag}@test.com",
        password_hash=get_password_hash("OfficerPass123!"),
        role="officer",
        status="active",
        availability_status="available",
        full_name=f"Finance Officer {tag}",
        unit_id=unit_id,
        max_capacity=cap,
    )
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _mk_lead(db, deps, officer, status_id, phone):
    lead = models.Lead(
        full_name="FD Lead",
        phone=phone,
        source="website",
        unit_id=deps["unit_id"],
        status="qualified",
        consultation_status_id=status_id,
        pipeline_stage_id=deps["stage_id"],
        assigned_officer_id=officer.id,
        assigned_at=datetime.now(timezone.utc),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _self_log(db, lead, officer):
    """AssignmentLog manual + reason DO CHÍNH officer ⇒ latest self-sourced."""
    db.add(
        models.AssignmentLog(
            lead_id=lead.id,
            officer_id=officer.id,
            method="manual",
            reason=build_assignment_reason("Assigned during lead creation", officer),
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    await db.flush()


def test_tuition_hold_status_ids_documented():
    """Ghim danh sách trạng thái học phí non-final được giảm trừ. Hardcode CÓ CHỦ
    ĐÍCH (KHÔNG derive theo stage_id='stg05') để sts18 (TUITION_REFUNDED, final)
    không lọt vào discount."""
    assert TUITION_HOLD_STATUS_IDS == ("sts14", "sts10")


async def test_tuition_hold_filter_and_union_dedup(db, seeded_dependencies):
    """production path: workload (non-final) / tuition_cnt / self_cnt / (self∩tuition).

    5 lead: sts14, sts10 (tuition), sts18 (FINAL → rớt workload), sts06 (non-final
    non-tuition), sts14+self-sourced. Chốt: sts18 KHÔNG vào workload lẫn tuition;
    dist_load = workload − |self ∪ tuition| dedup đúng qua phần giao."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)  # Chưa hoàn tất học phí (non-final)
    await _ensure_status(db, "sts10", False)  # Đã hoàn tất học phí (non-final)
    await _ensure_status(db, "sts18", True)   # Đã hoàn học phí / refund (FINAL)
    await _ensure_status(db, "sts06", False)  # Đồng ý tư vấn (non-final, non-tuition)
    o = await _mk_officer(db, deps["unit_id"], "flt")

    await _mk_lead(db, deps, o, "sts14", "0961000001")           # tuition
    await _mk_lead(db, deps, o, "sts10", "0961000002")           # tuition
    await _mk_lead(db, deps, o, "sts18", "0961000003")           # FINAL → excluded
    await _mk_lead(db, deps, o, "sts06", "0961000004")           # non-final non-tuition
    l5 = await _mk_lead(db, deps, o, "sts14", "0961000005")  # tuition + self-sourced
    await _self_log(db, l5, o)

    stmt = (
        select(
            func.count(models.Lead.id).label("workload"),
            func.count(models.Lead.id)
            .filter(_self_sourced_subquery())
            .label("self_cnt"),
            func.count(models.Lead.id)
            .filter(_tuition_hold_filter())
            .label("tuition_cnt"),
            func.count(models.Lead.id)
            .filter(and_(_self_sourced_subquery(), _tuition_hold_filter()))
            .label("both_cnt"),
        )
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,
        )
        .where(
            models.Lead.assigned_officer_id == o.id,
            models.Lead.deleted_at.is_(None),
            _non_final_status_filter(),
        )
    )
    row = (await db.execute(stmt)).one()

    # sts18 (final) rớt khỏi workload ⇒ còn L1,L2,L4,L5 = 4
    assert row.workload == 4
    assert row.tuition_cnt == 3   # L1(sts14), L2(sts10), L5(sts14)
    assert row.self_cnt == 1      # L5
    assert row.both_cnt == 1      # L5 = tuition ∩ self
    # dist_load = workload − |self ∪ tuition| = 4 − 1 − 3 + 1 = 1 (chỉ còn L4)
    assert row.workload - row.self_cnt - row.tuition_cnt + row.both_cnt == 1
    # bất biến subset cấu trúc: mỗi discount ⊆ workload
    assert row.tuition_cnt <= row.workload
    assert row.self_cnt <= row.workload


async def test_is_officer_at_threshold_finance_discount(
    db, seeded_dependencies, monkeypatch
):
    """Referral fast-path (Option A yêu cầu #1): cờ ON trừ tải học phí khỏi ngưỡng.

    cap=10; 7 lead sts06 + 2 lead sts14 = workload 9, tuition 2.
      - OFF: 9/10 = 0.90 ≥ 0.8  → at threshold (True)
      - ON:  (9−2)/10 = 0.70 < 0.8 → KHÔNG at threshold (False)
    """
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    await _ensure_status(db, "sts06", False)
    o = await _mk_officer(db, deps["unit_id"], "thr", cap=10)
    for i in range(7):
        await _mk_lead(db, deps, o, "sts06", f"09620001{i:02d}")
    for i in range(2):
        await _mk_lead(db, deps, o, "sts14", f"09620002{i:02d}")

    # Cờ OFF ⇒ ngưỡng theo TỔNG workload (y hệt hôm nay).
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", False)
    assert await is_officer_at_threshold(db, o) is True

    # Cờ ON ⇒ trừ tải học phí ⇒ dưới ngưỡng ⇒ referral vẫn gán thẳng được.
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    assert await is_officer_at_threshold(db, o) is False
