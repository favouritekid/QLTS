# app/schemas/notification_delivery.py
"""Schemas for NotificationDelivery admin ops API."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


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


# --- Phase D1: Quota schemas ---

class QuotaResponse(BaseModel):
    """Single quota record."""
    id: int
    channel: str
    provider: str
    period: str
    period_start: str
    quota_limit: int
    quota_used: int
    quota_remaining: Optional[int] = None
    blocked: bool = False
    usage_pct: float = 0.0


class QuotaListResponse(BaseModel):
    """List of quota records."""
    quotas: List[QuotaResponse] = []


# --- Phase D2: Circuit Breaker schemas ---

class CircuitBreakerState(BaseModel):
    """Single channel breaker state."""
    channel: str
    state: str  # "closed", "open", "half_open"
    fail_count: int = 0
    fail_max: int = 10
    timeout_duration: int = 300
    opened_at: Optional[datetime] = None


class CircuitBreakerListResponse(BaseModel):
    """All channel breaker states."""
    breakers: List[CircuitBreakerState] = []


# --- Phase D5: Dashboard schemas ---

class TimeSeriesBucket(BaseModel):
    bucket: datetime
    total: int = 0
    sent: int = 0
    failed: int = 0
    queued: int = 0

class TimeSeriesResponse(BaseModel):
    interval: str
    buckets: List[TimeSeriesBucket] = []

class TopEventStats(BaseModel):
    event: str
    total: int = 0
    failed: int = 0
    fail_rate: float = 0.0

class TopEventsResponse(BaseModel):
    events: List[TopEventStats] = []

class LatencyStats(BaseModel):
    p50_seconds: Optional[float] = None
    p95_seconds: Optional[float] = None
    sample_count: int = 0

class ChannelHealthItem(BaseModel):
    channel: str
    breaker_state: str = "closed"
    quota_used: Optional[int] = None
    quota_limit: Optional[int] = None
    quota_blocked: bool = False
    # Ratio (0..1), NOT percent. Frontend `ChannelHealthPanel` and
    # `AlertBanner` apply ×100 to render as a percentage. Aligned with
    # `top_events.fail_rate` (PR #144) and `get_failure_rate()` repo
    # contract.
    failure_rate_24h: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Ratio (0..1) of failed deliveries over total in the last 24 hours; FE multiplies by 100 to display percent.",
    )

class HealthSummaryResponse(BaseModel):
    channels: List[ChannelHealthItem] = []
    total_queued: int = 0
    # Ratio (0..1), NOT percent. See `ChannelHealthItem.failure_rate_24h`.
    failure_rate_30m: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Ratio (0..1) of failed deliveries over total in the last 30 minutes; FE multiplies by 100 to display percent.",
    )
    alerts_active: int = 0
