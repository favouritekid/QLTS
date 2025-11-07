# app/schemas/user_activity.py
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class UserActivityLogBase(BaseModel):
    """Base schema for user activity log"""
    action: str
    resource_type: str
    resource_id: Optional[int] = None
    description: Optional[str] = None
    changes: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class UserActivityLogCreate(UserActivityLogBase):
    """Schema for creating a new activity log"""
    actor_id: Optional[int] = None
    target_user_id: Optional[int] = None


class UserActivityLog(UserActivityLogBase):
    """Schema for reading activity log"""
    id: int
    actor_id: Optional[int] = None
    target_user_id: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserActivityLogWithDetails(UserActivityLog):
    """Activity log with actor and target user details"""
    actor_username: Optional[str] = None
    actor_full_name: Optional[str] = None
    target_username: Optional[str] = None
    target_full_name: Optional[str] = None


class ActivityLogsPage(BaseModel):
    """Paginated activity logs response"""
    total_count: int
    logs: List[UserActivityLogWithDetails]


class UserStatistics(BaseModel):
    """User statistics for dashboard"""
    total_users: int
    active_users: int
    pending_users: int
    banned_users: int
    new_users_last_7_days: int
    new_users_last_30_days: int
    users_by_role: Dict[str, int]
    recent_activities: List[UserActivityLogWithDetails]
