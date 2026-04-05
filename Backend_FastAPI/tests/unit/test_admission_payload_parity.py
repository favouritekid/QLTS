# tests/unit/test_admission_payload_parity.py
"""
Payload parity tests for admission notification events.

Locks the contract between event_catalog.py variables and
actual dispatch payloads in admissions.py.

Key design decisions protected:
- APPLICATION_* payloads intentionally omit officer_id
  (LeadOwnerResolver uses DB lookup via lead_id)
- Enroll payload includes student_id/student_code as optional extras
"""
import pytest

from app.core.events import SystemEvents
from app.core.event_catalog import get_event


class TestAdmissionCatalogVariables:
    """Catalog variables must match runtime payload contract."""

    def test_application_created_no_officer_id(self):
        """APPLICATION_CREATED must NOT declare officer_id in variables.

        Reason: payload intentionally omits officer_id so LeadOwnerResolver
        falls through to DB lookup. See regression tests in
        test_zalo_phase1_review_findings.py:944.
        """
        defn = get_event(SystemEvents.APPLICATION_CREATED)
        var_names = {v.name for v in defn.variables}
        assert "officer_id" not in var_names, (
            "officer_id must NOT be in APPLICATION_CREATED variables. "
            "LeadOwnerResolver uses DB lookup via lead_id."
        )
        assert "application_id" in var_names
        assert "lead_id" in var_names
        assert "actor_id" in var_names

    def test_application_status_changed_no_officer_id(self):
        """APPLICATION_STATUS_CHANGED must NOT declare officer_id."""
        defn = get_event(SystemEvents.APPLICATION_STATUS_CHANGED)
        var_names = {v.name for v in defn.variables}
        assert "officer_id" not in var_names
        assert "application_id" in var_names
        assert "lead_id" in var_names
        assert "old_status" in var_names
        assert "new_status" in var_names
        assert "actor_id" in var_names

    def test_application_status_changed_has_enroll_extras(self):
        """APPLICATION_STATUS_CHANGED must declare student_id/student_code
        as optional variables (present only when new_status=enrolled)."""
        defn = get_event(SystemEvents.APPLICATION_STATUS_CHANGED)
        var_names = {v.name for v in defn.variables}
        assert "student_id" in var_names, "Enroll payload sends student_id"
        assert "student_code" in var_names, "Enroll payload sends student_code"

        # Must be optional (not required)
        student_id_var = next(v for v in defn.variables if v.name == "student_id")
        student_code_var = next(v for v in defn.variables if v.name == "student_code")
        assert not student_id_var.required, "student_id must be optional (only present on enroll)"
        assert not student_code_var.required, "student_code must be optional (only present on enroll)"

    def test_application_deleted_no_officer_id(self):
        """APPLICATION_DELETED must NOT declare officer_id."""
        defn = get_event(SystemEvents.APPLICATION_DELETED)
        var_names = {v.name for v in defn.variables}
        assert "officer_id" not in var_names
        assert "application_id" in var_names
        assert "lead_id" in var_names
        assert "actor_id" in var_names


class TestAdmissionPayloadCatalogAlignment:
    """Cross-check: every variable declared in catalog must be present
    in at least one dispatch payload path, and vice versa."""

    # Actual payload keys sent by admissions.py dispatch calls
    # Source: grep "payload={" app/routers/admissions.py
    _CREATED_PAYLOAD_KEYS = {
        "application_id", "lead_id", "lead_name",
        "major_program_name", "actor_id", "actor_name",
    }
    _STATUS_CHANGED_PAYLOAD_KEYS = {
        "application_id", "lead_id", "old_status", "new_status",
        "actor_id", "actor_name",
        # enroll-only extras
        "student_id", "student_code",
    }
    _DELETED_PAYLOAD_KEYS = {
        "application_id", "lead_id", "lead_name",
        "actor_id", "actor_name",
    }

    # Keys that are intentionally in payload but NOT in catalog
    # (actor_name is a common runtime convenience, not declared as template variable)
    _UNDECLARED_BUT_INTENTIONAL = {"actor_name"}

    def test_created_catalog_vars_subset_of_payload(self):
        """Every catalog variable must be sendable by dispatch."""
        defn = get_event(SystemEvents.APPLICATION_CREATED)
        catalog_vars = {v.name for v in defn.variables}
        sendable = self._CREATED_PAYLOAD_KEYS | self._UNDECLARED_BUT_INTENTIONAL
        missing = catalog_vars - sendable
        assert not missing, f"Catalog declares vars not in payload: {missing}"

    def test_status_changed_catalog_vars_subset_of_payload(self):
        defn = get_event(SystemEvents.APPLICATION_STATUS_CHANGED)
        catalog_vars = {v.name for v in defn.variables}
        sendable = self._STATUS_CHANGED_PAYLOAD_KEYS | self._UNDECLARED_BUT_INTENTIONAL
        missing = catalog_vars - sendable
        assert not missing, f"Catalog declares vars not in payload: {missing}"

    def test_deleted_catalog_vars_subset_of_payload(self):
        defn = get_event(SystemEvents.APPLICATION_DELETED)
        catalog_vars = {v.name for v in defn.variables}
        sendable = self._DELETED_PAYLOAD_KEYS | self._UNDECLARED_BUT_INTENTIONAL
        missing = catalog_vars - sendable
        assert not missing, f"Catalog declares vars not in payload: {missing}"

    def test_no_undeclared_required_payload_keys(self):
        """Payload should not send required-looking keys that catalog doesn't declare.

        Exceptions: actor_name (runtime convenience) and enroll extras (optional).
        """
        for event_enum, payload_keys in [
            (SystemEvents.APPLICATION_CREATED, self._CREATED_PAYLOAD_KEYS),
            (SystemEvents.APPLICATION_STATUS_CHANGED, self._STATUS_CHANGED_PAYLOAD_KEYS),
            (SystemEvents.APPLICATION_DELETED, self._DELETED_PAYLOAD_KEYS),
        ]:
            defn = get_event(event_enum)
            catalog_vars = {v.name for v in defn.variables}
            allowed_extras = self._UNDECLARED_BUT_INTENTIONAL
            undeclared = payload_keys - catalog_vars - allowed_extras
            # lead_name is optional in some events, actor_name is convention
            # Only flag truly unexpected keys
            unexpected = undeclared - {"lead_name"}
            assert not unexpected, (
                f"{event_enum.value}: payload sends {unexpected} but catalog doesn't declare them"
            )
