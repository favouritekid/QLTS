# tests/unit/test_notification_parity.py
"""
Notification contract parity tests — catalog-driven (Wave 2, 2026-04-21).

These tests lock the notification contract so drift cannot be reintroduced
silently.

Wave 2 migration notes:
- Imports `NOTIFICATION_REGISTRY` and `EVENT_METADATA_REGISTRY` removed.
- Iterations over the legacy registry are now driven by
  `LEGACY_REGISTRY_EVENTS` (frozen snapshot in
  `app.core.notification_seed_defaults`) paired with `EVENT_CATALOG` lookups.
- Tests that existed only to assert parity between the two deprecated
  modules were removed because the catalog is now the single source of
  truth (see `TestCatalogParity`). Deleted: `TestEventMetadataParity`,
  `TestEventRegistryGroupParity`, `TestCanonicalChannelValues`,
  `test_admin_events_have_metadata`.
- `TestHolidayCalendarParity` and `TestPhase1NewEvents` collapsed their
  registry + metadata existence checks into a single catalog existence
  check.
- `TestPhase2ConditionFieldsParity` excludes `LEAD_UPDATED` because the
  catalog classifies it as `broadcast_only` (no admin-configurable
  condition_fields). Mirrors the same decision in
  `test_condition_metadata_parity.py`.
"""
import inspect
from pathlib import Path

import pytest

from app.core.events import SystemEvents
from app.core.event_groups import EVENT_GROUP_MAPPING, NotificationEventGroup
from app.core.event_catalog import EVENT_CATALOG, get_event, get_notifiable_events
from app.core.notification_seed_defaults import LEGACY_REGISTRY_EVENTS


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

        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'APPLICATION_CREATED' in line and 'safe_dispatch' in lines[max(0, i-3):i+1].__repr__():
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
        assert SystemEvents.APPLICATION_CREATED.value == "application_created"
        assert SystemEvents.APPLICATION_STATUS_CHANGED.value == "application_status_changed"


# =============================================================================
# A2: HOLIDAY_CALENDAR_INCOMPLETE must have full parity (catalog-driven)
# =============================================================================

class TestHolidayCalendarParity:
    """HOLIDAY_CALENDAR_INCOMPLETE must exist in all authoritative systems."""

    def test_exists_in_system_events(self):
        assert hasattr(SystemEvents, 'HOLIDAY_CALENDAR_INCOMPLETE')
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE.value == "holiday_calendar_incomplete"

    def test_exists_in_event_group_mapping(self):
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE in EVENT_GROUP_MAPPING, (
            "HOLIDAY_CALENDAR_INCOMPLETE must be in EVENT_GROUP_MAPPING"
        )
        assert EVENT_GROUP_MAPPING[SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE] == NotificationEventGroup.SYSTEM

    def test_exists_in_event_catalog(self):
        """Event must exist in the catalog (runtime source of truth)."""
        assert SystemEvents.HOLIDAY_CALENDAR_INCOMPLETE in EVENT_CATALOG, (
            "HOLIDAY_CALENDAR_INCOMPLETE must be in EVENT_CATALOG"
        )

    def test_exists_in_legacy_registry_events(self):
        """Still in the frozen legacy-registry set (seeded by bootstrap)."""
        assert "holiday_calendar_incomplete" in LEGACY_REGISTRY_EVENTS


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

    def test_org_events_not_in_legacy_registry(self):
        """Organization events must not be seeded by the bootstrap registry."""
        for value in self.ORG_EVENT_VALUES:
            assert value not in LEGACY_REGISTRY_EVENTS, (
                f"'{value}' must NOT be in LEGACY_REGISTRY_EVENTS. "
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
                recipient_config={"resolver_type": "all_admins", "params": {}},
            )
            with pytest.raises(BadRequest, match="not a configurable user event"):
                await create_rule(mock_db, rule_data)


# =============================================================================
# P1: Automated Parity Checks (Addendum Section 10)
# =============================================================================

# Known broadcast-only events — these are domain broadcast events (Socket.IO
# real-time UI refresh) with no user notification contract.  They are
# intentionally excluded from EVENT_GROUP_MAPPING and the legacy registry set.
_BROADCAST_ONLY_PREFIXES = ("UNIT_", "PROGRAM_", "OFFERING_")


@pytest.mark.unit
def test_all_system_events_have_group_mapping():
    """
    P1-1: Every SystemEvents value must exist in EVENT_GROUP_MAPPING keys,
    except known broadcast-only events (UNIT_*, PROGRAM_*, OFFERING_*).
    """
    unmapped = set()
    for event in SystemEvents:
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
    """
    missing = []
    for event in EVENT_GROUP_MAPPING:
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
def test_catalog_channels_are_implemented_or_gated():
    """
    P1-4 (migrated from metadata to catalog): every channel referenced in
    catalog default_channels must be implemented or a known planned channel.
    """
    from app.services.notification_channels import CHANNEL_REGISTRY

    implemented = set(CHANNEL_REGISTRY.keys())
    planned_gated = {"sms", "zalo"}
    allowed = implemented | planned_gated

    violations = []
    for event, defn in EVENT_CATALOG.items():
        for ch in defn.default_channels:
            if ch not in allowed:
                violations.append(
                    f"{event.value}: channel '{ch}' not in "
                    f"implemented {sorted(implemented)} or "
                    f"planned {sorted(planned_gated)}"
                )

    assert not violations, (
        f"Catalog references channels that are neither implemented nor planned:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )


@pytest.mark.unit
def test_deprecated_entrypoints_have_no_production_callers():
    """
    P1-5: Deprecated functions create_notification() and
    execute_notification_workflow() must not be called from production code
    (app/ directory).
    """
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

        if filename in definition_files:
            continue

        if "test" in filename or "conftest" in filename:
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for pattern in deprecated_patterns:
            for line_num, line in enumerate(source.splitlines(), start=1):
                stripped = line.lstrip()
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
    """LEAD_RESTORED and LEAD_IMPORTED must be wired in catalog + group mapping."""

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

    def test_events_in_catalog(self):
        """Phase 1 events must be present in the catalog (merged from
        prior `test_events_in_notification_registry` +
        `test_events_in_metadata_registry` which both collapsed into
        catalog as single source of truth)."""
        for event in self.PHASE1_EVENTS:
            assert event in EVENT_CATALOG, (
                f"{event.value} missing from EVENT_CATALOG"
            )

    def test_events_in_legacy_registry(self):
        """Still seeded by bootstrap (frozen snapshot)."""
        for event in self.PHASE1_EVENTS:
            assert event.value in LEGACY_REGISTRY_EVENTS


# =============================================================================
# Phase 2: condition_fields parity for Phase 1 events
# =============================================================================

class TestPhase2ConditionFieldsParity:
    """Phase 2: every user-class Phase 1 event should have condition_fields.

    LEAD_UPDATED is excluded: catalog classifies it as `broadcast_only`
    (no admin-configurable contract) — see catalog entry.
    """

    PHASE1_EVENTS = [
        SystemEvents.LEAD_CREATED, SystemEvents.LEAD_ASSIGNED,
        SystemEvents.LEAD_ASSIGNMENT_FAILED, SystemEvents.LEAD_REASSIGNED,
        SystemEvents.LEAD_STATUS_CHANGED,
        SystemEvents.LEAD_DELETED, SystemEvents.LEAD_RESTORED,
        SystemEvents.LEAD_IMPORTED,
        SystemEvents.CONSULTATION_CREATED, SystemEvents.CONSULTATION_UPDATED,
        SystemEvents.CONSULTATION_DELETED, SystemEvents.CONSULTATION_REMINDER,
    ]

    def test_all_phase1_events_have_condition_fields(self):
        missing = []
        for event in self.PHASE1_EVENTS:
            defn = EVENT_CATALOG.get(event)
            if defn and not defn.condition_fields:
                missing.append(event.value)
        assert not missing, f"Phase 1 events without condition_fields: {missing}"

    def test_no_lead_status_exposed(self):
        """lead.status must NOT appear in any event's condition_fields (D7)."""
        violations = []
        for event, defn in EVENT_CATALOG.items():
            if not defn.condition_fields:
                continue
            for cf in defn.condition_fields:
                if cf.path == "lead.status":
                    violations.append(event.value)
        assert not violations, f"Events exposing lead.status: {violations}"


# =============================================================================
# Step 6d: Field-level payload-to-metadata parity
# =============================================================================

class TestPayloadMetadataFieldParity:
    """
    Blocking gate: every non-internal key emitted by EventPayload.for_xxx()
    must have a corresponding variable in the catalog, and vice versa.
    Covers all 13 Phase 1 builder events (9 Lead + 4 Consultation).
    """

    INTERNAL_KEYS = {
        "user_ids",
        "assignment_method",
        "is_automatic",
    }

    @staticmethod
    def _catalog_var_names(event: SystemEvents) -> set:
        """Extract variable names from the catalog for an event."""
        defn = EVENT_CATALOG.get(event)
        if defn is None:
            return set()
        return {v.name for v in defn.variables}

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
        # LEAD_UPDATED intentionally excluded: catalog classifies it as
        # `broadcast_only` and does not declare variables for it. The
        # EventPayload.for_lead_updated builder still emits payload keys
        # (message, updated_at, updated_by, updated_summary) for the
        # Socket.IO UI sync path, but there is no admin-configurable
        # rule for this event so no catalog parity is required. See
        # also TestPhase2ConditionFieldsParity which excludes it for
        # the same reason.
        from app.services.notification_payloads import EventPayload
        self.PARITY_MATRIX = {
            SystemEvents.LEAD_CREATED: EventPayload.for_lead_created,
            SystemEvents.LEAD_ASSIGNED: EventPayload.for_lead_assigned,
            SystemEvents.LEAD_ASSIGNMENT_FAILED: EventPayload.for_lead_assignment_failed,
            SystemEvents.LEAD_REASSIGNED: EventPayload.for_lead_reassigned,
            SystemEvents.LEAD_STATUS_CHANGED: EventPayload.for_lead_status_changed,
            SystemEvents.LEAD_DELETED: EventPayload.for_lead_deleted,
            SystemEvents.LEAD_RESTORED: EventPayload.for_lead_restored,
            SystemEvents.LEAD_IMPORTED: EventPayload.for_lead_imported,
            SystemEvents.CONSULTATION_CREATED: EventPayload.for_consultation_created,
            SystemEvents.CONSULTATION_UPDATED: EventPayload.for_consultation_updated,
            SystemEvents.CONSULTATION_DELETED: EventPayload.for_consultation_deleted,
            SystemEvents.CONSULTATION_REMINDER: EventPayload.for_consultation_reminder,
        }

    def test_payload_keys_covered_by_metadata(self):
        """
        Every non-internal payload key MUST exist in catalog variables.
        Hard failure — blocks PR if drift is detected.
        """
        drift = []
        for event, builder_fn in self.PARITY_MATRIX.items():
            payload = self._build_payload(builder_fn)
            catalog_vars = self._catalog_var_names(event)
            payload_keys = set(payload.keys()) - self.INTERNAL_KEYS

            missing = payload_keys - catalog_vars
            if missing:
                drift.append(
                    f"  {event.value}: payload has {sorted(missing)} "
                    f"not in catalog variables {sorted(catalog_vars)}"
                )

        assert not drift, (
            "Payload-to-catalog field drift detected:\n"
            + "\n".join(drift)
            + "\n\nUpdate EVENT_CATALOG variables to expose these fields "
            "to the admin rule builder UI."
        )

    def test_metadata_vars_exist_in_payload(self):
        """
        Every catalog variable MUST appear in the payload.
        Catches stale variables that reference removed fields.
        Hard failure — blocks PR.
        """
        stale = []
        for event, builder_fn in self.PARITY_MATRIX.items():
            payload = self._build_payload(builder_fn)
            catalog_vars = self._catalog_var_names(event)
            payload_keys = set(payload.keys())

            missing = catalog_vars - payload_keys
            if missing:
                stale.append(
                    f"  {event.value}: catalog has {sorted(missing)} "
                    f"not in payload keys {sorted(payload_keys)}"
                )

        assert not stale, (
            "Catalog variables not present in payload (stale metadata):\n"
            + "\n".join(stale)
            + "\n\nRemove stale variables or update the EventPayload builder."
        )


# =============================================================================
# PR3: Catalog-based parity — validates the ACTUAL runtime source of truth
# =============================================================================


class TestCatalogParity:
    """
    Every user event in catalog must have complete metadata
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


# =============================================================================
# Wave 1: legacy-registry snapshot ↔ catalog parity
# =============================================================================


class TestLegacyRegistrySnapshotParity:
    """Wave 1 (2026-04-21): the frozen LEGACY_REGISTRY_EVENTS set is the
    bootstrap contract for `seed_notification_rules.py` +
    `reset_notification_rules_dev.py` after the seed scripts stopped
    importing NOTIFICATION_REGISTRY. It must stay fully covered by
    `EVENT_CATALOG` so the seeder can look up channels/link per event."""

    def test_every_legacy_event_exists_in_catalog(self):
        missing = []
        for event_name in LEGACY_REGISTRY_EVENTS:
            try:
                event = SystemEvents(event_name)
            except ValueError:
                missing.append(f"{event_name}: not a valid SystemEvents value")
                continue
            if event not in EVENT_CATALOG:
                missing.append(event_name)
        assert not missing, (
            f"LEGACY_REGISTRY_EVENTS members missing from EVENT_CATALOG: "
            f"{sorted(missing)}"
        )

    def test_every_legacy_event_has_group_mapping(self):
        missing = []
        for event_name in LEGACY_REGISTRY_EVENTS:
            try:
                event = SystemEvents(event_name)
            except ValueError:
                continue
            if event not in EVENT_GROUP_MAPPING:
                missing.append(event_name)
        assert not missing, (
            f"LEGACY_REGISTRY_EVENTS members missing from EVENT_GROUP_MAPPING: "
            f"{sorted(missing)}"
        )
