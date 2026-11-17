"""GĐ1b §4.6b — route tải tệp bằng chứng duyệt (hợp đồng API bản 4 §2.3).

``GET /api/admissions/{profile_id}/documents/{document_row_id}/evidence/{evidence_id}/download``

Đăng ký (Claude, khi tích hợp): ``fastapi_app.include_router(document_evidence.router, prefix="/api")`` — cùng khuôn
``admissions.router``. Không Casbin riêng: cổng quyền là dependency ``deps.get_admission_for_document_history`` như route
lịch sử K2. Chỉ có route GET ⇒ không thuộc danh mục route GHI của cần gạt đóng băng (``admission_freeze``).
"""
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models
from ..core import deps
from ..core.client_ip import get_client_ip
from ..core.rate_limits import RateLimits, limiter
from ..services import document_evidence_service
from ..services.document_evidence_service import EvidenceFileMissingError

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admissions", tags=["Admissions"])

#: Khoá chính int4 — số ngoài khoảng ⇒ 422 thay vì lỗi tràn của asyncpg (500).
_INT4_MAX = 2_147_483_647


async def _mark_missing_in_own_transaction(db: AsyncSession, *, evidence_id: int, profile_id: int) -> None:
    """Đánh dấu ``file_missing`` trong một giao dịch RIÊNG, commit độc lập với phản hồi 410. Best-effort: lỗi ghi cờ không
    biến 410 thành 500 (đặc tả §4.6b: tệp mất ⇒ báo, không 500)."""
    try:
        await document_evidence_service.mark_evidence_file_missing(db, evidence_id)
        await db.commit()
    except Exception as e:  # noqa: BLE001 — cờ là thông tin thêm; phản hồi vẫn là 410
        log.warning(
            "evidence file_missing flag not recorded",
            profile_id=profile_id,
            evidence_id=evidence_id,
            error=type(e).__name__,
        )
        await db.rollback()


@router.get(
    "/{profile_id}/documents/{document_row_id}/evidence/{evidence_id}/download",
    summary="GĐ1b — download a verification evidence file (manager in scope / admin)",
)
@limiter.limit(RateLimits.DATA_READ)  # ĐÚNG thứ tự: route ở trên, limiter ở dưới (test_ratelimit_order_guard)
async def download_document_evidence(
    request: Request,
    document_row_id: int = Path(..., ge=1, le=_INT4_MAX),
    evidence_id: int = Path(..., ge=1, le=_INT4_MAX),
    profile: models.AdmissionProfile = Depends(deps.get_admission_for_document_history),
    current_user: models.User = Depends(deps.get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Tải lại tệp đang gắn với giấy LÚC giấy được duyệt (đường dẫn bất biến, không phải tệp hiện hành của giấy).

    Quản lý trong phạm vi / Admin; sai phạm vi, cán bộ, cán bộ chéo ⇒ 404. Bằng chứng không thuộc đúng giấy + hồ sơ ⇒ 404.
    Tệp không còn ⇒ 410 ``EVIDENCE_FILE_MISSING`` + ``file_missing = true`` (giao dịch riêng), lịch sử không đổi. Tải được ⇒
    nhật ký ``downloaded`` + ``document_download_log`` commit TRƯỚC khi trả tệp, như route tải thường.
    """
    # Chụp định danh TRƯỚC mọi rollback (rollback làm hết hạn đối tượng ORM của phiên).
    profile_id = profile.id
    actor_user_id = current_user.id
    try:
        found = await document_evidence_service.get_evidence_file_for_download(
            db,
            profile_id=profile_id,
            document_row_id=document_row_id,
            evidence_id=evidence_id,
            actor_user_id=actor_user_id,
            actor_ip=get_client_ip(request),
            actor_user_agent=request.headers.get("user-agent"),
        )
        await db.commit()
    except EvidenceFileMissingError as exc:
        # Giao dịch đọc kết thúc (không có lệnh ghi nào trong đó), rồi cờ ghi ở giao dịch riêng; handler toàn cục trả 410.
        await db.rollback()
        await _mark_missing_in_own_transaction(db, evidence_id=exc.evidence_id, profile_id=profile_id)
        raise

    return FileResponse(
        found.abs_path,
        media_type=found.media_type,
        filename=found.filename,
        content_disposition_type="inline",
        headers={
            # Tài liệu có dữ liệu cá nhân: không lưu đệm, không lộ referrer, không đoán MIME (như route tải thường).
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
