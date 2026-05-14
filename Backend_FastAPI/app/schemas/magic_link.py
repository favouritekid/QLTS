"""PR-CO-2-BE / PR-3E: Pydantic schemas for the multi-action magic-link
consume endpoint.

Action enum locked to 4 values matching the DB CHECK constraint at
``AdmissionConfirmationToken.action_type`` (see
``alembic/versions/phase1_18_extend_confirmation_token_for_multi_action.py``).
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MagicLinkAction(str, Enum):
    """4-action enum locked by DB CHECK at admission_confirmation_token."""
    SUBMIT = "submit"
    RESUBMIT = "resubmit"
    CONFIRM = "confirm"
    WITHDRAW = "withdraw"


class MagicLinkConsumeRequest(BaseModel):
    """POST body for /api/v2/admissions/magic-link/{action}/{token}.

    ``cccd`` is the last 4 digits of the candidate's CCCD (citizen ID).
    The service constant-time compares it against
    ``profile.citizen_id[-4:]`` via ``hmac.compare_digest``. Matches the
    existing single-action /confirm/{token} contract — keeps the FE
    keypad UX (4-digit) unchanged.
    """
    cccd: str = Field(
        ...,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="Last 4 digits of citizen ID",
    )


class MagicLinkConsumeResponse(BaseModel):
    """Response when a token is successfully consumed."""
    message: str
    profile_id: int
    action: MagicLinkAction
    status: str
    consumed_at: datetime
    next_url: Optional[str] = Field(
        default=None,
        description="Optional FE redirect target after success",
    )
