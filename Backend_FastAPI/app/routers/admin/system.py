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
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import CasbinAuth  # Phase 2.2
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