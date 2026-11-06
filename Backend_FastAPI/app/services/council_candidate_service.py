# app/services/council_candidate_service.py
"""Hàm đọc hồ sơ cho bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.3 phần đọc).

Vào: danh sách MÃ HỒ SƠ (số CCCD — J1 dòng 8) đúng thứ tự admin đưa + NĂM HỌC tường minh
(CCCD chỉ duy nhất trong một năm học; thiếu năm ⇒ lỗi miền). Ra: ``CandidateRowV1``
đúng thứ tự đó + đơn vị từng hồ sơ + thông tin giao dịch đọc (mức cô lập, chỉ đọc, mốc chụp
— đo NGAY TRONG giao dịch).

* Đọc trong MỘT giao dịch ``REPEATABLE READ READ ONLY`` trên kết nối riêng
  (:func:`app.repositories.council_candidate_repository.giao_dich_chi_doc`) — không dùng giao
  dịch của request, không ghi gì; giao dịch này KẾT THÚC khi hàm trả về. Ghi bộ văn bản là
  giao dịch KHÁC, của request (F218).
* Mỗi trường DTO tính như cột cùng tên của truy vấn bộ xuất (luật v1) — SQL ở repository.
* KHÔNG lọc trạng thái, KHÔNG lọc trình độ ở tầng đọc: ảnh chụp giữ đúng bộ xuất; trình độ lạ
  do bộ dựng chặn. Cổng dựng bộ (lượt G — F228 trạng thái, F229 nguồn ngành / nguyện vọng /
  điểm, F231 khu vực) nằm ở ``council_set_gate_service``, chạy trên ``AnhChupHoSo.kiem`` —
  dữ liệu kiểm đọc trong CÙNG giao dịch chỉ đọc này.
* Lỗi đầu vào (mã rỗng, trùng, không khớp ĐÚNG MỘT hồ sơ) ⇒ ``DataValidationError`` nêu SỐ
  THỨ TỰ dòng, KHÔNG nêu giá trị. Lỗi CSDL ⇒ ``ServiceError`` không mang câu SQL / tham số
  (thông báo của trình điều khiển chứa danh sách mã). Không log mã, DTO ở bất kỳ mức nào.
"""
import json
import re
import unicodedata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.config import settings
from app.repositories.council_candidate_repository import (
    ThongTinGiaoDich,
    doc_kiem_nguon,
    doc_so_lieu,
    giao_dich_chi_doc,
    phan_giai_ma,
)
from app.services.council_document_render_service import (
    CANDIDATE_FIELDS,
    CandidateRowV1,
)
from app.services.council_set_gate_service import DuLieuKiem
from app.utils.exceptions import (
    DataValidationError,
    PriorityRateNotConfigured,
    ServiceError,
)

# Độ dài tối đa của một mã đầu vào (CCCD 12 số; CMND cũ 9 số) — giới hạn KỸ THUẬT để chuỗi
# lạ không tới CSDL; luật định dạng nghiệp vụ là ``_RE_DINH_DANG_MA`` dưới đây.
DAI_MA_TOI_DA = 32
# Định dạng mã hồ sơ (owner 04-11, ``Y-TUONG-…`` J1 dòng 28): ĐÚNG 12 chữ số (CCCD) HOẶC
# ĐÚNG 9 chữ số (CMND cũ), chỉ chữ số ASCII 0-9 — lớp ký tự viết tường minh, KHÔNG dùng
# ``\d`` (``\d`` của Python khớp cả chữ số toàn hình / Ả Rập-Ấn). Mã giữ NGUYÊN dạng chuỗi
# (số 0 đầu giữ nguyên), so CHÍNH XÁC với ``citizen_id`` kèm năm học; KHÔNG đệm 0 biến 9
# chữ số thành 12.
_RE_DINH_DANG_MA = re.compile(r"[0-9]{12}|[0-9]{9}")
# Số dòng tối đa nêu trong một thông báo lỗi (phần còn lại chỉ đếm).
_NEU_TOI_DA = 20


@dataclass(frozen=True)
class AnhChupHoSo:
    rows: Tuple[
        CandidateRowV1, ...
    ]  # = cột cùng tên của bộ xuất (``diem_kv`` theo luật cũ)
    don_vi: Tuple[Optional[int], ...]  # ``lead.unit_id`` từng hồ sơ, cùng thứ tự
    giao_dich: ThongTinGiaoDich
    # Dữ liệu cho cổng dựng bộ (lượt G) — cùng giao dịch, cùng thứ tự; KHÔNG ghi gì.
    kiem: Tuple[DuLieuKiem, ...] = ()


async def _kv_tinh_lai_lech(
    phien: AsyncSession, ho_so: object, snap: dict
) -> Optional[str]:
    """Câu 21 (owner 06-11 — "chặn và liệt kê"): mã lý do nếu KV TÍNH LẠI từ dữ liệu HIỆN TẠI
    của hồ sơ khác KV sẽ in (``kv_resolved`` của ảnh chụp), ``None`` nếu khớp.

    Tính bằng ĐÚNG resolver mà ``freeze_priority_snapshot`` gọi khi chụp (T1 nộp / T6 chấm) —
    ``priority_service.resolve_kv_for_profile`` (năm = năm học hồ sơ qua ``priority_academic_
    year`` bên trong nó; bảng KV xã / trường tra theo năm ấy) — với CÙNG ngữ cảnh trình độ /
    loại hình mà lần chụp đã dùng: ``freeze_priority_snapshot`` ghi ``target_level`` /
    ``admission_type`` vào ảnh chụp khi và chỉ khi chúng khác ``None`` ⇒ đọc lại từ ảnh chụp
    (vắng ⇒ ``None``) tái lập đúng lời gọi, chỉ dữ liệu hồ sơ / danh mục là của hiện tại. So MÃ
    KV (không so ``rule_applied``). Chỉ đọc: resolver chỉ SELECT; giao dịch là READ ONLY ở CSDL.
    Lỗi CSDL ⇒ để nổi lên (hàm gọi đổi thành ``ServiceError``); lỗi khác ⇒ chặn."""
    from app.services.priority_service import resolve_kv_for_profile

    try:
        kv_moi, _ = await resolve_kv_for_profile(
            ho_so,
            phien,
            target_level=snap.get("target_level"),
            admission_type=snap.get("admission_type"),
        )
    except DBAPIError:
        raise
    # Không tính lại được ⇒ không chứng minh được KV sẽ in còn đúng ⇒ chặn.
    except Exception:  # noqa: BLE001
        return "khu_vuc_khong_tinh_lai_duoc"
    if kv_moi != snap.get("kv_resolved"):
        return "khu_vuc_doi_sau_anh_chup"
    return None


async def _tra_khu_vuc(
    conn: AsyncConnection, hang_kiem: Sequence[dict]
) -> List[Tuple[Optional[str], Optional[str]]]:
    """F231 — ``(mã lý do chặn | None, mức điểm KV theo NĂM HỌC | None)`` từng dòng.

    Gọi ĐÚNG các helper app dùng khi tính điểm (``priority_service`` — không chép luật):
    ``kv_snapshot_resolved`` (vị từ "KV đã phân giải" của T1 / T6), ``verify_manual_override_
    provenance`` (ấn định thủ công còn hiệu lực — đúng hàm ``freeze_priority_snapshot`` gọi; chỉ
    ĐỌC sổ ``priority_audit_log``), ``priority_academic_year`` (năm = năm học của hồ sơ) và
    ``select_open_priority_rates`` (năm học + ``effective_to IS NULL``, không lọc ngày). KHÔNG
    gọi ``freeze_priority_snapshot`` (hàm GHI) — giao dịch này chỉ đọc. Câu 21: KV không ấn định
    thủ công được TÍNH LẠI chỉ đọc (:func:`_kv_tinh_lai_lech`) và so với KV sẽ in."""
    from app import models
    from app.services.priority_service import (
        RATE_TABLE_AREA,
        kv_snapshot_resolved,
        priority_academic_year,
        select_open_priority_rates,
        verify_manual_override_provenance,
    )

    muc_da_tra: Dict[Tuple[int, str], Tuple[Optional[str], Optional[str]]] = {}
    phien: Optional[AsyncSession] = None
    out: List[Tuple[Optional[str], Optional[str]]] = []
    try:
        for h in hang_kiem:
            snap = h.get("kv_snapshot")
            if isinstance(snap, str):
                snap = json.loads(snap)
            if not kv_snapshot_resolved(snap):
                out.append(("thieu_khu_vuc", None))
                continue
            if phien is None:
                # Phiên ORM trên CHÍNH kết nối đang ở giao dịch chỉ đọc (không mở giao dịch
                # mới, không commit / rollback giao dịch ngoài).
                phien = AsyncSession(bind=conn)
            ho_so = await phien.get(models.AdmissionProfile, h["pid"])
            if (
                h.get("area_resolution_basis") == "manual_override"
                or snap.get("rule_applied") == "manual_override"
            ):
                ok, _ly_do, _ = await verify_manual_override_provenance(phien, ho_so)
                if not ok:
                    out.append(("khu_vuc_thu_cong_khong_hieu_luc", None))
                    continue
            else:
                lech = await _kv_tinh_lai_lech(phien, ho_so, snap)
                if lech is not None:
                    out.append((lech, None))
                    continue
            nam = priority_academic_year(
                SimpleNamespace(academic_year=h.get("academic_year"), id=h.get("pid"))
            )
            kv = snap["kv_resolved"]
            khoa = (nam, kv)
            if khoa not in muc_da_tra:
                try:
                    muc = await select_open_priority_rates(
                        conn, table=RATE_TABLE_AREA, academic_year=nam, codes=[kv]
                    )
                    muc_da_tra[khoa] = (None, str(muc[kv]))
                except PriorityRateNotConfigured:
                    muc_da_tra[khoa] = ("chua_co_muc_khu_vuc", None)
                except RuntimeError:  # hơn một hàng ĐANG MỞ cùng mã, cùng năm
                    muc_da_tra[khoa] = ("muc_khu_vuc_khong_nhat_quan", None)
            out.append(muc_da_tra[khoa])
    finally:
        if phien is not None:
            await phien.close()
    return out


async def _luat_cong_diem_kv(
    conn: AsyncConnection, path_ids: Sequence[Optional[int]]
) -> List[Optional[str]]:
    """Câu 22 (owner 06-11 — "theo cấu hình đường xét"): luật cộng điểm KV của ĐƯỜNG XÉT của
    nguyện vọng in, từng dòng — ``cong`` / ``tat`` / ``khong_co_luat`` (``council_set_gate_
    service.LUAT_KV_*``), ``None`` khi không có đường xét / luật không đọc được.

    Đúng đường mã T6: nạp ``AdmissionPath`` kèm ``admission_method`` (như T6 nạp sẵn) trên phiên
    ORM của CHÍNH giao dịch chỉ đọc, ``resolve_effective_bonus_rule`` (override của đường xét, không
    thì mặc định của phương thức; JSON ``null`` qua ORM thành ``None`` ⇒ rơi về phương thức, như
    T6) rồi ``priority_service.area_bonus_enabled`` (hàm ``calculate_priority_bonus`` dùng). Không
    chép luật bằng SQL ở đây."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.admission_config.admission_path import AdmissionPath
    from app.services.admission_choice_engine_service import (
        resolve_effective_bonus_rule,
    )
    from app.services.council_set_gate_service import (
        LUAT_KV_CONG,
        LUAT_KV_KHONG_CO,
        LUAT_KV_TAT,
    )
    from app.services.priority_service import area_bonus_enabled

    ids = sorted({p for p in path_ids if isinstance(p, int)})
    duong: Dict[int, AdmissionPath] = {}
    phien = AsyncSession(bind=conn)
    try:
        if ids:
            kq = await phien.execute(
                select(AdmissionPath)
                .where(AdmissionPath.id.in_(ids))
                .options(selectinload(AdmissionPath.admission_method))
            )
            duong = {p.id: p for p in kq.scalars()}
        out: List[Optional[str]] = []
        for pid in path_ids:
            p = duong.get(pid) if isinstance(pid, int) else None
            if p is None:
                out.append(None)
                continue
            luat = resolve_effective_bonus_rule(p)
            try:
                bat = area_bonus_enabled(luat)
            # Luật không phải dict (dữ liệu lỗi) — T6 cũng hỏng ở đây ⇒ không xác định.
            except Exception:  # noqa: BLE001
                out.append(None)
                continue
            if bat:
                out.append(LUAT_KV_CONG)
            else:
                out.append(LUAT_KV_KHONG_CO if luat is None else LUAT_KV_TAT)
    finally:
        await phien.close()
    return out


def _neu_dong(dong: Sequence[int]) -> str:
    s = ", ".join(str(x) for x in dong[:_NEU_TOI_DA])
    return s + (" … (tổng %d dòng)" % len(dong) if len(dong) > _NEU_TOI_DA else "")


def chuan_hoa_ma(ma: Sequence[str]) -> List[str]:
    """MỘT nguồn kiểm danh sách mã hồ sơ. Bỏ khoảng trắng hai đầu từng mã; theo thứ tự: rỗng
    / quá dài / có ký tự nhóm C (kiểm kỹ thuật) → sai định dạng (không phải đúng 9 hoặc 12
    chữ số ASCII — J1 dòng 28) → trùng ⇒ lỗi nêu số thứ tự dòng (từ 1), KHÔNG nêu giá trị.
    """
    if not isinstance(ma, (list, tuple)):
        raise DataValidationError("Danh sách mã hồ sơ phải là một danh sách.")
    if not ma:
        raise DataValidationError("Danh sách mã hồ sơ rỗng.")
    out: List[str] = []
    gap: dict = {}
    for i, m in enumerate(ma, 1):
        if not isinstance(m, str):
            raise DataValidationError("Dòng %d: mã hồ sơ không phải chuỗi." % i)
        m = m.strip()
        if not m:
            raise DataValidationError("Dòng %d: mã hồ sơ rỗng." % i)
        if len(m) > DAI_MA_TOI_DA or any(unicodedata.category(c)[0] == "C" for c in m):
            raise DataValidationError(
                "Dòng %d: không phải mã hồ sơ (quá dài hoặc có ký tự điều khiển)." % i
            )
        if not _RE_DINH_DANG_MA.fullmatch(m):
            raise DataValidationError(
                "Dòng %d: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số "
                "(CMND), chỉ chữ số 0-9." % i
            )
        if m in gap:
            raise DataValidationError(
                "Dòng %d trùng mã hồ sơ với dòng %d — mỗi người một dòng." % (i, gap[m])
            )
        gap[m] = i
        out.append(m)
    return out


def _thanh_dto(stt: int, hang: dict) -> CandidateRowV1:
    gia_tri = {}
    for ten in CANDIDATE_FIELDS:
        v = hang.get(ten)
        if not isinstance(v, str):
            raise DataValidationError(
                "Dòng %d, trường %s: không đọc được dạng chữ." % (stt, ten)
            )
        gia_tri[ten] = v
    try:
        return CandidateRowV1(**gia_tri)
    except PydanticValidationError as e:
        truong = sorted(
            {
                str(loi["loc"][0]) if loi.get("loc") else "?"
                for loi in e.errors(include_url=False, include_input=False)
            }
        )
        raise DataValidationError(
            "Dòng %d: dữ liệu hồ sơ không hợp lệ ở trường %s."
            % (stt, ", ".join(truong))
        ) from None


def kiem_nam_hoc(academic_year: object) -> int:
    """Năm học TƯỜNG MINH của danh sách mã: CCCD chỉ duy nhất trong một năm học
    (``uq_citizen_academic_year``) ⇒ không có năm thì "mã hồ sơ" không xác định một hồ sơ.
    Không phải số nguyên (kể cả ``bool``) ⇒ ``DataValidationError``."""
    if isinstance(academic_year, bool) or not isinstance(academic_year, int):
        raise DataValidationError(
            "Thiếu năm học (academic_year) hoặc năm học không phải số nguyên — mã hồ sơ "
            "(CCCD) chỉ duy nhất trong một năm học."
        )
    return academic_year


async def doc_ho_so_theo_ma(
    engine: AsyncEngine,
    ma_ho_so: Sequence[str],
    *,
    academic_year: Optional[int],
    toi_da: Optional[int] = None,
) -> AnhChupHoSo:
    """Đọc DTO của các hồ sơ có mã ``ma_ho_so`` (đúng thứ tự) THUỘC năm học
    ``academic_year`` trong MỘT giao dịch chỉ đọc."""
    nam = kiem_nam_hoc(academic_year)
    ds = chuan_hoa_ma(ma_ho_so)
    gioi_han = settings.COUNCIL_SET_MAX_PROFILES if toi_da is None else toi_da
    if len(ds) > gioi_han:
        raise DataValidationError(
            "Danh sách có %d mã, vượt giới hạn kỹ thuật %d hồ sơ cho một bộ văn bản."
            % (len(ds), gioi_han)
        )
    try:
        async with giao_dich_chi_doc(engine) as (conn, tt):
            khop = await phan_giai_ma(conn, ds, nam)
            khong = [stt for stt, so, _ in khop if so == 0]
            nhieu = [stt for stt, so, _ in khop if so > 1]
            if khong or nhieu:
                phan = []
                if khong:
                    phan.append(
                        "dòng %s không có hồ sơ nào mang mã này trong năm học đã chọn"
                        % _neu_dong(khong)
                    )
                if nhieu:
                    phan.append("dòng %s khớp NHIỀU hồ sơ cùng mã" % _neu_dong(nhieu))
                raise DataValidationError(
                    "Mã hồ sơ phải khớp đúng một hồ sơ: %s." % "; ".join(phan)
                )
            if [stt for stt, _, _ in khop] != list(range(1, len(ds) + 1)):
                raise ServiceError("Phân giải mã hồ sơ trả sai thứ tự — không đọc.")
            pids = [pid for _, _, pid in khop]
            hang = await doc_so_lieu(conn, pids)
            # Cổng dựng bộ (lượt G): dữ liệu kiểm đọc trong CÙNG giao dịch chỉ đọc, theo đúng
            # nguyện vọng mà truy vấn số liệu in (cột phụ ``nv_in_id``).
            nv_in = {h["stt"]: h.get("nv_in_id") for h in hang}
            hang_kiem = await doc_kiem_nguon(
                conn, pids, [nv_in.get(i) for i in range(1, len(pids) + 1)]
            )
            khu_vuc = await _tra_khu_vuc(conn, hang_kiem)
            # Câu 22: luật cộng điểm KV của đường xét của nguyện vọng in — cùng giao dịch.
            luat_kv = await _luat_cong_diem_kv(
                conn, [h.get("nv_in_path_id") for h in hang_kiem]
            )
    except DBAPIError:
        # Thông báo của trình điều khiển có câu SQL + tham số (danh sách mã) ⇒ không giữ.
        raise ServiceError("Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.") from None

    # Mỗi hồ sơ đúng MỘT hàng: bảng tham chiếu (địa giới, khu vực) khớp nhiều hàng hiện
    # hành thì bộ xuất in TRÙNG người ⇒ dừng, không tự chọn một hàng.
    dem: dict = {}
    for h in hang:
        dem[h["stt"]] = dem.get(h["stt"], 0) + 1
    du = sorted(stt for stt, n in dem.items() if n > 1)
    if du:
        raise DataValidationError(
            "Dòng %s: dữ liệu tham chiếu (địa giới / khu vực) khớp nhiều hàng hiện hành "
            "— không dựng." % _neu_dong(du)
        )
    if sorted(dem) != list(range(1, len(ds) + 1)):
        raise ServiceError("Đọc số liệu hồ sơ thiếu hàng — không dựng.")
    hang.sort(key=lambda h: h["stt"])
    if (
        [h["stt"] for h in hang_kiem] != list(range(1, len(ds) + 1))
        or len(khu_vuc) != len(ds)
        or len(luat_kv) != len(ds)
    ):
        raise ServiceError(
            "Đọc dữ liệu kiểm hồ sơ sai thứ tự / thiếu hàng — không dựng."
        )
    so_lieu = {h["stt"]: h for h in hang}
    kiem = tuple(
        DuLieuKiem(
            stt=k["stt"],
            status=k["status"],
            uses_choice_engine=k["uses_choice_engine"],
            so_nv=k["so_nv"],
            nv1_id=k["nv1_id"],
            nv_in_id=so_lieu[k["stt"]].get("nv_in_id"),
            so_nv_trung=k["so_nv_trung"],
            nv_trung_id=k["nv_trung_id"],
            hp_co=bool(so_lieu[k["stt"]].get("hp_co")),
            hp_nganh_id=so_lieu[k["stt"]].get("hp_nganh_id"),
            nv_in_nganh_id=k["nv_in_nganh_id"],
            nv_in_path_id=k["nv_in_path_id"],
            nv_in_sg_id=k["nv_in_sg_id"],
            lg_nganh_id=k["lg_nganh_id"],
            lg_path_id=k["lg_path_id"],
            lg_sg_id=k["lg_sg_id"],
            diem_ca_hai_khac=k["diem_ca_hai_khac"],
            diem_chi_nv=k["diem_chi_nv"],
            diem_chi_hs=k["diem_chi_hs"],
            kv_ly_do=kv[0],
            kv_muc=kv[1],
            luat_kv=lk,
        )
        for k, kv, lk in zip(hang_kiem, khu_vuc, luat_kv)
    )
    return AnhChupHoSo(
        rows=tuple(_thanh_dto(h["stt"], h) for h in hang),
        don_vi=tuple(h["unit_id"] for h in hang),
        giao_dich=tt,
        kiem=kiem,
    )
