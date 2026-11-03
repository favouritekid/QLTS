# app/services/council_document_template_service.py
"""Kho mẫu văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.2) — service thuần.

* **Tải mẫu lên** = bytes + loại + ngày hiệu lực. Trước khi lưu, theo thứ tự: giới hạn kích
  thước tệp → đọc gói zip bằng ``zipfile`` (số mục, tổng kích thước giải nén khai báo, rồi
  ĐỌC THẬT từng mục theo khúc với trần tổng — tiêu đề zip nói dối thì vẫn dừng đúng trần,
  CRC sai thì dừng) → CHỈ KHI đó mới đưa cho python-docx qua
  :func:`council_document_render_service.kiem_mau` — ĐÚNG phép kiểm cấu trúc bộ dựng chạy
  trước khi dựng (một nguồn: dòng mẫu, dòng tổng, vùng dữ liệu F207, khối ngành…). Hỏng ở
  đâu ⇒ lỗi miền, KHÔNG lưu.
* **Chọn mẫu cho một bộ**: mỗi loại lấy mẫu có ``hieu_luc_tu`` lớn nhất ≤ ngày ký (J1 dòng
  7); thiếu một loại ⇒ lỗi miền, không dựng.

Service chỉ flush; router commit (lượt E2). Không log nội dung mẫu. Giới hạn là GIỚI HẠN KỸ
THUẬT trong cấu hình (``COUNCIL_TEMPLATE_*``), không phải số nghiệp vụ.
"""
import hashlib
import io
import zipfile
import zlib
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.council_document import CouncilDocumentTemplate
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import council_document_render_service as bo_dung
from app.utils.exceptions import (
    BusinessRuleViolation,
    DataValidationError,
    DuplicateResourceError,
    FileSizeError,
    FileValidationError,
)

TEN_LOAI = {
    "bien_ban": "Biên bản",
    "quyet_dinh": "Quyết định",
    "danh_sach": "Danh sách xét tuyển",
}
_KHUC = 64 * 1024


@dataclass(frozen=True)
class GioiHanGoi:
    """Trần kỹ thuật cho một gói mẫu (mặc định đọc từ cấu hình)."""

    tep: int
    giai_nen: int
    so_muc: int

    @classmethod
    def tu_cau_hinh(cls) -> "GioiHanGoi":
        return cls(
            tep=settings.COUNCIL_TEMPLATE_MAX_BYTES,
            giai_nen=settings.COUNCIL_TEMPLATE_MAX_UNCOMPRESSED_BYTES,
            so_muc=settings.COUNCIL_TEMPLATE_MAX_ZIP_ENTRIES,
        )


def kiem_goi_mau(
    noi_dung: bytes, ten: str, gioi_han: Optional[GioiHanGoi] = None
) -> None:
    """Chặn tệp quá cỡ / bom zip TRƯỚC python-docx. Chỉ dùng ``zipfile``; không giải nén ra
    đĩa. Thông báo chỉ có tên mẫu và số đếm."""
    gh = gioi_han or GioiHanGoi.tu_cau_hinh()
    if not isinstance(noi_dung, bytes) or not noi_dung:
        raise FileValidationError("Mẫu %s: tệp rỗng hoặc không phải bytes." % ten)
    if len(noi_dung) > gh.tep:
        raise FileSizeError(
            "Mẫu %s: tệp %d byte, vượt giới hạn %d byte." % (ten, len(noi_dung), gh.tep)
        )
    try:
        z = zipfile.ZipFile(io.BytesIO(noi_dung))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError):
        raise FileValidationError(
            "Mẫu %s không đọc được như tệp Word (.docx)." % ten
        ) from None
    with z:
        muc = z.infolist()
        if len(muc) > gh.so_muc:
            raise FileValidationError(
                "Mẫu %s: gói có %d mục, vượt giới hạn %d." % (ten, len(muc), gh.so_muc)
            )
        khai = sum(m.file_size for m in muc)
        if khai > gh.giai_nen:
            raise FileValidationError(
                "Mẫu %s: tổng kích thước giải nén khai báo %d byte, vượt giới hạn %d."
                % (ten, khai, gh.giai_nen)
            )
        # Mục mã hoá (mật khẩu): zipfile nổ RuntimeError khi MỞ mục ⇒ kiểm cờ trước (F211).
        bo_dung.kiem_goi_khong_ma_hoa(z, ten)
        # Đọc THẬT theo khúc với trần tổng; không bao giờ giữ quá một khúc trong RAM.
        # Đo 03-11 (CPython 3.12, ``cong-cu/kham_pha_zip_docx_e2.py``): zipfile CẮT mỗi mục ở
        # kích thước KHAI trong thư mục trung tâm — tiêu đề khai nhỏ hơn dữ liệu thì phần
        # dư không bao giờ được giải nén (CRC của phần khai sai ⇒ BadZipFile; CRC khớp phần
        # khai ⇒ chỉ đọc đúng phần khai). Vì vậy với zipfile, ``da_doc`` không vượt được tổng
        # khai đã kiểm ở trên; trần dưới đây là lớp PHỤ, giữ cho trường hợp bộ đọc không cắt
        # theo số khai (test giả lập bộ đọc như thế).
        da_doc = 0
        try:
            for m in muc:
                with z.open(m) as f:
                    while True:
                        khuc = f.read(_KHUC)
                        if not khuc:
                            break
                        da_doc += len(khuc)
                        if da_doc > gh.giai_nen:
                            raise FileValidationError(
                                "Mẫu %s: giải nén vượt giới hạn %d byte."
                                % (ten, gh.giai_nen)
                            )
        except (
            zipfile.BadZipFile,
            NotImplementedError,
            EOFError,
            ValueError,
            OSError,
            zlib.error,
        ):
            # Dòng nén hỏng ⇒ ``zlib.error`` — KHÔNG phải ``OSError`` (đo: MRO chỉ có
            # ``Exception``); mã nén không hỗ trợ ⇒ ``NotImplementedError``; CRC sai ⇒
            # ``BadZipFile``.
            raise FileValidationError(
                "Mẫu %s: gói zip hỏng (CRC / dữ liệu nén sai)." % ten
            ) from None


async def tai_mau_len(
    db: AsyncSession,
    *,
    loai: str,
    hieu_luc_tu: date,
    noi_dung: bytes,
    nguoi_tai_id: Optional[int],
    ghi_chu: Optional[str] = None,
    gioi_han: Optional[GioiHanGoi] = None,
) -> Tuple[CouncilDocumentTemplate, None]:
    """Kiểm rồi lưu một mẫu. Cùng loại + cùng ngày hiệu lực đã có ⇒ ``DuplicateResourceError``
    (không ghi đè: sửa mẫu = tải bản mới với ngày hiệu lực mới)."""
    if loai not in TEN_LOAI:
        raise DataValidationError(
            "Loại mẫu không thuộc %s." % " / ".join(bo_dung.LOAI_MAU)
        )
    if not isinstance(hieu_luc_tu, date):
        raise DataValidationError("Ngày hiệu lực của mẫu không phải ngày.")
    if ghi_chu is not None and (not isinstance(ghi_chu, str) or len(ghi_chu) > 500):
        raise DataValidationError("Ghi chú của mẫu dài quá 500 ký tự.")
    ten = TEN_LOAI[loai]
    kiem_goi_mau(noi_dung, ten, gioi_han)
    bo_dung.kiem_mau(loai, noi_dung)

    repo = CouncilDocumentRepository(db)
    if await repo.mau_cung_ngay(loai, hieu_luc_tu) is not None:
        raise DuplicateResourceError(
            "Đã có mẫu %s hiệu lực từ ngày %s." % (ten, hieu_luc_tu.isoformat())
        )
    mau = CouncilDocumentTemplate(
        loai=loai,
        hieu_luc_tu=hieu_luc_tu,
        sha256=hashlib.sha256(noi_dung).hexdigest(),
        kich_thuoc=len(noi_dung),
        noi_dung=noi_dung,
        nguoi_tai_id=nguoi_tai_id,
        ghi_chu=ghi_chu,
    )
    try:
        async with db.begin_nested():
            await repo.them_mau(mau)
    except IntegrityError:
        # Hai lần tải cùng lúc qua được phép kiểm trên ⇒ UNIQUE (loai, hieu_luc_tu) chặn.
        # Không giữ lỗi gốc: thông báo của trình điều khiển mang cả bytes tham số.
        raise DuplicateResourceError(
            "Đã có mẫu %s hiệu lực từ ngày %s." % (ten, hieu_luc_tu.isoformat())
        ) from None
    return mau, None


async def chon_mau(
    db: AsyncSession, ngay_ky: date
) -> Tuple[bo_dung.CouncilTemplates, Dict[str, Dict[str, object]]]:
    """Ba mẫu áp cho văn bản ký ngày ``ngay_ky`` + {loại: {id, sha256, hieu_luc_tu}}."""
    repo = CouncilDocumentRepository(db)
    chon: Dict[str, CouncilDocumentTemplate] = {}
    thieu = []
    for loai in bo_dung.LOAI_MAU:
        mau = await repo.mau_hieu_luc(loai, ngay_ky)
        if mau is None:
            thieu.append(TEN_LOAI[loai])
        else:
            chon[loai] = mau
    if thieu:
        raise BusinessRuleViolation(
            "Chưa có mẫu %s hiệu lực tới ngày ký %s — không dựng bộ văn bản."
            % (", ".join(thieu), ngay_ky.isoformat())
        )
    mau_dung = bo_dung.CouncilTemplates(
        **{loai: bytes(chon[loai].noi_dung) for loai in bo_dung.LOAI_MAU}
    )
    thong_tin = {
        loai: {
            "id": chon[loai].id,
            "sha256": chon[loai].sha256,
            "hieu_luc_tu": chon[loai].hieu_luc_tu.isoformat(),
        }
        for loai in bo_dung.LOAI_MAU
    }
    return mau_dung, thong_tin
