# app/routers/users.py
from fastapi import APIRouter, Depends, Request

from .. import models, schemas
from ..core import deps
from app.core.rate_limits import limiter, RateLimits

router = APIRouter(tags=["Users"])


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/me", response_model=schemas.User)
async def read_users_me(
    request: Request,
    current_user: models.User = Depends(deps.get_current_active_user)
):
    """
    Lấy thông tin của chính người dùng đang đăng nhập.

    Endpoint này được bảo vệ. Bạn phải cung cấp một Bearer Token hợp lệ.
    """
    return current_user