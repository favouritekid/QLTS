# app/routers/admission_review_secretary.py
"""API GĐ2-C C1 — quyền "Thư ký Hội đồng" (ĐT3 §11: ``GET / POST · POST`` ``/review-secretaries`` · ``/{grant_id}/revoke`` —
Admin) + ``GET /review-secretaries/candidates`` (ô tìm người của màn hình gán — owner 22-11 câu 3). Router MỎNG: kiểm quyền ở
``deps``, luật ở ``review_secretary_service``, router commit.

Dưới tiền tố ``/api/admission-config`` — tiền tố ĐÃ nằm trong ``FROZEN_PREFIXES`` (``app/middleware/admission_freeze.py``) và
khối đóng băng của nginx ⇒ cần gạt đóng băng tuyển sinh chặn hai route GHI ở đây (503). Module khai trong
``ADMISSION_ROUTER_MODULES``, hai route ghi trong ``ADMISSION_WRITE_ROUTES``.

Quyền: ``CasbinAuth`` (chỉ admin có dòng — wildcard; KHÔNG thêm dòng Casbin) + ``deps.require_review_secretary_admin`` (lớp
phụ fail-closed). Module riêng (không nhét vào ``admission_review``) để khỏi đụng các route lần xét của GĐ2-B khi gộp.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.client_ip import get_client_ip
from ..core.rate_limits import RateLimits, limiter
from ..schemas.review_secretary import (
    INT4_MAX,
    ReviewSecretaryCandidate,
    ReviewSecretaryGrantCreate,
    ReviewSecretaryGrantRevoke,
    ReviewSecretaryGrantView,
)
from ..services import review_secretary_service as secretary_service
from ..services.document_transition import RequestMeta

#: Tiền tố (dưới ``/api``) — dùng chung tiền tố đã đóng băng của cấu hình tuyển sinh.
ROUTER_PREFIX = "/admission-config"

router = APIRouter(prefix=ROUTER_PREFIX, tags=["Lần xét tuyển GĐ2-C — Thư ký Hội đồng"])


def _meta(request: Request) -> RequestMeta:
    return RequestMeta(get_client_ip(request), request.headers.get("user-agent"))


@router.get(
    "/review-secretaries",
    response_model=List[ReviewSecretaryGrantView],
    summary="Danh sách quyền Thư ký Hội đồng (mới nhất trước; lọc còn hiệu lực / theo người)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_review_secretaries(
    request: Request,
    active: Optional[bool] = Query(None),
    user_id: Optional[int] = Query(None, ge=1, le=INT4_MAX),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_secretary_admin),
    db: AsyncSession = Depends(database.get_db),
):
    return await secretary_service.list_grants(db, active=active, user_id=user_id)


@router.get(
    "/review-secretaries/candidates",
    response_model=List[ReviewSecretaryCandidate],
    summary="Ứng viên gán Thư ký: Quản lý / Cán bộ đang hoạt động, chưa có quyền; tìm theo họ tên / tên đăng nhập / email",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_review_secretary_candidates(
    request: Request,
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=secretary_service.CANDIDATE_LIMIT_MAX),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_secretary_admin),
    db: AsyncSession = Depends(database.get_db),
):
    return await secretary_service.list_candidates(db, q=q, limit=limit)


@router.post(
    "/review-secretaries",
    response_model=ReviewSecretaryGrantView,
    status_code=status.HTTP_201_CREATED,
    summary="Gán quyền Thư ký Hội đồng cho một Quản lý / Cán bộ (lý do bắt buộc; không hết hạn)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def create_review_secretary(
    request: Request,
    body: ReviewSecretaryGrantCreate,
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_secretary_admin),
    db: AsyncSession = Depends(database.get_db),
):
    result = await secretary_service.create_grant(
        db, admin_id=current_user.id, user_id=body.user_id, reason=body.reason, request_meta=_meta(request)
    )
    await db.commit()
    return result


@router.post(
    "/review-secretaries/{grant_id}/revoke",
    response_model=ReviewSecretaryGrantView,
    summary="Thu hồi quyền Thư ký Hội đồng (lý do bắt buộc; chỉ thu hồi, không xoá)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def revoke_review_secretary(
    request: Request,
    body: ReviewSecretaryGrantRevoke,
    grant_id: int = Path(..., ge=1, le=INT4_MAX),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_secretary_admin),
    db: AsyncSession = Depends(database.get_db),
):
    result = await secretary_service.revoke_grant(
        db, admin_id=current_user.id, grant_id=grant_id, reason=body.reason, request_meta=_meta(request)
    )
    await db.commit()
    return result
