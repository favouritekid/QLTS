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


# =============================================================================
# ✅ PHASE 2.2: Notification Rule Schemas
# =============================================================================


class NotificationRuleBase(BaseModel):
    """Base schema for notification rule"""
    event: str  # SystemEvents enum value (e.g., "LEAD_ASSIGNED")
    title_template: str  # Template with {placeholders}
    message_template: str  # Message template
    notification_type: str = "info"  # info, success, warning, error
    link_template: Optional[str] = None  # Optional link template
    channels: List[str] = ["browser"]  # ["browser", "email", "sms"]
    recipient_config: Dict[str, Any]  # {resolver_type, params}
    condition: Optional[Dict[str, Any]] = None  # Optional conditions
    enabled: bool = True  # Enable/disable rule


class NotificationRuleCreate(NotificationRuleBase):
    """Schema for creating a notification rule"""
    pass


class NotificationRuleUpdate(BaseModel):
    """Schema for updating a notification rule (partial update)"""
    title_template: Optional[str] = None
    message_template: Optional[str] = None
    notification_type: Optional[str] = None
    link_template: Optional[str] = None
    channels: Optional[List[str]] = None
    recipient_config: Optional[Dict[str, Any]] = None
    condition: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None


class NotificationRule(NotificationRuleBase):
    """Schema for reading notification rule (response)"""
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationRulesPage(BaseModel):
    """Paginated notification rules response"""
    total_count: int
    rules: List[NotificationRule]


# =============================================================================
# ✅ PHASE 3.1: Notification Template Schemas
# =============================================================================


class NotificationTemplateBase(BaseModel):
    """Base schema for notification template"""
    name: str  # Unique template name
    description: Optional[str] = None  # Template description
    title_template: str  # Title template with {placeholders}
    message_template: str  # Message template
    link_template: Optional[str] = None  # Optional link template
    variables: Optional[List[str]] = None  # Available variables
    category: Optional[str] = None  # Template category (lead, consultation, etc.)


class NotificationTemplateCreate(NotificationTemplateBase):
    """Schema for creating a notification template"""
    is_system: bool = False  # System template flag


class NotificationTemplateUpdate(BaseModel):
    """Schema for updating a notification template (partial update)"""
    name: Optional[str] = None
    description: Optional[str] = None
    title_template: Optional[str] = None
    message_template: Optional[str] = None
    link_template: Optional[str] = None
    variables: Optional[List[str]] = None
    category: Optional[str] = None


class NotificationTemplate(NotificationTemplateBase):
    """Schema for reading notification template (response)"""
    id: int
    is_system: bool
    usage_count: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationTemplatesPage(BaseModel):
    """Paginated notification templates response"""
    total_count: int
    templates: List[NotificationTemplate]
