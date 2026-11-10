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

Dòng bộ THIẾU khoá đếm (cột NULL): không khớp nơi đếm cần khoá ấy (đặc tả 1.1). Không đường dựng bộ nào tạo
được dòng như vậy (cổng dữ liệu chặn dòng không có nguyện vọng in; nguyện vọng in đòi đủ chuỗi đường xét →
học vụ → ngành — ``council_candidate_repository.SQL_SO_LIEU``). Gặp dòng như vậy thì làm gì (chặn ghi nhận /
báo lỗi khi đếm / đếm vào mọi nơi) là CÂU HỎI OWNER (báo cáo lượt J) — :func:`so_dong_hieu_luc_thieu_khoa`
đếm để báo, mỗi lần đếm gặp thì ghi cảnh báo (không âm thầm).

Khoá: các hàm đếm KHÔNG khoá; nơi gọi giữ thứ tự khoá của mình (hồ sơ → ``offering_academic_info`` →
``admission_path``). Thao tác làm TĂNG Phần B (ghi nhận, điều chỉnh có thêm dòng, huỷ ghi nhận bật lại dòng)
gọi :func:`khoa_chi_tieu_cua_dong_bo` SAU khi khoá hồ sơ — cùng thứ tự ⇒ Phê duyệt cũ / công bố đang đếm
và ghi nhận tuần tự hoá trên cùng dòng chỉ tiêu (bổ sung đặc tả lượt J).
"""
from typing import Dict, Iterable, Optional, Sequence

import structlog
from sqlalchemy import Integer, String, cast, distinct, func, select, text, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.council_document import (
    DIEU_KIEN_DONG_HIEU_LUC,
    CouncilDecisionRow,
    CouncilDocumentSetRow,
)

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


# ═══════════════════════════════ khoá dòng chỉ tiêu cho thao tác làm tăng Phần B ════════════
async def khoa_chi_tieu_cua_dong_bo(db: AsyncSession, set_row_ids: Iterable[int]) -> None:
    """``FOR UPDATE`` các dòng chỉ tiêu mà các dòng bộ ``set_row_ids`` sẽ chiếm ở Phần B —
    ``offering_academic_info`` (theo ``academic_info_id`` chụp và theo cặp ``offering_id`` + năm chụp) rồi
    ``admission_path``, mỗi bảng id TĂNG DẦN trong một câu. Gọi SAU khi đã khoá hồ sơ (thứ tự chung: hồ sơ →
    học vụ → đường xét — như Phê duyệt cũ và công bố) ⇒ ghi nhận và lần đếm của Phê duyệt cũ / công bố tuần
    tự hoá: lần đếm thấy dòng mới, hoặc ghi nhận chờ lần duyệt commit."""
    ids = sorted({int(x) for x in set_row_ids if x is not None})
    if not ids:
        return
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
    if ai_ids:
        await db.execute(
            select(oai.id).where(oai.id.in_(sorted(ai_ids))).order_by(oai.id).with_for_update()
        )
    path_ids = sorted({k.admission_path_id for k in khoa if k.admission_path_id is not None})
    if path_ids:
        path = models.AdmissionPath
        await db.execute(
            select(path.id).where(path.id.in_(path_ids)).order_by(path.id).with_for_update()
        )
