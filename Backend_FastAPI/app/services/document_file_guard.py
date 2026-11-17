"""GĐ1b §4.6b (K5) — MỘT chỗ hỏi trước khi xoá tệp của giấy thường: tệp đang là bằng chứng duyệt thì GIỮ.

Đặc tả bản 3.6 §4.6b: tải lại (tệp cũ), Đặt lại, xoá thư mục hồ sơ đều đi qua :func:`delete_document_file_unless_evidence`.
Danh sách tệp phải giữ được CHỐT TRONG GIAO DỊCH, trước commit (:func:`protected_evidence_paths`), rồi việc xoá tệp chạy
SAU commit với đúng danh sách ấy. Tệp minh chứng ưu tiên giữ như nay (P1 — ngoài phạm vi).

Quét mã (``tests/unit/test_gd1b_quet_xoa_tep.py``): các hàm xoá tệp của giấy thường không gọi ``os.remove`` /
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


def delete_document_file_unless_evidence(path: Optional[str], protected: FrozenSet[str]) -> str:
    """Xoá ``path`` trừ khi nó là tệp bằng chứng. Gọi SAU commit; không bao giờ ném (dọn tệp là best-effort)."""
    if not path:
        return MISSING
    if _norm(path) in protected:
        log.info("document file kept: evidence of a verification", file_path=path)
        return KEPT_EVIDENCE
    try:
        if not os.path.exists(path):
            return MISSING
        os.remove(path)
        return DELETED
    except OSError as e:
        log.warning("document file delete failed", file_path=path, error=str(e))
        return FAILED


def remove_profile_upload_dir_unless_evidence(profile_id: int, protected: FrozenSet[str]) -> None:
    """Xoá thư mục tải lên của hồ sơ đã xoá — từng tệp qua :func:`delete_document_file_unless_evidence`; thư mục chỉ bị
    xoá khi đã rỗng. Gọi SAU commit; không bao giờ ném."""
    upload_dir = f"uploads/admissions/{profile_id}"
    try:
        for root, dirs, files in os.walk(upload_dir, topdown=False):
            for name in files:
                delete_document_file_unless_evidence(os.path.join(root, name), protected)
            try:
                os.rmdir(root)
            except OSError:
                pass  # còn tệp bằng chứng, hoặc đã biến mất
    except Exception as e:  # noqa: BLE001 — best-effort sau commit
        log.warning("Failed to remove profile upload dir post-commit", upload_dir=upload_dir, error=str(e))
