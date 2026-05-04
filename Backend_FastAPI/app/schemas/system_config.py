# app/schemas/system_config.py
"""SystemConfig Pydantic schemas (#184 Wave 1 PR-1D / phase1_13).

Admin endpoint payload contract for ``GET /api/v2/admin/system-config``
+ ``GET /api/v2/admin/system-config/{key}`` + ``PATCH /api/v2/admin/
system-config/{key}``. Service layer (``SystemConfigService``) owns
the admin-only governance guard.

The ``value`` field is intentionally typed as ``Any`` because the
table holds heterogeneous JSONB shapes (bool / int / list / nested
object). Callers that consume specific keys cast to the expected
shape at use-site; SystemConfigService does NOT validate the inner
shape (admin's responsibility per Q10 governance scope).
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class SystemConfigResponse(BaseModel):
    """Single config row response."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any = Field(
        description=(
            "Config value — any JSON shape (bool, int, list, nested "
            "object). Caller casts to expected type at use-site."
        ),
    )
    description: Optional[str] = None
    updated_at: datetime
    updated_by_user_id: Optional[int] = None


class SystemConfigUpdate(BaseModel):
    """Admin PATCH payload for a single config key.

    ``value`` is REQUIRED — admin always commits a new value. To
    "clear" a key, admin should send an explicit ``null`` /
    ``false`` / ``0`` / ``""`` rather than DELETE the row, so the
    audit row + ``description`` survive.

    ``description`` is optional — admin can edit the docstring
    independently or alongside the value.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any = Field(
        description=(
            "New config value. Any JSON shape; service does not "
            "validate inner structure."
        ),
    )
    description: Optional[str] = Field(
        default=None,
        description=(
            "Optional. Update the admin-facing docstring "
            "alongside the value."
        ),
    )


class SystemConfigListResponse(BaseModel):
    """List response for admin overview."""

    total: int
    items: list[SystemConfigResponse]
