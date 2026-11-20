"""GĐ1b — duyệt chéo tạm thời (đặc tả bản 3.6 §6; hợp đồng API GĐ1b bản 4 §2.2).

Đường RIÊNG, phản hồi HẸP — KHÔNG nới ``GET`` hồ sơ chung. Quyền ở ``app/core/deps.py``: Admin cấp / thu hồi; Cán bộ có quyền
còn hiệu lực dùng hàng đợi / duyệt / từ chối / lô chéo; ``eligibility`` cho mọi người đã đăng nhập. Owner Q1 (20-11): trên 8 API
thực hiện duyệt chéo, kiểm VAI trước khi tra hồ sơ / lô — vai khác Cán bộ ⇒ 403; Cán bộ thiếu quyền cho đúng thao tác / ngoài
phạm vi / hồ sơ hay lô không tồn tại ⇒ 404 cùng thân.
Đăng ký chính thức (``fastapi_app.include_router(document_cross_review.router, prefix="/api")``) + Casbin: Claude khi tích hợp.
"""

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.client_ip import get_client_ip
from ..schemas.document_bulk import (
    BatchListResponse,
    BatchView,
    BulkVerifyExecuteRequest,
    BulkVerifyFinalizeRequest,
    CrossBulkVerifyPreviewRequest,
    CrossReviewActionRequest,
    CrossReviewActionResponse,
    CrossReviewEligibility,
    CrossReviewGrantCreate,
    CrossReviewGrantRevoke,
    CrossReviewGrantView,
    CrossReviewQueuePage,
    FinalizeResponse,
    PreviewResponse,
)
from ..services import document_bulk_verify_service as bulk_service
from ..services import document_cross_review_service as cross_service
from ..services.document_review_rules import ACTION_REJECT, ACTION_VERIFY
from ..services.document_transition import RequestMeta

router = APIRouter(prefix="/admissions/cross-review", tags=["GĐ1b — Cross review"])


def _meta(request: Request) -> RequestMeta:
    return RequestMeta(get_client_ip(request), request.headers.get("user-agent"))


# ------------------------------------------------------------------------------------------------- Admin: quyền
@router.post("/grants", response_model=CrossReviewGrantView, status_code=status.HTTP_201_CREATED)
async def create_cross_review_grant(
    request: Request,
    body: CrossReviewGrantCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_cross_review_admin),
):
    result = await cross_service.create_grant(db, admin_id=current_user.id, body=body, request_meta=_meta(request))
    await db.commit()
    return result


@router.post("/grants/{grant_id}/revoke", response_model=CrossReviewGrantView)
async def revoke_cross_review_grant(
    request: Request,
    body: CrossReviewGrantRevoke,
    grant_id: int = Path(..., ge=1, le=2147483647),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_cross_review_admin),
):
    result = await cross_service.revoke_grant(
        db, admin_id=current_user.id, grant_id=grant_id, reason=body.reason, request_meta=_meta(request)
    )
    await db.commit()
    return result


@router.get("/grants", response_model=List[CrossReviewGrantView])
async def list_cross_review_grants(
    active: Optional[bool] = Query(None),
    grantee_user_id: Optional[int] = Query(None, ge=1, le=2147483647),
    unit_id: Optional[int] = Query(None, ge=1, le=2147483647),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_cross_review_admin),
):
    return await cross_service.list_grants(db, active=active, grantee_user_id=grantee_user_id, unit_id=unit_id)


# ------------------------------------------------------------------------------------------------- Người gọi
@router.get("/eligibility", response_model=CrossReviewEligibility)
async def get_cross_review_eligibility(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_active_user),
):
    return await cross_service.eligibility(db, user_id=current_user.id, role=current_user.role)


@router.get("/queue", response_model=CrossReviewQueuePage)
async def get_cross_review_queue(
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_cross_reviewer),
):
    return await cross_service.queue(db, actor=current_user, page=page, page_size=page_size)


async def _cross_action(request: Request, db: AsyncSession, actor_id: int, action: str, body: CrossReviewActionRequest):
    result, finalize = await cross_service.cross_action(
        db,
        actor_id=actor_id,
        action=action,
        grant_id=body.grant_id,
        profile_id=body.profile_id,
        document_row_id=body.document_row_id,
        expected_row_version=body.expected_row_version,
        reason=body.reason,
        request_meta=_meta(request),
    )
    await db.commit()
    await finalize(True)
    return result


@router.post("/verify", response_model=CrossReviewActionResponse)
async def cross_review_verify(
    request: Request,
    body: CrossReviewActionRequest = Depends(deps.get_cross_review_verify_target),
    current_user: models.User = Depends(deps.require_cross_reviewer),
    db: AsyncSession = Depends(database.get_db),
):
    return await _cross_action(request, db, current_user.id, ACTION_VERIFY, body)


@router.post("/reject", response_model=CrossReviewActionResponse)
async def cross_review_reject(
    request: Request,
    body: CrossReviewActionRequest = Depends(deps.get_cross_review_reject_target),
    current_user: models.User = Depends(deps.require_cross_reviewer),
    db: AsyncSession = Depends(database.get_db),
):
    return await _cross_action(request, db, current_user.id, ACTION_REJECT, body)


# ------------------------------------------------------------------------------------------------- Lô chéo (khuôn §5)
@router.post("/bulk-verify/preview", response_model=PreviewResponse, status_code=status.HTTP_201_CREATED)
async def preview_cross_bulk_verify(
    request: Request,
    body: CrossBulkVerifyPreviewRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_cross_verifier),
):
    result = await bulk_service.preview_batch(
        db,
        actor=current_user,
        profile_ids=body.profile_ids,
        filter_=None,
        include_optional=body.include_optional,
        review_mode=bulk_service.REVIEW_MODE_CROSS,
        grant_id=body.grant_id,
        request_meta=_meta(request),
    )
    await db.commit()
    return result


@router.post("/bulk-verify/{batch_id}/execute", response_model=BatchView)
async def execute_cross_bulk_verify(
    request: Request,
    body: BulkVerifyExecuteRequest,
    batch: models.DocumentBulkBatch = Depends(deps.get_cross_bulk_batch_for_execute),
    current_user: models.User = Depends(deps.require_cross_verifier),
    db: AsyncSession = Depends(database.get_db),
):
    batch_id, actor_id = batch.batch_id, current_user.id
    view, post_commit = await bulk_service.execute_batch(
        db,
        batch_id=batch_id,
        actor_id=actor_id,
        confirmation_text=body.confirmation_text,
        review_mode=bulk_service.REVIEW_MODE_CROSS,
        request_meta=_meta(request),
    )
    await post_commit()
    return view


@router.get("/bulk-verify", response_model=BatchListResponse)
async def list_cross_bulk_verify_batches(
    scope: Literal["mine", "all"] = Query("mine"),  # ``all`` ⇒ 403 (cùng vị từ với cờ ``can_view_all`` = false)
    cursor: Optional[str] = Query(None, max_length=500),
    limit: int = Query(bulk_service.BULK_VERIFY_LIST_PAGE_SIZE, ge=1, le=50),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.require_cross_reviewer),
):
    return await bulk_service.list_batches(
        db,
        viewer_id=current_user.id,
        viewer_role=current_user.role,
        scope=scope,
        cursor=cursor,
        limit=limit,
        review_mode=bulk_service.REVIEW_MODE_CROSS,
        allow_scope_all=False,
    )


@router.get("/bulk-verify/{batch_id}", response_model=BatchView)
async def get_cross_bulk_verify_batch(
    batch: models.DocumentBulkBatch = Depends(deps.get_cross_bulk_batch_for_view),
    current_user: models.User = Depends(deps.require_cross_reviewer),
    db: AsyncSession = Depends(database.get_db),
):
    batch_id, viewer_id, viewer_role = batch.batch_id, current_user.id, current_user.role
    return await bulk_service.get_batch(db, batch_id=batch_id, viewer_id=viewer_id, viewer_role=viewer_role)


@router.post("/bulk-verify/{batch_id}/finalize", response_model=FinalizeResponse)
async def finalize_cross_bulk_verify_batch(
    request: Request,
    body: BulkVerifyFinalizeRequest,
    batch: models.DocumentBulkBatch = Depends(deps.get_cross_bulk_batch_for_view),
    current_user: models.User = Depends(deps.require_cross_reviewer),
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
