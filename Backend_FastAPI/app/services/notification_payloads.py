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
    def for_lead_created(lead, actor, *, major_name: Optional[str] = None) -> dict:
        """Build lead-created payload.

        ``major_name`` is resolved by the caller (e.g. ``lead_service.py``
        refreshes ``lead.offering.program``) and passed in — this builder
        stays pure per module contract. ``getattr`` defaults cover both stubs
        and real models where ``created_at`` is set by server_default after flush.
        """
        from app.utils.datetime_helpers import format_vn_date
        from app.utils.id_helpers import format_lead_code

        return {
            "lead_id": lead.id,
            "unit_id": lead.unit_id,
            "lead_name": lead.full_name or "Unknown",
            "source": lead.source or "Unknown",
            **EventPayload._actor_info(actor),
            # Channel-specific derived fields (e.g. Zalo ZNS 257524 params).
            "lead_code": format_lead_code(lead.id),
            "major_name": (major_name or "N/A")[:30],
            "created_date_vn": format_vn_date(getattr(lead, "created_at", None)),
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
        old_unit_id: Optional[int],
        new_unit_id: Optional[int],
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
    def for_consultation_reminder(
        consultation,
        lead,
        *,
        minutes_until: int,
        major_name: Optional[str] = None,
    ) -> dict:
        """Build reminder payload.

        ``major_name`` is resolved by the caller (e.g. ``notification_tasks.py``
        eager-loads ``lead.offering.program.name``) and passed in — this
        builder never touches ORM relationships per module contract.
        """
        from app.utils.datetime_helpers import format_vn_datetime
        from app.utils.id_helpers import format_booking_code, format_lead_code

        return {
            "consultation_id": consultation.id,
            "lead_id": lead.id,
            "lead_name": lead.full_name or "Unknown",
            "lead_phone": lead.phone or "",
            # Use lead owner (not consultation creator) so LeadOwnerResolver
            # sends to the officer currently responsible for the lead.
            "officer_id": lead.assigned_officer_id or consultation.officer_id,
            "scheduled_at": consultation.scheduled_at.isoformat(),
            "minutes_until": minutes_until,
            # Channel-specific derived fields (e.g. Zalo ZNS 333738 params).
            "scheduled_time_vn": format_vn_datetime(consultation.scheduled_at),
            "booking_code": format_booking_code(consultation.id),
            "lead_code": format_lead_code(lead.id),
            "major_name": (major_name or "N/A")[:30],
        }

    @staticmethod
    def for_invoice_issued(
        invoice,
        *,
        admission_profile_id: Optional[int] = None,
        lead_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        officer_id: Optional[int] = None,
        lead_full_name: Optional[str] = None,
        major_name: Optional[str] = None,
        degree_level: Optional[str] = None,
    ) -> dict:
        """Build invoice-issued payload.

        Caller resolves ``lead_full_name``, ``major_name``, ``degree_level``
        from ``AdmissionProfile.lead.offering.program`` (eager-loaded at the
        dispatch site in ``invoice_service.py``) and passes them via kwargs —
        this builder stays pure per module contract.

        Note: ``user_id`` is the assigned officer. Callers guard dispatch on
        ``bool(payload['user_id'])`` to skip invoices on leads without an owner.
        """
        from decimal import Decimal, InvalidOperation
        from app.utils.datetime_helpers import format_vn_date
        from app.utils.id_helpers import format_profile_code
        from app.utils.text_helpers import to_bank_transfer_note

        # Coerce amount to integer-VND string; Zalo CURRENCY rejects decimals.
        # invoice.amount is typically Decimal (Numeric column); str may have ".00".
        raw_amount = getattr(invoice, "amount", None)
        try:
            amount_vnd_int = int(Decimal(str(raw_amount))) if raw_amount is not None else 0
        except (TypeError, ValueError, InvalidOperation):
            amount_vnd_int = 0

        clean_name = (lead_full_name or "Unknown")[:30]
        clean_major = (major_name or "N/A")[:30]
        clean_level = (degree_level or "N/A")[:30]
        profile_code = (
            format_profile_code(admission_profile_id) if admission_profile_id else "HS-000000"
        )
        # Zalo BANK_TRANSFER_NOTE: ASCII alphanumeric + space only (≤90).
        bank_note_raw = f"{clean_name} {profile_code} thanh toan hoc phi {clean_major}"
        bank_note = to_bank_transfer_note(bank_note_raw, max_len=90)

        return {
            # Backward-compatible keys (payload contract prior to ZNS wire-up).
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "fee_id": invoice.fee_id,
            "amount": str(raw_amount) if raw_amount is not None else "0",
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "admission_profile_id": admission_profile_id,
            "lead_id": lead_id,
            "unit_id": unit_id,
            "user_id": officer_id,
            # New keys for ZNS template 557767 ``Thông báo thu học phí``.
            "profile_code": profile_code,
            "lead_full_name": clean_name,
            "major_name": clean_major,
            "degree_level": clean_level,
            "amount_vnd": str(amount_vnd_int),
            "due_date_vn": format_vn_date(invoice.due_date),
            "bank_transfer_note": bank_note,
        }
