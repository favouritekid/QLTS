# app/services/council_document_template_service.py
"""Kho mẫu văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.2) — service thuần.

* **Tải mẫu lên** = bytes + loại + ngày hiệu lực. Trước khi lưu, theo thứ tự: giới hạn kích
  thước tệp → đọc gói zip bằng ``zipfile`` (số mục, tổng kích thước giải nén khai báo, kiểu
  nén thuộc danh sách CHO PHÉP + không mục nào mã hoá — cả hai trên thư mục trung tâm, trước
  khi mở mục nào —, rồi ĐỌC THẬT từng mục theo khúc với trần tổng — tiêu đề zip nói dối thì
  vẫn dừng đúng trần, CRC sai thì dừng) → CHỈ KHI đó mới đưa cho python-docx qua
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
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.council_document import CouncilDocumentTemplate
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import council_document_render_service as render_service
from app.utils.exceptions import (
    BusinessRuleViolation,
    DataValidationError,
    DuplicateResourceError,
    FileSizeError,
    FileValidationError,
)

KIND_NAMES = {
    "bien_ban": "Biên bản",
    "quyet_dinh": "Quyết định",
    "danh_sach": "Danh sách xét tuyển",
}
_CHUNK = 64 * 1024


@dataclass(frozen=True)
class PackageLimits:
    """Trần kỹ thuật cho một gói mẫu (mặc định đọc từ cấu hình)."""

    max_file_bytes: int
    max_uncompressed_bytes: int
    max_entries: int

    @classmethod
    def from_settings(cls) -> "PackageLimits":
        return cls(
            max_file_bytes=settings.COUNCIL_TEMPLATE_MAX_BYTES,
            max_uncompressed_bytes=settings.COUNCIL_TEMPLATE_MAX_UNCOMPRESSED_BYTES,
            max_entries=settings.COUNCIL_TEMPLATE_MAX_ZIP_ENTRIES,
        )


def check_template_package(
    content: bytes, name: str, limits: Optional[PackageLimits] = None
) -> None:
    """Chặn tệp quá cỡ / bom zip TRƯỚC python-docx. Chỉ dùng ``zipfile``; không giải nén ra
    đĩa. Thông báo chỉ có tên mẫu và số đếm."""
    effective_limits = limits or PackageLimits.from_settings()
    if not isinstance(content, bytes) or not content:
        raise FileValidationError("Mẫu %s: tệp rỗng hoặc không phải bytes." % name)
    if len(content) > effective_limits.max_file_bytes:
        raise FileSizeError(
            "Mẫu %s: tệp %d byte, vượt giới hạn %d byte." % (name, len(content), effective_limits.max_file_bytes)
        )
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError):
        raise FileValidationError(
            "Mẫu %s không đọc được như tệp Word (.docx)." % name
        ) from None
    with z:
        item = z.infolist()
        if len(item) > effective_limits.max_entries:
            raise FileValidationError(
                "Mẫu %s: gói có %d mục, vượt giới hạn %d." % (name, len(item), effective_limits.max_entries)
            )
        declared_total = sum(m.file_size for m in item)
        if declared_total > effective_limits.max_uncompressed_bytes:
            raise FileValidationError(
                "Mẫu %s: tổng kích thước giải nén khai báo %d byte, vượt giới hạn %d."
                % (name, declared_total, effective_limits.max_uncompressed_bytes)
            )
        # Thư mục trung tâm TRƯỚC khi mở bất kỳ mục nào — cùng MỘT hàm với ``_open_docx`` của
        # bộ dựng: kiểu nén chỉ STORED / DEFLATED (F216 — LZMA / BZIP2 nở cả khúc trong RAM
        # trước khi zipfile cắt theo số khai) và không mục nào mã hoá (F211).
        render_service.check_package_before_open(z, name)
        # Đọc THẬT theo khúc với trần tổng; không bao giờ giữ quá một khúc trong RAM.
        # Đo 03-11 (CPython 3.12, ``cong-cu/kham_pha_zip_docx_e2.py``): zipfile CẮT mỗi mục ở
        # kích thước KHAI trong thư mục trung tâm — tiêu đề khai nhỏ hơn dữ liệu thì phần
        # dư không bao giờ được giải nén (CRC của phần khai sai ⇒ BadZipFile; CRC khớp phần
        # khai ⇒ chỉ đọc đúng phần khai). Vì vậy với zipfile, ``da_doc`` không vượt được tổng
        # khai đã kiểm ở trên; trần dưới đây là lớp PHỤ, giữ cho trường hợp bộ đọc không cắt
        # theo số khai (test giả lập bộ đọc như thế).
        bytes_read = 0
        try:
            for m in item:
                with z.open(m) as f:
                    while True:
                        chunk = f.read(_CHUNK)
                        if not chunk:
                            break
                        bytes_read += len(chunk)
                        if bytes_read > effective_limits.max_uncompressed_bytes:
                            raise FileValidationError(
                                "Mẫu %s: giải nén vượt giới hạn %d byte."
                                % (name, effective_limits.max_uncompressed_bytes)
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
                "Mẫu %s: gói zip hỏng (CRC / dữ liệu nén sai)." % name
            ) from None
        # Mọi mục đã đọc thử được trong trần ⇒ kiểm CÁC PHẦN của gói Word (kiểu nội dung,
        # DOCTYPE, quan hệ — không TargetMode External —, mã trường theo danh sách CHO PHÉP)
        # — cùng MỘT hàm với ``_open_docx`` của bộ dựng (bổ sung E3, owner 04-11; E4).
        render_service.check_word_package_parts(z, name)


async def upload_template(
    db: AsyncSession,
    *,
    kind: str,
    effective_from: date,
    content: bytes,
    downloader_id: Optional[int],
    note: Optional[str] = None,
    limits: Optional[PackageLimits] = None,
) -> Tuple[CouncilDocumentTemplate, None]:
    """Kiểm rồi lưu một mẫu. Cùng loại + cùng ngày hiệu lực đã có ⇒ ``DuplicateResourceError``
    (không ghi đè: sửa mẫu = tải bản mới với ngày hiệu lực mới)."""
    if kind not in KIND_NAMES:
        raise DataValidationError(
            "Loại mẫu không thuộc %s." % " / ".join(render_service.TEMPLATE_KINDS)
        )
    if not isinstance(effective_from, date):
        raise DataValidationError("Ngày hiệu lực của mẫu không phải ngày.")
    if note is not None and (not isinstance(note, str) or len(note) > 500):
        raise DataValidationError("Ghi chú của mẫu dài quá 500 ký tự.")
    name = KIND_NAMES[kind]
    check_template_package(content, name, limits)
    render_service.check_template(kind, content)

    repo = CouncilDocumentRepository(db)
    if await repo.template_same_date(kind, effective_from) is not None:
        raise DuplicateResourceError(
            "Đã có mẫu %s hiệu lực từ ngày %s." % (name, effective_from.isoformat())
        )
    template = CouncilDocumentTemplate(
        loai=kind,
        hieu_luc_tu=effective_from,
        sha256=hashlib.sha256(content).hexdigest(),
        kich_thuoc=len(content),
        noi_dung=content,
        nguoi_tai_id=downloader_id,
        ghi_chu=note,
    )
    try:
        async with db.begin_nested():
            await repo.add_template(template)
    except IntegrityError:
        # Hai lần tải cùng lúc qua được phép kiểm trên ⇒ UNIQUE (loai, hieu_luc_tu) chặn.
        # Không giữ lỗi gốc: thông báo của trình điều khiển mang cả bytes tham số.
        raise DuplicateResourceError(
            "Đã có mẫu %s hiệu lực từ ngày %s." % (name, effective_from.isoformat())
        ) from None
    return template, None


async def list_templates(db: AsyncSession) -> List[CouncilDocumentTemplate]:
    """Mọi mẫu trong kho — metadata, KHÔNG nạp bytes (cột ``noi_dung`` deferred)."""
    return await CouncilDocumentRepository(db).list_templates()


async def pick_templates(
    db: AsyncSession, signing_date: date
) -> Tuple[render_service.CouncilTemplates, Dict[str, Dict[str, object]]]:
    """Ba mẫu áp cho văn bản ký ngày ``ngay_ky`` + {loại: {id, sha256, hieu_luc_tu}}."""
    repo = CouncilDocumentRepository(db)
    picked: Dict[str, CouncilDocumentTemplate] = {}
    missing = []
    for kind in render_service.TEMPLATE_KINDS:
        template = await repo.effective_template(kind, signing_date)
        if template is None:
            missing.append(KIND_NAMES[kind])
        else:
            picked[kind] = template
    if missing:
        raise BusinessRuleViolation(
            "Chưa có mẫu %s hiệu lực tới ngày ký %s — không dựng bộ văn bản."
            % (", ".join(missing), signing_date.isoformat())
        )
    templates = render_service.CouncilTemplates(
        **{kind: bytes(picked[kind].noi_dung) for kind in render_service.TEMPLATE_KINDS}
    )
    info = {
        kind: {
            "id": picked[kind].id,
            "sha256": picked[kind].sha256,
            "hieu_luc_tu": picked[kind].hieu_luc_tu.isoformat(),
        }
        for kind in render_service.TEMPLATE_KINDS
    }
    return templates, info
