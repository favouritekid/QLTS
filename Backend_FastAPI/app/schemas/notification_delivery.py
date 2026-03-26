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
    payload_snapshot: Optional[Dict[str, Any]] = None
    provider_message_id: Optional[str] = None
    dedupe_key: Optional[str] = None
    rule_id: Optional[int] = None
    action_step: Optional[int] = None
    template_code: Optional[str] = None
    # C1 worker fields
    scheduled_for: Optional[datetime] = None
    attempt_count: int = 0
    last_attempt_at: Optional[datetime] = None
    # C2 retry/dead-letter fields
    next_retry_at: Optional[datetime] = None
    max_retries: int = 5
    dead_lettered_at: Optional[datetime] = None
    # Timestamps
    created_at: datetime
    updated_at: datetime
    sent_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationDeliveriesPage(BaseModel):
    """Paginated delivery list response."""
    total_count: int
    deliveries: List[NotificationDeliveryResponse]


class ReplayResponse(BaseModel):
    """Response for delivery replay action."""
    replayed: bool
    delivery_id: int
    message: str = ""


class DeliveryStatsResponse(BaseModel):
    """Aggregate delivery stats."""
    total: int = 0
    by_status: Dict[str, int] = {}
    by_channel: Dict[str, int] = {}
    success_rate: float = 0.0


class FailureReasonCount(BaseModel):
    """Single failure reason with count."""
    error_reason: str
    count: int
    latest_at: Optional[datetime] = None


class DeliveryFailureSummary(BaseModel):
    """Failure analytics grouped by reason."""
    total_failures: int = 0
    by_reason: List[FailureReasonCount] = []
