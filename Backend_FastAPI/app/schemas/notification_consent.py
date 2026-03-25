# app/schemas/notification_consent.py
"""Schemas for NotificationConsent API."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class NotificationConsentUpsert(BaseModel):
    """Request to upsert a single consent record."""
    channel: str
    source_type: str
    source_id: int
    consent_status: str = "granted"  # granted | revoked
    normalized_phone: Optional[str] = None
    normalized_email: Optional[str] = None
    consent_source: str = "manual"
    notes: Optional[str] = None


class NotificationConsentResponse(BaseModel):
    """Single consent record response."""
    id: int
    channel: str
    source_type: str
    source_id: int
    normalized_phone: Optional[str] = None
    normalized_email: Optional[str] = None
    consent_status: str
    consent_source: str
    granted_by: Optional[int] = None
    granted_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationConsentsPage(BaseModel):
    """Paginated consent list response."""
    total_count: int
    consents: List[NotificationConsentResponse]


class NotificationConsentImportResult(BaseModel):
    """Result of CSV bulk import."""
    processed: int
    granted: int
    revoked: int
    skipped: int
    errors: List[Dict[str, Any]]
