"""GĐ1b — lô duyệt giấy của Quản lý / Admin (``review_mode = batch``). Hợp đồng API GĐ1b bản 4 §2.1; đặc tả bản 3.6 §5.

Router MỎNG: quyền / IDOR ở ``app/core/deps.py`` (404 cùng thân), nghiệp vụ ở ``document_bulk_verify_service``. Đăng ký
chính thức (``app/main.py``: ``fastapi_app.include_router(document_bulk_verify.router, prefix="/api")``) + dòng Casbin do
Claude làm khi tích hợp; test của agent tự gắn router bằng fixture riêng.

Ngoại lệ "router commit": ``execute`` — người chạy lô commit TỪNG hồ sơ trong dịch vụ (đặc tả §1); router chỉ gọi callback
sau commit cuối (socket ``bulk_verify_finished``).
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.client_ip import get_client_ip
from ..schemas.document_bulk import (
    BatchListResponse,
    BatchView,
    BulkVerifyEligibility,
    BulkVerifyExecuteRequest,
    BulkVerifyFinalizeRequest,
    BulkVerifyPreviewRequest,
    FinalizeResponse,
    PreviewResponse,
)
from ..services import document_bulk_verify_service as bulk_service
from ..services.document_transition import RequestMeta

router = APIRouter(prefix="/admissions/documents/bulk-verify", tags=["GĐ1b — Bulk document verify"])


def _meta(request: Request) -> RequestMeta:
    return RequestMeta(get_client_ip(request), request.headers.get("user-agent"))


@router.post("/preview", response_model=PreviewResponse, status_code=status.HTTP_201_CREATED)
async def preview_bulk_verify(
    request: Request,
    body: BulkVerifyPreviewRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_bulk_verify_reviewer),
):
    result = await bulk_service.preview_batch(
        db,
        actor=current_user,
        profile_ids=body.profile_ids,
        filter_=body.filter,
        include_optional=body.include_optional,
        review_mode=bulk_service.REVIEW_MODE_BATCH,
        request_meta=_meta(request),
    )
    await db.commit()
    return result


# Khai TRƯỚC ``GET /{batch_id}`` (đường tĩnh trước đường tham số). Mọi người đã đăng nhập gọi được — chỉ trả cờ của chính
# người gọi (bổ sung hợp đồng bản 6 C1); không Casbin riêng cho route này.
@router.get("/eligibility", response_model=BulkVerifyEligibility)
async def get_bulk_verify_eligibility(
    request: Request,
    current_user: models.User = Depends(deps.get_current_active_user),
):
    return {"eligible": deps.bulk_verify_eligible(request, current_user)}


@router.post("/{batch_id}/execute", response_model=BatchView)
async def execute_bulk_verify(
    request: Request,
    body: BulkVerifyExecuteRequest,
    batch: models.DocumentBulkBatch = Depends(deps.get_bulk_batch_for_execute),
    current_user: models.User = Depends(deps.require_bulk_verify_reviewer),
    db: AsyncSession = Depends(database.get_db),
):
    batch_id, actor_id = batch.batch_id, current_user.id
    view, post_commit = await bulk_service.execute_batch(
        db,
        batch_id=batch_id,
        actor_id=actor_id,
        confirmation_text=body.confirmation_text,
        review_mode=bulk_service.REVIEW_MODE_BATCH,
        request_meta=_meta(request),
    )
    await post_commit()
    return view


@router.get("", response_model=BatchListResponse)
async def list_bulk_verify_batches(
    scope: Literal["mine", "all"] = Query("mine"),
    cursor: Optional[str] = Query(None, max_length=500),
    limit: int = Query(bulk_service.BULK_VERIFY_LIST_PAGE_SIZE, ge=1, le=50),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_bulk_verify_reviewer),
):
    return await bulk_service.list_batches(
        db,
        viewer_id=current_user.id,
        viewer_role=current_user.role,
        scope=scope,
        cursor=cursor,
        limit=limit,
        # PR-B lượt 3 (Codex điểm chặn 1): lô CHÉO không liệt kê ở đường thường, trừ Admin (X3) — theo ``review_mode`` lưu.
        review_mode=bulk_service.regular_route_list_mode(current_user.role),
        allow_scope_all=True,
    )


@router.get("/{batch_id}", response_model=BatchView)
async def get_bulk_verify_batch(
    batch: models.DocumentBulkBatch = Depends(deps.get_bulk_batch_for_view),
    current_user: models.User = Depends(deps.require_bulk_verify_reviewer),
    db: AsyncSession = Depends(database.get_db),
):
    batch_id, viewer_id, viewer_role = batch.batch_id, current_user.id, current_user.role
    return await bulk_service.get_batch(db, batch_id=batch_id, viewer_id=viewer_id, viewer_role=viewer_role)


@router.post("/{batch_id}/finalize", response_model=FinalizeResponse)
async def finalize_bulk_verify_batch(
    request: Request,
    body: BulkVerifyFinalizeRequest,
    batch: models.DocumentBulkBatch = Depends(deps.get_bulk_batch_for_view),
    current_user: models.User = Depends(deps.require_bulk_verify_reviewer),
    db: AsyncSession = Depends(database.get_db),
):
    batch_id, creator_id = batch.batch_id, batch.actor_user_id
    viewer_id, viewer_role = current_user.id, current_user.role
    result = await bulk_service.finalize_batch(
        db,
        batch_id=batch_id,
        creator_id=creator_id,
        viewer_id=viewer_id,
        viewer_role=viewer_role,
        reason=body.reason,
        request_meta=_meta(request),
    )
    await db.commit()
    return result
