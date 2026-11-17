"""GĐ1b §4.6b (K5) — tải lại tệp bằng chứng duyệt. Hợp đồng API bản 4 §2.3; đặc tả bản 3.6 §4.6b, §4.7, §9.

Quyền + phạm vi hồ sơ ở ``deps.get_admission_for_document_history`` (Quản lý trong phạm vi / Admin; cán bộ, cán bộ chéo,
sai phạm vi ⇒ 404). Ở đây:

* dòng bằng chứng phải thuộc ĐÚNG giấy (``document_row_id``) của ĐÚNG hồ sơ đã được phép — lệch ⇒ 404 cùng thân, không lộ
  giấy / bằng chứng của hồ sơ khác có tồn tại hay không;
* đường dẫn lưu trong CSDL kiểm bằng ``_resolve_under`` trong ``uploads/admissions/{profile_id}`` (cùng phép kiểm của tải
  lên / tải xuống / xoá tệp); ra ngoài ⇒ 404, KHÔNG phục vụ, KHÔNG đánh dấu ``file_missing`` (dữ liệu sai lệch, không phải
  tệp mất);
* tệp không còn trên ổ ⇒ :class:`EvidenceFileMissingError` (410 ``EVIDENCE_FILE_MISSING``) TRƯỚC mọi lệnh ghi: không ghi
  nhật ký tải, lịch sử không đổi. Router đánh dấu ``file_missing`` bằng :func:`mark_evidence_file_missing` trong một giao
  dịch RIÊNG;
* (hợp đồng bổ sung bản 5 B6) tệp có mặt ⇒ băm sha256 TOÀN BỘ nội dung (cùng thuật toán ``document_transition._sha256_file``
  dùng lúc duyệt) rồi so với ``document_evidence_file.sha256``. Khác (kể cả sha đã ghi rỗng — không chứng minh được) ⇒
  :class:`EvidenceFileAlteredError` (409 ``EVIDENCE_FILE_ALTERED``) TRƯỚC mọi lệnh ghi: không trả tệp, không đổi
  ``file_missing``, không ghi nhật ký tải;
* tải được ⇒ ghi nhật ký ``downloaded`` + ``document_download_log`` cùng giao dịch, như route tải thường
  (``admission_service.get_document_file_for_download``). Hai bản ghi nhật ký tải được khoá bằng nhau bởi
  ``tests/api/test_gd1b_bang_chung_tai.py::test_tai_bang_chung_ghi_nhat_ky_giong_het_route_tai_thuong``. Dòng đang
  ``file_missing = true`` mà tệp có mặt ĐÚNG băm ⇒ router tắt cờ bằng :func:`clear_evidence_file_missing` trong giao dịch
  RIÊNG (đối xứng lúc bật) — cờ chỉ tự tắt khi chứng minh được đúng tệp;
* QUYẾT ĐỊNH theo B6b (Claude chấp nhận 18-11): ``sha256`` đã ghi RỖNG (dòng điền ngược lúc migration khi tệp đã mất) mà tệp
  xuất hiện lại ⇒ không có gì để chứng minh ⇒ 409 ``EVIDENCE_FILE_ALTERED``, không trả tệp, cờ GIỮ ``true``. CHECK
  ``ck_document_evidence_file_sha256_present`` của CSDL cũng cấm tắt cờ khi ``sha256`` rỗng;
* không có khe giữa lúc băm và lúc trả (Claude 18-11): tệp được ĐỌC MỘT LẦN vào bộ nhớ (trần :data:`EVIDENCE_MAX_BYTES`;
  vượt trần ⇒ 409, không đọc), băm ĐÚNG các byte ấy và router trả ĐÚNG các byte ấy — không mở lại tệp theo đường dẫn.

Service không commit (router commit), không import FastAPI.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.utils.exceptions import ConflictError, GoneError, ResourceNotFoundError

log = structlog.get_logger(__name__)

EVIDENCE_FILE_MISSING = "EVIDENCE_FILE_MISSING"
EVIDENCE_FILE_ALTERED = "EVIDENCE_FILE_ALTERED"

#: Trần kích thước tệp bằng chứng = trần tải lên của ``admission_service.upload_document`` (biến cục bộ ``MAX_FILE_SIZE``,
#: không import được). Hai bản khoá bằng nhau bởi
#: ``tests/api/test_gd1b_bang_chung_toan_ven.py::test_tran_kich_thuoc_bang_chung_bang_tran_tai_len_cua_loi`` (CLAUDE.md §7).
#: Tệp trên ổ lớn hơn trần không thể là tệp đã tải lên ⇒ coi như đã bị sửa, KHÔNG đọc vào bộ nhớ.
EVIDENCE_MAX_BYTES = 10 * 1024 * 1024

#: Một thân 404 cho mọi nhánh "không thuộc / không hợp lệ" — không phân biệt giấy không có, bằng chứng của giấy khác,
#: bằng chứng của hồ sơ khác, đường dẫn sai lệch.
_NOT_FOUND = "Resource not found"

#: Loại nội dung theo phần mở rộng do MÁY CHỦ đặt lúc tải lên (từ chữ ký tệp) — cùng bảng của route tải thường; test
#: ``test_tai_bang_chung_ghi_nhat_ky_giong_het_route_tai_thuong`` so tiêu đề ``content-type`` của hai route.
_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


class EvidenceFileMissingError(GoneError):
    """410 — tệp bằng chứng không còn trên ổ lưu trữ. Không 500, không xoá lịch sử."""

    detail = "Tệp bằng chứng không còn trên ổ lưu trữ."
    error_code = EVIDENCE_FILE_MISSING

    def __init__(self, evidence_id: int):
        super().__init__()
        self.evidence_id = evidence_id


class EvidenceFileAlteredError(ConflictError):
    """409 — tệp trên ổ KHÔNG khớp mã băm ghi lúc duyệt: không trả tệp dưới danh nghĩa bằng chứng (hợp đồng bản 5 B6a)."""

    detail = "Tệp bằng chứng trên ổ lưu trữ không khớp mã băm đã ghi lúc duyệt — không trả tệp."
    error_code = EVIDENCE_FILE_ALTERED

    def __init__(self, evidence_id: int):
        super().__init__()
        self.evidence_id = evidence_id


@dataclass(frozen=True)
class EvidenceDownload:
    abs_path: str
    filename: str
    media_type: str
    evidence_id: int
    #: Dòng đang ``file_missing = true`` mà tệp có mặt và ĐÚNG băm ⇒ router tắt cờ trong giao dịch riêng (B6b).
    clear_missing_flag: bool
    #: ĐÚNG các byte đã băm và đã so với sha256 lúc duyệt — router trả các byte này, không mở lại ``abs_path``.
    content: bytes


def _profile_upload_dir(profile_id: int) -> str:
    return f"uploads/admissions/{profile_id}"


def _read_bounded(path: str, limit: int) -> Optional[bytes]:
    """Đọc tệp MỘT lần, tối đa ``limit + 1`` byte (lớp thứ hai: tệp lớn lên sau phép đo kích thước vẫn không vào trọn bộ
    nhớ). Vượt ``limit`` ⇒ ``None``."""
    with open(path, "rb") as f:
        data = f.read(limit + 1)
    return None if len(data) > limit else data


def _sha256_bytes(data: bytes) -> str:
    """sha256 của ĐÚNG các byte sẽ trả — cùng thuật toán ``document_transition._sha256_file`` dùng lúc duyệt (băm toàn
    nội dung tệp)."""
    return hashlib.sha256(data).hexdigest()


async def get_evidence_file_for_download(
    db: AsyncSession,
    *,
    profile_id: int,
    document_row_id: int,
    evidence_id: int,
    actor_user_id: int,
    actor_ip: Optional[str] = None,
    actor_user_agent: Optional[str] = None,
) -> EvidenceDownload:
    """Tìm tệp bằng chứng ``evidence_id`` của giấy ``document_row_id`` thuộc hồ sơ ``profile_id`` (ĐÃ qua cổng quyền), ghi
    nhật ký tải (flush, chưa commit) rồi trả đường dẫn tuyệt đối đã xác thực.

    Raises:
        ResourceNotFoundError: bằng chứng không thuộc giấy / hồ sơ này, hoặc đường dẫn ra ngoài thư mục hồ sơ.
        EvidenceFileMissingError: tệp không còn trên ổ — ném TRƯỚC mọi lệnh ghi.
    """
    from app.services.admission_service import _resolve_under
    from app.services.document_audit_service import DocumentAction, log_document_action

    row = (
        await db.execute(
            select(models.DocumentEvidenceFile, models.ConfigDocumentType.code)
            .join(models.ProfileDocument, models.ProfileDocument.id == models.DocumentEvidenceFile.profile_document_id)
            .outerjoin(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
            .where(
                models.DocumentEvidenceFile.id == evidence_id,
                models.DocumentEvidenceFile.profile_document_id == document_row_id,
                models.ProfileDocument.profile_id == profile_id,
                models.DocumentEvidenceFile.profile_id == profile_id,
                models.ProfileDocument.category == "path",
            )
        )
    ).first()
    if row is None:
        raise ResourceNotFoundError(_NOT_FOUND)
    evidence, type_code = row

    abs_path = _resolve_under(_profile_upload_dir(profile_id), evidence.file_path)
    if abs_path is None:
        log.warning(
            "evidence download refused: stored path outside the profile upload dir",
            profile_id=profile_id,
            document_row_id=document_row_id,
            evidence_id=evidence_id,
        )
        raise ResourceNotFoundError(_NOT_FOUND)
    if not os.path.isfile(abs_path):
        log.warning(
            "evidence download: file no longer on disk",
            profile_id=profile_id,
            document_row_id=document_row_id,
            evidence_id=evidence_id,
        )
        raise EvidenceFileMissingError(evidence.id)

    # Trần kích thước TRƯỚC khi đọc: tệp lớn hơn trần tải lên không thể là tệp đã duyệt ⇒ 409, không đọc vào bộ nhớ.
    try:
        size_on_disk = os.path.getsize(abs_path)
    except FileNotFoundError:
        raise EvidenceFileMissingError(evidence.id)
    if size_on_disk > EVIDENCE_MAX_BYTES:
        log.warning(
            "evidence download refused: file on disk exceeds the upload size cap",
            profile_id=profile_id,
            document_row_id=document_row_id,
            evidence_id=evidence_id,
        )
        raise EvidenceFileAlteredError(evidence.id)

    # B6a: đọc MỘT lần (luồng phụ), băm TOÀN BỘ đúng các byte ấy, so với sha256 lúc duyệt; trả đúng các byte ấy.
    try:
        content = await asyncio.to_thread(_read_bounded, abs_path, EVIDENCE_MAX_BYTES)
    except FileNotFoundError:
        # Tệp biến mất giữa phép kiểm có mặt và lúc đọc ⇒ cùng nhánh "tệp mất".
        raise EvidenceFileMissingError(evidence.id)
    if content is None:
        log.warning(
            "evidence download refused: file grew past the upload size cap while reading",
            profile_id=profile_id,
            document_row_id=document_row_id,
            evidence_id=evidence_id,
        )
        raise EvidenceFileAlteredError(evidence.id)
    actual_sha256 = await asyncio.to_thread(_sha256_bytes, content)
    if actual_sha256 != evidence.sha256:
        log.warning(
            "evidence download refused: file on disk does not match the recorded sha256",
            profile_id=profile_id,
            document_row_id=document_row_id,
            evidence_id=evidence_id,
            recorded_sha256_present=evidence.sha256 is not None,
        )
        raise EvidenceFileAlteredError(evidence.id)

    # Nhật ký tải — như route tải thường (K4c, §4.3): dòng ``downloaded`` + dấu tải độc lập vòng đời hồ sơ, CÙNG giao dịch
    # (router commit trước khi trả tệp). ``extra_data.evidence_id`` phân biệt "tải tệp bằng chứng" với "tải tệp hiện hành".
    audit_row = await log_document_action(
        db=db,
        profile_document_id=document_row_id,
        action=DocumentAction.DOWNLOADED,
        actor_user_id=actor_user_id,
        extra_data={"evidence_id": evidence.id},
        ip_address=actor_ip,
        user_agent=actor_user_agent,
    )
    db.add(
        models.DocumentDownloadLog(
            actor_user_id=actor_user_id,
            profile_id=profile_id,
            document_row_id=document_row_id,
            document_type_code=type_code,
            ip_address=actor_ip,
            user_agent=actor_user_agent,
            source_audit_id=audit_row.id,
        )
    )
    await db.flush()

    ext = os.path.splitext(abs_path)[1].lower()
    return EvidenceDownload(
        abs_path=abs_path,
        # CR/LF bỏ khỏi tên tệp để không chèn được tiêu đề (như route tải thường).
        filename=os.path.basename(abs_path).replace("\r", "").replace("\n", ""),
        media_type=_MEDIA_TYPES.get(ext, "application/octet-stream"),
        evidence_id=evidence.id,
        clear_missing_flag=bool(evidence.file_missing),
        content=content,
    )


async def mark_evidence_file_missing(db: AsyncSession, evidence_id: int) -> bool:
    """Đặt ``file_missing = true`` (chỉ thêm thông tin, không xoá gì). Gọi trong giao dịch RIÊNG của router, sau khi giao
    dịch đọc đã rollback. Trả ``True`` khi vừa đổi cờ (``False`` = đã đánh dấu từ trước)."""
    res = await db.execute(
        update(models.DocumentEvidenceFile)
        .where(
            models.DocumentEvidenceFile.id == evidence_id,
            models.DocumentEvidenceFile.file_missing.is_(False),
        )
        .values(file_missing=True)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1


async def clear_evidence_file_missing(db: AsyncSession, evidence_id: int) -> bool:
    """Đặt ``file_missing = false`` — CHỈ gọi sau khi tệp có mặt và khớp sha256 đã ghi (B6b). Giao dịch RIÊNG của router,
    sau commit nhật ký tải. Trả ``True`` khi vừa đổi cờ."""
    res = await db.execute(
        update(models.DocumentEvidenceFile)
        .where(
            models.DocumentEvidenceFile.id == evidence_id,
            models.DocumentEvidenceFile.file_missing.is_(True),
        )
        .values(file_missing=False)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount == 1
