"""Unit tests for Q9 #07 Phase E Foundation seed migration
(``q9_07_e0b_seed_priority_events``).

Mirrors `test_phase1_19c_seed_event_catalog.py` pattern. Locks:

1. Revision row + chain off ``q9_07_e0a`` (audit_log table).
2. ``PRIORITY_EVENTS`` tuple = exactly 3 entries per Phase E.2 + E.3 scope:
   * priority_kv_overridden (Phase E.2)
   * priority_object_verified (Phase E.3)
   * priority_object_rejected (Phase E.3)
3. Each event has every field needed by the seed.
4. Every channel listed is one of 4 known transports (browser/email/zalo/sms).
5. Migration body uses same idempotent guards as phase1_19c.
6. ``_template_code`` helper produces ``TPL_<event>`` shape.
7. Down direction deletes from all 3 tables — actions → rules → templates.

Catalog parity: each SystemEvents PRIORITY_* enum has matching
EventDefinition trong event_catalog.py + matching seed entry trong
migration. Drift catches misalignment per memory
``notification-event-gate-required-locally``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_Q9_07_E0B = _VERSIONS_DIR / "q9_07_e0b_seed_priority_events.py"

EXPECTED_EVENTS = (
    "priority_kv_overridden",
    "priority_object_verified",
    "priority_object_rejected",
)
KNOWN_CHANNELS = {"browser", "email", "zalo", "sms"}


def _load_migration():
    spec = importlib.util.spec_from_file_location(_Q9_07_E0B.stem, _Q9_07_E0B)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def q9_07_e0b():
    return _load_migration()


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_revision_id(q9_07_e0b) -> None:
    assert q9_07_e0b.revision == "q9_07_e0b"


def test_chains_off_audit_log_migration(q9_07_e0b) -> None:
    """Foundation seed depends on audit_log table existing."""
    assert q9_07_e0b.down_revision == "q9_07_e0a"


def test_no_branch_labels(q9_07_e0b) -> None:
    assert q9_07_e0b.branch_labels is None


# ---------------------------------------------------------------------------
# 2. PRIORITY_EVENTS tuple shape + count
# ---------------------------------------------------------------------------


def test_priority_events_count_3(q9_07_e0b) -> None:
    """Phase E.2 + E.3 scope = exactly 3 priority events."""
    assert len(q9_07_e0b.PRIORITY_EVENTS) == 3


def test_priority_events_in_order(q9_07_e0b) -> None:
    """Order locked: override (E.2) → verified (E.3) → rejected (E.3)."""
    actual = tuple(e["event"] for e in q9_07_e0b.PRIORITY_EVENTS)
    assert actual == EXPECTED_EVENTS


@pytest.mark.parametrize("event_name", EXPECTED_EVENTS)
def test_each_event_has_required_fields(q9_07_e0b, event_name) -> None:
    """Every seed entry has the 8 fields the SQL loop reads."""
    entry = next(e for e in q9_07_e0b.PRIORITY_EVENTS if e["event"] == event_name)
    required = {"event", "title", "message", "link", "channels",
                "resolver", "category", "priority"}
    assert required.issubset(entry.keys())


@pytest.mark.parametrize("event_name", EXPECTED_EVENTS)
def test_channels_are_known_transports(q9_07_e0b, event_name) -> None:
    """Reject typo channels (vd 'mail' instead of 'email')."""
    entry = next(e for e in q9_07_e0b.PRIORITY_EVENTS if e["event"] == event_name)
    for channel in entry["channels"]:
        assert channel in KNOWN_CHANNELS, f"Unknown channel {channel!r} in {event_name}"


def test_link_template_format(q9_07_e0b) -> None:
    """All priority events link to /admissions/$application_id."""
    for entry in q9_07_e0b.PRIORITY_EVENTS:
        assert entry["link"] == "/admissions/$application_id"


def test_category_is_application(q9_07_e0b) -> None:
    """Priority events fall under application category (not separate)."""
    for entry in q9_07_e0b.PRIORITY_EVENTS:
        assert entry["category"] == "application"


def test_rejected_includes_zalo_channel(q9_07_e0b) -> None:
    """Per plan v2: rejected event urgent → Zalo channel included."""
    rejected = next(
        e for e in q9_07_e0b.PRIORITY_EVENTS if e["event"] == "priority_object_rejected"
    )
    assert "zalo" in rejected["channels"]


def test_resolver_is_lead_owner(q9_07_e0b) -> None:
    """All priority events notify candidate (lead_owner resolver)."""
    for entry in q9_07_e0b.PRIORITY_EVENTS:
        assert entry["resolver"] == "lead_owner"


# ---------------------------------------------------------------------------
# 3. Template code helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_name", EXPECTED_EVENTS)
def test_template_code_shape(q9_07_e0b, event_name) -> None:
    """TPL_<event> shape — admin can predict from event name."""
    assert q9_07_e0b._template_code(event_name) == f"TPL_{event_name}"


# ---------------------------------------------------------------------------
# 4. SystemEvents enum + EventCatalog parity
# ---------------------------------------------------------------------------


def test_systemevents_enum_has_3_priority_events() -> None:
    """Foundation: SystemEvents enum exposes 3 PRIORITY_* values."""
    from app.core.events import SystemEvents

    enum_values = {
        SystemEvents.PRIORITY_KV_OVERRIDDEN.value,
        SystemEvents.PRIORITY_OBJECT_VERIFIED.value,
        SystemEvents.PRIORITY_OBJECT_REJECTED.value,
    }
    assert enum_values == set(EXPECTED_EVENTS)


def test_event_catalog_has_3_priority_definitions() -> None:
    """Foundation: EVENT_CATALOG contains 3 EventDefinition for priority.

    EVENT_CATALOG is a dict keyed by SystemEvents enum member.
    """
    from app.core.event_catalog import EVENT_CATALOG
    from app.core.events import SystemEvents

    assert SystemEvents.PRIORITY_KV_OVERRIDDEN in EVENT_CATALOG
    assert SystemEvents.PRIORITY_OBJECT_VERIFIED in EVENT_CATALOG
    assert SystemEvents.PRIORITY_OBJECT_REJECTED in EVENT_CATALOG


@pytest.mark.parametrize("event_name", EXPECTED_EVENTS)
def test_seed_channels_match_catalog_channels(q9_07_e0b, event_name) -> None:
    """Drift guard: seed entry channels = EventDefinition default_channels."""
    from app.core.event_catalog import EVENT_CATALOG
    from app.core.events import SystemEvents

    enum_member = SystemEvents(event_name)
    catalog_entry = EVENT_CATALOG[enum_member]
    seed_entry = next(
        e for e in q9_07_e0b.PRIORITY_EVENTS if e["event"] == event_name
    )
    assert tuple(seed_entry["channels"]) == catalog_entry.default_channels


# ---------------------------------------------------------------------------
# 5. Migration body idempotency markers
# ---------------------------------------------------------------------------


def test_upgrade_has_where_not_exists_guard(q9_07_e0b) -> None:
    """notification_rule INSERT must be idempotent (no UNIQUE on event)."""
    import inspect
    source = inspect.getsource(q9_07_e0b.upgrade)
    assert "WHERE NOT EXISTS" in source
    assert "FROM notification_rule WHERE event" in source


def test_upgrade_template_uses_on_conflict(q9_07_e0b) -> None:
    """notification_template INSERT uses ON CONFLICT (template_code UNIQUE)."""
    import inspect
    source = inspect.getsource(q9_07_e0b.upgrade)
    assert "ON CONFLICT (template_code) DO NOTHING" in source


def test_downgrade_deletes_in_fk_safe_order(q9_07_e0b) -> None:
    """actions → rules → templates (FK constraint order)."""
    import inspect
    source = inspect.getsource(q9_07_e0b.downgrade)
    actions_idx = source.find("notification_action")
    rules_idx = source.find("notification_rule")
    templates_idx = source.find("notification_template")
    assert actions_idx < rules_idx < templates_idx, (
        "Downgrade must delete actions BEFORE rules (FK constraint)"
    )
