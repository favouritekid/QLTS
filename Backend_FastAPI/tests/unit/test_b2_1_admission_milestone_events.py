"""B2.1 — coverage for the 12 ADMISSION_* milestone events.

Three layers, all unit-level (no DB):

1. **Enum + dataclass extension contract.** The 12 enum values exist on
   `SystemEvents`; `EventDefinition` carries the two new optional flags
   `requires_outbox` + `bypass_consent_check` (additive, default False),
   so the existing 200+ catalog entries keep their behaviour unchanged.
2. **Cross-file parity.** Each of the 12 events is wired into
   ``EVENT_CATALOG`` (semantics), ``EVENT_GROUP_MAPPING`` (admin UI
   cluster — APPLICATION group), and ``NOTIFICATION_SEED_DEFAULTS``
   (admin-UI seed content). One missing entry would silently skip the
   event from a downstream surface, which is exactly what the existing
   coverage script complains about. We assert it here so the failure
   surfaces in pytest, not only in the script.
3. **Outbox / consent-bypass routing matches PLAN §3.3.d table.** The 7
   `requires_outbox=True` events and the 5 `bypass_consent_check=True`
   events match the table the runbook depends on (line 1644-1657 of
   `Documents/ADMISSION_REFACTOR_PLAN.md`). If a future edit drops the
   flag on an event the matrix needs, this test bites loudly.

The coverage script (`app/scripts/check_notification_event_coverage.py`)
also reports a `no-dispatch-site` gap for all 12 events. That gap is
**expected** at B2.1 — dispatch sites ship in `#16` (state-service
transitions). When `dispatch_event()` lands in B2.3 and the 11
`profile.status =` assignments swap to `state_service.transition()` in
`#16`, the coverage script will go green.
"""
from __future__ import annotations

import pytest

from app.core.event_catalog import EVENT_CATALOG, EventDefinition
from app.core.event_groups import EVENT_GROUP_MAPPING, NotificationEventGroup
from app.core.events import SystemEvents
from app.core.notification_seed_defaults import NOTIFICATION_SEED_DEFAULTS


# Authoritative list — order matches PLAN §3.3.d table line 1644-1657.
NEW_ADMISSION_EVENTS: tuple[SystemEvents, ...] = (
    SystemEvents.ADMISSION_PROFILE_SUBMITTED,        # T1
    SystemEvents.ADMISSION_REVISION_REQUESTED,        # T3, T4
    SystemEvents.ADMISSION_RESUBMITTED,               # T5
    SystemEvents.ADMISSION_RESULT_PUBLISHED,          # T6  — outbox + bypass
    SystemEvents.ADMISSION_DECISION_ADMITTED,         # T7  — outbox + bypass
    SystemEvents.ADMISSION_DECISION_WAITLISTED,       # T8  — outbox + bypass
    SystemEvents.ADMISSION_DECISION_REJECTED,         # T9  — outbox + bypass
    SystemEvents.ADMISSION_WAITLIST_PROMOTED,         # T10 — outbox
    SystemEvents.ADMISSION_CONFIRMED,                 # T12
    SystemEvents.ADMISSION_ENROLLED,                  # T13 — outbox + bypass
    SystemEvents.ADMISSION_WITHDRAWN,                 # T14, T15, T16
    SystemEvents.ADMISSION_ROLLED_BACK,               # T17 — outbox
)

REQUIRES_OUTBOX_EVENTS: frozenset[SystemEvents] = frozenset({
    SystemEvents.ADMISSION_RESULT_PUBLISHED,
    SystemEvents.ADMISSION_DECISION_ADMITTED,
    SystemEvents.ADMISSION_DECISION_WAITLISTED,
    SystemEvents.ADMISSION_DECISION_REJECTED,
    SystemEvents.ADMISSION_WAITLIST_PROMOTED,
    SystemEvents.ADMISSION_ENROLLED,
    SystemEvents.ADMISSION_ROLLED_BACK,
})

BYPASS_CONSENT_EVENTS: frozenset[SystemEvents] = frozenset({
    SystemEvents.ADMISSION_RESULT_PUBLISHED,
    SystemEvents.ADMISSION_DECISION_ADMITTED,
    SystemEvents.ADMISSION_DECISION_WAITLISTED,
    SystemEvents.ADMISSION_DECISION_REJECTED,
    SystemEvents.ADMISSION_ENROLLED,
})


# ---------------------------------------------------------------------------
# Layer 1 — enum + dataclass contract
# ---------------------------------------------------------------------------


def test_12_new_enum_values_defined():
    """Lock the canonical 12 + their string values so a future rename
    becomes a visible breaking change."""
    expected_value_pairs = [
        ("ADMISSION_PROFILE_SUBMITTED", "admission_profile_submitted"),
        ("ADMISSION_REVISION_REQUESTED", "admission_revision_requested"),
        ("ADMISSION_RESUBMITTED", "admission_resubmitted"),
        ("ADMISSION_RESULT_PUBLISHED", "admission_result_published"),
        ("ADMISSION_DECISION_ADMITTED", "admission_decision_admitted"),
        ("ADMISSION_DECISION_WAITLISTED", "admission_decision_waitlisted"),
        ("ADMISSION_DECISION_REJECTED", "admission_decision_rejected"),
        ("ADMISSION_WAITLIST_PROMOTED", "admission_waitlist_promoted"),
        ("ADMISSION_CONFIRMED", "admission_confirmed"),
        ("ADMISSION_ENROLLED", "admission_enrolled"),
        ("ADMISSION_WITHDRAWN", "admission_withdrawn"),
        ("ADMISSION_ROLLED_BACK", "admission_rolled_back"),
    ]
    for name, expected_value in expected_value_pairs:
        assert hasattr(SystemEvents, name), f"SystemEvents.{name} missing"
        assert SystemEvents[name].value == expected_value, (
            f"SystemEvents.{name} = {SystemEvents[name].value!r}; "
            f"expected {expected_value!r}"
        )


def test_eventdefinition_carries_outbox_routing_flags():
    """The two new optional flags must exist on the dataclass."""
    field_names = set(EventDefinition.__dataclass_fields__)
    assert "requires_outbox" in field_names
    assert "bypass_consent_check" in field_names


def test_existing_events_default_to_false_on_new_flags():
    """Additive extension: pre-B2.1 catalog entries inherit the False
    defaults. If a future PR flips one accidentally, this fails."""
    legacy_examples = [
        SystemEvents.LEAD_ASSIGNED,
        SystemEvents.APPLICATION_CREATED,
        SystemEvents.PAYMENT_RECEIVED,
        SystemEvents.ADMISSION_CONFIRMATION_REMINDER_24H,
    ]
    for ev in legacy_examples:
        defn = EVENT_CATALOG[ev]
        assert defn.requires_outbox is False, (
            f"{ev.name} unexpectedly has requires_outbox=True; only the 12 "
            f"B2.1 events should opt in"
        )
        assert defn.bypass_consent_check is False, (
            f"{ev.name} unexpectedly has bypass_consent_check=True"
        )


# ---------------------------------------------------------------------------
# Layer 2 — cross-file parity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event", NEW_ADMISSION_EVENTS, ids=lambda e: e.name)
def test_event_present_in_catalog(event):
    assert event in EVENT_CATALOG, (
        f"{event.name} missing from EVENT_CATALOG. The seeder + admin UI "
        f"would skip it silently. Add an EventDefinition entry to "
        f"`app/core/event_catalog.py` `_ADMISSION_EVENTS` tuple."
    )
    defn = EVENT_CATALOG[event]
    assert defn.category == "application", (
        f"{event.name} category should be 'application' for admin-UI grouping"
    )


@pytest.mark.parametrize("event", NEW_ADMISSION_EVENTS, ids=lambda e: e.name)
def test_event_present_in_group_mapping(event):
    assert event in EVENT_GROUP_MAPPING, (
        f"{event.name} missing from EVENT_GROUP_MAPPING — the parity check "
        f"in `tests/unit/test_event_groups.py` would also fail. Add an "
        f"entry to `app/core/event_groups.py`."
    )
    assert EVENT_GROUP_MAPPING[event] is NotificationEventGroup.APPLICATION, (
        f"{event.name} must map to NotificationEventGroup.APPLICATION; "
        f"got {EVENT_GROUP_MAPPING[event]!r}"
    )


@pytest.mark.parametrize("event", NEW_ADMISSION_EVENTS, ids=lambda e: e.name)
def test_event_present_in_seed_defaults(event):
    """Coverage script (`check_notification_event_coverage.py:65`) requires
    every `notification_class="user"` non-retired catalog entry to have a
    seed default. All 12 B2.1 events default to user-class, so all 12
    must be in this dict."""
    assert event in NOTIFICATION_SEED_DEFAULTS, (
        f"{event.name} missing from NOTIFICATION_SEED_DEFAULTS — the "
        f"coverage script will fail with `seed-missing` on this event "
        f"and the seeder will skip it on dev/staging reset."
    )
    seed = NOTIFICATION_SEED_DEFAULTS[event]
    for required_key in ("title_template", "message_template", "notification_type", "recipient_config"):
        assert required_key in seed, (
            f"{event.name} seed missing required key {required_key!r}"
        )


# ---------------------------------------------------------------------------
# Layer 3 — outbox / bypass-consent routing matches PLAN §3.3.d
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event", NEW_ADMISSION_EVENTS, ids=lambda e: e.name)
def test_requires_outbox_flag_matches_plan(event):
    defn = EVENT_CATALOG[event]
    expected = event in REQUIRES_OUTBOX_EVENTS
    assert defn.requires_outbox is expected, (
        f"{event.name}: PLAN §3.3.d expects requires_outbox={expected}, "
        f"catalog has {defn.requires_outbox}. T0-4b worker delivery "
        f"guarantee depends on this matrix."
    )


@pytest.mark.parametrize("event", NEW_ADMISSION_EVENTS, ids=lambda e: e.name)
def test_bypass_consent_check_flag_matches_plan(event):
    defn = EVENT_CATALOG[event]
    expected = event in BYPASS_CONSENT_EVENTS
    assert defn.bypass_consent_check is expected, (
        f"{event.name}: PLAN §3.3.d expects bypass_consent_check={expected}, "
        f"catalog has {defn.bypass_consent_check}. Compliance with Quy chế "
        f"Bộ GD&ĐT (in-app + email always-on for the 5 critical events) "
        f"depends on this matrix."
    )


def test_total_outbox_count_is_7():
    """Round-trip assertion against PLAN §3.3.d wording 'outbox 7 / best-effort 5'."""
    catalog_outbox = {
        ev for ev in NEW_ADMISSION_EVENTS if EVENT_CATALOG[ev].requires_outbox
    }
    assert catalog_outbox == REQUIRES_OUTBOX_EVENTS
    assert len(catalog_outbox) == 7


def test_total_bypass_consent_count_is_5():
    catalog_bypass = {
        ev for ev in NEW_ADMISSION_EVENTS if EVENT_CATALOG[ev].bypass_consent_check
    }
    assert catalog_bypass == BYPASS_CONSENT_EVENTS
    assert len(catalog_bypass) == 5
