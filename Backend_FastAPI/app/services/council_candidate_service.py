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
* KHÔNG lọc trạng thái, KHÔNG lọc trình độ: ai trong danh sách thì vào (danh sách do QĐ
  quyết); trình độ lạ do bộ dựng chặn.
* Lỗi đầu vào (mã rỗng, trùng, không khớp ĐÚNG MỘT hồ sơ) ⇒ ``DataValidationError`` nêu SỐ
  THỨ TỰ dòng, KHÔNG nêu giá trị. Lỗi CSDL ⇒ ``ServiceError`` không mang câu SQL / tham số
  (thông báo của trình điều khiển chứa danh sách mã). Không log mã, DTO ở bất kỳ mức nào.
"""
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import settings
from app.repositories.council_candidate_repository import (
    ThongTinGiaoDich,
    doc_so_lieu,
    giao_dich_chi_doc,
    phan_giai_ma,
)
from app.services.council_document_render_service import (
    CANDIDATE_FIELDS,
    CandidateRowV1,
)
from app.utils.exceptions import DataValidationError, ServiceError

# Độ dài tối đa của một mã đầu vào (CCCD 12 số; CMND cũ 9 số) — giới hạn KỸ THUẬT để chuỗi
# lạ không tới CSDL, không phải luật nghiệp vụ về định dạng CCCD.
DAI_MA_TOI_DA = 32
# Số dòng tối đa nêu trong một thông báo lỗi (phần còn lại chỉ đếm).
_NEU_TOI_DA = 20


@dataclass(frozen=True)
class AnhChupHoSo:
    rows: Tuple[CandidateRowV1, ...]
    don_vi: Tuple[Optional[int], ...]  # ``lead.unit_id`` từng hồ sơ, cùng thứ tự
    giao_dich: ThongTinGiaoDich


def _neu_dong(dong: Sequence[int]) -> str:
    s = ", ".join(str(x) for x in dong[:_NEU_TOI_DA])
    return s + (" … (tổng %d dòng)" % len(dong) if len(dong) > _NEU_TOI_DA else "")


def chuan_hoa_ma(ma: Sequence[str]) -> List[str]:
    """Bỏ khoảng trắng hai đầu từng mã; rỗng / trùng / có ký tự điều khiển / quá dài ⇒ lỗi
    nêu số thứ tự dòng (từ 1), không nêu giá trị."""
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
            hang = await doc_so_lieu(conn, [pid for _, _, pid in khop])
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
    return AnhChupHoSo(
        rows=tuple(_thanh_dto(h["stt"], h) for h in hang),
        don_vi=tuple(h["unit_id"] for h in hang),
        giao_dich=tt,
    )
