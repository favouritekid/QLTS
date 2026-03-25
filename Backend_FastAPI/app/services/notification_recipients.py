# app/services/notification_recipients.py
"""
External Recipient Abstraction — Phase B6.

Provides a unified ResolvedRecipient dataclass that supports both
internal (user_id-based) and external (destination-based) recipients.

Internal resolvers continue returning user_ids as before.
This module adds helpers to:
  1. Convert internal users -> ResolvedRecipient
  2. Resolve external contacts (lead, admission_profile, collaborator)

Phase B scope:
  - Foundation only — external resolvers exist but are not live-routed
  - Dispatcher can create delivery rows for external recipients without crash
"""
import logging
from dataclasses import dataclass
from typing import List, Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedRecipient:
    """
    Unified recipient for both internal and external delivery.

    Internal: user_id is set, destination fields are optional convenience.
    External: user_id is None, at least one destination field is set.
    """
    recipient_kind: Literal["internal", "external"]
    user_id: Optional[int] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    destination_email: Optional[str] = None
    destination_phone: Optional[str] = None


def from_user_ids(
    user_ids: List[int],
    source_type: str | None = None,
    source_id: int | None = None,
) -> List[ResolvedRecipient]:
    """Convert a list of internal user IDs to ResolvedRecipient list."""
    return [
        ResolvedRecipient(
            recipient_kind="internal",
            user_id=uid,
            source_type=source_type,
            source_id=source_id,
        )
        for uid in user_ids
    ]


# ============================================================
# External Contact Resolvers (Phase B foundation)
# ============================================================

async def resolve_lead_contact(
    db: AsyncSession,
    lead_id: int,
) -> Optional[ResolvedRecipient]:
    """
    Resolve external contact info for a lead.

    Returns a ResolvedRecipient with destination_email/phone from the lead record.
    Returns None if lead not found or has no contact info.
    """
    try:
        result = await db.execute(
            select(models.Lead).where(models.Lead.id == lead_id)
        )
        lead = result.scalars().first()
        if not lead:
            return None

        email = getattr(lead, "email", None)
        phone = getattr(lead, "phone", None)

        if not email and not phone:
            return None

        return ResolvedRecipient(
            recipient_kind="external",
            source_type="lead",
            source_id=lead_id,
            destination_email=email,
            destination_phone=phone,
        )
    except Exception as e:
        log.warning("Failed to resolve lead contact: %s", e)
        return None


async def resolve_admission_contact(
    db: AsyncSession,
    profile_id: int,
) -> Optional[ResolvedRecipient]:
    """
    Resolve external contact info for an admission profile.

    Returns a ResolvedRecipient with destination from the linked lead.
    """
    try:
        result = await db.execute(
            select(models.AdmissionProfile).where(
                models.AdmissionProfile.id == profile_id
            )
        )
        profile = result.scalars().first()
        if not profile or not profile.lead_id:
            return None

        return await resolve_lead_contact(db, profile.lead_id)
    except Exception as e:
        log.warning("Failed to resolve admission contact: %s", e)
        return None


async def resolve_collaborator_contact(
    db: AsyncSession,
    collaborator_id: int,
) -> Optional[ResolvedRecipient]:
    """
    Resolve external contact info for a collaborator.

    Collaborators may have a linked user_id (internal) or just contact info (external).
    """
    try:
        result = await db.execute(
            select(models.Collaborator).where(
                models.Collaborator.id == collaborator_id
            )
        )
        collab = result.scalars().first()
        if not collab:
            return None

        # If collaborator has a linked user, treat as internal
        if collab.user_id:
            return ResolvedRecipient(
                recipient_kind="internal",
                user_id=collab.user_id,
                source_type="collaborator",
                source_id=collaborator_id,
            )

        # Otherwise external with contact info
        email = getattr(collab, "email", None)
        phone = getattr(collab, "phone", None)

        if not email and not phone:
            return None

        return ResolvedRecipient(
            recipient_kind="external",
            source_type="collaborator",
            source_id=collaborator_id,
            destination_email=email,
            destination_phone=phone,
        )
    except Exception as e:
        log.warning("Failed to resolve collaborator contact: %s", e)
        return None


# Registry for external contact resolvers
EXTERNAL_RESOLVER_REGISTRY = {
    "lead_contact": resolve_lead_contact,
    "admission_contact": resolve_admission_contact,
    "collaborator_contact": resolve_collaborator_contact,
}
