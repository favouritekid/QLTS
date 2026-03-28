# app/services/notification_payloads.py
"""
EventPayload builder — canonical payload factory for all Lead-module notification events.

Each static method returns a dict that matches the exact contract expected by
notification_dispatcher.dispatch().  Callers pass primitives and top-level model
attributes; the builder never touches ORM relationships.

Phase 1 scope: Lead + Consultation events.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


class EventPayload:
    """Canonical payload builders for notification events."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _actor_info(actor) -> dict:
        if actor is None:
            return {"actor_id": 0, "actor_name": "System"}
        return {
            "actor_id": actor.id,
            "actor_name": getattr(actor, "full_name", None) or getattr(actor, "username", "Unknown"),
        }

    @staticmethod
    def dedupe_key(event_name: str, *parts) -> str:
        """Match existing convention: {snake_case_event}:{primary_id}[:{secondary_id}]"""
        return f"{event_name}:{':'.join(str(p) for p in parts)}"

    # ------------------------------------------------------------------
    # LEAD events
    # ------------------------------------------------------------------

    @staticmethod
    def for_lead_created(lead, actor) -> dict:
        return {
            "lead_id": lead.id,
            "unit_id": lead.unit_id,
            "lead_name": lead.full_name or "Unknown",
            "source": lead.source or "Unknown",
            **EventPayload._actor_info(actor),
        }

    @staticmethod
    def for_lead_assigned(
        lead,
        officer_id: int,
        actor,
        *,
        offering_name: str = "N/A",
        is_automatic: bool = False,
        assignment_method: str = "manual",
    ) -> dict:
        actor_info = EventPayload._actor_info(actor)
        if is_automatic and actor is None:
            actor_info["actor_name"] = "System (Auto Assignment)"
        payload: Dict[str, Any] = {
            "lead_id": lead.id,
            "officer_id": officer_id,
            **actor_info,
            "lead_name": lead.full_name or "Unknown",
            "lead_phone": lead.phone or "",
            "offering_name": offering_name,
        }
        if is_automatic:
            payload["is_automatic"] = True
            payload["assignment_method"] = assignment_method
        return payload

    @staticmethod
    def for_lead_assignment_failed(lead, unit_id: int, reason: str) -> dict:
        return {
            "lead_id": lead.id if hasattr(lead, "id") else lead,
            "unit_id": unit_id,
            "reason": reason,
            "lead_name": lead.full_name or "Unknown" if hasattr(lead, "full_name") else "Unknown",
            "actor_id": 0,
            "actor_name": "System",
        }

    @staticmethod
    def for_lead_reassigned(
        lead_id: int,
        actor,
        *,
        old_officer_id: Optional[int],
        new_officer_id: Optional[int],
        old_unit_id: int,
        new_unit_id: int,
        reason: str,
        notify_user_ids: Optional[List[int]] = None,
    ) -> dict:
        return {
            "lead_id": lead_id,
            "old_officer_id": old_officer_id,
            "new_officer_id": new_officer_id,
            "old_unit_id": old_unit_id,
            "new_unit_id": new_unit_id,
            **EventPayload._actor_info(actor),
            "reason": reason,
            "user_ids": notify_user_ids if notify_user_ids is not None else [],
        }

    @staticmethod
    def for_lead_status_changed(
        lead,
        actor,
        *,
        old_status,
        new_status,
        officer_name: Optional[str] = None,
        old_stage=None,
        new_stage=None,
        updated_fields=None,
    ) -> dict:
        payload: Dict[str, Any] = {
            "lead_id": lead.id,
            "lead_name": lead.full_name or getattr(lead, "email", None) or f"Lead #{lead.id}",
            "officer_id": lead.assigned_officer_id,
            "officer_name": officer_name if officer_name is not None else "Unknown",
            "old_status": old_status,
            "new_status": new_status,
            **EventPayload._actor_info(actor),
        }
        if old_stage is not None:
            payload["old_stage"] = old_stage
        if new_stage is not None:
            payload["new_stage"] = new_stage
        if updated_fields is not None:
            payload["updated_fields"] = updated_fields
        return payload

    @staticmethod
    def for_lead_updated(
        lead,
        actor,
        *,
        updated_fields: list,
        status_changed: bool,
        updated_summary: Optional[str] = None,
        updated_at: Optional[str] = None,
        message: Optional[str] = None,
    ) -> dict:
        actor_name = (
            getattr(actor, "full_name", None) or getattr(actor, "username", "Unknown")
            if actor is not None
            else "System"
        )
        return {
            "lead_id": lead.id,
            "updated_fields": updated_fields,
            "status_changed": status_changed,
            "actor_id": actor.id if actor is not None else 0,
            "updated_by": actor_name,
            "actor_name": actor_name,
            "updated_summary": updated_summary if updated_summary is not None else (
                ", ".join(updated_fields[:3]) + ("..." if len(updated_fields) > 3 else "")
            ),
            "updated_at": updated_at if updated_at is not None else datetime.now().isoformat(),
            "message": message if message is not None else f"Lead updated by {actor_name}",
        }

    @staticmethod
    def for_lead_deleted(lead, actor) -> dict:
        return {
            "lead_id": lead.id,
            "lead_name": lead.full_name or "Unknown",
            "unit_id": lead.unit_id,
            "officer_id": lead.assigned_officer_id,
            **EventPayload._actor_info(actor),
        }

    @staticmethod
    def for_lead_restored(lead, actor) -> dict:
        return {
            "lead_id": lead.id,
            "lead_name": getattr(lead, "full_name", None) or "Unknown",
            "unit_id": lead.unit_id,
            "officer_id": lead.assigned_officer_id,
            **EventPayload._actor_info(actor),
        }

    @staticmethod
    def for_lead_imported(
        *,
        unit_id: int,
        actor,
        total_imported: int,
        filename: str,
        created_lead_ids: Optional[List[int]] = None,
    ) -> dict:
        sample = (created_lead_ids or [])[:10]
        return {
            "total_imported": total_imported,
            "sample_lead_ids": sample,
            "unit_id": unit_id,
            "filename": filename,
            **EventPayload._actor_info(actor),
        }

    # ------------------------------------------------------------------
    # CONSULTATION events
    # ------------------------------------------------------------------

    @staticmethod
    def for_consultation_created(consultation, lead, actor) -> dict:
        return {
            "consultation_id": consultation.id,
            "lead_id": lead.id,
            "officer_id": lead.assigned_officer_id,
            "status_id": consultation.consultation_status_id or "",
            **EventPayload._actor_info(actor),
            "unit_id": lead.unit_id,
        }

    @staticmethod
    def for_consultation_updated(consultation, lead, actor, *, old_status_id) -> dict:
        return {
            "consultation_id": consultation.id,
            "lead_id": lead.id,
            "officer_id": lead.assigned_officer_id,
            "old_status_id": old_status_id,
            "new_status_id": consultation.consultation_status_id,
            **EventPayload._actor_info(actor),
        }

    @staticmethod
    def for_consultation_deleted(consultation_id: int, lead, actor) -> dict:
        return {
            "consultation_id": consultation_id,
            "lead_id": lead.id,
            "officer_id": lead.assigned_officer_id,
            **EventPayload._actor_info(actor),
        }

    @staticmethod
    def for_consultation_reminder(consultation, lead, *, minutes_until: int) -> dict:
        return {
            "consultation_id": consultation.id,
            "lead_id": lead.id,
            "lead_name": lead.full_name or "Unknown",
            "lead_phone": lead.phone or "",
            "officer_id": consultation.officer_id,
            "scheduled_at": consultation.scheduled_at.isoformat(),
            "minutes_until": minutes_until,
        }
