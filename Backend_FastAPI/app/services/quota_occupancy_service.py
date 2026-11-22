# app/services/quota_occupancy_service.py
"""MỘT nguồn cho câu hỏi "đã dùng bao nhiêu chỗ chỉ tiêu" (F230 chặng 2b — đặc tả
``ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` mục 5.4; thiết kế bổ sung §4.7 câu hỏi 2; owner J1 dòng 5).

Module NHẸ: chỉ model + SQLAlchemy, KHÔNG import ``admission_service`` (vòng import là lý do bộ máy nguyện
vọng từng chép tay tập trạng thái chiếm chỗ). ``admission_service``, ``admission_choice_engine_service``,
``quota_matrix_service`` đều đếm qua đây; tập trạng thái chiếm chỗ ĐỊNH NGHĨA MỘT LẦN ở đây
(:data:`OCCUPYING_STATUSES`; nơi khác trỏ vào CÙNG đối tượng — kiểm kê AST trong
``tests/integration/test_quota_occupancy_db.py``).

Số chỗ đã dùng ở MỘT nơi đếm = **Phần A** + **Phần B**:

* **Phần A** — hồ sơ ở trạng thái chiếm chỗ, đếm ĐÚNG cách hiện có của nơi gọi, CHỈ hồ sơ KHÔNG có dòng
  Quyết định còn hiệu lực (:func:`no_effective_row`).
* **Phần B** — dòng Quyết định còn hiệu lực (``EFFECTIVE_ROW_CONDITION`` — một chuỗi với U3) nối DÒNG BỘ
  nguồn (``set_row_id``), đếm theo KHOÁ ĐẾM CHỤP ở dòng bộ (đường xét / thông tin học vụ / ngành + năm học
  của nguyện vọng in lúc dựng bộ) — KHÔNG theo giá trị hiện tại của hồ sơ (ảnh chụp thắng — J1 dòng 6). Hồ
  sơ đã ``withdrawn`` (rút hẳn) trả chỗ (C3); ``withdrawal_pending`` VẪN đếm (J1 dòng 5: chờ hoàn vẫn giữ
  chỗ). Trạng thái hồ sơ ở Phần B không cần thuộc tập chiếm chỗ (em có Quyết định ở "Đã nộp" vẫn giữ chỗ).

Mỗi hồ sơ đếm ĐÚNG MỘT lần: có dòng hiệu lực ⇒ chỉ ở B; không ⇒ chỉ ở A (U3: ≤ 1 dòng hiệu lực / hồ sơ;
Phần B vẫn ``count(DISTINCT profile_id)``). ``exclude_profile_id`` loại ở CẢ HAI phần; lọc năm: Phần A theo
``admission_profile.academic_year`` (như hôm nay), Phần B theo ``council_document_set_row.academic_year`` —
năm học của bộ, CHÍNH là năm học của hồ sơ lúc dựng (bộ chỉ nhận hồ sơ của năm học đã chọn —
``council_candidate_repository.SQL_RESOLVE_CODES``).

MỘT ẢNH CHỤP (F260 — Codex lần 15): mỗi hàm đếm tính Phần A + Phần B trong MỘT câu SQL (:func:`_tong`, hợp
``UNION ALL`` ở ma trận). READ COMMITTED chụp ảnh theo TỪNG CÂU ⇒ hai câu riêng cho A và B để một thao tác
chuyển hồ sơ A↔B (huỷ hiệu lực / huỷ ghi nhận / điều chỉnh bỏ dòng; ghi nhận ở ma trận không khoá) commit chen
giữa ⇒ đếm 0 (B→A) hoặc 2 (A→B) cho cùng một em. Một câu ⇒ em đếm đúng một lần.

B → A (C2 — owner 21-11): em mất dòng hiệu lực mà vẫn chiếm chỗ được đếm lại theo ô HIỆN TẠI (Phần A,
:func:`part_a_cells_of_profiles`) — ô ấy có thể KHÁC ô chụp và có thể thành vượt ⇒ điều chỉnh / huỷ hiệu lực / huỷ ghi nhận
khoá ô hiện tại cùng ô chụp (:func:`lock_quota_for_change`) và cảnh báo đúng ô tăng (:func:`quota_warnings_after_change`).
Ô MẤT chỗ (ô chụp của dòng tắt / bị bỏ; ô Phần A của em được thêm dòng — A → B) cũng vào tập khoá (C2-1, Codex PR-1 lượt 2):
không thì một văn bản khác chuỗi đang so "trước / sau" ở ô ấy đọc số trước khi ta trả chỗ và mất cảnh báo.

Dòng bộ THIẾU khoá đếm / lệch chuỗi cấu hình: owner chốt 10-11 (Q-J1) — CHẶN tại ba thao tác sinh / khôi phục
dòng B (ghi nhận, dòng thêm khi điều chỉnh, dòng bật lại khi huỷ ghi nhận) bằng MỘT hàm
(:func:`check_lock_and_count_set_rows`, 409 nêu số dòng). Bộ đếm vẫn giữ lớp phụ: dòng như vậy (chỉ có khi sửa tay
CSDL) không khớp nơi cần khoá ấy và mỗi lần đếm gặp thì ghi cảnh báo log (:func:`_report_missing_lock`).

Khoá — THỨ TỰ CHUẨN cho cả giao dịch (F259): mọi hồ sơ (id tăng dần) TRƯỚC, rồi mọi dòng chỉ tiêu qua
:func:`lock_quota_cells` (``offering_academic_info`` id tăng dần MỘT câu, RỒI ``admission_path`` id tăng dần
MỘT câu). Các hàm đếm KHÔNG khoá. Bốn thao tác Quyết định (ghi nhận / bổ sung, điều chỉnh, huỷ hiệu lực, huỷ ghi
nhận) khoá HỢP mọi ô đổi số — ô chụp của dòng thêm / bật lại, ô hiện tại của em quay về Phần A, ô mất chỗ — bằng MỘT lần
:func:`lock_quota_cells` (:func:`lock_quota_for_change`); Phê duyệt hàng loạt và công bố nhiều nguyện vọng khoá TRƯỚC mọi
dòng chỉ tiêu sẽ dùng (cùng hàm) rồi mới xét — giữ nguyên thứ tự xét nguyện vọng nghiệp vụ.

Dò ô theo CẶP (loại hình, năm) — ô ngành của Phê duyệt cũ — đọc tập học vụ của năm; lệnh tạo / dời năm học vụ đổi tập ấy (P2 —
Codex PR-1 lượt 2). Bốn thao tác Quyết định lấy KHOÁ NĂM CHIA SẺ của mọi năm có thể chạm Ở ĐẦU thao tác
(:func:`lock_years_of_change`, trước mọi khoá dòng — bất biến + thứ tự ở ``app.core.review_year_lock``) ⇒ tập học vụ đúng tới
lúc ghi; :func:`lock_quota_for_change` kiểm lại năm thật (dưới khoá hồ sơ) nằm trong tập đã khoá, không thì 409 "thử lại".

F230 (Codex 22-11 A-P4): mọi đường đổi số chỗ NGOÀI văn bản Hội đồng (Phê duyệt đơn / lô, công bố, chuyển chờ, rút, trả về Nháp,
chốt rút sau hoàn tiền) khoá CÙNG thứ tự — khoá năm chia sẻ (:func:`lock_years_of_profiles` / :func:`try_lock_years_of_profiles`)
→ dòng hồ sơ → MỘT lần khoá mọi ô em có thể chiếm (:func:`lock_quota_for_profiles`); chốt fail-closed ở
``admission_state_service.transition`` (:func:`check_quota_locked_for_transition`). Chỉ khoá — luật chặn / cảnh báo giữ nguyên.
"""
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

import structlog
from sqlalchemy import Integer, String, cast, distinct, func, or_, select, text, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import Session

from app import models
from app.core.review_year_lock import lock_review_years_shared, try_lock_review_years_shared
from app.models.council_document import (
    EFFECTIVE_ROW_CONDITION,
    CouncilDecision,
    CouncilDecisionRow,
    CouncilDocumentSetRow,
)
from app.utils.exceptions import ConflictError, ServiceError

log = structlog.get_logger(__name__)

#: Trạng thái hồ sơ CHIẾM một chỗ chỉ tiêu (Phần A) — ĐỊNH NGHĨA DUY NHẤT. ``withdrawn`` và các trạng thái
#: trước duyệt không chiếm chỗ. ``enrolled`` có ``is_dropped`` VẪN chiếm (chỗ đã dùng của năm học không cấp
#: lại). ``admitted``: bộ máy nguyện vọng (#15/#16).
OCCUPYING_STATUSES: tuple = (
    "approved",
    "overridden",
    "admitted",
    "confirmed",
    "enrolled",
)
#: Phần B: hồ sơ ở trạng thái này TRẢ chỗ (rút hẳn — C3). ``withdrawal_pending`` KHÔNG trả (J1 dòng 5).
RELEASED_STATUSES = "withdrawn"

#: F259: PostgreSQL huỷ ĐÚNG MỘT giao dịch của vòng chờ khoá (``deadlock_detected``). Nơi bị chọn huỷ trả câu
#: cố định dưới đây (409 / lỗi của mục hàng loạt) — MỘT chuỗi cho ghi nhận, Phê duyệt hàng loạt, công bố.
SQLSTATE_DEADLOCK = "40P01"
CONFLICT_MESSAGE = "Xung đột với thao tác khác cùng lúc — thử lại."


def transaction_root_error(transaction: Any) -> Optional[BaseException]:
    """D.2 (Codex lần 16): chỗ DUY NHẤT đọc thuộc tính RIÊNG ``_rollback_exception`` của SQLAlchemy (ghim 2.0.44) —
    lỗi đã làm giao dịch / savepoint ``gd`` lùi (SQLAlchemy ghi lỗi flush hỏng vào giao dịch cha của lần flush).
    ``gd``: ``SessionTransaction`` đồng bộ, hoặc ``AsyncSessionTransaction`` (lấy ``sync_transaction``). ``None`` khi
    ``gd`` là None, giao dịch còn sống, hoặc thư viện không ghi lỗi. Dùng khi một lớp dưới NUỐT lỗi flush rồi lỗi lộ
    ra ở lệnh sau dưới dạng khác (đọc SQLSTATE gốc ⇒ 40P01 ⇒ câu "thử lại" thay vì 500).

    Nâng SQLAlchemy ⇒ chạy lại ``tests/integration/test_loi_goc_giao_dich_db.py`` (ca canh thư viện: lỗi flush THẬT
    trong savepoint và trong giao dịch ngoài) TRƯỚC khi dùng."""
    if transaction is None:
        return None
    transaction = getattr(transaction, "sync_transaction", transaction)
    if transaction is None or transaction.is_active:
        return None
    return getattr(transaction, "_rollback_exception", None)


# ═══════════════════════════════ hai phần ══════════════════════════════════════════════════
def no_effective_row(profile_id_column):
    """Điều kiện Phần A: hồ sơ (cột id ở câu ngoài) KHÔNG có dòng Quyết định còn hiệu lực. Câu con
    ``FROM council_decision_row`` ⇒ tên cột của ``EFFECTIVE_ROW_CONDITION`` (không bí danh) thuộc bảng ấy."""
    return ~(
        select(CouncilDecisionRow.id)
        .where(
            CouncilDecisionRow.profile_id == profile_id_column,
            text(EFFECTIVE_ROW_CONDITION),
        )
        .exists()
    )


def _effective_row():
    """Dòng Quyết định còn hiệu lực — câu con riêng (biểu thức một nguồn, cột không bí danh)."""
    return (
        select(CouncilDecisionRow.profile_id, CouncilDecisionRow.set_row_id)
        .where(text(EFFECTIVE_ROW_CONDITION))
        .subquery("dong_hl")
    )


def _part_b(group_column, *conditions, exclude_profile_id: Optional[int] = None):
    """Phần B: ``count(DISTINCT hồ sơ)`` của dòng hiệu lực nối dòng bộ nguồn (khoá CHỤP), hồ sơ chưa trả
    chỗ. ``group_column`` (cột của dòng bộ) ⇒ đếm theo nhóm; ``None`` ⇒ một số."""
    d = _effective_row()
    b = CouncilDocumentSetRow
    p = models.AdmissionProfile
    counts = func.count(distinct(d.c.profile_id))
    q = (
        select(counts) if group_column is None else select(group_column, counts)
    ).select_from(d).join(b, b.id == d.c.set_row_id).join(p, p.id == d.c.profile_id).where(
        p.status != RELEASED_STATUSES, *conditions
    )
    if exclude_profile_id is not None:
        q = q.where(d.c.profile_id != exclude_profile_id)
    if group_column is not None:
        q = q.group_by(group_column)
    return q


async def _scalar(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _sum(db: AsyncSession, *part) -> int:
    """F260: cộng các phần đếm (mỗi phần một ``select count``) trong MỘT câu SQL ⇒ MỘT ảnh chụp READ
    COMMITTED cho cả A và B (câu con vô hướng dùng chung ảnh chụp của câu ngoài)."""
    total = None
    for c in part:
        s = func.coalesce(c.scalar_subquery(), 0)
        total = s if total is None else total + s
    return int((await db.execute(select(total))).scalar_one() or 0)


async def count_effective_rows_missing_lock(db: AsyncSession, column) -> int:
    """Số dòng Quyết định còn hiệu lực (hồ sơ chưa trả chỗ) mà dòng bộ THIẾU khoá ``cot`` (NULL) — để báo,
    không suy (đặc tả 1.1; câu hỏi owner lượt J)."""
    return await _scalar(db, _part_b(None, column.is_(None)))


async def _report_missing_lock(db: AsyncSession, column, where: str) -> None:
    n = await count_effective_rows_missing_lock(db, column)
    if n:
        log.warning("quota_phan_b_dong_thieu_khoa_dem", where=where, lock_column=column.key, row_count=n)


# ═══════════════════════════════ bốn nơi đếm ═══════════════════════════════════════════════
async def count_by_offering_year(
    db: AsyncSession,
    *,
    offering_id: int,
    academic_year: int,
    exclude_profile_id: Optional[int] = None,
) -> int:
    """Phê duyệt cũ (ADM-026 — ``admission_service._assert_quota_or_bypass``): Phần A = hồ sơ chiếm chỗ theo
    ``lead.offering_id`` + ``admission_profile.academic_year`` (đúng truy vấn cũ); Phần B = dòng bộ
    ``offering_id`` + ``academic_year`` CHỤP."""
    ap = models.AdmissionProfile
    a = (
        select(func.count(ap.id))
        .join(models.Lead, ap.lead_id == models.Lead.id)
        .where(
            models.Lead.offering_id == offering_id,
            ap.academic_year == academic_year,
            ap.status.in_(OCCUPYING_STATUSES),
            no_effective_row(ap.id),
        )
    )
    if exclude_profile_id is not None:
        a = a.where(ap.id != exclude_profile_id)
    b = _part_b(
        None,
        CouncilDocumentSetRow.offering_id == offering_id,
        CouncilDocumentSetRow.academic_year == academic_year,
        exclude_profile_id=exclude_profile_id,
    )
    n = await _sum(db, a, b)
    await _report_missing_lock(db, CouncilDocumentSetRow.offering_id, "nganh_nam")
    return n


def _part_a_multi_choice(*conditions, exclude_profile_id: Optional[int]):
    """Phần A — nguyện vọng ``admitted`` của hồ sơ chiếm chỗ (bộ máy nguyện vọng), đếm dòng nguyện vọng như
    ``check_choice_admit_capacity`` hôm nay."""
    ap = models.AdmissionProfile
    c = models.AdmissionProfileChoice
    q = (
        select(func.count(c.id))
        .join(ap, ap.id == c.admission_profile_id)
        .where(
            c.decision == "admitted",
            ap.status.in_(OCCUPYING_STATUSES),
            no_effective_row(ap.id),
            *conditions,
        )
    )
    if exclude_profile_id is not None:
        q = q.where(ap.id != exclude_profile_id)
    return q


def _legacy_path_id(ap):
    """``applied_rules->>'admission_path_id'`` ép số nguyên — biểu thức Phần A kiểu cũ, MỘT nguồn cho :func:`_part_a_legacy`
    (đếm) và :func:`part_a_cells_of_profiles` (ô)."""
    return ap.applied_rules["admission_path_id"].astext.cast(Integer)


def _part_a_legacy(path_condition, exclude_profile_id: Optional[int]):
    """Phần A — hồ sơ một nguyện vọng kiểu cũ (``uses_choice_engine`` = FALSE) theo
    ``applied_rules->>'admission_path_id'`` (ép kiểu như hôm nay)."""
    ap = models.AdmissionProfile
    q = select(func.count(ap.id)).where(
        ap.uses_choice_engine.is_(False),
        ap.status.in_(OCCUPYING_STATUSES),
        no_effective_row(ap.id),
        path_condition(_legacy_path_id(ap)),
    )
    if exclude_profile_id is not None:
        q = q.where(ap.id != exclude_profile_id)
    return q


async def part_a_cells_of_profiles(
    db: AsyncSession,
    profile_ids: Iterable[Optional[int]],
    *,
    counted_now: bool = False,
    assume_occupying: bool = False,
) -> Tuple[Set[int], Set[int]]:
    """C2 (owner 21-11): (id ``offering_academic_info``, id ``admission_path``) mà các hồ sơ ``profile_ids`` sẽ được đếm ở
    **Phần A** nếu KHÔNG còn dòng Quyết định hiệu lực — "ô HIỆN TẠI" của em bị bỏ tên / văn bản bị huỷ / bị huỷ ghi nhận.

    ĐÚNG điều kiện Phần A của các hàm đếm (một nguồn — cùng hằng, cùng biểu thức), BỎ riêng ``no_effective_row`` (câu hỏi là
    "mất dòng thì đếm ở đâu"); chỉ hồ sơ ở trạng thái chiếm chỗ (:data:`OCCUPYING_STATUSES` — trạng thái khác không vào Phần A):

    * Phê duyệt cũ (:func:`count_by_offering_year`): học vụ theo ``lead.offering_id`` + ``admission_profile.academic_year``;
    * công bố (:func:`count_by_academic_info` / :func:`count_by_path` — :func:`_part_a_multi_choice`): đường xét của nguyện vọng
      ``admitted`` + học vụ của đường xét ấy;
    * kiểu cũ (:func:`_part_a_legacy`): đường xét ``applied_rules->>'admission_path_id'`` + học vụ của nó.

    ``counted_now`` = True (C2-1 — ô MẤT chỗ khi em được THÊM dòng hiệu lực, A → B): chỉ em ĐANG được đếm ở Phần A (thêm đúng
    ``no_effective_row`` của các hàm đếm) — em đã có dòng hiệu lực thì không chiếm ô Phần A nào để mất.

    ``assume_occupying`` = True (F230 — :func:`profile_quota_cells`): BỎ điều kiện trạng thái — ô em SẼ / ĐÃ chiếm khi ở trạng
    thái chiếm chỗ, dùng cho đường làm em VÀO hoặc RA khỏi trạng thái chiếm chỗ (Phê duyệt, công bố, rút, trả về Nháp…).

    Gọi SAU khi đã khoá hồ sơ (trạng thái / nguyện vọng / dòng hiệu lực không đổi dưới tay) và SAU khoá năm của các hồ sơ
    (:func:`lock_years_of_change` — câu dò học vụ theo ngành + năm dưới đây đọc tập học vụ của năm, P2). Hai chiều mới của #733
    (nhóm ngành) CHƯA có ở đây."""
    ids = sorted({int(p) for p in profile_ids if p is not None})
    if not ids:
        return set(), set()
    ap, lead = models.AdmissionProfile, models.Lead
    oai, path, c = models.OfferingAcademicInfo, models.AdmissionPath, models.AdmissionProfileChoice
    occupying = (
        (ap.id.in_(ids),)
        + (() if assume_occupying else (ap.status.in_(OCCUPYING_STATUSES),))
        + ((no_effective_row(ap.id),) if counted_now else ())
    )
    ai_ids = set(
        (
            await db.execute(
                select(oai.id)
                .select_from(ap)
                .join(lead, ap.lead_id == lead.id)
                .join(oai, (oai.offering_id == lead.offering_id) & (oai.academic_year == ap.academic_year))
                .where(*occupying)
            )
        ).scalars()
    )
    path_rows = list(
        (
            await db.execute(
                select(path.id, path.academic_info_id)
                .select_from(c)
                .join(ap, ap.id == c.admission_profile_id)
                .join(path, path.id == c.admission_path_id)
                .where(*occupying, c.decision == "admitted")
            )
        ).all()
    ) + list(
        (
            await db.execute(
                select(path.id, path.academic_info_id)
                .select_from(ap)
                .join(path, path.id == _legacy_path_id(ap))
                .where(*occupying, ap.uses_choice_engine.is_(False))
            )
        ).all()
    )
    ai_ids |= {r.academic_info_id for r in path_rows if r.academic_info_id is not None}
    return ai_ids, {r.id for r in path_rows}


async def count_by_academic_info(
    db: AsyncSession, *, academic_info_id: int, exclude_profile_id: Optional[int] = None
) -> int:
    """Công bố — mức năm (``check_choice_admit_capacity`` Tier 1): Phần A = nguyện vọng trúng trên đường xét
    thuộc ``academic_info_id`` + hồ sơ kiểu cũ có đường xét thuộc nó; Phần B = dòng bộ ``academic_info_id``
    CHỤP."""
    path = models.AdmissionPath
    a1 = _part_a_multi_choice(
        path.academic_info_id == academic_info_id, exclude_profile_id=exclude_profile_id
    ).join(path, path.id == models.AdmissionProfileChoice.admission_path_id)
    a2 = _part_a_legacy(
        lambda column: column.in_(select(path.id).where(path.academic_info_id == academic_info_id)),
        exclude_profile_id,
    )
    b = _part_b(
        None,
        CouncilDocumentSetRow.academic_info_id == academic_info_id,
        exclude_profile_id=exclude_profile_id,
    )
    n = await _sum(db, a1, a2, b)
    await _report_missing_lock(db, CouncilDocumentSetRow.academic_info_id, "thong_tin_hoc_vu")
    return n


async def count_by_path(
    db: AsyncSession, *, admission_path_id: int, exclude_profile_id: Optional[int] = None
) -> int:
    """Công bố — mức đường xét (``check_choice_admit_capacity`` Tier 2): Phần A = nguyện vọng trúng trên
    đường xét + hồ sơ kiểu cũ trỏ đường xét; Phần B = dòng bộ ``admission_path_id`` CHỤP."""
    a1 = _part_a_multi_choice(
        models.AdmissionProfileChoice.admission_path_id == admission_path_id,
        exclude_profile_id=exclude_profile_id,
    )
    a2 = _part_a_legacy(lambda column: column == admission_path_id, exclude_profile_id)
    b = _part_b(
        None,
        CouncilDocumentSetRow.admission_path_id == admission_path_id,
        exclude_profile_id=exclude_profile_id,
    )
    n = await _sum(db, a1, a2, b)
    await _report_missing_lock(db, CouncilDocumentSetRow.admission_path_id, "duong_xet")
    return n


async def count_admitted_by_path(
    db: AsyncSession, path_ids: Sequence[int]
) -> Dict[int, int]:
    """Cột "approved" của ma trận chỉ tiêu (``quota_matrix_service._compute_funnel_counts``) — {đường xét:
    số}. Phần A = hai nhánh hôm nay của ma trận (M1 nguyện vọng trúng: ``count(DISTINCT hồ sơ)``; M2 kiểu cũ:
    so ``applied_rules->>'admission_path_id'`` DẠNG CHỮ, không ép kiểu); Phần B = dòng bộ
    ``admission_path_id`` CHỤP. Các cột phễu khác KHÔNG đếm ở đây (giữ nguyên ở ma trận)."""
    out: Dict[int, int] = {int(p): 0 for p in path_ids}
    if not out:
        return out
    ap = models.AdmissionProfile
    c = models.AdmissionProfileChoice
    rows = list(out)
    # Khoá nhóm của ba nhánh ở DẠNG CHỮ (M2 so ``applied_rules`` dạng chữ, không ép kiểu — như cũ) để hợp
    # được trong MỘT câu ``UNION ALL`` (F260: một ảnh chụp cho A và B).
    m1 = (
        select(
            cast(c.admission_path_id, String),
            func.count(distinct(c.admission_profile_id)),
        )
        .join(ap, ap.id == c.admission_profile_id)
        .where(
            c.admission_path_id.in_(rows),
            c.decision == "admitted",
            ap.status.in_(OCCUPYING_STATUSES),
            no_effective_row(ap.id),
        )
        .group_by(c.admission_path_id)
    )
    fill_text = ap.applied_rules["admission_path_id"].astext
    m2 = (
        select(fill_text, func.count(ap.id))
        .where(
            ap.uses_choice_engine.is_(False),
            fill_text.in_([str(p) for p in rows]),
            ap.status.in_(OCCUPYING_STATUSES),
            no_effective_row(ap.id),
        )
        .group_by(fill_text)
    )
    b = _part_b(
        cast(CouncilDocumentSetRow.admission_path_id, String),
        CouncilDocumentSetRow.admission_path_id.in_(rows),
    )
    for owner_id, n in (await db.execute(union_all(m1, m2, b))).all():
        try:
            pid = int(owner_id)
        except (TypeError, ValueError):
            continue
        if pid in out:
            out[pid] += int(n or 0)
    await _report_missing_lock(db, CouncilDocumentSetRow.admission_path_id, "ma_tran")
    return out


# ═══════════════════════════════ GĐ2-A — nhóm ngành ════════════════════════════════════════
def _sum_of_groups(grouped) -> Any:
    """Tổng cột đếm của một câu ``SELECT khoá, count … GROUP BY khoá`` (Σ theo từng ngành thành viên)."""
    s = grouped.subquery()
    return select(func.coalesce(func.sum(list(s.c)[-1]), 0))


async def count_by_group(db: AsyncSession, *, group_id: int) -> Dict[str, int]:
    """GĐ2-A (đặc tả GĐ2 bản 3 §6; ca biên B21): số chỗ đã dùng của MỘT nhóm ngành =
    ``max(Σ cách đếm công bố, Σ cách đếm Phê duyệt cũ)`` trên các học vụ thành viên của nhóm — mỗi phần là ĐÚNG phép đếm
    của :func:`count_by_academic_info` (công bố) / :func:`count_by_offering_year` (Phê duyệt cũ) cho từng thành viên,
    cộng lại. Nhóm không thành viên ⇒ 0.

    MỘT câu SQL (F260): mọi phần A + B của CẢ HAI cách đếm là câu con vô hướng của một câu ngoài ⇒ một ảnh chụp READ
    COMMITTED; không có ca một em chuyển A↔B giữa hai câu đếm. Không khoá (nơi gọi khoá nếu cần — GĐ2-C khoá năm + mọi
    ngành của nhóm). Phần C (giữ chỗ của lần xét đã khoá) THÊM ở GĐ2-C cùng bảng giữ chỗ.

    Trả ``{"publish_count", "approved_count", "used"}`` (``used`` = số lớn hơn)."""
    m = models.AdmissionQuotaGroupMember
    oai = models.OfferingAcademicInfo
    path = models.AdmissionPath
    member_ai = select(m.offering_academic_info_id).where(m.group_id == group_id)
    member_pairs = (
        select(oai.offering_id, oai.academic_year)
        .join(m, m.offering_academic_info_id == oai.id)
        .where(m.group_id == group_id)
    )
    # Cách đếm công bố (Σ count_by_academic_info): mỗi nguyện vọng / hồ sơ kiểu cũ thuộc ĐÚNG một học vụ ⇒ Σ theo thành
    # viên = đếm trên tập thành viên; Phần B cộng theo TỪNG học vụ (``count(DISTINCT)`` mỗi ô rồi cộng).
    pub_a1 = _part_a_multi_choice(path.academic_info_id.in_(member_ai), exclude_profile_id=None).join(
        path, path.id == models.AdmissionProfileChoice.admission_path_id
    )
    pub_a2 = _part_a_legacy(
        lambda column: column.in_(select(path.id).where(path.academic_info_id.in_(member_ai))), None
    )
    pub_b = _sum_of_groups(
        _part_b(CouncilDocumentSetRow.academic_info_id, CouncilDocumentSetRow.academic_info_id.in_(member_ai))
    )
    # Cách đếm Phê duyệt cũ (Σ count_by_offering_year): Phần A theo ``lead.offering_id`` + năm của hồ sơ; Phần B theo cặp
    # ngành + năm CHỤP ở dòng bộ, cộng theo từng cặp.
    ap = models.AdmissionProfile
    old_a = (
        select(func.count(ap.id))
        .join(models.Lead, ap.lead_id == models.Lead.id)
        .where(
            tuple_(models.Lead.offering_id, ap.academic_year).in_(member_pairs),
            ap.status.in_(OCCUPYING_STATUSES),
            no_effective_row(ap.id),
        )
    )
    # Mọi thành viên cùng MỘT năm (khoá ngoại ghép năm) ⇒ nhóm theo ``offering_id`` = nhóm theo cặp (ngành, năm).
    b = CouncilDocumentSetRow
    old_b = _sum_of_groups(
        _part_b(b.offering_id, tuple_(b.offering_id, b.academic_year).in_(member_pairs))
    )

    def _sc(q):
        return func.coalesce(q.scalar_subquery(), 0)

    publish, approved = (
        await db.execute(select(_sc(pub_a1) + _sc(pub_a2) + _sc(pub_b), _sc(old_a) + _sc(old_b)))
    ).one()
    publish, approved = int(publish or 0), int(approved or 0)
    return {"publish_count": publish, "approved_count": approved, "used": max(publish, approved)}


# ═══════════════════════════════ "đã chiếm chỗ chưa" ═══════════════════════════════════════
async def has_effective_row(db: AsyncSession, profile_id: int) -> bool:
    return bool(
        (
            await db.execute(
                select(
                    select(CouncilDecisionRow.id)
                    .where(
                        CouncilDecisionRow.profile_id == profile_id,
                        text(EFFECTIVE_ROW_CONDITION),
                    )
                    .exists()
                )
            )
        ).scalar()
    )


async def is_occupying(db: AsyncSession, profile) -> bool:
    """``is_already_occupying`` của Phê duyệt cũ: trạng thái chiếm chỗ HOẶC có dòng Quyết định hiệu lực (em
    đã được đếm ở Phần B — duyệt kiểu cũ cho em ấy không cộng thêm chỗ — đặc tả 5.4)."""
    if profile.status in OCCUPYING_STATUSES:
        return True
    return await has_effective_row(db, profile.id)


# ═══════════════════════════════ F230 — sổ khoá của giao dịch (chốt ở transition()) ═════════════
#: Khoá ``Session.info``: những gì giao dịch HIỆN TẠI đã khoá qua module này — id học vụ (``ai``), id đường xét (``path``), năm
#: (``years`` — khoá năm chia sẻ). Gắn với giao dịch GỐC (``Session.get_transaction()``): giao dịch mới ⇒ sổ mới. Chỉ để chốt ở
#: :func:`check_quota_locked_for_transition` đọc — KHÔNG phải nguồn của khoá (khoá thật là khoá của PostgreSQL). Giới hạn đã biết:
#: khoá lấy trong một SAVEPOINT đã lùi thì PostgreSQL đã nhả mà sổ vẫn ghi — các đường F230 khoá NGOÀI savepoint của từng mục.
_LOCK_BOOK_KEY = "qos_so_khoa_giao_dich"


def _lock_book(db: AsyncSession) -> Optional[Dict[str, Any]]:
    """Sổ khoá của giao dịch gốc hiện tại; ``None`` khi phiên không phải ``Session`` thật (test giả lập)."""
    s = getattr(db, "sync_session", None)
    if not isinstance(s, Session):
        return None
    tx = s.get_transaction()
    book = s.info.get(_LOCK_BOOK_KEY)
    if book is None or book["tx"] is not tx:
        book = {"tx": tx, "ai": set(), "path": set(), "years": set()}
        s.info[_LOCK_BOOK_KEY] = book
    return book


def _record_locks(db: AsyncSession, *, ai: Iterable[int] = (), path: Iterable[int] = (), years: Iterable[int] = ()) -> None:
    book = _lock_book(db)
    if book is not None:
        book["ai"].update(int(x) for x in ai)
        book["path"].update(int(x) for x in path)
        book["years"].update(int(x) for x in years)


# ═══════════════════════════════ THỨ TỰ KHOÁ CHUẨN của dòng chỉ tiêu (F259) ═════════════════
async def lock_quota_cells(
    db: AsyncSession, oai_ids: Iterable[Optional[int]], path_ids: Iterable[Optional[int]]
) -> None:
    """THỨ TỰ KHOÁ CHUẨN cho MỌI dòng chỉ tiêu một giao dịch sẽ dùng (F259 — Codex lần 15):
    ``offering_academic_info`` id TĂNG DẦN trong MỘT câu, RỒI ``admission_path`` id TĂNG DẦN trong MỘT câu.
    Nơi gọi khoá mọi hồ sơ (id tăng dần) TRƯỚC. Mọi lần khoá dòng chỉ tiêu SAU đó trong cùng giao dịch
    (``_resolve_quota_context``, ``check_choice_admit_capacity``) chỉ khoá LẠI dòng đã giữ ⇒ không chờ ⇒
    không vòng chờ với giao dịch khác cùng thứ tự (ghi nhận, Phê duyệt cũ, công bố, Phê duyệt hàng loạt)."""
    oai = sorted({int(x) for x in oai_ids if x is not None})
    if oai:
        t = models.OfferingAcademicInfo
        await db.execute(select(t.id).where(t.id.in_(oai)).order_by(t.id).with_for_update())
    paths = sorted({int(x) for x in path_ids if x is not None})
    if paths:
        t = models.AdmissionPath
        await db.execute(select(t.id).where(t.id.in_(paths)).order_by(t.id).with_for_update())
    _record_locks(db, ai=oai, path=paths)  # F230: sổ khoá cho chốt ở transition()


async def quota_cells_of_set_rows(
    db: AsyncSession, set_row_ids: Iterable[Optional[int]]
) -> Tuple[Set[int], Set[int]]:
    """(id ``offering_academic_info``, id ``admission_path``) mà các dòng bộ chiếm ở Phần B — học vụ theo
    ``academic_info_id`` CHỤP và theo cặp ``offering_id`` + năm CHỤP (phủ cả hai cách Phê duyệt cũ chọn dòng),
    đường xét theo ``admission_path_id`` CHỤP. MỘT nguồn cho ô chụp của dòng sắp chiếm chỗ và ô mất chỗ của dòng sắp tắt
    (:func:`lock_quota_for_change` — khoá + cảnh báo). Câu dò theo cặp đọc tập học vụ của năm CHỤP ⇒ gọi SAU khoá năm (P2)."""
    ids = sorted({int(x) for x in set_row_ids if x is not None})
    if not ids:
        return set(), set()
    b = CouncilDocumentSetRow
    lock = (
        await db.execute(
            select(b.academic_info_id, b.offering_id, b.academic_year, b.admission_path_id)
            .where(b.id.in_(ids))
            .distinct()
        )
    ).all()
    oai = models.OfferingAcademicInfo
    ai_ids = {k.academic_info_id for k in lock if k.academic_info_id is not None}
    cap = sorted(
        {(k.offering_id, k.academic_year) for k in lock if k.offering_id is not None}
    )
    if cap:
        ai_ids |= set(
            (
                await db.execute(
                    select(oai.id).where(tuple_(oai.offering_id, oai.academic_year).in_(cap))
                )
            ).scalars()
        )
    return ai_ids, {k.admission_path_id for k in lock if k.admission_path_id is not None}


def _ids(values: Iterable[Optional[int]]) -> List[int]:
    return sorted({int(x) for x in values if x is not None})


async def _years_of(db: AsyncSession, set_row_ids: Sequence[int], profile_ids: Sequence[int]) -> Set[int]:
    """Năm mà bước dò ô theo cặp (loại hình, năm) đọc: năm CHỤP của dòng bộ (:func:`quota_cells_of_set_rows`) + năm hồ sơ
    (:func:`part_a_cells_of_profiles` — ``lead.offering_id`` + ``admission_profile.academic_year``)."""
    years: Set[int] = set()
    if set_row_ids:
        b = CouncilDocumentSetRow
        years |= set((await db.execute(select(b.academic_year).where(b.id.in_(set_row_ids)).distinct())).scalars())
    if profile_ids:
        ap = models.AdmissionProfile
        years |= set((await db.execute(select(ap.academic_year).where(ap.id.in_(profile_ids)).distinct())).scalars())
    return {int(y) for y in years if y is not None}


async def lock_years_of_change(
    db: AsyncSession,
    *,
    set_ids: Iterable[Optional[int]] = (),
    decision_ids: Iterable[Optional[int]] = (),
    row_ids: Iterable[Optional[int]] = (),
) -> FrozenSet[int]:
    """P2 (Codex PR-1 GĐ1 lượt 2, 21-11): KHOÁ NĂM CHIA SẺ (``app.core.review_year_lock.lock_review_years_shared`` — MỘT định
    nghĩa) của mọi năm mà một thao tác Quyết định CÓ THỂ chạm, gọi Ở ĐẦU thao tác — TRƯỚC mọi khoá dòng (lượt gửi, gốc chuỗi, …,
    hồ sơ, ô chỉ tiêu). Lệnh tạo / dời năm / xoá / khôi phục học vụ (khoá năm ĐỘC QUYỀN) không chen được giữa bước dò ô theo cặp
    (loại hình, năm) và lúc commit ⇒ không có học vụ "vừa xuất hiện" vắng khỏi tập khoá + cảnh báo.

    Phạm vi đọc TRƯỚC khoá (tập rộng, chưa khoá gì): dòng bộ của ``set_ids`` (ghi nhận; dòng THÊM của điều chỉnh); dòng
    Quyết định ``row_ids`` (dòng BỎ của điều chỉnh); mọi dòng của văn bản ``decision_ids`` + dòng nó đã bỏ + dòng của văn bản đích
    nếu nó là văn bản huỷ (huỷ hiệu lực / huỷ ghi nhận) — năm chụp của dòng bộ nguồn và năm của hồ sơ. Trả tập năm đã khoá cho
    :func:`lock_quota_for_change` kiểm lại dưới khoá hồ sơ."""
    r, b, cd = CouncilDecisionRow, CouncilDocumentSetRow, CouncilDecision
    sets, decisions, rows = _ids(set_ids), _ids(decision_ids), _ids(row_ids)
    pairs: List[Any] = []
    conditions = []
    if decisions:
        targets = select(cd.huy_qd_id).where(cd.id.in_(decisions), cd.huy_qd_id.is_not(None))
        conditions += [r.decision_id.in_(decisions), r.decision_id.in_(targets), r.bi_bo_boi_id.in_(decisions)]
    if rows:
        conditions.append(r.id.in_(rows))
    if conditions:
        pairs += (await db.execute(select(r.set_row_id, r.profile_id).where(or_(*conditions)))).all()
    if sets:
        pairs += (await db.execute(select(b.id, b.profile_id).where(b.set_id.in_(sets)))).all()
    years = await _years_of(db, _ids(p[0] for p in pairs), _ids(p[1] for p in pairs))
    await lock_review_years_shared(db, years)
    _record_locks(db, years=years)
    return frozenset(years)


class QuotaChange:
    """Các ô chỉ tiêu mà MỘT thao tác ghi văn bản (ghi nhận / bổ sung, điều chỉnh, huỷ hiệu lực, huỷ ghi nhận) làm TĂNG số đếm —
    MỘT nguồn cho khoá (:func:`lock_quota_for_change`) và cảnh báo (:func:`quota_warnings_after_change`).

    * ``snapshot_*``: ô CHỤP của dòng sắp chiếm chỗ (Phần B — dòng ghi nhận / thêm / bật lại) ⇒ cảnh báo khi VƯỢT sau ghi (N9 /
      K-1);
    * ``current_*``: ô HIỆN TẠI (Phần A) của em sắp mất dòng hiệu lực mà vẫn chiếm chỗ — KỂ CẢ ô cũng là ô chụp (ô HAI VAI —
      C2-2) ⇒ cảnh báo khi số chính TĂNG so với ``before`` VÀ vượt (ô hai vai: vượt là báo, như ô chụp), bản ghi mang số trước;
    * ``before``: {(``"nganh"`` | ``"duong_xet"``, id): số chính} TRƯỚC khi ghi, đếm DƯỚI khoá — mọi ô ``current_*`` có chỉ tiêu.

    Ô MẤT chỗ (C2-1) chỉ được KHOÁ (không cảnh báo — số đếm ở đó không tăng vì chúng) nên không nằm ở đây."""

    __slots__ = ("snapshot_ai_ids", "snapshot_path_ids", "current_ai_ids", "current_path_ids", "before")

    def __init__(self, snapshot_ai_ids, snapshot_path_ids, current_ai_ids, current_path_ids, before):
        self.snapshot_ai_ids = frozenset(snapshot_ai_ids)
        self.snapshot_path_ids = frozenset(snapshot_path_ids)
        self.current_ai_ids = frozenset(current_ai_ids)
        self.current_path_ids = frozenset(current_path_ids)
        self.before: Dict[Tuple[str, int], int] = dict(before)


async def lock_quota_for_change(
    db: AsyncSession,
    *,
    locked_years: Iterable[int],
    set_row_ids: Iterable[Optional[int]],
    returning_profile_ids: Iterable[Optional[int]],
    released_set_row_ids: Iterable[Optional[int]] = (),
    entering_profile_ids: Iterable[Optional[int]] = (),
) -> QuotaChange:
    """C2 (owner 21-11 — CHẶN F230): khoá MỌI ô chỉ tiêu mà thao tác làm đổi số đếm bằng MỘT lần :func:`lock_quota_cells`
    (gọi nhiều lần là phá thứ tự tăng dần F259 ⇒ vòng chờ với Phê duyệt hàng loạt / công bố đang khoá [thấp, cao]); rồi đếm số
    "trước" DƯỚI khoá. Nơi gọi: SAU khi khoá hồ sơ, TRƯỚC mọi câu ghi.

    Ô TĂNG (cảnh báo — :class:`QuotaChange`):

    * ô CHỤP của dòng ``set_row_ids`` sắp chiếm chỗ (ghi nhận / thêm / bật lại);
    * ô HIỆN TẠI (:func:`part_a_cells_of_profiles`) của em ``returning_profile_ids`` sắp mất dòng hiệu lực (B → A). Vì sao khoá:
      Phê duyệt cũ / công bố đồng thời ở ô ấy phải CHỜ thao tác này commit rồi mới đếm (thấy em đã về Phần A).

    Ô MẤT chỗ (C2-1 — Codex PR-1 lượt 2; chỉ khoá): ô CHỤP của dòng ``released_set_row_ids`` sắp tắt / bị bỏ, và ô Phần A mà em
    ``entering_profile_ids`` ĐANG được đếm (sắp được thêm dòng hiệu lực, A → B — ``counted_now``). Vì sao khoá: một văn bản KHÁC
    chuỗi đang so "trước / sau" ở cùng ô (đã đọc 31 / 30 dưới khoá) phải thấy chỗ ta trả TRƯỚC hoặc SAU cả lần so — không thì nó
    trả 1 chỗ giữa chừng, văn bản kia đưa em về (31) rồi so 31 với 31 và mất cảnh báo.

    P2: ``locked_years`` = tập năm :func:`lock_years_of_change` đã khoá ở đầu thao tác (bắt buộc — không thể quên khoá năm). Năm
    THẬT của dòng bộ + hồ sơ (đọc lại dưới khoá hồ sơ) ngoài tập ấy (hồ sơ vừa đổi năm ở nơi khác) ⇒ 409 "thử lại": khoá thêm năm
    sau khi đã giữ khoá dòng là phá thứ tự."""
    gain, lost = _ids(set_row_ids), _ids(released_set_row_ids)
    returning, entering = _ids(returning_profile_ids), _ids(entering_profile_ids)
    missing = await _years_of(db, gain + lost, returning + entering) - set(locked_years)
    if missing:
        log.warning("quota_nam_ngoai_khoa_nam", years=sorted(missing))
        raise ConflictError(CONFLICT_MESSAGE)
    snapshot_ai, snapshot_path = await quota_cells_of_set_rows(db, gain)
    current_ai, current_path = await part_a_cells_of_profiles(db, returning)
    lost_ai, lost_path = await quota_cells_of_set_rows(db, lost)
    leaving_ai, leaving_path = await part_a_cells_of_profiles(db, entering, counted_now=True)
    await lock_quota_cells(
        db,
        snapshot_ai | current_ai | lost_ai | leaving_ai,
        snapshot_path | current_path | lost_path | leaving_path,
    )
    # C2-2 (Codex PR-1 lượt 2): đếm trước MỌI ô hiện tại — KỂ CẢ ô hai vai (cũng là ô chụp); bỏ ô ấy khỏi tập TRƯỚC khi đếm thì
    # cảnh báo của nó thiếu số trước + câu owner.
    return QuotaChange(
        snapshot_ai,
        snapshot_path,
        current_ai,
        current_path,
        await _main_used(db, current_ai, current_path),
    )


# ═══════════════════════════════ F230 — đường đổi số chỗ NGOÀI văn bản Hội đồng ═══════════════════════
# Codex 22-11 A-P4; thiết kế ``phat-hanh-gd1/pr-f230/THIET-KE-PHA1-2026-11-22.md``; owner Q1–Q5 (``QUYET-DINH-OWNER-F230-…``).
# Phê duyệt đơn / lô, công bố, chuyển chờ (TĂNG); rút, trả về Nháp, chốt rút sau hoàn tiền (GIẢM) đổi số của ô mà một văn bản
# Hội đồng đang so "trước / sau" (C2) ⇒ khoá ĐỦ ô theo CÙNG thứ tự của PR-1: khoá năm chia sẻ → dòng (hồ sơ …) → MỘT lần
# :func:`lock_quota_cells`. CHỈ khoá — luật chặn / cảnh báo của từng đường GIỮ NGUYÊN (owner Q1, Q2, Q4).
OCCUPANCY_TRANSITION_UNLOCKED_MESSAGE = (
    "Lỗi hệ thống: chuyển trạng thái làm đổi số chỗ chỉ tiêu mà chưa khoá ô chỉ tiêu — đã ghi log, không chuyển."
)


async def _effective_set_rows_of_profiles(db: AsyncSession, profile_ids: Sequence[int]) -> List[int]:
    """Id dòng bộ nguồn của các dòng Quyết định HIỆU LỰC của các hồ sơ (Phần B — ô chụp)."""
    if not profile_ids:
        return []
    r = CouncilDecisionRow
    return _ids(
        (
            await db.execute(
                select(r.set_row_id).where(r.profile_id.in_(list(profile_ids)), text(EFFECTIVE_ROW_CONDITION))
            )
        ).scalars()
    )


async def _years_of_profiles(db: AsyncSession, profile_ids: Sequence[int]) -> Set[int]:
    """Năm mà bước dò ô của :func:`profile_quota_cells` đọc: năm hồ sơ + năm chụp của dòng bộ của dòng hiệu lực."""
    return await _years_of(db, await _effective_set_rows_of_profiles(db, profile_ids), profile_ids)


async def profile_quota_cells(
    db: AsyncSession,
    profile_ids: Iterable[Optional[int]],
    *,
    effective_set_rows: Optional[Sequence[int]] = None,
) -> Tuple[Set[int], Set[int]]:
    """MỘT nguồn (F230): (id học vụ, id đường xét) mà các hồ sơ CÓ THỂ chiếm — mọi ô Phần A, BẤT KỂ trạng thái hiện tại
    (:func:`part_a_cells_of_profiles` ``assume_occupying``: ngành theo lead + năm, nguyện vọng trúng, đường xét kiểu cũ) ∪ ô chụp
    của dòng Quyết định hiệu lực (Phần B, :func:`quota_cells_of_set_rows`). Một tập cho cả đường VÀO lẫn RA khỏi trạng thái chiếm
    chỗ (rộng hơn cần — chủ ý: không phân nhánh theo cạnh). Gọi SAU khoá năm + khoá hồ sơ. ``effective_set_rows``: dòng bộ của
    dòng hiệu lực ĐÃ đọc (nơi gọi đọc một lần cho cả năm lẫn ô — :func:`check_quota_locked_for_transition`); ``None`` ⇒ tự đọc."""
    ids = _ids(profile_ids)
    if effective_set_rows is None:
        effective_set_rows = await _effective_set_rows_of_profiles(db, ids)
    a_ai, a_path = await part_a_cells_of_profiles(db, ids, assume_occupying=True)
    b_ai, b_path = await quota_cells_of_set_rows(db, effective_set_rows)
    return a_ai | b_ai, a_path | b_path


async def lock_years_of_profiles(db: AsyncSession, profile_ids: Iterable[Optional[int]]) -> FrozenSet[int]:
    """F230: khoá năm CHIA SẺ, CÓ CHỜ, của các hồ sơ (năm hồ sơ + năm chụp của dòng hiệu lực) — gọi TRƯỚC khi khoá dòng hồ sơ
    (đọc phạm vi khi CHƯA khoá; :func:`lock_quota_for_profiles` kiểm lại dưới khoá hồ sơ). Thứ tự + lý do không vòng chờ:
    ``app.core.review_year_lock`` (đoạn F230)."""
    years = await _years_of_profiles(db, _ids(profile_ids))
    await lock_review_years_shared(db, years)
    _record_locks(db, years=years)
    return frozenset(years)


async def try_lock_years_of_profiles(
    db: AsyncSession, profile_ids: Iterable[Optional[int]], *, busy_message: str = CONFLICT_MESSAGE
) -> FrozenSet[int]:
    """F230: bản KHÔNG CHỜ (hồ sơ ĐÃ bị khoá ở ``deps.py`` — Công bố, Chuyển chờ, Trả về Nháp; đường dẫn thư). Một giao dịch đang
    giữ / chờ khoá năm ĐỘC QUYỀN (cấu hình cùng năm) ⇒ 409 (owner Q3) — không chờ khi đang giữ dòng hồ sơ ⇒ không khép vòng.
    ``busy_message``: câu của 409 — mặc định câu "thử lại" chung; đường ứng viên tự rút qua thư dùng câu owner riêng
    (``magic_link_service.WITHDRAW_CONFIG_BUSY_MESSAGE``)."""
    years = await _years_of_profiles(db, _ids(profile_ids))
    if not await try_lock_review_years_shared(db, years):
        log.info("quota_khoa_nam_ban_thu_khong_lay_duoc", years=sorted(years))
        raise ConflictError(busy_message)
    _record_locks(db, years=years)
    return frozenset(years)


async def lock_quota_for_profiles(
    db: AsyncSession,
    *,
    locked_years: Iterable[int],
    profile_ids: Iterable[Optional[int]],
    extra_ai_ids: Iterable[Optional[int]] = (),
    extra_path_ids: Iterable[Optional[int]] = (),
) -> Tuple[Set[int], Set[int]]:
    """F230: khoá MỘT lần (:func:`lock_quota_cells`, F259) mọi ô các hồ sơ có thể chiếm (:func:`profile_quota_cells`) ∪ ô thêm
    của nơi gọi (học vụ cổng chỉ tiêu của Phê duyệt cũ, ô nguyện vọng của công bố…) — THAY lần khoá ô sẵn có của đường ấy (các câu
    ``FOR UPDATE`` theo id về sau chỉ khoá lại dòng đã giữ). Gọi SAU khi khoá hồ sơ, TRƯỚC mọi câu ghi / cổng chỉ tiêu.

    ``locked_years`` bắt buộc (= kết quả :func:`lock_years_of_profiles` / :func:`try_lock_years_of_profiles`): năm THẬT dưới khoá
    hồ sơ ngoài tập đã khoá (hồ sơ vừa đổi năm ở nơi khác) ⇒ 409 "thử lại" — khoá thêm năm sau khi giữ dòng là phá thứ tự."""
    ids = _ids(profile_ids)
    missing = await _years_of_profiles(db, ids) - set(locked_years)
    if missing:
        log.warning("quota_nam_ngoai_khoa_nam", years=sorted(missing), where="lock_quota_for_profiles")
        raise ConflictError(CONFLICT_MESSAGE)
    ai, path = await profile_quota_cells(db, ids)
    ai |= {int(x) for x in extra_ai_ids if x is not None}
    path |= {int(x) for x in extra_path_ids if x is not None}
    await lock_quota_cells(db, ai, path)
    return ai, path


async def check_quota_locked_for_transition(db: AsyncSession, profile: Any, old_status: Optional[str], new_status: str) -> None:
    """F230 — CHỐT ở tầng chủ sở hữu trạng thái (``admission_state_service.transition``; owner Q5): chuyển trạng thái làm đổi số
    chỗ — VÀO / RA khỏi :data:`OCCUPYING_STATUSES`, hoặc sang :data:`RELEASED_STATUSES` khi em còn dòng Quyết định hiệu lực (Phần
    B) — mà giao dịch CHƯA khoá năm + ĐỦ ô (:func:`profile_quota_cells`) qua module này ⇒ ``ServiceError`` (500) + log lỗi. Đường
    mới quên khoá bị chặn ngay ở test thay vì lặng lẽ làm mất cảnh báo của văn bản Hội đồng."""
    book = _lock_book(db)
    if book is None:
        # Phiên không phải ``Session`` thật (test đơn vị giả lập ``AsyncSession`` bằng MagicMock — không có CSDL để đọc ô) ⇒ không
        # kiểm được. Mọi phiên của ứng dụng là ``AsyncSession`` thật nên đường chạy thật luôn qua chốt.
        return
    crosses = (old_status in OCCUPYING_STATUSES) != (new_status in OCCUPYING_STATUSES)
    may_release_b = new_status == RELEASED_STATUSES and old_status != RELEASED_STATUSES
    if not (crosses or may_release_b):
        return
    # Phiên ``autoflush=False`` (``app.database``) ⇒ đẩy thay đổi đang chờ (vd ``decision`` nguyện vọng vừa đặt) xuống TRƯỚC MỌI
    # câu đọc của chốt (kể cả câu hỏi dòng hiệu lực ngay dưới) — đường mới quên flush không làm chốt mù (Codex F230 P5 mục 6).
    await db.flush()
    # Sang "đã rút" mà KHÔNG vượt ranh giới chiếm chỗ (vd ``withdrawal_pending``): chỉ đổi số khi em còn dòng hiệu lực (trả chỗ
    # Phần B).
    if not crosses and not await has_effective_row(db, profile.id):
        return
    # Dòng hiệu lực đọc MỘT lần cho cả năm lẫn ô.
    ids = [profile.id]
    set_rows = await _effective_set_rows_of_profiles(db, ids)
    years = await _years_of(db, set_rows, ids)
    ai, path = await profile_quota_cells(db, ids, effective_set_rows=set_rows)
    missing = {
        "years": sorted(years - book["years"]),
        "ai": sorted(ai - book["ai"]),
        "path": sorted(path - book["path"]),
    }
    if any(missing.values()):
        log.error(
            "quota_chuyen_trang_thai_chua_khoa_o",
            profile_id=profile.id,
            from_status=old_status,
            to_status=new_status,
            missing=missing,
        )
        raise ServiceError(OCCUPANCY_TRANSITION_UNLOCKED_MESSAGE)


# ═══════════════════════════════ Q-J1 — khoá đếm của dòng bộ (owner 10-11) ════════════════════
#: Khoá đếm có thể NULL ở dòng bộ mà các hàm đếm thực dùng (``academic_year`` NOT NULL ở CSDL;
#: ``major_id`` không hàm đếm nào dùng ⇒ không kiểm).
LOCKS_COUNT_MAY_BE_MISSING = ("admission_path_id", "academic_info_id", "offering_id")


async def check_lock_and_count_set_rows(
    db: AsyncSession, row: Sequence[Tuple[int, Optional[int]]]
) -> None:
    """Q-J1 (owner chốt 10-11): MỘT hàm kiểm cho ba thao tác sinh / khôi phục dòng Phần B — ghi nhận, dòng
    THÊM khi điều chỉnh, dòng BẬT LẠI khi huỷ ghi nhận. Gọi DƯỚI khoá (sau :func:`lock_quota_for_change`),
    TRƯỚC khi ghi. ``dong`` = [(số dòng, id dòng bộ nguồn)].

    Chặn (409, nêu SỐ DÒNG — không tên, không CCCD) khi một dòng:

    * không có dòng bộ nguồn (``thieu_dong_nguon``);
    * thiếu khoá đếm mà hàm đếm thực dùng (``thieu_khoa``: đường xét / học vụ / ngành);
    * khoá không khớp chuỗi cấu hình (``lech_chuoi_cau_hinh``): đường xét không còn / không thuộc học vụ chụp;
      học vụ không còn / không thuộc ngành + năm chụp — khi ấy các hàm đếm đặt em vào các ô KHÁC nhau.

    Owner KHÔNG chọn: 503 toàn hệ, đếm dòng ấy vào mọi ô, chỉ log. Cảnh báo log ở bộ đếm
    (:func:`_report_missing_lock`) giữ làm lớp phụ."""
    b = CouncilDocumentSetRow
    ids = sorted({int(sid) for _, sid in row if sid is not None})
    source = {}
    if ids:
        source = {
            r.id: r
            for r in (
                await db.execute(
                    select(
                        b.id, b.admission_path_id, b.academic_info_id, b.offering_id, b.academic_year
                    ).where(b.id.in_(ids))
                )
            ).all()
        }
    t_oai, t_path = models.OfferingAcademicInfo, models.AdmissionPath
    ai_ids = sorted({r.academic_info_id for r in source.values() if r.academic_info_id is not None})
    path_ids = sorted({r.admission_path_id for r in source.values() if r.admission_path_id is not None})
    academic_infos = {}
    if ai_ids:
        academic_infos = {
            r.id: (r.offering_id, r.academic_year)
            for r in (
                await db.execute(
                    select(t_oai.id, t_oai.offering_id, t_oai.academic_year).where(t_oai.id.in_(ai_ids))
                )
            ).all()
        }
    paths = {}
    if path_ids:
        paths = {
            r.id: r.academic_info_id
            for r in (
                await db.execute(
                    select(t_path.id, t_path.academic_info_id).where(t_path.id.in_(path_ids))
                )
            ).all()
        }
    error: List[Dict[str, Any]] = []
    for seq, sid in sorted(row, key=lambda x: (x[0], x[1] or 0)):
        r = source.get(sid) if sid is not None else None
        if r is None:
            error.append({"dong": seq, "ly_do": "thieu_dong_nguon"})
            continue
        missing = [k for k in LOCKS_COUNT_MAY_BE_MISSING if getattr(r, k) is None]
        if missing:
            error.append({"dong": seq, "ly_do": "thieu_khoa", "khoa": missing})
            continue
        if (
            paths.get(r.admission_path_id) != r.academic_info_id
            or academic_infos.get(r.academic_info_id) != (r.offering_id, r.academic_year)
        ):
            error.append({"dong": seq, "ly_do": "lech_chuoi_cau_hinh"})
    if error:
        raise ConflictError(
            "Dòng %s: dòng bộ thiếu khoá đếm chỉ tiêu hoặc lệch chuỗi cấu hình (đường xét → học vụ → "
            "ngành + năm) — không ghi được; dựng lại bộ cho đúng." % ", ".join(str(x["dong"]) for x in error),
            public_payload={"dong_thieu_khoa_dem": error},
        )


# ═══════════════════════════════ N9 — cảnh báo vượt chỉ tiêu (không chặn) ═══════════════════
async def quota_warnings_after_change(db: AsyncSession, change: QuotaChange) -> List[Dict[str, Any]]:
    """Cảnh báo vượt chỉ tiêu SAU khi ghi (cùng giao dịch, dưới khoá của :func:`lock_quota_for_change`) — KHÔNG chặn (K-1).
    MỘT hàm cho cả bốn thao tác Quyết định (ghi nhận / bổ sung dùng nó từ PR-1 GĐ1 lượt 2 — trước đó ``over_quota_warnings``):

    * N9 (đặc tả 5.3) — ô CHỤP của dòng ghi nhận / thêm / bật lại: VƯỢT sau ghi ⇒ báo. "Vượt" = số đã dùng > chỉ tiêu — ĐÚNG nghĩa
      sẵn có của phần mềm (Phê duyệt cũ / công bố chặn khi ``đã dùng + 1 > chỉ tiêu`` ⇒ bằng chỉ tiêu là ĐẦY, chưa vượt). Chỉ
      tiêu NULL = không giới hạn ⇒ không xét. Số đã dùng đếm qua ĐÚNG các hàm đếm của module (một nguồn): ô ngành (học vụ, chỉ
      tiêu năm) có HAI cách đếm đang dùng — công bố (:func:`count_by_academic_info`) và Phê duyệt cũ
      (:func:`count_by_offering_year`) — trả cả hai, vượt ở cách nào cũng báo; ô đường xét theo :func:`count_by_path`;
    * C2 (owner 21-11) — ô HIỆN TẠI của em quay về Phần A: chỉ báo ô mà số chính TĂNG (so ``change.before``) VÀ vượt — "chỉ
      đúng ô tăng số chỗ đã dùng"; 29 / 30 → 30 / 30 là đầy, KHÔNG báo. Bản ghi mang thêm ``o_hien_tai``, ``da_dung_truoc``
      và câu owner ``cau`` (ô ngành :data:`CURRENT_CELL_OVER_QUOTA_MESSAGE`, ô đường xét :data:`CURRENT_PATH_OVER_QUOTA_MESSAGE`);
    * C2-2 (Codex PR-1 lượt 2) — ô HAI VAI (vừa ô chụp vừa ô hiện tại, vd văn bản vừa bỏ một em về Y vừa thêm một em vào Y): MỘT
      bản ghi — vượt là báo (luật ô chụp), mang đủ ``o_hien_tai`` / ``da_dung_truoc`` / ``cau`` (vd 30 → 32)."""
    return await _cell_warnings(
        db,
        change.snapshot_ai_ids,
        change.snapshot_path_ids,
        change.current_ai_ids,
        change.current_path_ids,
        change.before,
    )


#: C2 (owner 21-11) — câu cảnh báo ô NGÀNH hiện tại: NGUYÊN VĂN mẫu owner ("Ngành Y, đường xét hiện tại: 30 → 31 chỗ đã dùng,
#: chỉ tiêu 30, vượt 1."), chỉ điền tên ngành (``major_program.name``; thiếu ⇒ "học vụ #id") + số chính trước / sau (ô ngành:
#: mức lớn nhất trong hai cách đếm — K-4) + chỉ tiêu + số vượt.
CURRENT_CELL_OVER_QUOTA_MESSAGE = "Ngành %s, đường xét hiện tại: %d → %d chỗ đã dùng, chỉ tiêu %d, vượt %d."
#: C2 (owner 21-11, câu ô ĐƯỜNG XÉT) — NGUYÊN VĂN "Đường xét Z (ngành Y): 30 → 31 chỗ đã dùng, chỉ tiêu 30, vượt 1.": tên đường xét
#: TRƯỚC (``display_name``; thiếu ⇒ "#id"), rồi tên ngành của học vụ của đường xét (thiếu ⇒ "học vụ #id"); số trước / sau / chỉ
#: tiêu lấy từ CHÍNH ô đường xét (:func:`count_by_path`, ``admit_quota``).
CURRENT_PATH_OVER_QUOTA_MESSAGE = "Đường xét %s (ngành %s): %d → %d chỗ đã dùng, chỉ tiêu %d, vượt %d."


async def _nganh_cells(db: AsyncSession, ai_ids: Iterable[int]):
    # Vòng giao diện (đặc tả 3.8): ``ten`` = tên ngành của học vụ (``major_program.name`` qua ``program_offering``) — chỉ
    # để hiển thị; thiếu ⇒ None (giao diện hiện mã + id).
    t_oai = models.OfferingAcademicInfo
    return (
        await db.execute(
            select(
                t_oai.id,
                t_oai.offering_id,
                t_oai.academic_year,
                t_oai.annual_admission_quota,
                models.MajorProgram.name.label("ten"),
            )
            .select_from(t_oai)
            .outerjoin(models.ProgramOffering, models.ProgramOffering.id == t_oai.offering_id)
            .outerjoin(models.MajorProgram, models.MajorProgram.id == models.ProgramOffering.program_id)
            .where(t_oai.id.in_(sorted(ai_ids)))
            .order_by(t_oai.id)
        )
    ).all()


async def _path_cells(db: AsyncSession, path_ids: Iterable[int]):
    # ``ten_nganh`` = tên ngành của học vụ của đường xét — chỉ cho câu cảnh báo ô đường xét (C2); thiếu ⇒ None.
    t_path, t_oai = models.AdmissionPath, models.OfferingAcademicInfo
    return (
        await db.execute(
            select(
                t_path.id,
                t_path.admit_quota,
                t_path.display_name,
                t_path.academic_info_id,
                models.MajorProgram.name.label("ten_nganh"),
            )
            .select_from(t_path)
            .outerjoin(t_oai, t_oai.id == t_path.academic_info_id)
            .outerjoin(models.ProgramOffering, models.ProgramOffering.id == t_oai.offering_id)
            .outerjoin(models.MajorProgram, models.MajorProgram.id == models.ProgramOffering.program_id)
            .where(t_path.id.in_(sorted(path_ids)))
            .order_by(t_path.id)
        )
    ).all()


async def _nganh_used(db: AsyncSession, cell) -> Tuple[int, int]:
    """(công bố, Phê duyệt cũ) — HAI cách đếm ô ngành đang dùng (F264); số chính = mức lớn nhất (K-4)."""
    return (
        await count_by_academic_info(db, academic_info_id=cell.id),
        await count_by_offering_year(db, offering_id=cell.offering_id, academic_year=cell.academic_year),
    )


async def _main_used(db: AsyncSession, ai_ids: Set[int], path_ids: Set[int]) -> Dict[Tuple[str, int], int]:
    """Số chính đã dùng của các ô CÓ chỉ tiêu (ô ngành: mức lớn nhất trong hai cách đếm; ô đường xét: :func:`count_by_path`)."""
    out: Dict[Tuple[str, int], int] = {}
    if ai_ids:
        for cell in await _nganh_cells(db, ai_ids):
            if cell.annual_admission_quota is not None:
                out[("nganh", cell.id)] = max(await _nganh_used(db, cell))
    if path_ids:
        for p in await _path_cells(db, path_ids):
            if p.admit_quota is not None:
                out[("duong_xet", p.id)] = await count_by_path(db, admission_path_id=p.id)
    return out


async def _cell_warnings(
    db: AsyncSession,
    snapshot_ai_ids: Iterable[int],
    snapshot_path_ids: Iterable[int],
    current_ai_ids: Iterable[int],
    current_path_ids: Iterable[int],
    before: Dict[Tuple[str, int], int],
) -> List[Dict[str, Any]]:
    """MỘT chỗ dựng cảnh báo vượt cho :func:`quota_warnings_after_change` (ô ngành trước, rồi ô đường xét; id tăng dần). Ô
    CHỈ là ô hiện tại có số "trước" ⇒ chỉ báo khi số chính TĂNG; ô hai vai (cũng là ô chụp) vượt là báo; mọi ô có số "trước"
    (``before`` — chỉ ô hiện tại) mang ``o_hien_tai`` / ``da_dung_truoc`` / ``cau``."""
    snapshot_ai, snapshot_path = set(snapshot_ai_ids), set(snapshot_path_ids)
    ai_ids = snapshot_ai | set(current_ai_ids)
    path_ids = snapshot_path | set(current_path_ids)
    out: List[Dict[str, Any]] = []
    if ai_ids:
        for cell in await _nganh_cells(db, ai_ids):
            quota = cell.annual_admission_quota
            if quota is None:
                continue
            publish_count, approved_count = await _nganh_used(db, cell)
            used = max(publish_count, approved_count)
            if used <= quota:
                continue
            entry: Dict[str, Any] = {
                "loai": "nganh",
                "academic_info_id": cell.id,
                "chi_tieu": quota,
                "da_dung_cong_bo": publish_count,
                "da_dung_phe_duyet_cu": approved_count,
                "nhan": cell.ten,
            }
            prior = before.get(("nganh", cell.id))
            if prior is not None:
                if used <= prior and cell.id not in snapshot_ai:
                    continue  # C2: ô CHỈ là ô hiện tại, không TĂNG ⇒ không phải ô thao tác này làm vượt
                entry.update(
                    o_hien_tai=True,
                    da_dung_truoc=prior,
                    cau=CURRENT_CELL_OVER_QUOTA_MESSAGE
                    % (cell.ten or "học vụ #%d" % cell.id, prior, used, quota, used - quota),
                )
            out.append(entry)
    if path_ids:
        for p in await _path_cells(db, path_ids):
            if p.admit_quota is None:
                continue
            n = await count_by_path(db, admission_path_id=p.id)
            if n <= p.admit_quota:
                continue
            entry = {
                "loai": "duong_xet",
                "admission_path_id": p.id,
                "chi_tieu": p.admit_quota,
                "da_dung": n,
                "nhan": p.display_name,
            }
            prior = before.get(("duong_xet", p.id))
            if prior is not None:
                if n <= prior and p.id not in snapshot_path:
                    continue  # C2: ô CHỈ là ô hiện tại, không TĂNG
                entry.update(
                    o_hien_tai=True,
                    da_dung_truoc=prior,
                    cau=CURRENT_PATH_OVER_QUOTA_MESSAGE
                    % (
                        p.display_name or "#%d" % p.id,
                        p.ten_nganh or "học vụ #%s" % p.academic_info_id,
                        prior,
                        n,
                        p.admit_quota,
                        n - p.admit_quota,
                    ),
                )
            out.append(entry)
    if out:
        log.warning(
            "council_decision_vuot_chi_tieu",
            cell_count=len(out),
            o=[(x["loai"], x.get("academic_info_id") or x.get("admission_path_id")) for x in out],
        )
    return out
