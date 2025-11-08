# app/schemas/notification.py
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class NotificationBase(BaseModel):
    """Base schema for notification"""
    type: str = "info"  # info, success, warning, error, admin_update, system
    title: str
    message: str
    link: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class NotificationCreate(NotificationBase):
    """Schema for creating a notification"""
    user_id: int


class Notification(NotificationBase):
    """Schema for reading notification"""
    id: int
    user_id: int
    is_read: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationsPage(BaseModel):
    """Paginated notifications response"""
    total_count: int
    unread_count: int
    notifications: List[Notification]


class MarkAsReadRequest(BaseModel):
    """Request to mark notifications as read"""
    notification_ids: List[int]
