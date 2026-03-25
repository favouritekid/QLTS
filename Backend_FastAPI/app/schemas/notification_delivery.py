# app/schemas/notification_delivery.py
"""Schemas for NotificationDelivery admin ops API."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class NotificationDeliveryResponse(BaseModel):
    """Single delivery record response."""
    id: int
    notification_id: Optional[int] = None
    event: str
    channel: str
    recipient_kind: str
    user_id: Optional[int] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    destination: Optional[str] = None
    status: str
    error_reason: Optional[str] = None
    dedupe_key: Optional[str] = None
    rule_id: Optional[int] = None
    action_step: Optional[int] = None
    template_code: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationDeliveriesPage(BaseModel):
    """Paginated delivery list response."""
    total_count: int
    deliveries: List[NotificationDeliveryResponse]
