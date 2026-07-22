# app/services/assignment_service.py
"""
Lead Assignment Service - Automatic lead distribution logic.

✅ REFACTORED: Now uses notification_dispatcher for all notifications.
This ensures notifications are persisted to database AND sent via Socket.IO/Email.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import OperationalError  # Dùng để bắt LockNotAvailableError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.constants import UserRole
from ..core.events import SystemEvents
from ..core.status_mapping import is_lead_consultation_terminal
from ..core.task_constants import AssignmentResult, AssignmentFailureReason
from ..utils.exceptions import LockContentionError
from .assignment_reason import SELF_SOURCED_REASON_TOKEN
from .notification_dispatcher import dispatch
from .notification_payloads import EventPayload
from .status_helper import StatusHelper, AssignmentStatus

# Lấy logger chuẩn ở đây, dùng làm fallback
default_log = logging.getLogger(__name__)

# Ngưỡng tải an toàn (utilization). Officer có utilization >= ngưỡng này bị
# xếp sau trong round-robin (BƯỚC 5) và bị nhánh referral né (Phần C). Tách ra
# module-level để assignment_service + lead_service dùng chung một con số.
SAFETY_THRESHOLD = 0.8


def _non_final_status_filter():
    """
    SQL condition: a lead's consultation_status is non-final (is_final False or
    NULL). Single source of truth for "counts as active workload", shared by
    is_officer_at_threshold and automatically_assign_lead BƯỚC 3 so the referral
    fast-path and the balancer can never drift on what "load" means.
    """
    return (
        (models.ConsultationStatus.is_final == False) |  # noqa: E712
        (models.ConsultationStatus.is_final.is_(None))
    )


# Non-final tuition fee statuses (stg05 "Xử lý học phí" — tuition-hold). Khách
# đã chuyển đổi, đang chờ đóng đủ / xác nhận nhập học ⇒ KHÔNG còn là tải tư vấn.
# Được GIẢM TRỪ khỏi cơ sở sắp xếp + cổng quá tải + referral fast-path khi
# ``ENABLE_FINANCE_WORKLOAD_DISCOUNT`` ON. Excludes sts18 (TUITION_REFUNDED,
# is_final) — trạng thái final KHÔNG BAO GIỜ tính tải nên không cần liệt kê.
# ⚠️ Hardcode có chủ đích (KHÔNG derive theo stage_id='stg05') để sts18 không
# lọt vào; ghim bởi test_tuition_hold_status_ids_documented.
TUITION_HOLD_STATUS_IDS = ("sts14", "sts10")

# sts10 "Đã hoàn tất học phí" = HK1 settled (đóng đủ HOẶC miễn 100% —
# ``fee_calculation_service.is_hk1_settled``) ⇒ tự nó ĐÃ là bằng chứng thu tiền,
# không cần soi bảng fee.
TUITION_SETTLED_STATUS_ID = "sts10"


def _tuition_payment_confirmed_subquery():
    """Correlated EXISTS — lead có ÍT NHẤT MỘT khoản HỌC PHÍ đã ghi nhận tiền
    thực thu (``fee.paid_amount > 0``).

    ``fee.paid_amount`` chỉ tăng ở money-math chạy SAU khi payment chuyển
    ``verified`` (payment_service ~:433) ⇒ > 0 nghĩa là kế toán ĐÃ XÁC NHẬN đóng,
    một phần hay đủ đều tính. Cố ý KHÔNG xét ``waived_amount``: miễn giảm không
    phải "đã đóng" (ca miễn TOÀN PHẦN đi đường sts10 ở trên nên không lọt lưới).
    Cố ý bó ``fee_type='tuition'``: lệ phí hồ sơ / BHYT đã thu KHÔNG làm lead
    thoát tải tư vấn. ``status <> 'cancelled'`` loại phiếu phí đã huỷ.

    ⚠️ INDEX: dựa ``ix_admission_profile_lead_id`` + ``ix_fee_admission_profile_id``.
    """
    return (
        select(1)
        .select_from(models.Fee)
        .join(
            models.AdmissionProfile,
            models.Fee.admission_profile_id == models.AdmissionProfile.id,
        )
        .where(
            models.AdmissionProfile.lead_id == models.Lead.id,
            models.Fee.fee_type == "tuition",
            models.Fee.status != "cancelled",
            models.Fee.paid_amount > 0,
        )
        .correlate(models.Lead)
        .exists()
    )


def _tuition_hold_filter():
    """SQL condition: lead ĐÃ CÓ TIỀN HỌC PHÍ VÀO (một phần hoặc đủ).

    = ``TUITION_HOLD_STATUS_IDS`` VÀ (sts10 HOẶC có fee học phí ``paid_amount>0``).

    ⚠️ sts14 "Chưa hoàn tất học phí" gộp HAI ca khác hẳn nhau về tải:
      * đã đóng MỘT PHẦN (còn nợ) → khách đã chốt, không còn là tải tư vấn ⇒ TRỪ.
      * mới TÍNH PHÍ, chưa thu đồng nào → officer vẫn phải theo đuổi ⇒ KHÔNG trừ.
    Status một mình không phân biệt được, nên phải soi bảng ``fee``.

    Dùng làm FILTER aggregate trong workload_stmt (và referral fast-path) để đếm
    riêng phần tải học phí — chỉ khi ``ENABLE_FINANCE_WORKLOAD_DISCOUNT`` ON.
    """
    return and_(
        models.ConsultationStatus.id.in_(TUITION_HOLD_STATUS_IDS),
        or_(
            models.ConsultationStatus.id == TUITION_SETTLED_STATUS_ID,
            _tuition_payment_confirmed_subquery(),
        ),
    )


# _ASSIGNMENT_SOURCE_METHODS = method của SỰ KIỆN (RE-)PHÂN CÔNG (cách officer CÓ
# lead). _self_sourced_subquery chỉ xét bản ghi có method này cho "latest", BỎ QUA
# status-action / keep-sync giữ nguyên officer (chúng KHÔNG đổi "nguồn sở hữu").
#
# ⚠️ AUDIT 7 write-site models.AssignmentLog(method=...) (11-07):
#  SOURCE (whitelist): 'automatic' · 'manual' · 'manual_reassignment' · (defensive)
#    'system_auto_reassign'.
#  NON-SOURCE (loại đúng — KHÔNG reset phân loại):
#   - 'offering_change_unit_synced' (keep-sync đổi ngành, GIỮ officer + non-final):
#     case LUÔN load-bearing.
#   - 'officer_reject' (process_officer_action reject, GIỮ officer): thành non-final
#     qua get_rejected_status()→None→fallback consultation_status_id=None (prod: 0
#     status legacy='rejected'+is_final=true → luôn None), hoặc FINAL nếu env có
#     status đó (khi đó lead rớt khỏi workload, việc loại thành no-op). Prod scope
#     officer_reject-as-latest hiện = 0 lead.
#  DEAD-nhưng-defensive: 'officer_reassign' + 'system_auto_reassign' đều NULL/đổi
#    assigned_officer_id nên KHÔNG BAO GIỜ correlate (al.officer_id==assigned) — vô
#    hại, giữ để rõ ý "source".
# ⚠️ THÊM method mới (re-)assign lead cho officer + giữ non-final ⇒ PHẢI thêm vào
#    đây; quên → lead phân phối bị coi self-sourced → OVER-GRANT (UNSAFE). Ghim bởi
#    test_assignment_source_methods_documented.
_ASSIGNMENT_SOURCE_METHODS = (
    "automatic",
    "manual",
    "manual_reassignment",
    "system_auto_reassign",
)


def _self_sourced_subquery():
    """Correlated boolean scalar subquery — True nếu lead do CHÍNH officer đang
    được gán TỰ TUYỂN (tự tạo + tự nhận), theo bản ghi (RE-)PHÂN CÔNG MỚI NHẤT của
    cặp (lead, officer hiện tại) — CHỈ xét ``_ASSIGNMENT_SOURCE_METHODS``, bỏ qua
    hành động status (officer_reject) / keep-sync.

    Tự tuyển = latest (assignment-source) method='manual' VÀ ``reason`` do một
    OFFICER khởi tạo. Mọi thứ khác — 'automatic', reassign, manual do admin/manager
    chỉ định (phân phối), hay không có log — đều KHÔNG phải tự tuyển ⇒ tính vào tải
    đã-chia. ⚠️ offering_change_unit_synced (keep-sync, LUÔN giữ officer + non-final)
    và officer_reject KHÔNG reset phân loại (nếu xét MỌI log, self-sourced lead sau
    các action đó hoá đã-chia OAN → giảm suất officer, ngược ý đồ) — xem
    ``_ASSIGNMENT_SOURCE_METHODS``. Dùng khi ``exclude_active`` để loại lead tự tuyển
    khỏi CƠ SỞ SẮP XẾP (real_util/eff_util), KHÔNG khỏi tổng workload.

    ⚠️ NGỮ NGHĨA (latent): pattern chỉ kiểm VAI TRÒ người-gán = officer, KHÔNG kiểm
    assigner == assigned_officer_id. Hôm nay AN TOÀN vì officer-create ép
    direct_assignment = created_by (lead_service.py:~837) và ``/assign`` chỉ
    manager/admin (Casbin OFFICER_TEMPLATE không cấp). NẾU RBAC sau cho officer gán
    cho ĐỒNG NGHIỆP → lead đã-chia của B bị tính B tự tuyển → over-grant (UNSAFE,
    ngược ý đồ). Khi đó ghi ý định ở write-time (method='self_claim' / actor_id)
    thay vì match chuỗi reason.

    Fail-safe: NULL (không log) hoặc reason không khớp ⇒ KHÔNG phải tự tuyển (an
    toàn: không cấp thêm suất).

    ⚠️ COUPLING: khớp ``reason`` sinh ở lead_service.py (create+direct-assign
    ~1179 + assign_lead_to_officer ~2350); ghim bởi test_assignment_self_sourced.py.
    ⚠️ INDEX: ORDER BY ... LIMIT 1 dựa ``ix_assignment_log_lead_officer_ts``
    (lead_id, officer_id, timestamp DESC) — thiếu → seq-scan mỗi lead-row. Audit
    prod unit 14 (2026-07-10): 467/537 manual = 'by officer', 70 = admin gán.
    """
    al = models.AssignmentLog
    return (
        select(
            (al.method == "manual")
            # token single-source từ assignment_reason (= "by officer ") — khớp
            # reason build_assignment_reason() sinh khi actor là OFFICER.
            & al.reason.ilike(f"%{SELF_SOURCED_REASON_TOKEN}%")
        )
        .where(
            al.lead_id == models.Lead.id,
            al.officer_id == models.Lead.assigned_officer_id,
            # CHỈ xét sự kiện (re-)phân công — bỏ qua status-action (officer_reject)
            # + keep-sync (offering_change_unit_synced) để chúng KHÔNG reset phân
            # loại tự-tuyển của lead.
            al.method.in_(_ASSIGNMENT_SOURCE_METHODS),
        )
        # tie-breaker id DESC: timestamp=datetime.now() có thể trùng microsecond
        # trên 2 log cùng (lead, officer) ⇒ LIMIT 1 non-deterministic; id DESC làm
        # sort toàn phần.
        .order_by(al.timestamp.desc(), al.id.desc())
        .limit(1)
        .correlate(models.Lead)
        .scalar_subquery()
    )


def _safe_positive_int(value: int | None, default: int) -> int:
    """Coerce to a usable positive int: None → ``default``, any value <= 0 → 1.
    Single backbone for _safe_capacity / _safe_weight."""
    if value is None:
        return default
    return value if value > 0 else 1


def _safe_capacity(officer: models.User) -> int:
    """Officer capacity with a safe fallback (default 100, never <= 0).
    Shared by the referral threshold check and the assignment loop (BƯỚC 4)."""
    return _safe_positive_int(officer.max_capacity, 100)


def _safe_weight(officer: models.User) -> int:
    """Officer member-assignment weight with a safe fallback (default 1, never <= 0).

    A higher weight lowers ``eff_util = workload / (capacity * weight)`` so the
    officer is treated as emptier and receives more leads. Weight 1 makes
    ``eff_util == real_util`` — but note that with ENABLE_MEMBER_WEIGHTED_ASSIGNMENT
    ON this is NOT identical to legacy round-robin: member mode orders by eff_util
    (workload-proportional), whereas legacy ignores workload magnitude in its
    tie-break. Direct attribute access (not getattr) so an attribute-name typo
    surfaces instead of silently returning 1. The None fallback only matters for an
    unflushed/mock ``User`` in tests (the prod column is NOT NULL + server_default
    '1' + CHECK 1..100)."""
    return _safe_positive_int(officer.assignment_weight, 1)


async def is_officer_at_threshold(
    db: AsyncSession,
    officer: models.User,
    threshold: float = SAFETY_THRESHOLD,
) -> bool:
    """
    Trả True nếu tải hiện tại của officer đã đạt/vượt ngưỡng an toàn
    (workload / capacity >= threshold).

    Workload được định nghĩa GIỐNG HỆT automatically_assign_lead BƯỚC 3-4: đếm
    số lead (chưa xóa, deleted_at IS NULL) được gán cho officer mà
    consultation_status.is_final là False hoặc NULL (một lead ở sts04 "Từ chối
    tư vấn" is_final=false vẫn tính tải). Dùng bởi nhánh referral (lead_service)
    để KHÔNG gán thẳng referral lead cho managing officer đã đầy tải — thay vào
    đó fallback sang auto-assign cân bằng. Giữ cùng định nghĩa workload với thuật
    toán né officer, nên kết luận ở đây khớp với việc officer có bị auto-assign né.
    """
    from ..config import settings

    finance_on = settings.ENABLE_FINANCE_WORKLOAD_DISCOUNT
    _cols = [func.count(models.Lead.id).label("workload")]
    if finance_on:
        # Đếm riêng tải HỌC PHÍ để GIẢM TRỪ khỏi ngưỡng referral (Option A) —
        # cùng discount với auto-assign, tránh referral fast-path né officer mà
        # balancer đã coi là KHÔNG quá tải (chỉ thêm cột khi cờ ON ⇒ OFF y hệt).
        _cols.append(
            func.count(models.Lead.id)
            .filter(_tuition_hold_filter())
            .label("tuition_cnt")
        )
    workload_stmt = (
        select(*_cols)
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,  # LEFT JOIN để bao gồm cả lead chưa có status
        )
        .where(
            models.Lead.assigned_officer_id == officer.id,
            models.Lead.deleted_at.is_(None),  # lead đã xóa không tính tải
            _non_final_status_filter(),
        )
    )
    # COUNT không GROUP BY ⇒ luôn đúng 1 dòng (kể cả khi 0) → .one() an toàn,
    # giữ nguyên kết quả với path .scalar_one() cũ khi cờ OFF.
    row = (await db.execute(workload_stmt)).one()
    workload = row.workload or 0
    tuition_cnt = (row.tuition_cnt or 0) if finance_on else 0
    cap = _safe_capacity(officer)

    # ⚠️ TRẦN CỨNG cho referral fast-path: đường referral (lead_service, gán
    # THẲNG cho managing officer) CHỈ có guard duy nhất là hàm này — KHÔNG có gate
    # `workload < capacity` riêng như auto-assign BƯỚC 4. Nếu chỉ trả theo tải
    # HIỆU DỤNG (đã trừ học phí), officer đầy toàn lead học phí (raw workload ≥
    # cap) sẽ "thoát ngưỡng" → bị bơm thêm referral → VƯỢT capacity, phá bất biến
    # config "không ôm quá capacity". Vì thế: khi cờ ON, raw workload ≥ cap LUÔN
    # coi là quá tải (chặn referral), discount chỉ áp KHI CÒN dưới trần.
    # finance_on=False ⇒ nhánh này no-op (raw ≥ cap ⇒ raw/cap ≥ 1 ≥ threshold vẫn
    # True) → OFF y hệt hôm nay.
    if finance_on and workload >= cap:
        return True

    # Option A: ngưỡng referral theo TẢI HIỆU DỤNG (trừ học phí) khi cờ ON.
    # tuition_cnt ⊆ workload ⇒ (workload - tuition_cnt) ≥ 0.
    return ((workload - tuition_cnt) / cap) >= threshold


async def _log_assignment_decision(
    db: AsyncSession,
    lead_id: int,
    assigned_officer_id: int | None,
    eligible_officer_ids: list[int],
    unit_id: int | None,
    channel: str,
    reason: str,
    scores_snapshot: dict | None = None,
    capacity_snapshot: dict | None = None,
    log: logging.Logger = default_log,
) -> None:
    """
    Phase A8: Log assignment decision for fairness analysis (v2.1 prep).
    Fail-safe — exceptions are caught and warned, never fail the assign flow.
    """
    try:
        entry = models.AssignmentDecisionLog(
            lead_id=lead_id,
            assigned_officer_id=assigned_officer_id,
            eligible_officer_ids=eligible_officer_ids,
            channel=channel,
            unit_id=unit_id,
            scores_snapshot=scores_snapshot,
            capacity_snapshot=capacity_snapshot,
            reason=reason,
        )
        db.add(entry)
    except Exception as e:
        log.warning(f"[Lead ID: {lead_id}] Failed to log assignment decision: {e}")


# Thêm tham số logger=None
class AssignmentFlags(NamedTuple):
    """Anh chup 4 co dieu khien cach cham diem phan phoi (doc 1 lan/quyet dinh)."""

    member_on: bool
    fairness_on: bool
    exclude_active: bool
    finance_on: bool


def read_assignment_flags() -> AssignmentFlags:
    """Doc co tu settings - BYTE-IDENTICAL voi logic goc o BUOC 3.

    ``exclude_active`` bi GATE KEP: co loai-self chi co tac dung o che do
    member/fairness (legacy sap xep thuan last_assigned => dist_load vo nghia).
    ``finance_on`` DOC LAP (overloaded/threshold ap moi che do).
    """
    from ..config import settings

    member_on = settings.ENABLE_MEMBER_WEIGHTED_ASSIGNMENT
    fairness_on = settings.ENABLE_FAIRNESS_WEIGHTED_ASSIGNMENT
    exclude_active = (
        settings.ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED
        and (member_on or fairness_on)
    )
    finance_on = settings.ENABLE_FINANCE_WORKLOAD_DISCOUNT
    return AssignmentFlags(member_on, fairness_on, exclude_active, finance_on)


@dataclass
class UnitOfficerLoads:
    """Ket qua cham diem tai cua MOT don vi.

    ``loads``: TAT CA officer duoc truyen vao (ke ca day tai / khong eligible),
    da sap xep: nhom eligible (sort theo engine) truoc, phan con lai noi sau.
    Caller loc ``eligible_for_assignment`` de lay pool chon nguoi.
    """

    loads: list
    scoring: str | None
    assign_reason: str | None
    flags: AssignmentFlags


async def compute_unit_officer_loads(
    db: AsyncSession,
    officers,
    *,
    include_at_capacity: bool = True,
    eligible_officer_ids=None,
    lead_unit_id: int = None,
    flags: AssignmentFlags = None,
    log: logging.Logger = None,
) -> UnitOfficerLoads:
    """Tinh tai + cham diem + sap xep officer cua mot don vi (HAM THUAN).

    NGUON SU THAT DUY NHAT cho bo so phan phoi. ``automatically_assign_lead``
    va dashboard "diem ban" deu goi ham nay => KHONG THE lech nhau. Moi thay doi
    cong thuc phai sua o day.

    Args:
        officers: pool HIEN THI - moi officer can tinh metric.
        include_at_capacity: False => loai han officer day tai khoi ``loads``.
        eligible_officer_ids: pool CHAM DIEM. ``None`` => moi officer truyen vao
            deu eligible (duong engine: BUOC 2 da loc availability + blacklist).
            Dashboard truyen tap officer ``availability_status == 'available'``
            de officer offline/busy van co metric hien thi nhung KHONG tham gia
            cham diem/sap xep => diem cua nguoi eligible y het engine.
            Ham nay KHONG tu doc ``availability_status`` - loc la viec cua caller.
    """
    _log = log or default_log
    flags = flags or read_assignment_flags()
    member_on, fairness_on = flags.member_on, flags.fairness_on
    exclude_active, finance_on = flags.exclude_active, flags.finance_on

    officer_ids = [o.id for o in officers]
    eligible_set = (
        set(eligible_officer_ids)
        if eligible_officer_ids is not None
        else set(officer_ids)
    )

    # --- Dem tai (+ tu tuyen / hoc phi theo co) - 1 round-trip ---
    _wl_cols = [
        models.Lead.assigned_officer_id,
        func.count(models.Lead.id).label("workload"),
    ]
    if exclude_active:
        _wl_cols.append(
            func.count(models.Lead.id)
            .filter(_self_sourced_subquery())
            .label("self_cnt")
        )
    if finance_on:
        _wl_cols.append(
            func.count(models.Lead.id)
            .filter(_tuition_hold_filter())
            .label("tuition_cnt")
        )
    if exclude_active and finance_on:
        _wl_cols.append(
            func.count(models.Lead.id)
            .filter(
                and_(
                    _self_sourced_subquery(),
                    _tuition_hold_filter(),
                )
            )
            .label("self_and_tuition_cnt")
        )
    workload_stmt = (
        select(*_wl_cols)
        .join(
            models.ConsultationStatus,
            models.Lead.consultation_status_id == models.ConsultationStatus.id,
            isouter=True,
        )
        .where(
            models.Lead.assigned_officer_id.in_(officer_ids),
            models.Lead.deleted_at.is_(None),
            _non_final_status_filter(),
        )
        .group_by(models.Lead.assigned_officer_id)
    )
    workload_map: dict = {}
    self_map: dict = {}
    tuition_map: dict = {}
    self_and_tuition_map: dict = {}
    for row in await db.execute(workload_stmt):
        workload_map[row.assigned_officer_id] = row.workload
        if exclude_active:
            self_map[row.assigned_officer_id] = row.self_cnt
        if finance_on:
            tuition_map[row.assigned_officer_id] = row.tuition_cnt
        if exclude_active and finance_on:
            self_and_tuition_map[row.assigned_officer_id] = (
                row.self_and_tuition_cnt
            )
    _dbg_load = (
        f"[Unit: {lead_unit_id}] Workloads={workload_map} "
        f"self-sourced={self_map}"
    )
    if finance_on:
        _dbg_load += f" tuition-hold={tuition_map}"
    _log.debug(_dbg_load)

    # --- Dung metric per-officer (pool-independent) ---
    loads = []
    for officer in officers:
        workload = workload_map.get(officer.id, 0)
        capacity = _safe_capacity(officer)
        at_capacity = workload >= capacity
        if at_capacity and not include_at_capacity:
            _log.debug(
                f"Officer {officer.id} skipped (at full capacity: "
                f"{workload}/{capacity})"
            )
            continue
        weight = _safe_weight(officer)
        self_cnt = self_map.get(officer.id, 0) if exclude_active else 0
        tuition_cnt = tuition_map.get(officer.id, 0) if finance_on else 0
        overlap = (
            self_and_tuition_map.get(officer.id, 0)
            if (exclude_active and finance_on)
            else 0
        )
        balance_load = workload - self_cnt - tuition_cnt + overlap
        real_util = balance_load / capacity
        eff_util = balance_load / (capacity * weight)
        loads.append(
            {
                "officer": officer,
                "workload": workload,
                "dist_load": balance_load,
                "real_util": real_util,
                "eff_util": eff_util,
                "weight": weight,
                "overloaded": ((workload - tuition_cnt) / capacity)
                >= SAFETY_THRESHOLD,
                "tuition_hold": tuition_cnt,
                # Surface cho dashboard (da tinh san, khong ton query them).
                # capacity = _safe_capacity(officer) -> dashboard doc thang, khong
                # goi lai helper => khong the lech mau so voi engine.
                "capacity": capacity,
                "self_cnt": self_cnt,
                # BAT BUOC surface: deducted = self + tuition - overlap. Neu chi
                # tra self/tuition, moi UI hien thi chung se ngam hieu la phep
                # CONG va sai bang dung phan giao (lead vua tu tim vua da dong tien).
                "overlap": overlap,
                "at_capacity": at_capacity,
                "eligible_for_assignment": (
                    officer.id in eligible_set and not at_capacity
                ),
                "score": real_util,
                "last_assigned": officer.last_assigned_at
                or datetime.min.replace(tzinfo=timezone.utc),
            }
        )

    scoring_pool = [ol for ol in loads if ol["eligible_for_assignment"]]
    others = [ol for ol in loads if not ol["eligible_for_assignment"]]
    # ``others`` KHONG BAO GIO di qua khau cham diem, nen phai co thu tu on dinh
    # RIENG. Neu de nguyen thu tu DB, caller (dashboard) enumerate ra `rank` se
    # xuat ban mot thu tu tuy y duoi dang bang xep hang.
    others.sort(key=lambda x: (x["at_capacity"], x["eff_util"], x["officer"].id))
    if not scoring_pool:
        # Khong ai du dieu kien => BO QUA han khau cham diem (giu dung hanh vi
        # cu: engine return som o nhanh at_capacity, KHONG query lich su).
        # Van tra ve theo thu tu on dinh (khong phai thu tu DB).
        return UnitOfficerLoads(
            loads=others, scoring=None, assign_reason=None, flags=flags
        )

    # --- Lich su phan cong (chi khi fairness bat) ---
    hist_counts: dict = {}
    if fairness_on:
        try:
            from sqlalchemy import select as sel, func as fn
            hist_q = await db.execute(
                sel(
                    models.AssignmentDecisionLog.assigned_officer_id,
                    fn.count(models.AssignmentDecisionLog.id).label("cnt"),
                )
                .where(
                    models.AssignmentDecisionLog.unit_id == lead_unit_id,
                    models.AssignmentDecisionLog.assigned_officer_id.isnot(None),
                )
                .group_by(models.AssignmentDecisionLog.assigned_officer_id)
            )
            hist_counts = {r.assigned_officer_id: r.cnt for r in hist_q.all()}
        except Exception as e:
            _log.warning(
                f"[Unit: {lead_unit_id}] Fairness history query failed, "
                f"falling back: {e}"
            )

    # --- Quyet dinh CHE DO cham diem (pool = scoring_pool) ---
    if member_on and fairness_on:
        eligible_hist_total = sum(
            hist_counts.get(e["officer"].id, 0) for e in scoring_pool
        )
        scoring = "member_fairness" if eligible_hist_total >= 10 else "member"
    elif fairness_on:
        total_hist = sum(hist_counts.values())
        scoring = "fairness" if total_hist >= 10 else "legacy"
    elif member_on:
        scoring = "member"
    else:
        scoring = "legacy"

    if scoring == "member_fairness":
        total_weight = sum(e["weight"] for e in scoring_pool)
        for e in scoring_pool:
            target_share = e["weight"] / total_weight
            actual_share = (
                hist_counts.get(e["officer"].id, 0) / eligible_hist_total
            )
            e["score"] = 0.6 * e["eff_util"] + 0.4 * (actual_share - target_share)
        assign_reason = "member_fairness_weighted"
        _log.info(
            f"[Unit: {lead_unit_id}] Member+fairness weighted "
            f"(pool_hist={eligible_hist_total})"
        )
    elif scoring == "fairness":
        for e in scoring_pool:
            share = hist_counts.get(e["officer"].id, 0) / total_hist
            e["score"] = 0.6 * e["real_util"] + 0.4 * share
        assign_reason = "fairness_weighted"
        _log.info(
            f"[Unit: {lead_unit_id}] Using fairness-weighted scoring "
            f"(history={total_hist})"
        )
    elif scoring == "member":
        for e in scoring_pool:
            e["score"] = e["eff_util"]
        assign_reason = "member_weighted"
        _log.info(f"[Unit: {lead_unit_id}] Using member-weighted scoring")
    else:
        assign_reason = "lowest_workload"
        _log.info(f"[Unit: {lead_unit_id}] Using legacy round-robin")

    if scoring == "legacy":
        scoring_pool.sort(key=lambda x: (x["overloaded"], x["last_assigned"]))
    else:
        scoring_pool.sort(
            key=lambda x: (x["overloaded"], x["score"], x["last_assigned"])
        )

    return UnitOfficerLoads(
        loads=scoring_pool + others,
        scoring=scoring,
        assign_reason=assign_reason,
        flags=flags,
    )


async def automatically_assign_lead(
    lead_id: int, db: AsyncSession, logger: logging.Logger = None
) -> tuple[dict, list]:
    """
    Logic nghiệp vụ chính để tự động phân công Lead.
    Sử dụng logger được truyền vào hoặc logger mặc định.
    Sử dụng 'SKIP LOCKED' để xử lý concurrency khi khóa officers.
    Xử lý lock contention trên Lead bằng Celery Retry.

    Returns:
        tuple[dict, list]: (result_dict, post_commit_callbacks)
            result_dict has "status" key:
            - "assigned": Lead successfully assigned to officer
            - "failed": No officers available or all at capacity
            - "skipped": Lead already assigned or not found
            post_commit_callbacks: list of async callables to run after commit
    """
    log = logger or default_log
    log.info(f"[Lead ID: {lead_id}] Auto-assign task started")
    _post_commit_callbacks = []

    try:
        # Sử dụng transaction lồng nhau để kiểm soát rollback tốt hơn
        async with db.begin_nested():
            # === BƯỚC 1: Lấy VÀ KHÓA Lead (Giữ nguyên nowait=True hoặc đổi sang skip_locked=True) ===
            # Việc khóa lead ít khi xung đột hơn, nhưng nowait giúp phát hiện sớm
            # nếu có transaction khác đang xử lý chính lead này.
            stmt = (
                select(models.Lead)
                .where(models.Lead.id == lead_id)
                .with_for_update(nowait=True)
            )
            result = await db.execute(stmt)
            lead = result.scalar_one_or_none()

            # --- Kiểm tra trạng thái Lead ---
            if not lead:
                log.warning(
                    f"[Lead ID: {lead_id}] Lead not found, skipping assignment."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.LEAD_NOT_FOUND, "lead_id": lead_id}, _post_commit_callbacks
            
            # ✅ FIX: Check if lead is deleted (soft delete)
            elif lead.deleted_at is not None:
                log.warning(
                    f"[Lead ID: {lead_id}] Lead is soft-deleted, skipping assignment."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.LEAD_DELETED, "lead_id": lead_id}, _post_commit_callbacks
            
            elif lead.assigned_officer_id:
                log.info(
                    f"[Lead ID: {lead_id}] Lead already assigned to officer {lead.assigned_officer_id}, skipping."
                )
                return {"status": AssignmentResult.SKIPPED, "reason": AssignmentFailureReason.ALREADY_ASSIGNED, "lead_id": lead_id, "officer_id": lead.assigned_officer_id}, _post_commit_callbacks
            else:
                # ✅ R1: auto-assign KHÔNG BAO GIỜ vớ lead consultation-terminal
                # (đã đóng, vd sts20) — phải reopen trước. Chạy per-lead-id nên
                # terminal = no-op có log (KHÔNG raise). sts20 vốn đã bị
                # _non_final_status_filter loại khỏi khâu QUÉT workload, nhưng
                # auto-assign per-id vẫn tới đây nếu bị enqueue → chặn tại đây.
                if await is_lead_consultation_terminal(db, lead):
                    log.info(
                        f"[Lead ID: {lead_id}] Lead consultation-terminal (đã "
                        f"đóng), skip auto-assign."
                    )
                    return {
                        "status": AssignmentResult.SKIPPED,
                        "reason": AssignmentFailureReason.LEAD_TERMINAL,
                        "lead_id": lead_id,
                    }, _post_commit_callbacks

                lead_unit_id = lead.unit_id
                # Get blacklisted officers for this lead
                blacklisted_officer_ids = lead.rejected_by_officer_ids or []
                log.debug(
                    f"[Lead ID: {lead_id}] Lead found and locked (Unit: {lead_unit_id}). Status: '{lead.status}', Blacklist: {blacklisted_officer_ids}"
                )

                # === BƯỚC 2: Khóa các Officer liên quan (SỬ DỤNG SKIP LOCKED) ===
                # ✅ NEW: Also exclude blacklisted officers
                available_officers_query = (
                    select(models.User).where(
                        models.User.role == UserRole.OFFICER,
                        models.User.status == "active",
                        models.User.availability_status
                        == "available",  # Chỉ lấy officer đang sẵn sàng
                        models.User.unit_id == lead_unit_id,  # Cùng đơn vị với Lead
                    )
                    # ✅ CẢI TIẾN: Bỏ qua các officer đang bị khóa bởi transaction khác
                    .with_for_update(skip_locked=True)
                )
                
                # ✅ BLACKLIST FILTER: Exclude officers who previously reassigned this lead
                if blacklisted_officer_ids:
                    available_officers_query = available_officers_query.where(
                        ~models.User.id.in_(blacklisted_officer_ids)
                    )
                    log.info(
                        f"[Lead ID: {lead_id}] Excluding {len(blacklisted_officer_ids)} blacklisted officers from assignment pool"
                    )
                
                officer_results = await db.execute(available_officers_query)
                # Lấy danh sách officer chưa bị khóa
                available_officers = officer_results.scalars().all()

                # --- Xử lý khi không có Officer ---
                if not available_officers:
                    log.warning(
                        f"[Lead ID: {lead_id}] No available (and unlocked) officers found for unit {lead_unit_id}. Setting assignment_status to failed."
                    )
                    # Update assignment_status to "failed" (no officers available)
                    StatusHelper.set_assignment_status(lead, AssignmentStatus.FAILED)
                    db.add(lead)

                    # ✅ REFACTOR: Dispatch notification for assignment failure
                    try:
                        from app.services.notification_dispatcher import rooms_for_lead
                        _, notif_cb = await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                            payload=EventPayload.for_lead_assignment_failed(lead, lead_unit_id, "No officers available"),
                            dedupe_key=f"lead_assignment_failed:{lead_id}:no_officers",
                            rooms=rooms_for_lead(lead),
                        )
                        if notif_cb:
                            _post_commit_callbacks.append(notif_cb)
                    except Exception as e:
                        log.error(
                            f"[Lead ID: {lead_id}] Failed to dispatch assignment failure notification: {e}"
                        )

                    # A8: Log decision — no officers available
                    await _log_assignment_decision(
                        db, lead_id=lead_id, assigned_officer_id=None,
                        eligible_officer_ids=[], unit_id=lead_unit_id,
                        channel="auto", reason="no_officers", log=log,
                    )
                    return {"status": AssignmentResult.FAILED, "reason": AssignmentFailureReason.NO_OFFICERS, "lead_id": lead_id, "unit_id": lead_unit_id}, _post_commit_callbacks

                log.debug(
                    f"[Lead ID: {lead_id}] Found {len(available_officers)} available officers for unit {lead_unit_id}."
                )

                # === BUOC 3-5: TINH TAI + CHAM DIEM + SAP XEP ===
                # Dung HAM CHUNG compute_unit_officer_loads - cung duong code voi
                # dashboard "diem ban" nen hai ben KHONG THE lech so. O day pool da
                # duoc BUOC 2 loc availability + blacklist nen KHONG truyen
                # eligible_officer_ids (mac dinh: moi officer deu eligible) => hanh
                # vi y het truoc refactor.
                officer_ids = [o.id for o in available_officers]
                _loads_res = await compute_unit_officer_loads(
                    db,
                    available_officers,
                    include_at_capacity=True,
                    lead_unit_id=lead_unit_id,
                    log=log,
                )
                finance_on = _loads_res.flags.finance_on
                # officer_loads = pool CHON NGUOI (con capacity), da sort theo engine.
                officer_loads = [
                    ol for ol in _loads_res.loads if ol["eligible_for_assignment"]
                ]

                # --- Xử lý khi tất cả Officer đã đầy tải ---
                if not officer_loads:
                    log.warning(
                        f"[Lead ID: {lead_id}] All available officers ({len(available_officers)}) in unit {lead_unit_id} are at full capacity. Setting assignment_status to failed."
                    )
                    # Update assignment_status to "failed" (all at capacity)
                    StatusHelper.set_assignment_status(lead, AssignmentStatus.FAILED)
                    db.add(lead)

                    # ✅ REFACTOR: Dispatch notification for assignment failure
                    try:
                        from app.services.notification_dispatcher import rooms_for_lead
                        _, notif_cb = await dispatch(
                            db=db,
                            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                            payload=EventPayload.for_lead_assignment_failed(lead, lead_unit_id, "All officers at full capacity"),
                            dedupe_key=f"lead_assignment_failed:{lead_id}:capacity",
                            rooms=rooms_for_lead(lead),
                        )
                        if notif_cb:
                            _post_commit_callbacks.append(notif_cb)
                    except Exception as e:
                        log.error(
                            f"[Lead ID: {lead_id}] Failed to dispatch assignment failure notification: {e}"
                        )

                    # A8: Log decision — all at capacity
                    await _log_assignment_decision(
                        db, lead_id=lead_id, assigned_officer_id=None,
                        eligible_officer_ids=officer_ids, unit_id=lead_unit_id,
                        channel="auto", reason="at_capacity",
                        capacity_snapshot={
                            str(ol["officer"].id): {
                                "current": ol["workload"],
                                "max": ol["officer"].max_capacity or 100,
                                **(
                                    {"tuition_hold": ol["tuition_hold"]}
                                    if finance_on
                                    else {}
                                ),
                            }
                            for ol in _loads_res.loads
                        }, log=log,
                    )
                    return {"status": AssignmentResult.FAILED, "reason": AssignmentFailureReason.AT_CAPACITY, "lead_id": lead_id, "unit_id": lead_unit_id}, _post_commit_callbacks

                # === BUOC 5: da tinh trong compute_unit_officer_loads ===
                scoring = _loads_res.scoring
                assign_reason = _loads_res.assign_reason

                chosen_officer_data = officer_loads[0]
                chosen_one = chosen_officer_data["officer"]
                chosen_workload = chosen_officer_data["workload"]
                log.info(
                    f"[Lead ID: {lead_id}] Selected officer {chosen_one.id} ({chosen_one.username}). "
                    f"Current Workload (TỔNG): {chosen_workload}, Max Capacity: {chosen_one.max_capacity}, "
                    f"Util(cơ sở sắp xếp, dist khi exclude_active): {chosen_officer_data['real_util']:.2f}, "
                    f"Last Assigned: {chosen_officer_data['last_assigned']}"
                )

                # === BƯỚC 6: Gán Lead, Cập nhật Officer và Ghi Log Assignment ===
                now_utc = datetime.now(timezone.utc)
                lead.assigned_officer_id = chosen_one.id
                lead.assigned_at = now_utc
                # Update assignment_status to "assigned"
                StatusHelper.set_assignment_status(lead, AssignmentStatus.ASSIGNED)

                chosen_one.last_assigned_at = now_utc

                log_entry = models.AssignmentLog(
                    lead_id=lead.id,  # Lead ID chắc chắn đã có
                    officer_id=chosen_one.id,
                    method="automatic",
                    reason="Hệ thống phân công tự động",
                    timestamp=now_utc,
                )

                # await _log_lead_state_change(...) # Ghi lại sự thay đổi trạng thái lead

                # Thêm tất cả các thay đổi vào session
                db.add_all([lead, chosen_one, log_entry])

                # A8/P2-2: Log decision — successful assignment. `assign_reason` đã
                # được BƯỚC 5 set theo decision matrix (lowest_workload /
                # fairness_weighted / member_weighted / member_fairness_weighted).
                # scores_snapshot (thuần audit — KHÔNG consumer runtime nào đọc;
                # fairness_service chỉ đọc capacity_snapshot):
                #  - Chế độ weighted → dict {workload, dist_load, real_util, eff_util,
                #    weight, score} (workload=TỔNG; dist_load=cơ sở sắp xếp = tổng khi
                #    KHÔNG exclude_active; `score` = thành phần SẮP XẾP, đọc kèm reason).
                #  - Legacy/round-robin → gọn: chỉ real_util (eff_util==real_util,
                #    weight==1, score==real_util nên các field kia thừa; sort chỉ theo
                #    overloaded + last_assigned).
                await _log_assignment_decision(
                    db, lead_id=lead_id, assigned_officer_id=chosen_one.id,
                    eligible_officer_ids=officer_ids, unit_id=lead_unit_id,
                    channel="auto", reason=assign_reason,
                    scores_snapshot=(
                        {
                            str(ol["officer"].id): round(ol["real_util"], 4)
                            for ol in officer_loads
                        }
                        if scoring == "legacy"
                        else {
                            str(ol["officer"].id): {
                                "workload": ol["workload"],  # TỔNG (cổng an toàn)
                                "dist_load": ol["dist_load"],  # =tổng khi flag OFF
                                "real_util": round(ol["real_util"], 4),
                                "eff_util": round(ol["eff_util"], 4),
                                "weight": ol["weight"],
                                "score": round(ol["score"], 4),
                                # Option A: chỉ thêm khi finance_on ⇒ OFF giữ nguyên
                                # audit-shape (byte-identical).
                                **(
                                    {"tuition_hold": ol["tuition_hold"]}
                                    if finance_on
                                    else {}
                                ),
                            }
                            for ol in officer_loads
                        }
                    ),
                    capacity_snapshot={
                        str(ol["officer"].id): {
                            "current": ol["workload"],
                            "max": ol["officer"].max_capacity or 100,
                            **(
                                {"tuition_hold": ol["tuition_hold"]}
                                if finance_on
                                else {}
                            ),
                        }
                        for ol in officer_loads
                    }, log=log,
                )

                log.info(
                    f"[Lead ID: {lead_id}] Lead assignment successful to officer {chosen_one.id}."
                )

        # Kết thúc `async with db.begin_nested()` - Nested transaction commits (savepoint)

        # === ✅ REFACTOR: Dispatch notification after nested transaction ===
        # This happens after DB changes are saved (in nested transaction)
        # Dispatcher will commit the outer transaction and send notifications
        try:
            # Load relationships for notification payload
            await db.refresh(lead, ["unit", "offering"])

            # Prepare notification payload according to LEAD_ASSIGNED schema
            # Note: offering relationship should be loaded via db.refresh above
            offering_name = "N/A"
            if lead.offering:
                offering_name = getattr(lead.offering, 'offering_type', 'N/A')

            # Dispatch notification (saves to DB via flush, caller commits)
            from app.services.notification_dispatcher import rooms_for_lead
            _, notif_cb = await dispatch(
                db=db,
                event=SystemEvents.LEAD_ASSIGNED,
                payload=EventPayload.for_lead_assigned(
                    lead, chosen_one.id, None,
                    offering_name=offering_name,
                    is_automatic=True,
                    assignment_method="automatic",
                ),
                dedupe_key=f"lead_assigned:{lead.id}:{chosen_one.id}",
                rooms=rooms_for_lead(lead),
            )
            if notif_cb:
                _post_commit_callbacks.append(notif_cb)

            log.info(
                f"[Lead ID: {lead_id}] Automatic assignment notification dispatched to officer {chosen_one.id}."
            )
        except Exception as e:
            # Log but don't fail - lead assignment already succeeded
            log.error(
                f"[Lead ID: {lead_id}] Failed to dispatch assignment notification: {e}"
            )

        # Return success result
        return {"status": AssignmentResult.ASSIGNED, "lead_id": lead_id, "officer_id": chosen_one.id}, _post_commit_callbacks

    except OperationalError as e:
        # Bắt lỗi "LockNotAvailableError" (chủ yếu cho việc khóa Lead ban đầu)
        if (
            "could not obtain lock" in str(e).lower()
            or "lock not available" in str(e).lower()
        ):
            log.warning(
                f"[Lead ID: {lead_id}] Lock contention detected (possibly on Lead row). "
                "Celery will retry automatically via autoretry_for."
            )
            # Raise LockContentionError - Celery's autoretry_for=(Exception,) will handle retry
            raise LockContentionError(
                f"Lock contention on lead {lead_id}",
                context={"lead_id": lead_id, "original_error": str(e)}
            )
        else:
            # Nếu là lỗi OperationalError khác (vd: mất kết nối), log và ném ra
            log.error(
                f"[Lead ID: {lead_id}] OperationalError during transaction.",
                exc_info=True,
            )
            # Rollback sẽ tự động xảy ra khi exception thoát khỏi `async with`
            raise e  # Ném lại lỗi để Celery biết task thất bại
    except Exception as e:
        # Bất kỳ lỗi nào khác cũng sẽ được log và ném ra
        log.error(
            f"[Lead ID: {lead_id}] Auto-assign task failed unexpectedly within transaction.",
            exc_info=True,
        )
        # Rollback tự động
        raise e  # Ném lại lỗi để Celery biết task thất bại
