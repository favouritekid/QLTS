"""Unit tests for #184 Wave 5-A migration
(``phase1_19c_seed_event_catalog_db_rows``).

Pure-text contract tests + ORM constants integrity. Locks:

1. Revision row + linear chain off ``phase1_10`` (head pre-Wave-5).
2. ``MILESTONE_EVENTS`` tuple = exactly 12 entries matching PLAN
   §3.3.d line 1644-1657.
3. Each event has every field needed by the seed (title /
   message / link / channels / resolver / category / priority).
4. Every channel listed in ``default_channels`` is one of the 4
   known transports (``browser`` / ``email`` / ``zalo`` / ``sms``).
5. Migration body uses idempotent guards:
   * ``WHERE NOT EXISTS`` for ``notification_rule`` (no UNIQUE
     constraint on the event column).
   * ``ON CONFLICT (template_code) DO NOTHING`` for
     ``notification_template`` (UNIQUE template_code).
   * ``WHERE NOT EXISTS`` for ``notification_action`` (UNIQUE on
     ``(rule_id, step)`` exists, but the ``WHERE NOT EXISTS``
     pattern lets us skip without raising).
6. ``_template_code`` helper produces ``TPL_<EVENT>`` shape
   (admin can predict the template code without query).
7. Down direction deletes from all 3 tables — actions BEFORE
   rules (FK constraint), templates last (independent).

What does NOT live here:
* Live alembic upgrade/downgrade — covered by manual roundtrip
  on dev DB pre-merge per SOP.
* Notification dispatcher integration — covered by existing
  ``test_check_notification_event_coverage_deferred.py`` lock.
* Coverage script gate (``check_notification_event_coverage.py``) —
  see PR-merge SOP step "full notification CI suite local"
  (memory ``notification-event-gate-required-locally``).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_19C = _VERSIONS_DIR / "phase1_19c_seed_event_catalog_db_rows.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location(_PHASE1_19C.stem, _PHASE1_19C)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_19c():
    return _load_migration()


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_phase1_19c_revision_id(phase1_19c) -> None:
    assert phase1_19c.revision == "phase1_19c"


def test_phase1_19c_chains_off_phase1_10(phase1_19c) -> None:
    """Wave 5 starts after Wave 2 head (phase1_10)."""
    assert phase1_19c.down_revision == "phase1_10"


def test_phase1_19c_no_branch_labels(phase1_19c) -> None:
    assert phase1_19c.branch_labels is None


# ---------------------------------------------------------------------------
# 2. MILESTONE_EVENTS — exactly 12 entries per PLAN §3.3.d
# ---------------------------------------------------------------------------


def test_phase1_19c_declares_exactly_12_events(phase1_19c) -> None:
    assert len(phase1_19c.MILESTONE_EVENTS) == 12


def test_phase1_19c_covers_all_12_admission_milestone_events(phase1_19c) -> None:
    """Event set match PLAN §3.3.d table (line 1644-1657)."""
    expected = {
        "ADMISSION_PROFILE_SUBMITTED",
        "ADMISSION_REVISION_REQUESTED",
        "ADMISSION_RESUBMITTED",
        "ADMISSION_RESULT_PUBLISHED",
        "ADMISSION_DECISION_ADMITTED",
        "ADMISSION_DECISION_WAITLISTED",
        "ADMISSION_DECISION_REJECTED",
        "ADMISSION_WAITLIST_PROMOTED",
        "ADMISSION_CONFIRMED",
        "ADMISSION_ENROLLED",
        "ADMISSION_WITHDRAWN",
        "ADMISSION_ROLLED_BACK",
    }
    actual = {entry["event"] for entry in phase1_19c.MILESTONE_EVENTS}
    assert actual == expected


# ---------------------------------------------------------------------------
# 3. Per-entry shape
# ---------------------------------------------------------------------------


def test_phase1_19c_every_entry_has_required_fields(phase1_19c) -> None:
    required = {
        "event",
        "title",
        "message",
        "link",
        "channels",
        "resolver",
        "category",
        "priority",
    }
    for entry in phase1_19c.MILESTONE_EVENTS:
        missing = required - set(entry.keys())
        assert not missing, f"{entry['event']} missing fields: {missing}"


def test_phase1_19c_titles_are_vietnamese(phase1_19c) -> None:
    """Sanity guard — titles must be non-empty Vietnamese strings.

    Each title must include at least one Vietnamese diacritic OR be
    a known short form (e.g., "$" template placeholder counted only
    if title is purely placeholder, not allowed)."""
    for entry in phase1_19c.MILESTONE_EVENTS:
        title = entry["title"]
        assert len(title) > 0
        # Allow accented chars from VN; sanity check rejects pure-ASCII titles.
        has_diacritic = any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ()/-" for c in title)
        assert has_diacritic, f"{entry['event']} title ({title!r}) has no Vietnamese diacritic — likely placeholder"


# ---------------------------------------------------------------------------
# 4. Channels are valid transports
# ---------------------------------------------------------------------------


def test_phase1_19c_channels_are_known_transports(phase1_19c) -> None:
    """Every channel must be one of the 4 supported transports.

    Drift here would silently route notifications to a non-existent
    handler — dispatcher fails closed but admin queue won't surface
    the issue without manual log dive."""
    allowed = {"browser", "email", "zalo", "sms"}
    for entry in phase1_19c.MILESTONE_EVENTS:
        for channel in entry["channels"]:
            assert channel in allowed, (
                f"{entry['event']} has unknown channel {channel!r}"
            )


def test_phase1_19c_critical_events_route_to_zalo(phase1_19c) -> None:
    """Per PLAN §3.3.d ``Bypass consent`` column — critical milestone
    events (admitted/waitlisted/rejected/result_published) must
    include zalo channel for breaking-news delivery to candidates.
    Bypass consent enforced at runtime by ``EventDefinition.bypass_consent_check``;
    here we just lock that the channel is wired."""
    critical_events = {
        "ADMISSION_RESULT_PUBLISHED",
        "ADMISSION_DECISION_ADMITTED",
        "ADMISSION_DECISION_WAITLISTED",
        "ADMISSION_DECISION_REJECTED",
        "ADMISSION_WAITLIST_PROMOTED",
    }
    for entry in phase1_19c.MILESTONE_EVENTS:
        if entry["event"] in critical_events:
            assert "zalo" in entry["channels"], (
                f"{entry['event']} (critical) missing zalo channel"
            )


# ---------------------------------------------------------------------------
# 5. Idempotent guards in upgrade body
# ---------------------------------------------------------------------------


def test_phase1_19c_rule_insert_uses_where_not_exists() -> None:
    """notification_rule.event has no UNIQUE constraint, so ON CONFLICT
    cannot apply — must use WHERE NOT EXISTS guard."""
    src = _PHASE1_19C.read_text(encoding="utf-8")
    # Both rule INSERT and action INSERT use NOT EXISTS guard.
    assert "INSERT INTO notification_rule" in src
    # Look for the WHERE NOT EXISTS pattern AFTER the rule INSERT
    rule_block_start = src.index("INSERT INTO notification_rule")
    rule_block_end = src.index("INSERT INTO notification_template")
    rule_block = src[rule_block_start:rule_block_end]
    assert "WHERE NOT EXISTS" in rule_block


def test_phase1_19c_template_insert_uses_on_conflict() -> None:
    """notification_template.template_code is UNIQUE — canonical
    idempotency shape."""
    src = _PHASE1_19C.read_text(encoding="utf-8")
    template_block_start = src.index("INSERT INTO notification_template")
    template_block_end = src.index("INSERT INTO notification_action")
    template_block = src[template_block_start:template_block_end]
    assert "ON CONFLICT (template_code) DO NOTHING" in template_block


def test_phase1_19c_action_insert_uses_not_exists_guard() -> None:
    """notification_action has UNIQUE (rule_id, step) but the
    NOT EXISTS guard pre-empts the constraint violation cleanly.
    Action body uses ``WHERE r.event = :event AND NOT EXISTS (...)``
    (different shape from rule's standalone ``WHERE NOT EXISTS``
    because action SELECT joins notification_rule first)."""
    src = _PHASE1_19C.read_text(encoding="utf-8")
    action_block_start = src.index("INSERT INTO notification_action")
    action_block = src[action_block_start:]
    upgrade_action_section = action_block[:action_block.index("def downgrade")]
    # Either standalone WHERE NOT EXISTS or AND NOT EXISTS as part
    # of joined-WHERE — both pre-empt the UNIQUE violation.
    assert "NOT EXISTS" in upgrade_action_section
    # And must include the action-specific predicate.
    assert "notification_action a" in upgrade_action_section
    assert "a.rule_id = r.id" in upgrade_action_section


# ---------------------------------------------------------------------------
# 6. Template code helper
# ---------------------------------------------------------------------------


def test_phase1_19c_template_code_pattern(phase1_19c) -> None:
    """Admin can predict template_code without DB query —
    deterministic ``TPL_<EVENT>`` shape."""
    helper = phase1_19c._template_code
    assert helper("ADMISSION_PROFILE_SUBMITTED") == "TPL_ADMISSION_PROFILE_SUBMITTED"
    assert helper("ADMISSION_DECISION_ADMITTED") == "TPL_ADMISSION_DECISION_ADMITTED"


# ---------------------------------------------------------------------------
# 7. Downgrade contract
# ---------------------------------------------------------------------------


def test_phase1_19c_downgrade_deletes_actions_before_rules() -> None:
    """FK constraint forces this order — explicit DELETE keeps the
    log readable during cutover rollback."""
    src = _PHASE1_19C.read_text(encoding="utf-8")
    downgrade_section = src[src.index("def downgrade"):]
    delete_action_pos = downgrade_section.index("DELETE FROM notification_action")
    delete_rule_pos = downgrade_section.index("DELETE FROM notification_rule")
    assert delete_action_pos < delete_rule_pos


def test_phase1_19c_downgrade_deletes_all_3_tables() -> None:
    src = _PHASE1_19C.read_text(encoding="utf-8")
    downgrade_section = src[src.index("def downgrade"):]
    for table in (
        "notification_action",
        "notification_rule",
        "notification_template",
    ):
        assert f"DELETE FROM {table}" in downgrade_section, (
            f"downgrade missing DELETE for {table}"
        )


# ---------------------------------------------------------------------------
# 8. Sanity — migration imports cleanly
# ---------------------------------------------------------------------------


def test_phase1_19c_defines_upgrade_and_downgrade(phase1_19c) -> None:
    assert callable(getattr(phase1_19c, "upgrade", None))
    assert callable(getattr(phase1_19c, "downgrade", None))
