# app/routers/notification_preferences.py
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import notification_preference_service

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Notification Preferences"])
PermissionDep = Depends(deps.check_permission)


@router.get("/preferences", response_model=schemas.NotificationPreference)
async def get_notification_preferences(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Get user's notification preferences."""
    preference = await notification_preference_service.get_user_preference(
        db, current_user.id
    )

    return preference


@router.put("/preferences", response_model=schemas.NotificationPreference)
async def update_notification_preferences(
    preference_update: schemas.NotificationPreferenceUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Update user's notification preferences."""
    preference = await notification_preference_service.update_user_preference(
        db, current_user.id, preference_update
    )

    log.info(
        "User updated notification preferences",
        user_id=current_user.id,
        username=current_user.username,
    )

    return preference
