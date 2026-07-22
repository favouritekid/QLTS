# tests/services/test_assignment_finance_discount.py
# -*- coding: utf-8 -*-
"""Real-DB test cho GIẢM TRỪ TẢI HỌC PHÍ (Option A, ENABLE_FINANCE_WORKLOAD_DISCOUNT).

Bọc sau cờ ``ENABLE_FINANCE_WORKLOAD_DISCOUNT`` (default OFF). Khi ON: lead ở
trạng thái học phí non-final (``TUITION_HOLD_STATUS_IDS`` = sts14/sts10) VÀ ĐÃ CÓ
TIỀN HỌC PHÍ VÀO (sts10, hoặc sts14 có ``fee.paid_amount > 0``) được giảm trừ khỏi:
  - cơ sở sắp xếp ``dist_load`` (eff_util) — GỘP với self-tuyển, chống trừ 2 lần
    qua phần giao S∩T,
  - cổng ``overloaded`` = ((workload − tuition)/capacity) >= SAFETY_THRESHOLD,
  - ``is_officer_at_threshold`` (referral fast-path).
Trần cứng ``workload < capacity`` VẪN theo TỔNG workload (không test ở đây).

⚠️ sts14 "đã tính phí nhưng CHƯA thu đồng nào" KHÔNG được trừ — officer vẫn phải
theo đuổi thu tiền nên đó vẫn là tải thật (ghim bởi
``test_sts14_unpaid_stays_in_workload``).

Seed lead + consultation_status + fee THẬT rồi execute production path
(``COUNT(id) FILTER(_tuition_hold_filter())`` + union self∩tuition) và gọi thẳng
``is_officer_at_threshold``. Chạy one-off container (CLAUDE.md) — seed DB thật.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import and_, func, select

from app import models
from app.config import settings
from app.security import get_password_hash
from app.services.assignment_reason import build_assignment_reason
from app.services.assignment_service import (
    TUITION_HOLD_STATUS_IDS,
    TUITION_SETTLED_STATUS_ID,
    _non_final_status_filter,
    _self_sourced_subquery,
    _tuition_hold_filter,
    is_officer_at_threshold,
)

# asyncio_mode=auto (pytest.ini) ⇒ async test tự chạy, KHÔNG cần mark asyncio
# (mark asyncio ở module-level sẽ dính nhầm vào test đồng bộ documented → warning).
pytestmark = pytest.mark.integration


async def _ensure_status(db, sid, is_final):
    """create-if-absent ConsultationStatus (test DB không seed sẵn sts14/10/18/06).

    ⚠️ KHÔNG ghi đè ``is_final`` của row ĐÃ tồn tại: đây là row lookup dùng chung,
    ghi đè sẽ rewrite semantics cho test khác trong cùng session. Nếu gặp seed sẵn
    mâu thuẫn → FAIL rõ ràng thay vì âm thầm sửa bảng tra cứu.
    """
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
        await db.flush()
    elif st.is_final != is_final:
        pytest.fail(
            f"ConsultationStatus {sid} đã tồn tại với is_final={st.is_final}, "
            f"test cần {is_final} — KHÔNG ghi đè row lookup dùng chung."
        )


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


async def _mk_paid_tuition(
    db,
    lead,
    *,
    paid=Decimal("5000000"),
    fee_type="tuition",
    status="partial",
):
    """Hồ sơ + 1 khoản phí đã ghi nhận tiền thu — bằng chứng "đã xác nhận đóng".

    ``paid=0`` ⇒ mô phỏng ca ĐÃ TÍNH PHÍ NHƯNG CHƯA THU (không được trừ tải).
    """
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        citizen_id=uuid.uuid4().hex[:12],
        status="approved",
        applied_rules={},
        academic_year=2026,
        version=1,
    )
    db.add(profile)
    await db.flush()

    db.add(
        models.Fee(
            admission_profile_id=profile.id,
            fee_type=fee_type,
            semester_no=1 if fee_type == "tuition" else None,
            academic_year=2026,
            base_amount=Decimal("10000000"),
            total_discount=Decimal("0"),
            final_amount=Decimal("10000000"),
            paid_amount=paid,
            waived_amount=Decimal("0"),
            status=status,
            calculated_at=datetime.now(timezone.utc),
            version=1,
        )
    )
    await db.flush()
    return profile


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
    """Ghim danh sách trạng thái học phí non-final được giảm trừ + NEO vào nguồn
    taxonomy chính ``phase_manager.PHASE_STATUSES[FEE]`` để BẮT DRIFT: thêm/đổi
    trạng thái fee mà quên cập nhật đây → test gãy. Hardcode CÓ CHỦ ĐÍCH (KHÔNG
    derive theo stage_id='stg05') để sts18 (TUITION_REFUNDED, final) không lọt."""
    from app.services.phase_manager import LeadPhase, PHASE_STATUSES

    assert TUITION_HOLD_STATUS_IDS == ("sts14", "sts10")
    # sts10 = HK1 settled ⇒ tự nó là bằng chứng thu tiền, KHÔNG cần soi bảng fee.
    assert TUITION_SETTLED_STATUS_ID == "sts10"
    assert TUITION_SETTLED_STATUS_ID in TUITION_HOLD_STATUS_IDS
    fee = PHASE_STATUSES[LeadPhase.FEE]
    # Là tập con của nhóm FEE chính thức, và đúng bằng FEE trừ sts18 (fee status
    # FINAL duy nhất, bị loại có chủ đích khỏi discount tải).
    assert set(TUITION_HOLD_STATUS_IDS) <= fee
    assert set(TUITION_HOLD_STATUS_IDS) == fee - {"sts18"}
    assert "sts18" in fee  # neo: nếu sts18 rời nhóm FEE, xem lại giả định loại trừ


async def test_tuition_hold_filter_and_union_dedup(db, seeded_dependencies):
    """production path: workload (non-final) / tuition_cnt / self_cnt / (self∩tuition).

    5 lead: sts14 ĐÃ THU một phần, sts10, sts18 (FINAL → rớt workload), sts06
    (non-final non-tuition), sts14 ĐÃ THU + self-sourced. Chốt: sts18 KHÔNG vào
    workload lẫn tuition; dist_load = workload − |self ∪ tuition| dedup đúng qua
    phần giao."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)  # Chưa hoàn tất học phí (non-final)
    await _ensure_status(db, "sts10", False)  # Đã hoàn tất học phí (non-final)
    await _ensure_status(db, "sts18", True)   # Đã hoàn học phí / refund (FINAL)
    await _ensure_status(db, "sts06", False)  # Đồng ý tư vấn (non-final, non-tuition)
    o = await _mk_officer(db, deps["unit_id"], "flt")

    l1 = await _mk_lead(db, deps, o, "sts14", "0961000001")   # tuition đã thu 1 phần
    await _mk_paid_tuition(db, l1)
    await _mk_lead(db, deps, o, "sts10", "0961000002")        # settled (không cần fee)
    await _mk_lead(db, deps, o, "sts18", "0961000003")           # FINAL → excluded
    await _mk_lead(db, deps, o, "sts06", "0961000004")           # non-final non-tuition
    l5 = await _mk_lead(db, deps, o, "sts14", "0961000005")  # tuition + self-sourced
    await _mk_paid_tuition(db, l5)
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


async def test_sts14_unpaid_stays_in_workload(db, seeded_dependencies):
    """🔒 YÊU CẦU NGHIỆP VỤ: "đã tính phí nhưng CHƯA xác nhận đóng" VẪN tính tải.

    Cùng trạng thái sts14, chỉ khác chứng cứ tiền — 5 ca:
      L1 fee học phí paid>0                → TRỪ (đã thu một phần)
      L2 fee học phí paid=0                → GIỮ (mới tính phí, chưa thu)
      L3 KHÔNG có hồ sơ/fee                → GIỮ
      L4 fee học phí paid>0 nhưng CANCELLED→ GIỮ (phiếu phí đã huỷ, tiền không tính)
      L5 fee LỆ PHÍ HỒ SƠ paid>0           → GIỮ (không phải học phí)
    ⇒ tuition_cnt == 1. Đây là hàng rào duy nhất chặn tái diễn hành vi cũ
    (trừ theo status trần, gộp cả lead chưa thu đồng nào)."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    o = await _mk_officer(db, deps["unit_id"], "unpaid")

    l1 = await _mk_lead(db, deps, o, "sts14", "0963000001")
    await _mk_paid_tuition(db, l1)
    l2 = await _mk_lead(db, deps, o, "sts14", "0963000002")
    await _mk_paid_tuition(db, l2, paid=Decimal("0"), status="calculated")
    await _mk_lead(db, deps, o, "sts14", "0963000003")  # không hồ sơ/fee
    l4 = await _mk_lead(db, deps, o, "sts14", "0963000004")
    await _mk_paid_tuition(db, l4, status="cancelled")
    l5 = await _mk_lead(db, deps, o, "sts14", "0963000005")
    await _mk_paid_tuition(db, l5, fee_type="application", status="paid")

    stmt = (
        select(
            func.count(models.Lead.id).label("workload"),
            func.count(models.Lead.id)
            .filter(_tuition_hold_filter())
            .label("tuition_cnt"),
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

    assert row.workload == 5
    assert row.tuition_cnt == 1  # CHỈ L1


async def test_is_officer_at_threshold_finance_discount(
    db, seeded_dependencies, monkeypatch
):
    """Referral fast-path (Option A yêu cầu #1): cờ ON trừ tải học phí khỏi ngưỡng.

    cap=10; 7 lead sts06 + 2 lead sts14 ĐÃ THU = workload 9, tuition 2.
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
        _l = await _mk_lead(db, deps, o, "sts14", f"09620002{i:02d}")
        await _mk_paid_tuition(db, _l)

    # Cờ OFF ⇒ ngưỡng theo TỔNG workload (y hệt hôm nay).
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", False)
    assert await is_officer_at_threshold(db, o) is True

    # Cờ ON ⇒ trừ tải học phí ⇒ dưới ngưỡng ⇒ referral vẫn gán thẳng được.
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    assert await is_officer_at_threshold(db, o) is False
