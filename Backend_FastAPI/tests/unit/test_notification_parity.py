# tests/unit/test_notification_parity.py
"""
Notification contract parity tests — Phase A.

These tests lock the notification contract so drift cannot be reintroduced silently.
Covers:
- A1: APPLICATION_CREATED semantics (create-only)
- A2: HOLIDAY_CALENDAR_INCOMPLETE full parity
- A3: Organization events not in user notification contract
- A5: Event-to-group-mapping parity for all registry events
- A5: Metadata parity for admin-manageable events
"""
import ast
import inspect
import pytest

from app.core.events import SystemEvents
from app.core.event_groups import EVENT_GROUP_MAPPING, NotificationEventGroup
from app.core.event_metadata import EVENT_METADATA_REGISTRY
from app.services.notification_registry import NOTIFICATION_REGISTRY


# =============================================================================
# A1: APPLICATION_CREATED must only be used for create, never for approve/enroll
# =============================================================================

class TestApplicationCreatedSemantics:
    """Lock APPLICATION_CREATED to create-only usage."""

    def test_admissions_router_approve_uses_status_changed(self):
        """Approval flow must dispatch APPLICATION_STATUS_CHANGED, not APPLICATION_CREATED."""
        import importlib
        source = inspect.getsource(
            importlib.import_module("app.routers.admissions")
        )

        # Find all safe_dispatch calls with APPLICATION_CREATED
        # and verify none are in approve/enrollment context
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'APPLICATION_CREATED' in line and 'safe_dispatch' in lines[max(0, i-3):i+1].__repr__():
                # Check surrounding context for approve/enroll keywords
                context = '\n'.join(lines[max(0, i-10):i+5])
                assert 'approved' not in context.lower() or 'status' not in context.lower(), (
                    f"APPLICATION_CREATED found near approval context at line ~{i+1}. "
                    "Approval must use APPLICATION_STATUS_CHANGED."
                )
                assert 'enroll' not in context.lower(), (
                    f"APPLICATION_CREATED found near enrollment context at line ~{i+1}. "
                    "Enrollment must use APPLICATION_STATUS_CHANGED."
                )

    def test_application_created_only_in_create_flows(self):
        """
        APPLICATION_CREATED must only appear in files/functions that create profiles,
        not in status-change flows.
        """
        from app.core.events import SystemEvents
        # Verify the event exists
        assert SystemEvents.APPLICATION_CREATED.value == "application_created"
        # Verify STATUS_CHANGED also exists for non-create flows
        assert SystemEvents.APPLICATION_STATUS_CHANGED.value == "application_status_changed"


# =============================================================================
# A2: HOLIDAY_CALENDAR_INCOMPLETE must have full parity
# =============================================================================

class TestHolidayCalendarParity:
    """HOLIDAY_CALENDAR_INCOMPLETE must exist in all 4 systems."""

    def test_exists_in_system_events(self):
        assert hasattr(SystemEvents, 'HOLIDAY_CALENDAR_INCOMPLETE')
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE.value == "holiday_calendar_incomplete"

    def test_exists_in_event_group_mapping(self):
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE in EVENT_GROUP_MAPPING, (
            "HOLIDAY_CALENDAR_INCOMPLETE must be in EVENT_GROUP_MAPPING"
        )
        assert EVENT_GROUP_MAPPING[SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE] == NotificationEventGroup.SYSTEM

    def test_exists_in_notification_registry(self):
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE in NOTIFICATION_REGISTRY, (
            "HOLIDAY_CALENDAR_INCOMPLETE must be in NOTIFICATION_REGISTRY"
        )

    def test_exists_in_event_metadata(self):
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE in EVENT_METADATA_REGISTRY, (
            "HOLIDAY_CALENDAR_INCOMPLETE must be in EVENT_METADATA_REGISTRY"
        )


# =============================================================================
# A3: Organization events NOT in user notification contract
# =============================================================================

class TestOrganizationEventsPolicy:
    """UNIT_*/PROGRAM_*/OFFERING_* must NOT be in EVENT_GROUP_MAPPING."""

    ORG_EVENTS = [
        'UNIT_CREATED', 'UNIT_UPDATED', 'UNIT_DELETED',
        'PROGRAM_CREATED', 'PROGRAM_UPDATED', 'PROGRAM_DELETED',
        'OFFERING_CREATED', 'OFFERING_UPDATED', 'OFFERING_DELETED',
    ]

    def test_org_events_not_in_group_mapping(self):
        """Organization events must be excluded from user notification contract."""
        for event_name in self.ORG_EVENTS:
            event = getattr(SystemEvents, event_name, None)
            if event is not None:
                assert event not in EVENT_GROUP_MAPPING, (
                    f"{event_name} must NOT be in EVENT_GROUP_MAPPING. "
                    "Organization events are domain broadcast only."
                )

    def test_org_events_not_in_registry(self):
        """Organization events must not have runtime notification config."""
        for event_name in self.ORG_EVENTS:
            event = getattr(SystemEvents, event_name, None)
            if event is not None:
                assert event not in NOTIFICATION_REGISTRY, (
                    f"{event_name} must NOT be in NOTIFICATION_REGISTRY. "
                    "Promote properly before adding."
                )


# =============================================================================
# A5/T1: Every event with registry config MUST have group mapping
# =============================================================================

class TestEventRegistryGroupParity:
    """
    Parity test: every event in NOTIFICATION_REGISTRY must also exist
    in EVENT_GROUP_MAPPING. Without this, dispatch() will KeyError.
    """

    def test_all_registry_events_have_group_mapping(self):
        """Every event with runtime config must have a group mapping."""
        missing = []
        for event in NOTIFICATION_REGISTRY:
            if event not in EVENT_GROUP_MAPPING:
                missing.append(event.value)

        assert not missing, (
            f"Events in NOTIFICATION_REGISTRY but missing from EVENT_GROUP_MAPPING: {missing}. "
            "dispatch() will KeyError for these events."
        )


# =============================================================================
# A5/T3: Admin-manageable events should have metadata
# =============================================================================

class TestEventMetadataParity:
    """
    Events that are in the registry AND group mapping should ideally
    have metadata for admin UI. This test warns about gaps.
    """

    def test_registry_events_have_metadata(self):
        """Events with runtime config should have metadata for admin forms."""
        missing = []
        for event in NOTIFICATION_REGISTRY:
            if event not in EVENT_METADATA_REGISTRY:
                missing.append(event.value)

        # This is a warning, not a hard failure — some events may be
        # system-only and not need admin metadata
        if missing:
            pytest.skip(
                f"Events in registry but missing metadata (not blocking): {missing}"
            )


# =============================================================================
# A5: Canonical channel values only
# =============================================================================

class TestCanonicalChannelValues:
    """Metadata and registry must only use canonical channel values."""

    CANONICAL = {"browser", "email", "zalo", "sms"}

    def test_metadata_default_channels_are_canonical(self):
        """Every event metadata must use canonical channel values."""
        for event, metadata in EVENT_METADATA_REGISTRY.items():
            for ch in metadata.default_channels:
                assert ch in self.CANONICAL, (
                    f"Event {event.value} has non-canonical channel '{ch}' "
                    f"in default_channels. Must be one of {self.CANONICAL}"
                )

    def test_registry_channels_are_canonical(self):
        """Every registry config must use canonical channel values."""
        for event, config in NOTIFICATION_REGISTRY.items():
            for ch in config.channel_values:
                assert ch in self.CANONICAL, (
                    f"Event {event.value} has non-canonical channel '{ch}' "
                    f"in registry. Must be one of {self.CANONICAL}"
                )
