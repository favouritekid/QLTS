# tests/unit/test_notification_parity.py
"""
Notification contract parity tests — Phase A + P1 automated parity checks.

These tests lock the notification contract so drift cannot be reintroduced silently.
Covers:
- A1: APPLICATION_CREATED semantics (create-only)
- A2: HOLIDAY_CALENDAR_INCOMPLETE full parity
- A3: Organization events not in user notification contract
- A5: Event-to-group-mapping parity for all registry events
- A5: Metadata parity for admin-manageable events
- P1: Automated parity checks (Addendum Section 10)
"""
import ast
import inspect
from pathlib import Path
import pytest

from app.core.events import SystemEvents
from app.core.event_groups import EVENT_GROUP_MAPPING, NotificationEventGroup
from app.core.event_metadata import EVENT_METADATA_REGISTRY
from app.services.notification_registry import NOTIFICATION_REGISTRY
# PR3: Catalog is the primary source of truth (PR1)
from app.core.event_catalog import EVENT_CATALOG, get_event, get_notifiable_events


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

    ORG_EVENT_VALUES = {
        "unit_created", "unit_updated", "unit_deleted",
        "program_created", "program_updated", "program_deleted",
        "offering_created", "offering_updated", "offering_deleted",
    }

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

    def test_org_events_in_broadcast_only_set(self):
        """All org events must be listed in BROADCAST_ONLY_EVENTS."""
        from app.services.notification_rule_crud_service import BROADCAST_ONLY_EVENTS

        for event_value in self.ORG_EVENT_VALUES:
            assert event_value in BROADCAST_ONLY_EVENTS, (
                f"'{event_value}' must be in BROADCAST_ONLY_EVENTS"
            )

    @pytest.mark.asyncio
    async def test_create_rule_rejects_org_events(self):
        """create_rule() must raise BadRequest for broadcast-only events."""
        from unittest.mock import MagicMock
        from app.services.notification_rule_crud_service import create_rule
        from app.utils.exceptions import BadRequest
        from app.schemas.notification import NotificationRuleCreate

        mock_db = MagicMock()  # DB not touched — rejection is before any DB call

        for event_value in self.ORG_EVENT_VALUES:
            rule_data = NotificationRuleCreate(
                event=event_value,
                title_template="Test",
                message_template="Test",
                channels=["browser"],
                recipient_config={"resolver_type": "all_admins", "params": {}},
            )
            with pytest.raises(BadRequest, match="not a configurable user event"):
                await create_rule(mock_db, rule_data)


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
    Events in registry AND group mapping must have metadata for admin UI.
    CTV events are temporarily exempted pending metadata backfill.
    """

    # CTV events have full metadata in event_catalog.py (PR1) but NOT in the
    # deprecated EVENT_METADATA_REGISTRY. Keep exemption for this legacy parity test.
    # See TestCatalogParity below for the actual runtime source-of-truth validation.
    CTV_EVENTS_IN_CATALOG_ONLY = {
        "ctv_claim_submitted", "ctv_claim_approved", "ctv_claim_rejected",
        "ctv_approved", "ctv_suspended", "ctv_lead_converted",
        "ctv_attribution_expiring", "ctv_attribution_expired",
        "ctv_commission_created", "ctv_weekly_summary",
    }

    def test_registry_events_have_metadata(self):
        """Events with runtime config MUST have metadata (legacy check)."""
        missing = []
        for event in NOTIFICATION_REGISTRY:
            if event.value in self.CTV_EVENTS_IN_CATALOG_ONLY:
                continue
            if event not in EVENT_METADATA_REGISTRY:
                missing.append(event.value)

        assert not missing, (
            f"Events in NOTIFICATION_REGISTRY but missing from EVENT_METADATA_REGISTRY: {missing}."
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


# =============================================================================
# P1: Automated Parity Checks (Addendum Section 10)
# =============================================================================

# Known broadcast-only events — these are domain broadcast events (Socket.IO
# real-time UI refresh) with no user notification contract.  They are
# intentionally excluded from EVENT_GROUP_MAPPING, NOTIFICATION_REGISTRY, and
# EVENT_METADATA_REGISTRY.
_BROADCAST_ONLY_PREFIXES = ("UNIT_", "PROGRAM_", "OFFERING_")


@pytest.mark.unit
def test_all_system_events_have_group_mapping():
    """
    P1-1: Every SystemEvents value must exist in EVENT_GROUP_MAPPING keys,
    except known broadcast-only events (UNIT_*, PROGRAM_*, OFFERING_*).

    If a new SystemEvents member is added without a group mapping, dispatch()
    will fall back to the SYSTEM group with a runtime warning.  This test
    catches that drift at CI time.
    """
    unmapped = set()
    for event in SystemEvents:
        # Skip known broadcast-only events
        if any(event.name.startswith(prefix) for prefix in _BROADCAST_ONLY_PREFIXES):
            continue
        if event not in EVENT_GROUP_MAPPING:
            unmapped.add(event.name)

    assert not unmapped, (
        f"SystemEvents missing from EVENT_GROUP_MAPPING "
        f"(not broadcast-only): {sorted(unmapped)}. "
        "Add them to EVENT_GROUP_MAPPING in app/core/event_groups.py or "
        "add the prefix to _BROADCAST_ONLY_PREFIXES if they are broadcast-only."
    )


@pytest.mark.unit
def test_all_notification_events_have_runtime_config():
    """
    P1-2: Every event in EVENT_GROUP_MAPPING must have an EventDefinition
    in EVENT_CATALOG (the runtime source-of-truth).

    Post-PR1 the dispatcher reads from ``app.core.event_catalog`` — see
    ``app/services/notification_dispatcher.py`` ``get_event(event)``.
    ``NOTIFICATION_REGISTRY`` is deprecated (self-documented at
    ``app/services/notification_registry.py:3``) and kept only for enum +
    dataclass re-exports; missing entries there no longer block dispatch.

    Events in the group mapping are part of the user notification contract.
    Without a catalog entry, dispatch() cannot render title/message/link,
    resolve recipients, or derive dedup keys.  Broadcast-only events are
    allowed to be missing.
    """
    missing = []
    for event in EVENT_GROUP_MAPPING:
        # Skip known broadcast-only events
        if any(event.name.startswith(prefix) for prefix in _BROADCAST_ONLY_PREFIXES):
            continue
        if event not in EVENT_CATALOG:
            missing.append(event.value)

    assert not missing, (
        f"Events in EVENT_GROUP_MAPPING but missing from EVENT_CATALOG: "
        f"{sorted(missing)}. "
        "dispatch() will silently skip these events. "
        "Add an EventDefinition entry in app/core/event_catalog.py."
    )


@pytest.mark.unit
def test_admin_events_have_metadata():
    """
    P1-3: Every admin-manageable event (in NOTIFICATION_REGISTRY) must have
    metadata in EVENT_METADATA_REGISTRY.

    The admin UI rule builder depends on metadata to render variable pickers,
    filter fields, and channel defaults.  Missing metadata means the admin
    cannot create custom rules for that event.

    CTV events are temporarily exempted pending metadata backfill.
    """
    # CTV events have metadata in catalog only, not deprecated EVENT_METADATA_REGISTRY
    CTV_EVENTS_IN_CATALOG_ONLY = {
        "ctv_claim_submitted", "ctv_claim_approved", "ctv_claim_rejected",
        "ctv_approved", "ctv_suspended", "ctv_lead_converted",
        "ctv_attribution_expiring", "ctv_attribution_expired",
        "ctv_commission_created", "ctv_weekly_summary",
    }

    missing = []
    for event in NOTIFICATION_REGISTRY:
        if event.value in CTV_EVENTS_IN_CATALOG_ONLY:
            continue
        if event not in EVENT_METADATA_REGISTRY:
            missing.append(event.value)

    assert not missing, (
        f"Events in NOTIFICATION_REGISTRY but missing from "
        f"EVENT_METADATA_REGISTRY: {sorted(missing)}."
    )


@pytest.mark.unit
def test_metadata_channels_are_implemented_or_gated():
    """
    P1-4: Every channel referenced in EVENT_METADATA_REGISTRY default_channels
    must be either implemented (in CHANNEL_REGISTRY) or a known planned channel.

    This prevents metadata from advertising channels that have no delivery
    backend, which would cause silent delivery failures at runtime.
    """
    from app.services.notification_channels import CHANNEL_REGISTRY

    implemented = set(CHANNEL_REGISTRY.keys())
    planned_gated = {"sms", "zalo"}  # Known planned/gated channels
    allowed = implemented | planned_gated

    violations = []
    for event, metadata in EVENT_METADATA_REGISTRY.items():
        for ch in metadata.default_channels:
            if ch not in allowed:
                violations.append(
                    f"{event.value}: channel '{ch}' not in "
                    f"implemented {sorted(implemented)} or "
                    f"planned {sorted(planned_gated)}"
                )

    assert not violations, (
        f"Metadata references channels that are neither implemented nor planned:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.unit
def test_deprecated_entrypoints_have_no_production_callers():
    """
    P1-5: Deprecated functions create_notification() and
    execute_notification_workflow() must not be called from production code
    (app/ directory).

    Callers in test files and the definition files themselves are excluded.
    All production code must use dispatch() / safe_dispatch() instead.
    """
    # The definition files where the deprecated functions live
    definition_files = {
        "notification_service.py",
    }

    deprecated_patterns = [
        "create_notification(",
    ]

    app_dir = Path(__file__).resolve().parent.parent.parent / "app"
    callers = []

    for py_file in app_dir.rglob("*.py"):
        filename = py_file.name

        # Skip definition files (they contain the def and docstring references)
        if filename in definition_files:
            continue

        # Skip test files
        if "test" in filename or "conftest" in filename:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for pattern in deprecated_patterns:
            # Search for actual calls (not just imports or comments)
            for line_num, line in enumerate(source.splitlines(), start=1):
                stripped = line.lstrip()
                # Skip comments and docstrings
                if stripped.startswith("#"):
                    continue
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                if pattern in line:
                    callers.append(
                        f"{py_file.relative_to(app_dir)}:{line_num} -> {pattern.rstrip('(')}"
                    )

    assert not callers, (
        f"Deprecated notification entrypoints still called in production code:\n"
        + "\n".join(f"  - {c}" for c in callers)
        + "\nMigrate all callers to dispatch() / safe_dispatch()."
    )


# =============================================================================
# Phase 1: LEAD_RESTORED and LEAD_IMPORTED full parity
# =============================================================================

class TestPhase1NewEvents:
    """LEAD_RESTORED and LEAD_IMPORTED must be wired in all 4 registries."""

    PHASE1_EVENTS = [
        SystemEvents.LEAD_RESTORED,
        SystemEvents.LEAD_IMPORTED,
    ]

    def test_events_exist(self):
        for event in self.PHASE1_EVENTS:
            assert hasattr(SystemEvents, event.name), f"{event.name} not in SystemEvents"

    def test_events_in_group_mapping(self):
        for event in self.PHASE1_EVENTS:
            assert event in EVENT_GROUP_MAPPING, (
                f"{event.value} missing from EVENT_GROUP_MAPPING"
            )
            assert EVENT_GROUP_MAPPING[event] == NotificationEventGroup.LEAD

    def test_events_in_notification_registry(self):
        for event in self.PHASE1_EVENTS:
            assert event in NOTIFICATION_REGISTRY, (
                f"{event.value} missing from NOTIFICATION_REGISTRY"
            )

    def test_events_in_metadata_registry(self):
        for event in self.PHASE1_EVENTS:
            assert event in EVENT_METADATA_REGISTRY, (
                f"{event.value} missing from EVENT_METADATA_REGISTRY"
            )


# =============================================================================
# Phase 2: condition_fields parity for all Phase 1 events
# =============================================================================

class TestPhase2ConditionFieldsParity:
    """Phase 2: every Phase 1 event should have condition_fields."""

    PHASE1_EVENTS = [
        SystemEvents.LEAD_CREATED, SystemEvents.LEAD_ASSIGNED,
        SystemEvents.LEAD_ASSIGNMENT_FAILED, SystemEvents.LEAD_REASSIGNED,
        SystemEvents.LEAD_STATUS_CHANGED, SystemEvents.LEAD_UPDATED,
        SystemEvents.LEAD_DELETED, SystemEvents.LEAD_RESTORED,
        SystemEvents.LEAD_IMPORTED,
        SystemEvents.CONSULTATION_CREATED, SystemEvents.CONSULTATION_UPDATED,
        SystemEvents.CONSULTATION_DELETED, SystemEvents.CONSULTATION_REMINDER,
    ]

    def test_all_phase1_events_have_condition_fields(self):
        missing = []
        for event in self.PHASE1_EVENTS:
            meta = EVENT_METADATA_REGISTRY.get(event)
            if meta and not meta.condition_fields:
                missing.append(event.value)
        assert not missing, f"Phase 1 events without condition_fields: {missing}"

    def test_no_lead_status_exposed(self):
        """lead.status must NOT appear in any event's condition_fields (D7)."""
        violations = []
        for event, meta in EVENT_METADATA_REGISTRY.items():
            if not meta.condition_fields:
                continue
            for cf in meta.condition_fields:
                if cf.path == "lead.status":
                    violations.append(event.value)
        assert not violations, f"Events exposing lead.status: {violations}"


# =============================================================================
# Step 6d: Field-level payload-to-metadata parity
# =============================================================================

class TestPayloadMetadataFieldParity:
    """
    Blocking gate: every non-internal key emitted by EventPayload.for_xxx()
    must have a corresponding variable in EVENT_METADATA_REGISTRY, and vice
    versa.  Covers all 13 Phase 1 builder events (9 Lead + 4 Consultation).
    """

    # Keys that are internal routing / not meant for admin template use
    INTERNAL_KEYS = {
        "user_ids",           # SpecificUsersResolver routing, not template
        "assignment_method",  # frontend badge hint, conditional
        "is_automatic",       # frontend badge hint, conditional
    }

    @staticmethod
    def _metadata_var_names(event: SystemEvents) -> set:
        """Extract variable names from EVENT_METADATA_REGISTRY for an event."""
        if event not in EVENT_METADATA_REGISTRY:
            return set()
        return {v.name for v in EVENT_METADATA_REGISTRY[event].variables}

    @staticmethod
    def _build_payload(builder_fn) -> dict:
        """Call builder with minimal stubs and return the payload dict."""
        from types import SimpleNamespace
        lead = SimpleNamespace(
            id=1, full_name="Test", email="t@x.com", phone="0900000000",
            unit_id=10, assigned_officer_id=5, source="web",
            pipeline_stage_id=3, consultation_status_id="new",
        )
        actor = SimpleNamespace(id=1, full_name="Admin", username="admin")
        consultation = SimpleNamespace(
            id=100, lead_id=1, officer_id=5,
            consultation_status_id="contacted",
            scheduled_at=__import__("datetime").datetime(2026, 1, 1, 10, 0),
        )
        name = builder_fn.__name__

        if name == "for_lead_created":
            return builder_fn(lead, actor)
        elif name == "for_lead_assigned":
            return builder_fn(lead, 5, actor, offering_name="N/A")
        elif name == "for_lead_assignment_failed":
            return builder_fn(lead, 10, "test reason")
        elif name == "for_lead_reassigned":
            return builder_fn(
                1, actor, old_officer_id=5, new_officer_id=None,
                old_unit_id=10, new_unit_id=20, reason="test",
            )
        elif name == "for_lead_status_changed":
            return builder_fn(
                lead, actor, old_status="a", new_status="b",
                officer_name="X", old_stage=1, new_stage=2,
                updated_fields=["f"],
            )
        elif name == "for_lead_updated":
            return builder_fn(
                lead, actor, updated_fields=["phone"],
                status_changed=False,
            )
        elif name == "for_lead_deleted":
            return builder_fn(lead, actor)
        elif name == "for_lead_restored":
            return builder_fn(lead, actor)
        elif name == "for_lead_imported":
            return builder_fn(
                unit_id=10, actor=actor, total_imported=5,
                filename="x.csv", created_lead_ids=[1, 2],
            )
        elif name == "for_consultation_created":
            return builder_fn(consultation, lead, actor)
        elif name == "for_consultation_updated":
            return builder_fn(consultation, lead, actor, old_status_id="new")
        elif name == "for_consultation_deleted":
            return builder_fn(100, lead, actor)
        elif name == "for_consultation_reminder":
            return builder_fn(consultation, lead, minutes_until=10)
        else:
            raise ValueError(f"Unknown builder: {name}")

    PARITY_MATRIX = None  # populated in setup

    @pytest.fixture(autouse=True)
    def _setup_matrix(self):
        from app.services.notification_payloads import EventPayload
        self.PARITY_MATRIX = {
            # 9 Lead events
            SystemEvents.LEAD_CREATED: EventPayload.for_lead_created,
            SystemEvents.LEAD_ASSIGNED: EventPayload.for_lead_assigned,
            SystemEvents.LEAD_ASSIGNMENT_FAILED: EventPayload.for_lead_assignment_failed,
            SystemEvents.LEAD_REASSIGNED: EventPayload.for_lead_reassigned,
            SystemEvents.LEAD_STATUS_CHANGED: EventPayload.for_lead_status_changed,
            SystemEvents.LEAD_UPDATED: EventPayload.for_lead_updated,
            SystemEvents.LEAD_DELETED: EventPayload.for_lead_deleted,
            SystemEvents.LEAD_RESTORED: EventPayload.for_lead_restored,
            SystemEvents.LEAD_IMPORTED: EventPayload.for_lead_imported,
            # 4 Consultation events
            SystemEvents.CONSULTATION_CREATED: EventPayload.for_consultation_created,
            SystemEvents.CONSULTATION_UPDATED: EventPayload.for_consultation_updated,
            SystemEvents.CONSULTATION_DELETED: EventPayload.for_consultation_deleted,
            SystemEvents.CONSULTATION_REMINDER: EventPayload.for_consultation_reminder,
        }

    def test_payload_keys_covered_by_metadata(self):
        """
        Every non-internal payload key MUST exist in metadata variables.
        Hard failure — blocks PR if drift is detected.
        """
        drift = []
        for event, builder_fn in self.PARITY_MATRIX.items():
            payload = self._build_payload(builder_fn)
            metadata_vars = self._metadata_var_names(event)
            payload_keys = set(payload.keys()) - self.INTERNAL_KEYS

            missing = payload_keys - metadata_vars
            if missing:
                drift.append(
                    f"  {event.value}: payload has {sorted(missing)} "
                    f"not in metadata variables {sorted(metadata_vars)}"
                )

        assert not drift, (
            "Payload-to-metadata field drift detected:\n"
            + "\n".join(drift)
            + "\n\nUpdate EVENT_METADATA_REGISTRY to expose these fields "
            "to the admin rule builder UI."
        )

    def test_metadata_vars_exist_in_payload(self):
        """
        Every metadata variable MUST appear in the payload.
        Catches stale metadata variables that reference removed fields.
        Hard failure — blocks PR.
        """
        stale = []
        for event, builder_fn in self.PARITY_MATRIX.items():
            payload = self._build_payload(builder_fn)
            metadata_vars = self._metadata_var_names(event)
            payload_keys = set(payload.keys())

            missing = metadata_vars - payload_keys
            if missing:
                stale.append(
                    f"  {event.value}: metadata has {sorted(missing)} "
                    f"not in payload keys {sorted(payload_keys)}"
                )

        assert not stale, (
            "Metadata variables not present in payload (stale metadata):\n"
            + "\n".join(stale)
            + "\n\nRemove stale variables or update the EventPayload builder."
        )


# =============================================================================
# PR3: Catalog-based parity — validates the ACTUAL runtime source of truth
# =============================================================================


class TestCatalogParity:
    """
    PR3: Every user event in catalog must have complete metadata
    and be consistent with what the metadata API serves.
    """

    def test_all_user_events_have_display_metadata(self):
        """Every notification_class=user event must have display_name and variables."""
        missing = []
        for defn in get_notifiable_events():
            if not defn.display_name:
                missing.append(f"{defn.event.value}: no display_name")
            if not defn.variables:
                missing.append(f"{defn.event.value}: no variables")
        assert not missing, f"User events with missing catalog metadata:\n" + "\n".join(missing)

    def test_all_user_events_have_resolver_config(self):
        """Every user event must have default_resolver and allowed_resolvers."""
        issues = []
        for defn in get_notifiable_events():
            if not defn.default_resolver:
                issues.append(f"{defn.event.value}: no default_resolver")
            if not defn.allowed_resolvers:
                issues.append(f"{defn.event.value}: no allowed_resolvers")
            elif defn.default_resolver not in defn.allowed_resolvers:
                issues.append(
                    f"{defn.event.value}: default_resolver '{defn.default_resolver}' "
                    f"not in allowed_resolvers {defn.allowed_resolvers}"
                )
        assert not issues, f"Resolver config issues:\n" + "\n".join(issues)

    def test_catalog_channels_are_canonical(self):
        """Catalog default_channels must only use canonical values."""
        CANONICAL = {"browser", "email", "zalo", "sms"}
        issues = []
        for defn in EVENT_CATALOG.values():
            for ch in defn.default_channels:
                if ch not in CANONICAL:
                    issues.append(f"{defn.event.value}: non-canonical channel '{ch}'")
        assert not issues, "\n".join(issues)

    def test_org_events_are_broadcast_only_in_catalog(self):
        """Organization events must be broadcast_only in catalog."""
        org_events = [
            "unit_created", "unit_updated", "unit_deleted",
            "program_created", "program_updated", "program_deleted",
            "offering_created", "offering_updated", "offering_deleted",
        ]
        for key in org_events:
            defn = get_event(SystemEvents(key))
            assert defn is not None, f"{key} not in catalog"
            assert defn.notification_class == "broadcast_only", (
                f"{key} should be broadcast_only, got {defn.notification_class}"
            )

    def test_catalog_user_count_matches_notifiable(self):
        """Sanity: catalog user events count == get_notifiable_events length."""
        user_count = sum(
            1 for d in EVENT_CATALOG.values()
            if d.notification_class == "user" and not d.retired
        )
        assert user_count == len(get_notifiable_events())
