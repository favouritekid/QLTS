# app/routers/users.py
from fastapi import APIRouter

from .. import models, schemas
from ..core import deps

router = APIRouter(tags=["Users"])


@router.get("/me", response_model=schemas.User)
async def read_users_me(current_user: models.User = deps.CurrentUser):
    """
    Lấy thông tin của chính người dùng đang đăng nhập.

    Endpoint này được bảo vệ. Bạn phải cung cấp một Bearer Token hợp lệ.
    """
    return current_user
