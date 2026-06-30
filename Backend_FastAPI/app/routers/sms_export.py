# app/routers/sms_export.py
"""
SMS Marketing — export Excel per nhà mạng + download + mark-handed-off (admin).
PR-4. Router "dumb": dịch HTTP ↔ service, commit, không business logic. Hard
gate `require_admin`. KHÔNG sửa main.py (đã wire ở PR-1).

File export sinh ở POST-COMMIT (service trả callback) — router commit business
transaction TRƯỚC rồi await callback (§8.3). Download trả bytes (đã verify
sha256) qua Response no-store.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas import sms as sms_schemas
from app.services.sms_export_service import SmsExportService

router = APIRouter(prefix="/api/sms", tags=["SMS Export"])

# Giới hạn ID khớp cột Integer (int4) — chặn int32 overflow → 500.
_MAX_ID = 2147483647


@router.post(
    "/campaigns/{campaign_id}/export",
    response_model=sms_schemas.SmsExportResult,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(RateLimits.DATA_EXPORT)  # build workbook nặng + chứa PII
async def export_campaign(
    request: Request,  # required by slowapi rate limiter
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """Sinh file Excel per nhà mạng cho bản build hiện tại (idempotent theo
    campaign/revision/nhà mạng). Gate fail-closed: cần đủ 3 attestation đúng
    revision, không còn over_limit, không drift consent/suppression."""
    service = SmsExportService(db)
    callback, _meta = await service.prepare_export(campaign_id, current_user)
    await db.commit()
    if callback is not None:
        await callback()
    return await service.get_export_result(campaign_id)


@router.get(
    "/campaigns/{campaign_id}/exports",
    response_model=sms_schemas.SmsExportBatchList,
)
async def list_exports(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """Danh sách batch export của bản build hiện tại (FE hiển thị lại sau
    reload)."""
    return await SmsExportService(db).list_export_batches(campaign_id)


@router.get("/campaigns/{campaign_id}/exports/{batch_id}/download")
@limiter.limit(RateLimits.DATA_EXPORT)
async def download_export(
    request: Request,  # required by slowapi rate limiter
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    batch_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
) -> FileResponse:
    """Tải file export (auth + verify sha256 + chưa hết hạn/vô hiệu). Stream từ
    đĩa bằng FileResponse (KHÔNG nạp cả file PII vào RAM); Starlette tự encode
    Content-Disposition an toàn cho filename."""
    storage_path, filename, media = await SmsExportService(db).get_export_file(
        campaign_id, batch_id
    )
    return FileResponse(
        storage_path,
        media_type=media,
        filename=filename,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/campaigns/{campaign_id}/exports/{batch_id}/mark-handed-off",
    response_model=sms_schemas.SmsExportBatchOut,
)
async def mark_handed_off(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    batch_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """Xác nhận đã bàn giao/upload file cho nhà mạng (ngoài QLTS). Neo
    handed_off lên recipient (chặn rebuild) + frequency-cap; đóng campaign khi
    mọi nhà mạng đã bàn giao."""
    result = await SmsExportService(db).mark_handed_off(
        campaign_id, batch_id, current_user
    )
    await db.commit()
    return result
