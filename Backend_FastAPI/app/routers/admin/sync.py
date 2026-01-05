# app/routers/admin/sync.py
"""
Casbin-DB Sync Router (Alias/Backward Compatible)

This router provides backward-compatible endpoints for sync operations
that were originally under /api/admin/sync/* before the refactoring.

After PHASE 2A refactoring, these endpoints moved to /api/admin/users/sync/*
but we keep these aliases to match Casbin policies in main.py.

Endpoints:
- GET /api/admin/sync/status → Delegates to users.get_sync_status()
- POST /api/admin/sync → Delegates to users.sync_users()

IMPORTANT: These are ALIASES only. The actual implementation is in users.py.
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import CasbinAuth  # Phase 2.2


# Router definition
router = APIRouter(prefix="/sync", tags=["Admin - Sync (Aliases)"])


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/status")
async def get_sync_status_alias(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep
):
    """
    (Admin only) Alias for /api/admin/users/sync/status

    Kiểm tra tình trạng đồng bộ giữa DB (user.role) và Casbin (grouping policies).
    Trả về số lượng user đã sync, chưa sync, và chi tiết các user bị lệch.

    **Note:** This is an alias endpoint for backward compatibility.
    The actual implementation is in `app.routers.admin.users.get_sync_status()`
    """
    # Import here to avoid circular dependency
    from . import users

    return await users.get_sync_status(request, db, current_admin)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post("")
async def sync_users_alias(
    request: Request,
    sync_request: schemas.SyncUsersRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Alias for /api/admin/users/sync

    Đồng bộ role từ Casbin về DB cho tất cả users hoặc một nhóm users cụ thể.
    Casbin được coi là source of truth (nguồn chân lý).

    - `user_ids`: Danh sách ID users cần sync. Nếu None hoặc rỗng, sync tất cả users.

    **Note:** This is an alias endpoint for backward compatibility.
    The actual implementation is in `app.routers.admin.users.sync_users()`
    """
    # Import here to avoid circular dependency
    from . import users

    return await users.sync_users(request, sync_request, db, current_admin)