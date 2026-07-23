# tests/services/test_assignment_finance_discount.py
# -*- coding: utf-8 -*-
"""Real-DB test cho GIẢM TRỪ TẢI HỌC PHÍ (Option A, ENABLE_FINANCE_WORKLOAD_DISCOUNT).

Bọc sau cờ ``ENABLE_FINANCE_WORKLOAD_DISCOUNT`` (default OFF). Khi ON: lead ở
trạng thái học phí non-final (``TUITION_HOLD_STATUS_IDS`` = sts14/sts10) VÀ ĐÃ CÓ
TIỀN HỌC PHÍ HK1 CỦA LẦN ỨNG TUYỂN HIỆN TẠI (sts10 có chống lưng, hoặc sts14 có
fee tuition HK1 ``paid_amount > 0``) được giảm trừ khỏi:
  - cơ sở sắp xếp ``dist_load`` (eff_util) — GỘP với self-tuyển, chống trừ 2 lần
    qua phần giao S∩T,
  - cổng ``overloaded`` = ((workload − tuition)/capacity) >= SAFETY_THRESHOLD,
  - ``is_officer_at_threshold`` (referral fast-path).
Trần cứng ``workload < capacity`` VẪN theo TỔNG workload.

BA HÀNG RÀO nghiệp vụ, mỗi cái một test — gỡ cái nào cũng phải thấy đỏ:
  * ``test_sts14_unpaid_stays_in_workload`` — chưa thu đồng nào ⇒ VẪN là tải.
  * ``test_hk2_paid_hk1_unpaid_stays_in_workload`` — tiền HK2 không cứu nợ HK1.
  * ``test_prior_year_payment_does_not_discount_new_attempt`` — tiền mùa cũ không
    cứu hồ sơ mùa mới.
Cộng ``test_sts10_without_money_backing_stays_in_workload`` cho nhãn sts10 rỗng ruột.

Seed lead + consultation_status + fee THẬT rồi execute production path — cả mảnh
SQL (``_counts``) lẫn entrypoint thật (``compute_unit_officer_loads``,
``is_officer_at_threshold``). Chạy one-off container (CLAUDE.md) — seed DB thật.
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
    SAFETY_THRESHOLD,
    TUITION_DISCOUNT_RULE,
    TUITION_HOLD_STATUS_IDS,
    TUITION_SETTLED_STATUS_ID,
    _non_final_status_filter,
    _self_sourced_subquery,
    _tuition_hold_filter,
    compute_unit_officer_loads,
    is_officer_at_threshold,
    read_assignment_flags,
)

# asyncio_mode=auto (pytest.ini) ⇒ async test tự chạy, KHÔNG cần mark asyncio
# (mark asyncio ở module-level sẽ dính nhầm vào test đồng bộ documented → warning).
pytestmark = pytest.mark.integration

_FULL = Decimal("10000000")


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


async def _mk_profile(db, lead, *, academic_year=2026):
    """Hồ sơ tuyển sinh tối thiểu để treo fee lên.

    ``academic_year`` tham số hoá vì ``uq_admission_profile_lead_year`` cho phép
    1 lead nhiều hồ sơ — mỗi mùa một cái (xem test tiền-mùa-cũ).
    """
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        citizen_id=uuid.uuid4().hex[:12],
        status="approved",
        applied_rules={},
        academic_year=academic_year,
        version=1,
    )
    db.add(profile)
    await db.flush()
    return profile


def _status_for(final, paid, waived):
    """Trạng thái fee SUY RA TỪ TIỀN — đúng luật ``invoice_service._derive_fee_status``.

    Không để test tự đặt status lệch số tiền: một row ``status='paid'`` mà vẫn còn
    ``remaining > 0`` là trạng thái production không tạo ra được, và test ghim trên
    row như thế sẽ xanh vì lý do sai.
    """
    if final - paid - waived <= 0:
        return "paid"
    return "partial" if paid > 0 else "calculated"


async def _add_fee(
    db,
    profile,
    *,
    paid=Decimal("5000000"),
    waived=Decimal("0"),
    final=_FULL,
    fee_type="tuition",
    semester_no=1,
    status=None,
    academic_year=None,
):
    """1 khoản phí. ``paid > 0`` = bằng chứng kế toán ĐÃ XÁC NHẬN thu.

    ``paid=0`` ⇒ ca ĐÃ TÍNH PHÍ NHƯNG CHƯA THU (không được trừ tải).
    ``status`` mặc định suy ra từ tiền (``_status_for``); chỉ truyền tay cho ca cố
    ý lệch — hôm nay chỉ có ``'cancelled'``.
    ⚠️ CHECK ``chk_fee_nontuition_semester_no_null``: phí non-tuition phải để
    ``semester_no`` NULL.
    """
    db.add(
        models.Fee(
            admission_profile_id=profile.id,
            fee_type=fee_type,
            semester_no=semester_no if fee_type == "tuition" else None,
            academic_year=academic_year or profile.academic_year,
            base_amount=final,
            total_discount=Decimal("0"),
            final_amount=final,
            paid_amount=paid,
            waived_amount=waived,
            status=status or _status_for(final, paid, waived),
            calculated_at=datetime.now(timezone.utc),
            version=1,
        )
    )
    await db.flush()


async def _mk_profile_with_fee(db, lead, *, academic_year=2026, **fee_kw):
    """Hồ sơ + ĐÚNG MỘT khoản phí. Tên cố ý KHÔNG khẳng định trạng thái tiền —
    call site truyền ``paid=0`` / ``status='cancelled'`` / ``fee_type='application'``
    để dựng ca ngược."""
    profile = await _mk_profile(db, lead, academic_year=academic_year)
    await _add_fee(db, profile, **fee_kw)


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


async def _counts(db, officer, *extra_cols):
    """Chạy ĐÚNG các mảnh production (``_non_final_status_filter`` +
    ``_tuition_hold_filter``) trên DB thật, một chỗ duy nhất.

    Trước đây mỗi test tự chép lại câu SELECT này — sửa định nghĩa workload ở
    engine mà quên sửa bản chép thì test vẫn xanh trên hình dạng cũ, mất đúng giá
    trị "execute production path".
    """
    stmt = (
        select(
            func.count(models.Lead.id).label("workload"),
            func.count(models.Lead.id)
            .filter(_tuition_hold_filter())
            .label("tuition_cnt"),
            *extra_cols,
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
    )
    return (await db.execute(stmt)).one()


def test_tuition_hold_status_ids_documented():
    """Ghim danh sách trạng thái học phí non-final được giảm trừ + NEO vào nguồn
    taxonomy chính ``phase_manager.PHASE_STATUSES[FEE]`` để BẮT DRIFT: thêm/đổi
    trạng thái fee mà quên cập nhật đây → test gãy. Hardcode CÓ CHỦ ĐÍCH (KHÔNG
    derive theo stage_id='stg05') để sts18 (TUITION_REFUNDED, final) không lọt."""
    from app.services.phase_manager import LeadPhase, PHASE_STATUSES

    assert TUITION_HOLD_STATUS_IDS == ("sts14", "sts10")
    # sts10 = HK1 settled; miễn 100% có paid=0 nên nhánh này KHÔNG đối chiếu được
    # bằng tiền thu, chỉ loại ca nhãn rỗng ruột.
    assert TUITION_SETTLED_STATUS_ID == "sts10"
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
    await _mk_profile_with_fee(db, l1)
    await _mk_lead(db, deps, o, "sts10", "0961000002")        # settled (không cần fee)
    await _mk_lead(db, deps, o, "sts18", "0961000003")        # FINAL → excluded
    await _mk_lead(db, deps, o, "sts06", "0961000004")        # non-final non-tuition
    l5 = await _mk_lead(db, deps, o, "sts14", "0961000005")   # tuition + self-sourced
    await _mk_profile_with_fee(db, l5)
    await _self_log(db, l5, o)

    row = await _counts(
        db,
        o,
        func.count(models.Lead.id).filter(_self_sourced_subquery()).label("self_cnt"),
        func.count(models.Lead.id)
        .filter(and_(_self_sourced_subquery(), _tuition_hold_filter()))
        .label("both_cnt"),
    )

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

    Cùng trạng thái sts14, chỉ khác chứng cứ tiền — 6 ca:
      L1 HK1 paid > 0 (còn nợ)             → TRỪ (đã thu một phần)
      L2 HK1 paid = 0                      → GIỮ (mới tính phí, chưa thu)
      L3 KHÔNG có hồ sơ/fee                → GIỮ
      L4 HK1 đã HUỶ đúng luật (paid = 0)   → GIỮ
      L5 LỆ PHÍ HỒ SƠ đã thu               → GIỮ (không phải học phí)
      L6 HK1 paid = final (đóng ĐỦ)        → TRỪ
    ⇒ tuition_cnt == 2. Đây là hàng rào chính chặn tái diễn hành vi cũ (trừ theo
    status trần, gộp cả lead chưa thu đồng nào).

    ⚠️ L4 cố ý dùng ``paid=0``: ``cancel_fee`` raise khi ``paid_amount > 0``
    (fee_calculation_service ~:1137) nên "fee cancelled còn tiền" là trạng thái
    ứng dụng KHÔNG tạo ra được — ghim nó bằng row giả sẽ cho cảm giác an toàn sai.
    Mệnh đề ``status != 'cancelled'`` trong subquery vì thế là BELT (bất biến chỉ ở
    tầng app, không có CHECK DB, ops còn sửa tay bằng superuser) — giữ, nhưng
    không giả vờ rằng test này đang ghim nó."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    o = await _mk_officer(db, deps["unit_id"], "unpaid")

    l1 = await _mk_lead(db, deps, o, "sts14", "0963000001")
    await _mk_profile_with_fee(db, l1)
    l2 = await _mk_lead(db, deps, o, "sts14", "0963000002")
    await _mk_profile_with_fee(db, l2, paid=Decimal("0"))
    await _mk_lead(db, deps, o, "sts14", "0963000003")  # không hồ sơ/fee
    l4 = await _mk_lead(db, deps, o, "sts14", "0963000004")
    await _mk_profile_with_fee(db, l4, paid=Decimal("0"), status="cancelled")
    l5 = await _mk_lead(db, deps, o, "sts14", "0963000005")
    await _mk_profile_with_fee(db, l5, fee_type="application")
    l6 = await _mk_lead(db, deps, o, "sts14", "0963000006")
    await _mk_profile_with_fee(db, l6, paid=_FULL)  # đóng ĐỦ ⇒ status='paid'

    row = await _counts(db, o)

    assert row.workload == 6
    assert row.tuition_cnt == 2  # CHỈ L1 (một phần) + L6 (đủ)


async def test_hk2_paid_hk1_unpaid_stays_in_workload(db, seeded_dependencies):
    """🔒 Bằng chứng thu tiền phải BÓ ĐÚNG HK1 — vòng đời mà sts14/sts10 đại diện.

    Lead sts14 đã đóng HK2 nhưng HK1 VẪN CHƯA THU: officer còn phải đòi HK1 ⇒
    KHÔNG được trừ tải. Không có ``semester_no == 1`` thì EXISTS khớp mọi học kỳ
    và lead này bị trừ oan (prod hôm nay 0 fee HK2+, nhưng sẽ có khi mở HK2).

    Đối chứng L2: cùng cấu hình + HK1 ĐÃ thu ⇒ trừ. Thiếu đối chứng thì test vẫn
    xanh cả khi subquery hỏng hoàn toàn (không khớp gì)."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    o = await _mk_officer(db, deps["unit_id"], "hk2")

    l1 = await _mk_lead(db, deps, o, "sts14", "0964000001")
    p1 = await _mk_profile(db, l1)
    await _add_fee(db, p1, semester_no=1, paid=Decimal("0"))
    await _add_fee(db, p1, semester_no=2, paid=Decimal("7000000"))

    l2 = await _mk_lead(db, deps, o, "sts14", "0964000002")
    p2 = await _mk_profile(db, l2)
    await _add_fee(db, p2, semester_no=1, paid=Decimal("3000000"))
    await _add_fee(db, p2, semester_no=2, paid=Decimal("7000000"))

    row = await _counts(db, o)

    assert row.workload == 2
    assert row.tuition_cnt == 1  # CHỈ L2 (HK1 đã thu); L1 nợ HK1 vẫn là tải


async def test_prior_year_payment_does_not_discount_new_attempt(
    db, seeded_dependencies
):
    """🔒 Bằng chứng thu tiền phải BÓ ĐÚNG LẦN ỨNG TUYỂN HIỆN TẠI (năm học mới nhất).

    ``uq_admission_profile_lead_year`` cố ý cho 1 lead nhiều hồ sơ (mỗi mùa một
    cái) và lead ở terminal fee/enrolled được nộp lại mùa sau; tiền mùa cũ thì
    sống sót (rút hồ sơ ``admitted`` không hoàn không huỷ fee, bỏ học sang sts12,
    hoàn một phần, refund kẹt pending vì unit không có manager).

    L1: hồ sơ 2026 ĐÃ THU HK1 + hồ sơ 2027 CHƯA thu ⇒ officer đang đi đòi tiền
        2027 ⇒ KHÔNG được trừ.
    L2 (đối chứng): y hệt nhưng hồ sơ 2027 ĐÃ thu ⇒ trừ. Thiếu đối chứng thì test
        vẫn xanh cả khi subquery ngừng khớp mọi thứ."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    o = await _mk_officer(db, deps["unit_id"], "year")

    l1 = await _mk_lead(db, deps, o, "sts14", "0965000001")
    p1_old = await _mk_profile(db, l1, academic_year=2026)
    await _add_fee(db, p1_old, paid=_FULL)                    # mùa cũ: đóng đủ
    p1_new = await _mk_profile(db, l1, academic_year=2027)
    await _add_fee(db, p1_new, paid=Decimal("0"))             # mùa mới: chưa thu

    l2 = await _mk_lead(db, deps, o, "sts14", "0965000002")
    p2_old = await _mk_profile(db, l2, academic_year=2026)
    await _add_fee(db, p2_old, paid=_FULL)
    p2_new = await _mk_profile(db, l2, academic_year=2027)
    await _add_fee(db, p2_new, paid=Decimal("2000000"))       # mùa mới: đã thu 1 phần

    row = await _counts(db, o)

    assert row.workload == 2
    assert row.tuition_cnt == 1  # CHỈ L2; tiền 2026 KHÔNG cứu hồ sơ 2027 của L1


async def test_sts10_without_money_backing_stays_in_workload(db, seeded_dependencies):
    """🔒 Nhãn sts10 phải CÓ CHỐNG LƯNG — chặn nhãn chết sau khi tiền bị đảo.

    Void lô import đảo tiền NGOÀI savepoint rồi bước lùi nhãn lead thất bại trong
    ``try/except`` chỉ ``log.error`` (payment_import_service ~:1666/:1688) ⇒ lead
    đứng nguyên sts10 với HK1 ``paid=0, waived=0, còn nợ``. Không có beat nào đối
    soát lead-status ↔ fee, nên tin sts10 vô điều kiện = miễn trừ tải vĩnh viễn.

    L1 sts10 + HK1 (paid=0, waived=0, còn nợ)  → GIỮ (nhãn rỗng ruột)
    L2 sts10 + HK1 MIỄN 100% (waived=final)    → TRỪ (miễn hợp lệ, paid=0 là đúng)
    L3 sts10 + HK1 đã thu đủ                   → TRỪ
    L4 sts10 KHÔNG có fee HK1                  → TRỪ (giữ hành vi cũ, không suy diễn)"""
    deps = seeded_dependencies
    await _ensure_status(db, "sts10", False)
    o = await _mk_officer(db, deps["unit_id"], "unbacked")

    l1 = await _mk_lead(db, deps, o, "sts10", "0966000001")
    await _mk_profile_with_fee(db, l1, paid=Decimal("0"))
    l2 = await _mk_lead(db, deps, o, "sts10", "0966000002")
    await _mk_profile_with_fee(db, l2, paid=Decimal("0"), waived=_FULL)
    l3 = await _mk_lead(db, deps, o, "sts10", "0966000003")
    await _mk_profile_with_fee(db, l3, paid=_FULL)
    await _mk_lead(db, deps, o, "sts10", "0966000004")

    row = await _counts(db, o)

    assert row.workload == 4
    assert row.tuition_cnt == 3  # L2, L3, L4 — L1 (nhãn rỗng ruột) vẫn là tải


async def test_compute_unit_officer_loads_reflects_payment_evidence(
    db, seeded_dependencies, monkeypatch
):
    """Entrypoint THẬT (``compute_unit_officer_loads``) — ghim HỆ QUẢ, không chỉ SQL.

    Ba test trên chạy mảnh ``_tuition_hold_filter`` qua câu SELECT dựng tại chỗ;
    test này đi qua đúng hàm mà engine phân công VÀ dashboard "điểm bận" cùng gọi,
    trên câu lệnh production đầy đủ (GROUP BY + cột FILTER), để chốt hệ quả:

    cap=10, 9 lead sts14 mà CHỈ 2 đã thu ⇒ tuition_hold=2, dist_load=7,
    overloaded = (9−2)/10 = 0.7 < 0.8 → False.
    Hành vi CŨ (trừ theo status) cho tuition_hold=9, dist_load=0, overloaded=False
    — nên assert dist_load/tuition_hold là thứ bắt được drift."""
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    o = await _mk_officer(db, deps["unit_id"], "engine", cap=10)
    for i in range(2):
        _l = await _mk_lead(db, deps, o, "sts14", f"09670001{i:02d}")
        await _mk_profile_with_fee(db, _l)
    for i in range(7):
        _l = await _mk_lead(db, deps, o, "sts14", f"09670002{i:02d}")
        await _mk_profile_with_fee(db, _l, paid=Decimal("0"))

    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    res = await compute_unit_officer_loads(
        db,
        [o],
        include_at_capacity=True,
        lead_unit_id=deps["unit_id"],
        flags=read_assignment_flags(),
    )
    load = next(x for x in res.loads if x["officer"].id == o.id)

    assert load["workload"] == 9
    assert load["tuition_hold"] == 2
    assert load["dist_load"] == 7      # 9 − 2, KHÔNG phải 0 như hành vi cũ
    assert load["overloaded"] is ((9 - 2) / 10 >= SAFETY_THRESHOLD) is False


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
        await _mk_profile_with_fee(db, _l)

    # Cờ OFF ⇒ ngưỡng theo TỔNG workload (y hệt hôm nay).
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", False)
    assert await is_officer_at_threshold(db, o) is True

    # Cờ ON ⇒ trừ tải học phí ⇒ dưới ngưỡng ⇒ referral vẫn gán thẳng được.
    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    assert await is_officer_at_threshold(db, o) is False


async def test_is_officer_at_threshold_unpaid_sts14_not_discounted(
    db, seeded_dependencies, monkeypatch
):
    """🔒 Nhánh referral phải dùng CÙNG bằng chứng tiền với balancer.

    ``is_officer_at_threshold`` là guard DUY NHẤT chặn bơm referral cho managing
    officer, và nó dựng cột ``tuition_cnt`` RIÊNG (assignment_service ~:269) chứ
    không đi qua ``compute_unit_officer_loads`` — nên nếu ai đó inline lại
    ``id.in_(TUITION_HOLD_STATUS_IDS)`` ở đó "cho nhanh", mọi test filter vẫn xanh.

    Số liệu đặt ĐÚNG ranh giới 0.8 để hai công thức cho hai kết quả khác nhau:
    cap=10; 7×sts06 + 2×sts14 mà CHỈ 1 đã thu ⇒ workload 9, tuition 1.
      - đúng (trừ theo tiền):   (9−1)/10 = 0.80 ≥ 0.8 → True
      - sai  (trừ theo status): (9−2)/10 = 0.70 < 0.8 → False ⇒ test ĐỎ
    """
    deps = seeded_dependencies
    await _ensure_status(db, "sts14", False)
    await _ensure_status(db, "sts06", False)
    o = await _mk_officer(db, deps["unit_id"], "thrunpaid", cap=10)
    for i in range(7):
        await _mk_lead(db, deps, o, "sts06", f"09680001{i:02d}")
    l_paid = await _mk_lead(db, deps, o, "sts14", "0968000201")
    await _mk_profile_with_fee(db, l_paid)
    l_unpaid = await _mk_lead(db, deps, o, "sts14", "0968000202")
    await _mk_profile_with_fee(db, l_unpaid, paid=Decimal("0"))

    monkeypatch.setattr(settings, "ENABLE_FINANCE_WORKLOAD_DISCOUNT", True)
    assert await is_officer_at_threshold(db, o) is True


def test_discount_rule_marker_documented():
    """Marker phiên bản ghi kèm ``tuition_hold`` vào assignment_decision_log.

    Cùng một khoá JSON từng mang hai nghĩa (trước/sau 22-07). Đổi quy tắc giảm trừ
    mà quên đổi marker ⇒ chuỗi thời gian audit lẫn hai nghĩa, không cách nào tách."""
    assert TUITION_DISCOUNT_RULE == "paid-hk1-current-year"
