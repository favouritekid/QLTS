# app/schemas/user_session.py
"""
Pydantic schemas for UserSession model.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserSessionBase(BaseModel):
    """Base schema for UserSession."""

    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_type: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None


class UserSessionCreate(UserSessionBase):
    """Schema for creating a new session."""

    user_id: int
    refresh_jti: str = Field(..., min_length=36, max_length=36)
    expires_at: datetime
    is_suspicious: bool = False


class UserSessionUpdate(BaseModel):
    """Schema for updating session (mainly last_activity_at and refresh_jti)."""

    refresh_jti: Optional[str] = Field(None, min_length=36, max_length=36)
    last_activity_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class UserSessionResponse(UserSessionBase):
    """Schema for returning session data to client."""

    id: int
    user_id: int
    refresh_jti: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    is_suspicious: bool
    revoked_at: Optional[datetime] = None

    # Computed fields
    is_active: bool = Field(
        default=True,
        description="Whether session is active (not revoked and not expired)",
    )
    is_current: bool = Field(
        default=False, description="Whether this is the current session"
    )

    model_config = ConfigDict(from_attributes=True)


class UserSessionListResponse(BaseModel):
    """Schema for returning list of sessions."""

    sessions: list[UserSessionResponse]
    total: int
    current_session_id: Optional[int] = None
