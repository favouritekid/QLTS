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
# ✅ PHASE 2.2 + FIX: Notification Rule Schemas (with validation)
# =============================================================================


class RecipientConfig(BaseModel):
    """
    Schema for recipient resolver configuration.

    Validates resolver_type and params structure.

    Example:
        {"resolver_type": "lead_owner", "params": {}}
        {"resolver_type": "composite", "params": {"resolvers": [...]}}
    """
    resolver_type: str  # Resolver type (lead_owner, unit_staff, all_admins, etc.)
    params: Dict[str, Any] = {}  # Resolver-specific parameters


class NotificationRuleBase(BaseModel):
    """Base schema for notification rule (with validation)"""
    event: str  # SystemEvents enum value (e.g., "LEAD_ASSIGNED")
    title_template: str  # Template with {placeholders}
    message_template: str  # Message template
    notification_type: str = "info"  # info, success, warning, error
    link_template: Optional[str] = None  # Optional link template
    channels: List[str] = ["browser"]  # ["browser", "email", "sms"]

    # ✅ Now typed with validation
    recipient_config: RecipientConfig  # Validated resolver config
    condition: Optional[Dict[str, Any]] = None  # Optional conditions (validated at runtime)

    enabled: bool = True  # Enable/disable rule
    template_id: Optional[int] = None  # ✅ Optional template reference


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


# =============================================================================
# ✅ FIX: Edge Case #4 - JSON Schema Validation (Condition Models)
# =============================================================================


class SimpleCondition(BaseModel):
    """
    Schema for simple condition (field-operator-value).

    Example:
        {"field": "status", "operator": "eq", "value": "active"}
    """
    field: str  # Field name from payload (e.g., "lead.status")
    operator: str  # Comparison operator (eq, ne, gt, gte, lt, lte, in, not_in, contains)
    value: Any  # Expected value to compare against


class CompoundCondition(BaseModel):
    """
    Schema for compound condition (nested AND/OR groups).

    Example:
        {
            "operator": "and",
            "conditions": [
                {"field": "status", "operator": "eq", "value": "active"},
                {
                    "operator": "or",
                    "conditions": [...]
                }
            ]
        }
    """
    operator: str  # "and" or "or"
    conditions: List[Any]  # List of SimpleCondition or CompoundCondition (recursive)

    class Config:
        # Allow recursive validation
        arbitrary_types_allowed = True


# Union type for condition validation
Condition = SimpleCondition | CompoundCondition | None
