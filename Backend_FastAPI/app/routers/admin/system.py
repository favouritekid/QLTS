# app/routers/admin/system.py
"""
System Management Admin Router

Handles system-wide operations including:
- System Alerts (critical notifications)
- System Announcements (general messages)

Created: 2025-12-02 for NOTIFICATION 2.0 dispatch events
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

from typing import Optional
from datetime import datetime

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import CasbinAuth  # Phase 2.2
from app.core.event_catalog import is_safe_notification_link
from app.services.notification_dispatcher import _all_role_rooms, safe_dispatch
from app.core.events import SystemEvents

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - System Management"])



# ============================================================================
# SYSTEM ALERTS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/system/alert",
    status_code=status.HTTP_201_CREATED,
    summary="Create system-wide alert",
)
async def create_system_alert(
    request: Request,
    severity: str,  # info, warning, error
    message: str,
    action_url: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Create a system-wide alert notification.

    **Severity levels:**
    - info: Informational (blue)
    - warning: Warning (yellow/orange)
    - error: Critical (red)

    **Use cases:**
    - Maintenance announcements
    - System downtime warnings
    - Critical security alerts
    - Feature deprecation notices

    **Delivery:**
    - Sent to ALL active users
    - Displayed in notification center
    - Can include action URL for more info
    - Optional expiration time

    **Example:**
    ```json
    {
        "severity": "warning",
        "message": "System maintenance scheduled at 2AM-4AM UTC",
        "action_url": "/maintenance-info",
        "expires_at": "2025-12-03T04:00:00Z"
    }
    ```
    """
    # 🔒 D8-17 — CHẶN Ở NGAY CỬA VÀO, không chỉ ở link đã lưu.
    #
    # ``render_link`` gác ``notification.link`` nên cột ấy luôn sạch. Nhưng
    # CÙNG một ``action_url`` còn đi ra ngoài qua HAI đường KHÁC, cả hai đều
    # mang chuỗi THÔ, không qua vị từ nào ở backend:
    #
    #   1. ``_emit_domain_event`` phát nguyên ``payload`` qua Socket.IO tới
    #      toàn bộ ma trận role room ⇒ frontend
    #      ``SocketHandler.tsx`` đọc ``data.action_url`` và gán thẳng vào
    #      ``window.location.href``.
    #   2. ``notification.data`` (dispatcher trộn nguyên payload vào) ⇒
    #      ``GET /notifications`` và sự kiện socket ``notification``.
    #
    # Chặn ở mỗi sink là bốn nhánh phải nhớ; chặn ở ingress là MỘT. Tầng
    # chủ sở hữu của bất biến "action_url do người dùng nhập phải là đường
    # nội bộ" là ĐÚNG chỗ này — nơi chuỗi không tin cậy bước vào hệ thống.
    # ``render_link`` vẫn giữ nguyên vai trò phòng thủ chiều sâu cho mọi
    # event khác.
    #
    # Hành vi: TỪ CHỐI to tiếng (400). KHÔNG sửa đầu vào thành ``/``,
    # KHÔNG âm thầm bỏ link. Chuỗi được KIỂM chính là chuỗi được ĐƯA vào
    # payload — không cắt, không chuẩn hoá ở giữa.
    #
    # ⚠️ ĐỔI HỢP ĐỒNG, ghi rõ: trước bản vá endpoint trả 201 cho MỌI
    # ``action_url`` (kể cả ``javascript:``/``//evil``) rồi lặng lẽ bỏ link
    # trong khi vẫn phát chuỗi thô lên socket. Nay ``action_url`` không đạt
    # ⇒ 400 và KHÔNG có thông báo nào được tạo.
    if action_url not in (None, "") and not is_safe_notification_link(action_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "action_url phải là đường dẫn nội bộ bắt đầu bằng '/' "
                "(không '//', không scheme, không backslash, không ký tự "
                "điều khiển, không khoảng trắng bao ngoài)."
            ),
        )

    # ✅ NOTIFICATION 2.0: Dispatch SYSTEM_ALERT.
    # SYSTEM_ALERT is catalog-sensitive; admin-triggered broadcast must
    # pass the full role matrix explicitly (no implicit all-users fanout).
    # Use ``_all_role_rooms()`` helper so adding a new ``UserRole`` value
    # (e.g. ``COLLABORATOR``) automatically picks up here without
    # forgetting to extend a hardcoded list — silent broadcast gap to
    # the new role would otherwise be invisible until a complaint.
    await safe_dispatch(
        db=db,
        event=SystemEvents.SYSTEM_ALERT,
        payload={
            "severity": severity,
            "message": message,
            "action_url": action_url,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
        dedupe_key=f"system_alert:{datetime.utcnow().isoformat()}",
        rooms=_all_role_rooms(),
    )

    log.info(
        "System alert created",
        severity=severity,
        admin_id=current_admin.id,
        message=message[:50]
    )

    return {
        "success": True,
        "message": "System alert dispatched to all users",
        "severity": severity,
        "created_by": current_admin.username,
    }


# ============================================================================
# SYSTEM ANNOUNCEMENTS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/system/announcement",
    status_code=status.HTTP_201_CREATED,
    summary="Create system-wide announcement",
)
async def create_system_announcement(
    request: Request,
    title: str,
    message: str,
    priority: str = "normal",  # normal, high
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
):
    """
    (Admin only) Create a system-wide announcement.

    **Priority levels:**
    - normal: Regular announcement (default)
    - high: Important announcement (highlighted)

    **Use cases:**
    - New feature releases
    - Policy updates
    - Event notifications
    - General communications

    **Delivery:**
    - Sent to ALL active users
    - Displayed in notification center
    - Users can dismiss after reading

    **Example:**
    ```json
    {
        "title": "New Feature: Lead Import from Excel",
        "message": "You can now import leads in bulk using Excel files. See User Guide for details.",
        "priority": "high"
    }
    ```
    """
    # ✅ NOTIFICATION 2.0: Dispatch SYSTEM_ANNOUNCEMENT
    await safe_dispatch(
        db=db,
        event=SystemEvents.SYSTEM_ANNOUNCEMENT,
        payload={
            "title": title,
            "message": message,
            "priority": priority,
            "actor_id": current_admin.id,
        },
        dedupe_key=f"system_announcement:{datetime.utcnow().isoformat()}"
    )

    log.info(
        "System announcement created",
        priority=priority,
        admin_id=current_admin.id,
        title=title
    )

    return {
        "success": True,
        "message": "System announcement dispatched to all users",
        "title": title,
        "priority": priority,
        "created_by": current_admin.username,
    }