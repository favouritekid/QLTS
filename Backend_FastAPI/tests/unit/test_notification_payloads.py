# tests/unit/test_notification_payloads.py
"""
Unit tests for EventPayload builder — Phase 1 Lead-module payload contract.

Tests cover:
- Exact key/value-type verification per method
- actor=None → System fallback
- Fallback chains (full_name=None → "Unknown")
- Backward-compat snapshot tests matching pre-refactor payloads
"""
import pytest
from types import SimpleNamespace
from datetime import datetime

from app.services.notification_payloads import EventPayload


# ---------------------------------------------------------------------------
# Helpers — lightweight stubs for lead/actor/consultation
# ---------------------------------------------------------------------------

def _make_lead(**overrides):
    defaults = dict(
        id=42,
        full_name="Nguyen Van A",
        email="a@example.com",
        phone="0901234567",
        unit_id=10,
        assigned_officer_id=5,
        source="website",
        offering=None,
        pipeline_stage_id=3,
        consultation_status_id="new",
        created_at=datetime(2026, 4, 20, 10, 30, 0),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_actor(**overrides):
    defaults = dict(id=1, full_name="Admin User", username="admin")
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_consultation(**overrides):
    defaults = dict(
        id=100,
        lead_id=42,
        officer_id=5,
        consultation_status_id="contacted",
        scheduled_at=datetime(2026, 4, 1, 10, 0, 0),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ===========================================================================
# _actor_info
# ===========================================================================

class TestActorInfo:
    def test_none_actor_returns_system(self):
        info = EventPayload._actor_info(None)
        assert info == {"actor_id": 0, "actor_name": "System"}

    def test_actor_with_full_name(self):
        actor = _make_actor()
        info = EventPayload._actor_info(actor)
        assert info == {"actor_id": 1, "actor_name": "Admin User"}

    def test_actor_fallback_to_username(self):
        actor = _make_actor(full_name=None, username="admin_x")
        info = EventPayload._actor_info(actor)
        assert info == {"actor_id": actor.id, "actor_name": "admin_x"}


# ===========================================================================
# dedupe_key
# ===========================================================================

class TestDedupeKey:
    def test_single_part(self):
        assert EventPayload.dedupe_key("lead_created", 42) == "lead_created:42"

    def test_multiple_parts(self):
        assert EventPayload.dedupe_key("lead_assigned", 42, 5) == "lead_assigned:42:5"


# ===========================================================================
# for_lead_created
# ===========================================================================

class TestLeadCreated:
    def test_exact_keys(self):
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_created(lead, actor, major_name="Công nghệ thông tin")
        assert payload == {
            "lead_id": 42,
            "unit_id": 10,
            "lead_name": "Nguyen Van A",
            "source": "website",
            "actor_id": 1,
            "actor_name": "Admin User",
            "lead_code": "LEAD-000042",
            "major_name": "Công nghệ thông tin",
            "created_date_vn": "20/04/2026",
        }

    def test_none_actor(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_created(lead, None)
        assert payload["actor_id"] == 0
        assert payload["actor_name"] == "System"

    def test_fallback_lead_name(self):
        lead = _make_lead(full_name=None)
        payload = EventPayload.for_lead_created(lead, _make_actor())
        assert payload["lead_name"] == "Unknown"

    def test_fallback_source(self):
        lead = _make_lead(source=None)
        payload = EventPayload.for_lead_created(lead, _make_actor())
        assert payload["source"] == "Unknown"

    def test_major_name_defaults_to_na_when_kwarg_omitted(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_created(lead, _make_actor())
        assert payload["major_name"] == "N/A"

    def test_major_name_defaults_to_na_when_kwarg_none(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_created(lead, _make_actor(), major_name=None)
        assert payload["major_name"] == "N/A"

    def test_major_name_truncated_to_30_chars(self):
        lead = _make_lead()
        long_name = "Công nghệ thông tin và truyền thông đa phương tiện"
        payload = EventPayload.for_lead_created(lead, _make_actor(), major_name=long_name)
        assert len(payload["major_name"]) <= 30
        assert payload["major_name"] == long_name[:30]

    def test_lead_code_format(self):
        lead = _make_lead(id=7)
        payload = EventPayload.for_lead_created(lead, _make_actor())
        assert payload["lead_code"] == "LEAD-000007"

    def test_created_date_vn_format_locked(self):
        lead = _make_lead(created_at=datetime(2026, 4, 20, 15, 30, 0))
        payload = EventPayload.for_lead_created(lead, _make_actor())
        assert payload["created_date_vn"] == "20/04/2026"

    def test_created_date_vn_empty_when_created_at_missing(self):
        """Builder stays defensive: SimpleNamespace w/o created_at yields empty string."""
        lead = SimpleNamespace(
            id=1, full_name="X", unit_id=1, source="web",
        )
        payload = EventPayload.for_lead_created(lead, _make_actor())
        assert payload["created_date_vn"] == ""


# ===========================================================================
# for_lead_assigned
# ===========================================================================

class TestLeadAssigned:
    def test_manual_assignment(self):
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_assigned(lead, 5, actor, offering_name="CS - Regular")
        assert payload == {
            "lead_id": 42,
            "officer_id": 5,
            "actor_id": 1,
            "actor_name": "Admin User",
            "lead_name": "Nguyen Van A",
            "lead_phone": "0901234567",
            "offering_name": "CS - Regular",
        }
        assert "is_automatic" not in payload
        assert "assignment_method" not in payload

    def test_auto_assignment(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_assigned(
            lead, 7, None,
            offering_name="N/A",
            is_automatic=True,
            assignment_method="automatic",
        )
        assert payload["actor_id"] == 0
        assert payload["actor_name"] == "System (Auto Assignment)"
        assert payload["is_automatic"] is True
        assert payload["assignment_method"] == "automatic"

    def test_default_offering_name(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_assigned(lead, 5, _make_actor())
        assert payload["offering_name"] == "N/A"


# ===========================================================================
# for_lead_assignment_failed
# ===========================================================================

class TestLeadAssignmentFailed:
    def test_with_lead_object(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_assignment_failed(lead, 10, "No officers available")
        assert payload == {
            "lead_id": 42,
            "unit_id": 10,
            "reason": "No officers available",
            "lead_name": "Nguyen Van A",
            "actor_id": 0,
            "actor_name": "System",
        }


# ===========================================================================
# for_lead_reassigned
# ===========================================================================

class TestLeadReassigned:
    def test_exact_keys(self):
        actor = _make_actor()
        payload = EventPayload.for_lead_reassigned(
            42, actor,
            old_officer_id=5,
            new_officer_id=None,
            old_unit_id=10,
            new_unit_id=20,
            reason="Offering changed from #1 to #2",
            notify_user_ids=[5],
        )
        assert payload == {
            "lead_id": 42,
            "old_officer_id": 5,
            "new_officer_id": None,
            "old_unit_id": 10,
            "new_unit_id": 20,
            "actor_id": 1,
            "actor_name": "Admin User",
            "reason": "Offering changed from #1 to #2",
            "user_ids": [5],
        }

    def test_default_notify_user_ids(self):
        payload = EventPayload.for_lead_reassigned(
            42, _make_actor(),
            old_officer_id=None,
            new_officer_id=None,
            old_unit_id=10,
            new_unit_id=20,
            reason="test",
        )
        assert payload["user_ids"] == []


# ===========================================================================
# for_lead_status_changed
# ===========================================================================

class TestLeadStatusChanged:
    def test_full_variant(self):
        """Matches leads.py:update_existing_lead call site."""
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_status_changed(
            lead, actor,
            old_status="none",
            new_status="contacted",
            officer_name="Officer X",
            old_stage=1,
            new_stage=2,
            updated_fields=["consultation_status_id"],
        )
        assert payload["lead_id"] == 42
        assert payload["lead_name"] == "Nguyen Van A"
        assert payload["officer_id"] == 5
        assert payload["officer_name"] == "Officer X"
        assert payload["old_status"] == "none"
        assert payload["new_status"] == "contacted"
        assert payload["old_stage"] == 1
        assert payload["new_stage"] == 2
        assert payload["updated_fields"] == ["consultation_status_id"]
        assert payload["actor_id"] == 1
        assert payload["actor_name"] == "Admin User"

    def test_fsm_variant(self):
        """Matches leads.py:update_lead_consultation_status FSM call site."""
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_status_changed(
            lead, actor,
            old_status="none",
            new_status="contacted",
            officer_name="Unknown",
        )
        assert "old_stage" not in payload
        assert "new_stage" not in payload
        assert "updated_fields" not in payload
        assert payload["officer_name"] == "Unknown"

    def test_lead_name_fallback_chain(self):
        lead = _make_lead(full_name=None, email="b@x.com")
        payload = EventPayload.for_lead_status_changed(
            lead, _make_actor(), old_status="a", new_status="b",
        )
        assert payload["lead_name"] == "b@x.com"

        lead2 = _make_lead(full_name=None, email=None)
        payload2 = EventPayload.for_lead_status_changed(
            lead2, _make_actor(), old_status="a", new_status="b",
        )
        assert payload2["lead_name"] == f"Lead #{lead2.id}"


# ===========================================================================
# for_lead_updated
# ===========================================================================

class TestLeadUpdated:
    def test_auto_computed_fields(self):
        """Builder computes updated_summary, updated_at, message from inputs."""
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_updated(
            lead, actor,
            updated_fields=["phone", "email", "full_name", "source"],
            status_changed=False,
        )
        assert payload["lead_id"] == 42
        assert payload["updated_fields"] == ["phone", "email", "full_name", "source"]
        assert payload["status_changed"] is False
        assert payload["actor_id"] == 1
        assert payload["updated_by"] == "Admin User"
        assert payload["actor_name"] == "Admin User"
        assert payload["updated_summary"] == "phone, email, full_name..."
        assert "updated_at" in payload
        assert payload["message"] == "Lead updated by Admin User"

    def test_explicit_overrides(self):
        """Caller can override derived fields for deterministic testing."""
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_updated(
            lead, actor,
            updated_fields=["phone"],
            status_changed=False,
            updated_summary="phone",
            updated_at="2026-01-01T00:00:00",
            message="custom msg",
        )
        assert payload["updated_summary"] == "phone"
        assert payload["updated_at"] == "2026-01-01T00:00:00"
        assert payload["message"] == "custom msg"

    def test_backward_compat_dual_names(self):
        """Both updated_by and actor_name present for backward compat."""
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_updated(
            lead, actor, updated_fields=[], status_changed=False,
        )
        assert payload["updated_by"] == payload["actor_name"]

    def test_short_updated_fields_no_ellipsis(self):
        lead = _make_lead()
        payload = EventPayload.for_lead_updated(
            lead, _make_actor(),
            updated_fields=["phone", "email"],
            status_changed=False,
        )
        assert payload["updated_summary"] == "phone, email"


# ===========================================================================
# for_lead_deleted
# ===========================================================================

class TestLeadDeleted:
    def test_exact_keys(self):
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_deleted(lead, actor)
        assert payload == {
            "lead_id": 42,
            "lead_name": "Nguyen Van A",
            "unit_id": 10,
            "officer_id": 5,
            "actor_id": 1,
            "actor_name": "Admin User",
        }


# ===========================================================================
# for_lead_restored (NEW event)
# ===========================================================================

class TestLeadRestored:
    def test_exact_keys(self):
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_lead_restored(lead, actor)
        assert payload == {
            "lead_id": 42,
            "lead_name": "Nguyen Van A",
            "unit_id": 10,
            "officer_id": 5,
            "actor_id": 1,
            "actor_name": "Admin User",
        }


# ===========================================================================
# for_lead_imported (NEW event)
# ===========================================================================

class TestLeadImported:
    def test_basic(self):
        actor = _make_actor()
        payload = EventPayload.for_lead_imported(
            unit_id=10,
            actor=actor,
            total_imported=50,
            filename="leads.csv",
            created_lead_ids=list(range(1, 51)),
        )
        assert payload["total_imported"] == 50
        assert payload["sample_lead_ids"] == list(range(1, 11))  # max 10
        assert payload["unit_id"] == 10
        assert payload["filename"] == "leads.csv"
        assert payload["actor_id"] == 1

    def test_no_created_ids(self):
        payload = EventPayload.for_lead_imported(
            unit_id=10, actor=_make_actor(), total_imported=5, filename="x.csv",
        )
        assert payload["sample_lead_ids"] == []


# ===========================================================================
# CONSULTATION events
# ===========================================================================

class TestConsultationCreated:
    def test_exact_keys(self):
        consultation = _make_consultation()
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_consultation_created(consultation, lead, actor)
        assert payload == {
            "consultation_id": 100,
            "lead_id": 42,
            "officer_id": 5,
            "status_id": "contacted",
            "actor_id": 1,
            "actor_name": "Admin User",
            "unit_id": 10,
        }


class TestConsultationUpdated:
    def test_exact_keys(self):
        consultation = _make_consultation()
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_consultation_updated(consultation, lead, actor, old_status_id="new")
        assert payload == {
            "consultation_id": 100,
            "lead_id": 42,
            "officer_id": 5,
            "old_status_id": "new",
            "new_status_id": "contacted",
            "actor_id": 1,
            "actor_name": "Admin User",
        }


class TestConsultationDeleted:
    def test_exact_keys(self):
        lead = _make_lead()
        actor = _make_actor()
        payload = EventPayload.for_consultation_deleted(100, lead, actor)
        assert payload == {
            "consultation_id": 100,
            "lead_id": 42,
            "officer_id": 5,
            "actor_id": 1,
            "actor_name": "Admin User",
        }


class TestConsultationReminder:
    def test_exact_keys(self):
        consultation = _make_consultation()
        lead = _make_lead()
        payload = EventPayload.for_consultation_reminder(
            consultation, lead, minutes_until=10, major_name="Công nghệ thông tin",
        )
        assert payload == {
            "consultation_id": 100,
            "lead_id": 42,
            "lead_name": "Nguyen Van A",
            "lead_phone": "0901234567",
            "officer_id": 5,  # lead.assigned_officer_id
            "scheduled_at": "2026-04-01T10:00:00",
            "minutes_until": 10,
            "scheduled_time_vn": "01/04/2026 10:00",
            "booking_code": "CONS-000100",
            "lead_code": "LEAD-000042",
            "major_name": "Công nghệ thông tin",
        }

    def test_uses_lead_owner_not_consultation_creator(self):
        """Reminder must target lead owner, not the user who created the consultation."""
        consultation = _make_consultation(officer_id=15)  # admin created it
        lead = _make_lead(assigned_officer_id=18)  # officer owns the lead
        payload = EventPayload.for_consultation_reminder(consultation, lead, minutes_until=10)
        assert payload["officer_id"] == 18  # lead owner wins

    def test_falls_back_to_consultation_officer_when_lead_unassigned(self):
        """If lead has no assigned_officer_id, fall back to consultation.officer_id."""
        consultation = _make_consultation(officer_id=15)
        lead = _make_lead(assigned_officer_id=None)
        payload = EventPayload.for_consultation_reminder(consultation, lead, minutes_until=10)
        assert payload["officer_id"] == 15  # fallback

    def test_fallbacks(self):
        consultation = _make_consultation()
        lead = _make_lead(full_name=None, phone=None)
        payload = EventPayload.for_consultation_reminder(consultation, lead, minutes_until=5)
        assert payload["lead_name"] == "Unknown"
        assert payload["lead_phone"] == ""

    def test_major_name_defaults_to_na_when_kwarg_omitted(self):
        """Caller always resolves major_name; default ensures Zalo required
        field is never empty if caller has no offering link."""
        consultation = _make_consultation()
        lead = _make_lead()
        payload = EventPayload.for_consultation_reminder(consultation, lead, minutes_until=10)
        assert payload["major_name"] == "N/A"

    def test_major_name_defaults_to_na_when_kwarg_none(self):
        consultation = _make_consultation()
        lead = _make_lead()
        payload = EventPayload.for_consultation_reminder(
            consultation, lead, minutes_until=10, major_name=None,
        )
        assert payload["major_name"] == "N/A"

    def test_major_name_truncated_to_30_chars(self):
        """Zalo STRING params cap at 30 chars for template 333738 `ten_nganh_hoc`."""
        consultation = _make_consultation()
        lead = _make_lead()
        long_name = "Công nghệ thông tin và truyền thông đa phương tiện"
        payload = EventPayload.for_consultation_reminder(
            consultation, lead, minutes_until=10, major_name=long_name,
        )
        assert len(payload["major_name"]) <= 30
        assert payload["major_name"] == long_name[:30]

    def test_derived_code_formats(self):
        consultation = _make_consultation(id=7)
        lead = _make_lead(id=3)
        payload = EventPayload.for_consultation_reminder(consultation, lead, minutes_until=10)
        assert payload["booking_code"] == "CONS-000007"
        assert payload["lead_code"] == "LEAD-000003"

    def test_scheduled_time_vn_format_locked(self):
        """Must be DD/MM/YYYY HH:MM (≤20 chars, fits Zalo DATE param)."""
        consultation = _make_consultation(scheduled_at=datetime(2026, 4, 20, 15, 30, 0))
        lead = _make_lead()
        payload = EventPayload.for_consultation_reminder(consultation, lead, minutes_until=10)
        assert payload["scheduled_time_vn"] == "20/04/2026 15:30"
        assert len(payload["scheduled_time_vn"]) <= 20


# ===========================================================================
# for_invoice_issued
# ===========================================================================


def _make_invoice(**overrides):
    defaults = dict(
        id=501,
        invoice_number="INV-2026-0501",
        fee_id=77,
        amount="7000000",
        due_date=datetime(2026, 5, 15, 0, 0, 0),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestInvoiceIssued:
    def test_exact_keys(self):
        inv = _make_invoice()
        payload = EventPayload.for_invoice_issued(
            inv,
            admission_profile_id=42,
            lead_id=99,
            unit_id=10,
            officer_id=5,
            lead_full_name="Phạm Thái Hà",
            major_name="Điều dưỡng",
            degree_level="Cao đẳng",
        )
        assert payload == {
            # Backward-compat
            "invoice_id": 501,
            "invoice_number": "INV-2026-0501",
            "fee_id": 77,
            "amount": "7000000",
            "due_date": "2026-05-15T00:00:00",
            "admission_profile_id": 42,
            "lead_id": 99,
            "unit_id": 10,
            "user_id": 5,
            # New
            "profile_code": "HS-000042",
            "lead_full_name": "Phạm Thái Hà",
            "major_name": "Điều dưỡng",
            "degree_level": "Cao đẳng",
            "amount_vnd": "7000000",
            "due_date_vn": "15/05/2026",
            "bank_transfer_note": "Pham Thai Ha HS 000042 thanh toan hoc phi Dieu duong",
        }

    def test_lead_full_name_fallback_unknown(self):
        inv = _make_invoice()
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=1)
        assert payload["lead_full_name"] == "Unknown"

    def test_major_name_fallback_na(self):
        inv = _make_invoice()
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=1)
        assert payload["major_name"] == "N/A"
        assert payload["degree_level"] == "N/A"

    def test_amount_vnd_strips_decimal(self):
        """Zalo CURRENCY type rejects decimals; must coerce to integer."""
        inv = _make_invoice(amount="5500000.00")
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=1)
        assert payload["amount_vnd"] == "5500000"
        assert payload["amount"] == "5500000.00"  # raw preserved for other channels

    def test_amount_vnd_invalid_becomes_zero(self):
        inv = _make_invoice(amount="not-a-number")
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=1)
        assert payload["amount_vnd"] == "0"

    def test_due_date_vn_format(self):
        inv = _make_invoice(due_date=datetime(2026, 5, 15, 0, 0, 0))
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=1)
        assert payload["due_date_vn"] == "15/05/2026"

    def test_due_date_missing_yields_empty_vn(self):
        inv = _make_invoice(due_date=None)
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=1)
        assert payload["due_date"] is None
        assert payload["due_date_vn"] == ""

    def test_profile_code_format(self):
        inv = _make_invoice()
        payload = EventPayload.for_invoice_issued(inv, admission_profile_id=7)
        assert payload["profile_code"] == "HS-000007"

    def test_profile_code_defaults_when_absent(self):
        inv = _make_invoice()
        payload = EventPayload.for_invoice_issued(inv)  # no admission_profile_id
        assert payload["profile_code"] == "HS-000000"

    def test_bank_transfer_note_zalo_compliant(self):
        """Must match ^[a-zA-Z0-9 ]+$ — Zalo BANK_TRANSFER_NOTE constraint."""
        import re
        inv = _make_invoice()
        payload = EventPayload.for_invoice_issued(
            inv,
            admission_profile_id=42,
            lead_full_name="Phạm Thái Hà",
            major_name="Điều dưỡng",
        )
        note = payload["bank_transfer_note"]
        assert re.match(r"^[a-zA-Z0-9 ]+$", note), f"not Zalo-compliant: {note!r}"
        assert len(note) <= 90

    def test_truncation_caps_on_30_char_fields(self):
        inv = _make_invoice()
        long_name = "a" * 50
        payload = EventPayload.for_invoice_issued(
            inv,
            admission_profile_id=1,
            lead_full_name=long_name,
            major_name=long_name,
            degree_level=long_name,
        )
        assert len(payload["lead_full_name"]) == 30
        assert len(payload["major_name"]) == 30
        assert len(payload["degree_level"]) == 30
