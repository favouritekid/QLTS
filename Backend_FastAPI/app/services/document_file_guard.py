"""GĐ1b §4.6b (K5) — MỘT chỗ hỏi trước khi xoá tệp của giấy thường: tệp đang là bằng chứng duyệt thì GIỮ.

Đặc tả bản 3.6 §4.6b: tải lại (tệp cũ), Đặt lại, xoá thư mục hồ sơ đều đi qua :func:`delete_document_file_unless_evidence`.
Danh sách tệp phải giữ được CHỐT TRONG GIAO DỊCH, trước commit (:func:`protected_evidence_paths`), rồi việc xoá tệp chạy
SAU commit với đúng danh sách ấy. Tệp minh chứng ưu tiên giữ như nay (P1 — ngoài phạm vi).

Quét mã (``tests/api/test_gd1b_khoa_va_tep.py::test_quet_ma_khong_xoa_tep_giay_thuong_truc_tiep_ngoai_helper``): các hàm xoá tệp của giấy thường không gọi ``os.remove`` /
``os.unlink`` / ``shutil.rmtree`` trực tiếp, trừ tệp tạm ``staging_path`` của chính lượt tải.
"""

from __future__ import annotations

import os
from typing import FrozenSet, Iterable, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

log = structlog.get_logger(__name__)

DELETED = "deleted"
KEPT_EVIDENCE = "kept_evidence"
MISSING = "missing"
FAILED = "failed"
#: Codex 68: đường dẫn (từ CSDL) không nằm trong ``uploads/admissions/{profile_id}`` ⇒ KHÔNG xoá (fail closed).
REFUSED_OUTSIDE_PROFILE_DIR = "refused_outside_profile_dir"


def _norm(path: str) -> str:
    return os.path.normpath(path)


async def protected_evidence_paths(
    db: AsyncSession, *, profile_id: Optional[int] = None, paths: Iterable[Optional[str]] = ()
) -> FrozenSet[str]:
    """Đường dẫn tệp đang có dòng ``document_evidence_file`` — gọi TRONG giao dịch, trước commit."""
    wanted = [p for p in paths if p]
    if profile_id is None and not wanted:
        return frozenset()
    stmt = select(models.DocumentEvidenceFile.file_path)
    if profile_id is not None:
        stmt = stmt.where(models.DocumentEvidenceFile.profile_id == profile_id)
    else:
        stmt = stmt.where(models.DocumentEvidenceFile.file_path.in_(wanted))
    return frozenset(_norm(p) for p in (await db.execute(stmt)).scalars())


def _safe_path(path: str, profile_id: int) -> Optional[str]:
    """Đường dẫn tuyệt đối ĐÃ XÁC THỰC nằm trong ``uploads/admissions/{profile_id}`` (``_resolve_under`` — cùng phép kiểm của
    tải lên / tải xuống); ngoài thư mục ⇒ None."""
    from app.services.admission_service import _resolve_under

    return _resolve_under(f"uploads/admissions/{profile_id}", path)


def delete_file_inside_profile_dir(path: Optional[str], *, profile_id: int) -> str:
    """Xoá tệp CHỈ khi đường dẫn nằm trong thư mục hồ sơ (Codex 68 / 69). Đường dẫn trong CSDL sai lệch, có ``..``, tuyệt đối ra
    ngoài ⇒ KHÔNG xoá, ghi cảnh báo. Không xét bằng chứng — dùng trực tiếp cho tệp minh chứng ưu tiên (owner 17-11: chỉ thêm
    phép kiểm đường dẫn, không đổi chính sách giữ / xoá minh chứng). Gọi SAU commit; không bao giờ ném."""
    if not path:
        return MISSING
    safe = _safe_path(path, profile_id)
    if safe is None:
        log.warning("file NOT deleted: path outside the profile upload dir", profile_id=profile_id)
        return REFUSED_OUTSIDE_PROFILE_DIR
    try:
        if not os.path.exists(safe):
            return MISSING
        os.remove(safe)
        return DELETED
    except OSError as e:
        log.warning("file delete failed", file_path=path, error=str(e))
        return FAILED


def delete_document_file_unless_evidence(path: Optional[str], protected: FrozenSet[str], *, profile_id: int) -> str:
    """Xoá tệp giấy thường trừ khi nó là tệp bằng chứng; chỉ trong thư mục hồ sơ (:func:`delete_file_inside_profile_dir`).
    Gọi SAU commit; không bao giờ ném (dọn tệp là best-effort)."""
    if not path:
        return MISSING
    safe = _safe_path(path, profile_id)
    if safe is None:
        log.warning("document file NOT deleted: path outside the profile upload dir", profile_id=profile_id)
        return REFUSED_OUTSIDE_PROFILE_DIR
    if _norm(path) in protected or safe in {_resolved(p) for p in protected}:
        log.info("document file kept: evidence of a verification", file_path=path)
        return KEPT_EVIDENCE
    return delete_file_inside_profile_dir(path, profile_id=profile_id)


def _resolved(path: str) -> str:
    from pathlib import Path

    return str(Path(path).resolve(strict=False))


def remove_profile_upload_dir_unless_evidence(profile_id: int, protected: FrozenSet[str]) -> None:
    """Xoá thư mục tải lên của hồ sơ đã xoá — từng tệp qua :func:`delete_document_file_unless_evidence`; thư mục chỉ bị
    xoá khi đã rỗng. Gọi SAU commit; không bao giờ ném."""
    upload_dir = f"uploads/admissions/{profile_id}"
    try:
        for root, dirs, files in os.walk(upload_dir, topdown=False):
            for name in files:
                delete_document_file_unless_evidence(os.path.join(root, name), protected, profile_id=profile_id)
            try:
                os.rmdir(root)
            except OSError:
                pass  # còn tệp bằng chứng, hoặc đã biến mất
    except Exception as e:  # noqa: BLE001 — best-effort sau commit
        log.warning("Failed to remove profile upload dir post-commit", upload_dir=upload_dir, error=str(e))
