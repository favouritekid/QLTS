# app/services/quota_occupancy_service.py
"""MỘT nguồn cho câu hỏi "đã dùng bao nhiêu chỗ chỉ tiêu" (F230 chặng 2b — đặc tả
``ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` mục 5.4; thiết kế bổ sung §4.7 câu hỏi 2; owner J1 dòng 5).

Module NHẸ: chỉ model + SQLAlchemy, KHÔNG import ``admission_service`` (vòng import là lý do bộ máy nguyện
vọng từng chép tay tập trạng thái chiếm chỗ). ``admission_service``, ``admission_choice_engine_service``,
``quota_matrix_service`` đều đếm qua đây; tập trạng thái chiếm chỗ ĐỊNH NGHĨA MỘT LẦN ở đây
(:data:`TRANG_THAI_CHIEM_CHO`; nơi khác trỏ vào CÙNG đối tượng — kiểm kê AST trong
``tests/integration/test_quota_occupancy_db.py``).

Số chỗ đã dùng ở MỘT nơi đếm = **Phần A** + **Phần B**:

* **Phần A** — hồ sơ ở trạng thái chiếm chỗ, đếm ĐÚNG cách hiện có của nơi gọi, CHỈ hồ sơ KHÔNG có dòng
  Quyết định còn hiệu lực (:func:`khong_co_dong_hieu_luc`).
* **Phần B** — dòng Quyết định còn hiệu lực (``DIEU_KIEN_DONG_HIEU_LUC`` — một chuỗi với U3) nối DÒNG BỘ
  nguồn (``set_row_id``), đếm theo KHOÁ ĐẾM CHỤP ở dòng bộ (đường xét / thông tin học vụ / ngành + năm học
  của nguyện vọng in lúc dựng bộ) — KHÔNG theo giá trị hiện tại của hồ sơ (ảnh chụp thắng — J1 dòng 6). Hồ
  sơ đã ``withdrawn`` (rút hẳn) trả chỗ (C3); ``withdrawal_pending`` VẪN đếm (J1 dòng 5: chờ hoàn vẫn giữ
  chỗ). Trạng thái hồ sơ ở Phần B không cần thuộc tập chiếm chỗ (em có Quyết định ở "Đã nộp" vẫn giữ chỗ).

Mỗi hồ sơ đếm ĐÚNG MỘT lần: có dòng hiệu lực ⇒ chỉ ở B; không ⇒ chỉ ở A (U3: ≤ 1 dòng hiệu lực / hồ sơ;
Phần B vẫn ``count(DISTINCT profile_id)``). ``exclude_profile_id`` loại ở CẢ HAI phần; lọc năm: Phần A theo
``admission_profile.academic_year`` (như hôm nay), Phần B theo ``council_document_set_row.academic_year`` —
năm học của bộ, CHÍNH là năm học của hồ sơ lúc dựng (bộ chỉ nhận hồ sơ của năm học đã chọn —
``council_candidate_repository.SQL_PHAN_GIAI_MA``).

MỘT ẢNH CHỤP (F260 — Codex lần 15): mỗi hàm đếm tính Phần A + Phần B trong MỘT câu SQL (:func:`_tong`, hợp
``UNION ALL`` ở ma trận). READ COMMITTED chụp ảnh theo TỪNG CÂU ⇒ hai câu riêng cho A và B để một thao tác
chuyển hồ sơ A↔B (huỷ hiệu lực / huỷ ghi nhận / điều chỉnh bỏ dòng — KHÔNG khoá dòng chỉ tiêu; ghi nhận ở
ma trận không khoá) commit chen giữa ⇒ đếm 0 (B→A) hoặc 2 (A→B) cho cùng một em. Một câu ⇒ em đếm đúng một lần.

Dòng bộ THIẾU khoá đếm / lệch chuỗi cấu hình: owner chốt 10-11 (Q-J1) — CHẶN tại ba thao tác sinh / khôi phục
dòng B (ghi nhận, dòng thêm khi điều chỉnh, dòng bật lại khi huỷ ghi nhận) bằng MỘT hàm
(:func:`kiem_khoa_dem_dong_bo`, 409 nêu số dòng). Bộ đếm vẫn giữ lớp phụ: dòng như vậy (chỉ có khi sửa tay
CSDL) không khớp nơi cần khoá ấy và mỗi lần đếm gặp thì ghi cảnh báo log (:func:`_bao_thieu_khoa`).

Khoá — THỨ TỰ CHUẨN cho cả giao dịch (F259): mọi hồ sơ (id tăng dần) TRƯỚC, rồi mọi dòng chỉ tiêu qua
:func:`khoa_o_chi_tieu` (``offering_academic_info`` id tăng dần MỘT câu, RỒI ``admission_path`` id tăng dần
MỘT câu). Các hàm đếm KHÔNG khoá. Ghi nhận / điều chỉnh thêm dòng / huỷ ghi nhận bật lại (làm TĂNG Phần B) khoá
qua :func:`khoa_chi_tieu_cua_dong_bo`; Phê duyệt hàng loạt và công bố nhiều nguyện vọng khoá TRƯỚC mọi dòng chỉ
tiêu sẽ dùng (cùng hàm) rồi mới xét — giữ nguyên thứ tự xét nguyện vọng nghiệp vụ.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import structlog
from sqlalchemy import Integer, String, cast, distinct, func, select, text, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.council_document import (
    DIEU_KIEN_DONG_HIEU_LUC,
    CouncilDecisionRow,
    CouncilDocumentSetRow,
)
from app.utils.exceptions import ConflictError

log = structlog.get_logger(__name__)

#: Trạng thái hồ sơ CHIẾM một chỗ chỉ tiêu (Phần A) — ĐỊNH NGHĨA DUY NHẤT. ``withdrawn`` và các trạng thái
#: trước duyệt không chiếm chỗ. ``enrolled`` có ``is_dropped`` VẪN chiếm (chỗ đã dùng của năm học không cấp
#: lại). ``admitted``: bộ máy nguyện vọng (#15/#16).
TRANG_THAI_CHIEM_CHO: tuple = (
    "approved",
    "overridden",
    "admitted",
    "confirmed",
    "enrolled",
)
#: Phần B: hồ sơ ở trạng thái này TRẢ chỗ (rút hẳn — C3). ``withdrawal_pending`` KHÔNG trả (J1 dòng 5).
TRANG_THAI_TRA_CHO = "withdrawn"

#: F259: PostgreSQL huỷ ĐÚNG MỘT giao dịch của vòng chờ khoá (``deadlock_detected``). Nơi bị chọn huỷ trả câu
#: cố định dưới đây (409 / lỗi của mục hàng loạt) — MỘT chuỗi cho ghi nhận, Phê duyệt hàng loạt, công bố.
SQLSTATE_DEADLOCK = "40P01"
THONG_DIEP_XUNG_DOT = "Xung đột với thao tác khác cùng lúc — thử lại."


# ═══════════════════════════════ hai phần ══════════════════════════════════════════════════
def khong_co_dong_hieu_luc(profile_id_cot):
    """Điều kiện Phần A: hồ sơ (cột id ở câu ngoài) KHÔNG có dòng Quyết định còn hiệu lực. Câu con
    ``FROM council_decision_row`` ⇒ tên cột của ``DIEU_KIEN_DONG_HIEU_LUC`` (không bí danh) thuộc bảng ấy."""
    return ~(
        select(CouncilDecisionRow.id)
        .where(
            CouncilDecisionRow.profile_id == profile_id_cot,
            text(DIEU_KIEN_DONG_HIEU_LUC),
        )
        .exists()
    )


def _dong_hieu_luc():
    """Dòng Quyết định còn hiệu lực — câu con riêng (biểu thức một nguồn, cột không bí danh)."""
    return (
        select(CouncilDecisionRow.profile_id, CouncilDecisionRow.set_row_id)
        .where(text(DIEU_KIEN_DONG_HIEU_LUC))
        .subquery("dong_hl")
    )


def _phan_b(cot_nhom, *dieu_kien, exclude_profile_id: Optional[int] = None):
    """Phần B: ``count(DISTINCT hồ sơ)`` của dòng hiệu lực nối dòng bộ nguồn (khoá CHỤP), hồ sơ chưa trả
    chỗ. ``cot_nhom`` (cột của dòng bộ) ⇒ đếm theo nhóm; ``None`` ⇒ một số."""
    d = _dong_hieu_luc()
    b = CouncilDocumentSetRow
    p = models.AdmissionProfile
    dem = func.count(distinct(d.c.profile_id))
    q = (
        select(dem) if cot_nhom is None else select(cot_nhom, dem)
    ).select_from(d).join(b, b.id == d.c.set_row_id).join(p, p.id == d.c.profile_id).where(
        p.status != TRANG_THAI_TRA_CHO, *dieu_kien
    )
    if exclude_profile_id is not None:
        q = q.where(d.c.profile_id != exclude_profile_id)
    if cot_nhom is not None:
        q = q.group_by(cot_nhom)
    return q


async def _so(db: AsyncSession, cau) -> int:
    return int((await db.execute(cau)).scalar_one() or 0)


async def _tong(db: AsyncSession, *phan) -> int:
    """F260: cộng các phần đếm (mỗi phần một ``select count``) trong MỘT câu SQL ⇒ MỘT ảnh chụp READ
    COMMITTED cho cả A và B (câu con vô hướng dùng chung ảnh chụp của câu ngoài)."""
    tong = None
    for c in phan:
        s = func.coalesce(c.scalar_subquery(), 0)
        tong = s if tong is None else tong + s
    return int((await db.execute(select(tong))).scalar_one() or 0)


async def so_dong_hieu_luc_thieu_khoa(db: AsyncSession, cot) -> int:
    """Số dòng Quyết định còn hiệu lực (hồ sơ chưa trả chỗ) mà dòng bộ THIẾU khoá ``cot`` (NULL) — để báo,
    không suy (đặc tả 1.1; câu hỏi owner lượt J)."""
    return await _so(db, _phan_b(None, cot.is_(None)))


async def _bao_thieu_khoa(db: AsyncSession, cot, noi: str) -> None:
    n = await so_dong_hieu_luc_thieu_khoa(db, cot)
    if n:
        log.warning("quota_phan_b_dong_thieu_khoa_dem", noi=noi, khoa=cot.key, so_dong=n)


# ═══════════════════════════════ bốn nơi đếm ═══════════════════════════════════════════════
async def dem_theo_nganh_nam(
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
            ap.status.in_(TRANG_THAI_CHIEM_CHO),
            khong_co_dong_hieu_luc(ap.id),
        )
    )
    if exclude_profile_id is not None:
        a = a.where(ap.id != exclude_profile_id)
    b = _phan_b(
        None,
        CouncilDocumentSetRow.offering_id == offering_id,
        CouncilDocumentSetRow.academic_year == academic_year,
        exclude_profile_id=exclude_profile_id,
    )
    n = await _tong(db, a, b)
    await _bao_thieu_khoa(db, CouncilDocumentSetRow.offering_id, "nganh_nam")
    return n


def _a_nhieu_nv(*dieu_kien, exclude_profile_id: Optional[int]):
    """Phần A — nguyện vọng ``admitted`` của hồ sơ chiếm chỗ (bộ máy nguyện vọng), đếm dòng nguyện vọng như
    ``check_choice_admit_capacity`` hôm nay."""
    ap = models.AdmissionProfile
    c = models.AdmissionProfileChoice
    q = (
        select(func.count(c.id))
        .join(ap, ap.id == c.admission_profile_id)
        .where(
            c.decision == "admitted",
            ap.status.in_(TRANG_THAI_CHIEM_CHO),
            khong_co_dong_hieu_luc(ap.id),
            *dieu_kien,
        )
    )
    if exclude_profile_id is not None:
        q = q.where(ap.id != exclude_profile_id)
    return q


def _a_kieu_cu(dieu_kien_duong_xet, exclude_profile_id: Optional[int]):
    """Phần A — hồ sơ một nguyện vọng kiểu cũ (``uses_choice_engine`` = FALSE) theo
    ``applied_rules->>'admission_path_id'`` (ép kiểu như hôm nay)."""
    ap = models.AdmissionProfile
    q = select(func.count(ap.id)).where(
        ap.uses_choice_engine.is_(False),
        ap.status.in_(TRANG_THAI_CHIEM_CHO),
        khong_co_dong_hieu_luc(ap.id),
        dieu_kien_duong_xet(ap.applied_rules["admission_path_id"].astext.cast(Integer)),
    )
    if exclude_profile_id is not None:
        q = q.where(ap.id != exclude_profile_id)
    return q


async def dem_theo_thong_tin_hoc_vu(
    db: AsyncSession, *, academic_info_id: int, exclude_profile_id: Optional[int] = None
) -> int:
    """Công bố — mức năm (``check_choice_admit_capacity`` Tier 1): Phần A = nguyện vọng trúng trên đường xét
    thuộc ``academic_info_id`` + hồ sơ kiểu cũ có đường xét thuộc nó; Phần B = dòng bộ ``academic_info_id``
    CHỤP."""
    path = models.AdmissionPath
    a1 = _a_nhieu_nv(
        path.academic_info_id == academic_info_id, exclude_profile_id=exclude_profile_id
    ).join(path, path.id == models.AdmissionProfileChoice.admission_path_id)
    a2 = _a_kieu_cu(
        lambda cot: cot.in_(select(path.id).where(path.academic_info_id == academic_info_id)),
        exclude_profile_id,
    )
    b = _phan_b(
        None,
        CouncilDocumentSetRow.academic_info_id == academic_info_id,
        exclude_profile_id=exclude_profile_id,
    )
    n = await _tong(db, a1, a2, b)
    await _bao_thieu_khoa(db, CouncilDocumentSetRow.academic_info_id, "thong_tin_hoc_vu")
    return n


async def dem_theo_duong_xet(
    db: AsyncSession, *, admission_path_id: int, exclude_profile_id: Optional[int] = None
) -> int:
    """Công bố — mức đường xét (``check_choice_admit_capacity`` Tier 2): Phần A = nguyện vọng trúng trên
    đường xét + hồ sơ kiểu cũ trỏ đường xét; Phần B = dòng bộ ``admission_path_id`` CHỤP."""
    a1 = _a_nhieu_nv(
        models.AdmissionProfileChoice.admission_path_id == admission_path_id,
        exclude_profile_id=exclude_profile_id,
    )
    a2 = _a_kieu_cu(lambda cot: cot == admission_path_id, exclude_profile_id)
    b = _phan_b(
        None,
        CouncilDocumentSetRow.admission_path_id == admission_path_id,
        exclude_profile_id=exclude_profile_id,
    )
    n = await _tong(db, a1, a2, b)
    await _bao_thieu_khoa(db, CouncilDocumentSetRow.admission_path_id, "duong_xet")
    return n


async def dem_da_trung_tuyen_theo_duong_xet(
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
    ds = list(out)
    # Khoá nhóm của ba nhánh ở DẠNG CHỮ (M2 so ``applied_rules`` dạng chữ, không ép kiểu — như cũ) để hợp
    # được trong MỘT câu ``UNION ALL`` (F260: một ảnh chụp cho A và B).
    m1 = (
        select(
            cast(c.admission_path_id, String),
            func.count(distinct(c.admission_profile_id)),
        )
        .join(ap, ap.id == c.admission_profile_id)
        .where(
            c.admission_path_id.in_(ds),
            c.decision == "admitted",
            ap.status.in_(TRANG_THAI_CHIEM_CHO),
            khong_co_dong_hieu_luc(ap.id),
        )
        .group_by(c.admission_path_id)
    )
    chu = ap.applied_rules["admission_path_id"].astext
    m2 = (
        select(chu, func.count(ap.id))
        .where(
            ap.uses_choice_engine.is_(False),
            chu.in_([str(p) for p in ds]),
            ap.status.in_(TRANG_THAI_CHIEM_CHO),
            khong_co_dong_hieu_luc(ap.id),
        )
        .group_by(chu)
    )
    b = _phan_b(
        cast(CouncilDocumentSetRow.admission_path_id, String),
        CouncilDocumentSetRow.admission_path_id.in_(ds),
    )
    for chu_id, n in (await db.execute(union_all(m1, m2, b))).all():
        try:
            pid = int(chu_id)
        except (TypeError, ValueError):
            continue
        if pid in out:
            out[pid] += int(n or 0)
    await _bao_thieu_khoa(db, CouncilDocumentSetRow.admission_path_id, "ma_tran")
    return out


# ═══════════════════════════════ "đã chiếm chỗ chưa" ═══════════════════════════════════════
async def co_dong_hieu_luc(db: AsyncSession, profile_id: int) -> bool:
    return bool(
        (
            await db.execute(
                select(
                    select(CouncilDecisionRow.id)
                    .where(
                        CouncilDecisionRow.profile_id == profile_id,
                        text(DIEU_KIEN_DONG_HIEU_LUC),
                    )
                    .exists()
                )
            )
        ).scalar()
    )


async def dang_chiem_cho(db: AsyncSession, profile) -> bool:
    """``is_already_occupying`` của Phê duyệt cũ: trạng thái chiếm chỗ HOẶC có dòng Quyết định hiệu lực (em
    đã được đếm ở Phần B — duyệt kiểu cũ cho em ấy không cộng thêm chỗ — đặc tả 5.4)."""
    if profile.status in TRANG_THAI_CHIEM_CHO:
        return True
    return await co_dong_hieu_luc(db, profile.id)


# ═══════════════════════════════ THỨ TỰ KHOÁ CHUẨN của dòng chỉ tiêu (F259) ═════════════════
async def khoa_o_chi_tieu(
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
    duong = sorted({int(x) for x in path_ids if x is not None})
    if duong:
        t = models.AdmissionPath
        await db.execute(select(t.id).where(t.id.in_(duong)).order_by(t.id).with_for_update())


async def o_chi_tieu_cua_dong_bo(
    db: AsyncSession, set_row_ids: Iterable[Optional[int]]
) -> Tuple[Set[int], Set[int]]:
    """(id ``offering_academic_info``, id ``admission_path``) mà các dòng bộ chiếm ở Phần B — học vụ theo
    ``academic_info_id`` CHỤP và theo cặp ``offering_id`` + năm CHỤP (phủ cả hai cách Phê duyệt cũ chọn dòng),
    đường xét theo ``admission_path_id`` CHỤP. MỘT nguồn cho khoá (:func:`khoa_chi_tieu_cua_dong_bo`) và cảnh
    báo vượt chỉ tiêu (:func:`canh_bao_vuot_chi_tieu`)."""
    ids = sorted({int(x) for x in set_row_ids if x is not None})
    if not ids:
        return set(), set()
    b = CouncilDocumentSetRow
    khoa = (
        await db.execute(
            select(b.academic_info_id, b.offering_id, b.academic_year, b.admission_path_id)
            .where(b.id.in_(ids))
            .distinct()
        )
    ).all()
    oai = models.OfferingAcademicInfo
    ai_ids = {k.academic_info_id for k in khoa if k.academic_info_id is not None}
    cap = sorted(
        {(k.offering_id, k.academic_year) for k in khoa if k.offering_id is not None}
    )
    if cap:
        ai_ids |= set(
            (
                await db.execute(
                    select(oai.id).where(tuple_(oai.offering_id, oai.academic_year).in_(cap))
                )
            ).scalars()
        )
    return ai_ids, {k.admission_path_id for k in khoa if k.admission_path_id is not None}


async def khoa_chi_tieu_cua_dong_bo(db: AsyncSession, set_row_ids: Iterable[int]) -> None:
    """``FOR UPDATE`` các dòng chỉ tiêu mà các dòng bộ ``set_row_ids`` sẽ chiếm ở Phần B — qua THỨ TỰ CHUẨN
    (:func:`khoa_o_chi_tieu`). Gọi SAU khi đã khoá hồ sơ ⇒ ghi nhận và lần đếm của Phê duyệt cũ / công bố
    tuần tự hoá: lần đếm thấy dòng mới, hoặc ghi nhận chờ lần duyệt commit."""
    ai_ids, path_ids = await o_chi_tieu_cua_dong_bo(db, set_row_ids)
    await khoa_o_chi_tieu(db, ai_ids, path_ids)


# ═══════════════════════════════ Q-J1 — khoá đếm của dòng bộ (owner 10-11) ════════════════════
#: Khoá đếm có thể NULL ở dòng bộ mà các hàm đếm thực dùng (``academic_year`` NOT NULL ở CSDL;
#: ``major_id`` không hàm đếm nào dùng ⇒ không kiểm).
KHOA_DEM_CO_THE_THIEU = ("admission_path_id", "academic_info_id", "offering_id")


async def kiem_khoa_dem_dong_bo(
    db: AsyncSession, dong: Sequence[Tuple[int, Optional[int]]]
) -> None:
    """Q-J1 (owner chốt 10-11): MỘT hàm kiểm cho ba thao tác sinh / khôi phục dòng Phần B — ghi nhận, dòng
    THÊM khi điều chỉnh, dòng BẬT LẠI khi huỷ ghi nhận. Gọi DƯỚI khoá (sau :func:`khoa_chi_tieu_cua_dong_bo`),
    TRƯỚC khi ghi. ``dong`` = [(số dòng, id dòng bộ nguồn)].

    Chặn (409, nêu SỐ DÒNG — không tên, không CCCD) khi một dòng:

    * không có dòng bộ nguồn (``thieu_dong_nguon``);
    * thiếu khoá đếm mà hàm đếm thực dùng (``thieu_khoa``: đường xét / học vụ / ngành);
    * khoá không khớp chuỗi cấu hình (``lech_chuoi_cau_hinh``): đường xét không còn / không thuộc học vụ chụp;
      học vụ không còn / không thuộc ngành + năm chụp — khi ấy các hàm đếm đặt em vào các ô KHÁC nhau.

    Owner KHÔNG chọn: 503 toàn hệ, đếm dòng ấy vào mọi ô, chỉ log. Cảnh báo log ở bộ đếm
    (:func:`_bao_thieu_khoa`) giữ làm lớp phụ."""
    b = CouncilDocumentSetRow
    ids = sorted({int(sid) for _, sid in dong if sid is not None})
    nguon = {}
    if ids:
        nguon = {
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
    ai_ids = sorted({r.academic_info_id for r in nguon.values() if r.academic_info_id is not None})
    path_ids = sorted({r.admission_path_id for r in nguon.values() if r.admission_path_id is not None})
    hoc_vu = {}
    if ai_ids:
        hoc_vu = {
            r.id: (r.offering_id, r.academic_year)
            for r in (
                await db.execute(
                    select(t_oai.id, t_oai.offering_id, t_oai.academic_year).where(t_oai.id.in_(ai_ids))
                )
            ).all()
        }
    duong_xet = {}
    if path_ids:
        duong_xet = {
            r.id: r.academic_info_id
            for r in (
                await db.execute(
                    select(t_path.id, t_path.academic_info_id).where(t_path.id.in_(path_ids))
                )
            ).all()
        }
    loi: List[Dict[str, Any]] = []
    for stt, sid in sorted(dong, key=lambda x: (x[0], x[1] or 0)):
        r = nguon.get(sid) if sid is not None else None
        if r is None:
            loi.append({"dong": stt, "ly_do": "thieu_dong_nguon"})
            continue
        thieu = [k for k in KHOA_DEM_CO_THE_THIEU if getattr(r, k) is None]
        if thieu:
            loi.append({"dong": stt, "ly_do": "thieu_khoa", "khoa": thieu})
            continue
        if (
            duong_xet.get(r.admission_path_id) != r.academic_info_id
            or hoc_vu.get(r.academic_info_id) != (r.offering_id, r.academic_year)
        ):
            loi.append({"dong": stt, "ly_do": "lech_chuoi_cau_hinh"})
    if loi:
        raise ConflictError(
            "Dòng %s: dòng bộ thiếu khoá đếm chỉ tiêu hoặc lệch chuỗi cấu hình (đường xét → học vụ → "
            "ngành + năm) — không ghi được; dựng lại bộ cho đúng." % ", ".join(str(x["dong"]) for x in loi),
            public_payload={"dong_thieu_khoa_dem": loi},
        )


# ═══════════════════════════════ N9 — cảnh báo vượt chỉ tiêu (không chặn) ═══════════════════
async def canh_bao_vuot_chi_tieu(
    db: AsyncSession, set_row_ids: Iterable[Optional[int]]
) -> List[Dict[str, Any]]:
    """N9 (đặc tả 5.3): sau khi ghi (cùng giao dịch, dưới khoá dòng chỉ tiêu), các ô chỉ tiêu mà dòng bộ
    chiếm (:func:`o_chi_tieu_cua_dong_bo` — cùng nguồn với khoá) bị VƯỢT thì trả cảnh báo; KHÔNG chặn.

    "Vượt" = số đã dùng > chỉ tiêu — ĐÚNG nghĩa sẵn có của phần mềm (Phê duyệt cũ / công bố chặn khi
    ``đã dùng + 1 > chỉ tiêu`` ⇒ bằng chỉ tiêu là ĐẦY, chưa vượt). Chỉ tiêu NULL = không giới hạn ⇒ không xét.
    Số đã dùng đếm qua ĐÚNG các hàm đếm của module (một nguồn): ô ngành (học vụ, chỉ tiêu năm) có HAI cách
    đếm đang dùng — công bố (:func:`dem_theo_thong_tin_hoc_vu`) và Phê duyệt cũ (:func:`dem_theo_nganh_nam`)
    — trả cả hai, vượt ở cách nào cũng báo; ô đường xét theo :func:`dem_theo_duong_xet`. Chỉ id + số đếm."""
    ai_ids, path_ids = await o_chi_tieu_cua_dong_bo(db, set_row_ids)
    out: List[Dict[str, Any]] = []
    t_oai, t_path = models.OfferingAcademicInfo, models.AdmissionPath
    if ai_ids:
        for o in (
            await db.execute(
                select(t_oai.id, t_oai.offering_id, t_oai.academic_year, t_oai.annual_admission_quota)
                .where(t_oai.id.in_(sorted(ai_ids)))
                .order_by(t_oai.id)
            )
        ).all():
            if o.annual_admission_quota is None:
                continue
            cong_bo = await dem_theo_thong_tin_hoc_vu(db, academic_info_id=o.id)
            phe_duyet = await dem_theo_nganh_nam(
                db, offering_id=o.offering_id, academic_year=o.academic_year
            )
            if max(cong_bo, phe_duyet) > o.annual_admission_quota:
                out.append(
                    {
                        "loai": "nganh",
                        "academic_info_id": o.id,
                        "chi_tieu": o.annual_admission_quota,
                        "da_dung_cong_bo": cong_bo,
                        "da_dung_phe_duyet_cu": phe_duyet,
                    }
                )
    if path_ids:
        for p in (
            await db.execute(
                select(t_path.id, t_path.admit_quota)
                .where(t_path.id.in_(sorted(path_ids)))
                .order_by(t_path.id)
            )
        ).all():
            if p.admit_quota is None:
                continue
            n = await dem_theo_duong_xet(db, admission_path_id=p.id)
            if n > p.admit_quota:
                out.append(
                    {
                        "loai": "duong_xet",
                        "admission_path_id": p.id,
                        "chi_tieu": p.admit_quota,
                        "da_dung": n,
                    }
                )
    if out:
        log.warning(
            "council_decision_vuot_chi_tieu",
            so_o=len(out),
            o=[(x["loai"], x.get("academic_info_id") or x.get("admission_path_id")) for x in out],
        )
    return out
