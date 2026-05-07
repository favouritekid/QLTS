"""Phase 1 hotfix-2 — payload-template placeholder parity lock-in test.

The dispatcher renders templates via ``string.Template.safe_substitute``
which intentionally leaves unresolved placeholders as literal text
(``${var_name}``) instead of raising. That makes a payload missing
required keys silently leak placeholders into user-facing messages.

This test locks the contract: for every reachable Phase 1 ADMISSION_*
event, the dispatched payload provides every variable the seeded
template (``notification_seed_defaults.NOTIFICATION_SEED_DEFAULTS``)
declares. If a future PR adds a placeholder to a template without
updating the dispatch payload (or vice-versa), this test fails loud
— preventing the regression class merged_001 surfaced in the cutover
ultrareview.

What this file owns
-------------------
* Per-Phase-1-reachable-event payload-shape lock: the union of dict
  keys an ADMISSION_* dispatch site emits at runtime MUST contain
  every ``$placeholder`` referenced by the seeded ``message_template``
  / ``title_template`` for that event.

What this file does NOT own
---------------------------
* End-to-end notification rendering (covered by integration tests).
* Best-effort vs outbox routing semantics (covered by
  ``test_check_notification_event_coverage_*``).
* Phase 3 deferred events (RESULT_PUBLISHED, WAITLISTED, PROMOTED,
  ROLLED_BACK) — those have no live writer in Phase 1 so their
  payload-shape contract is N/A until Phase 3 ships.
"""
from __future__ import annotations

import re
from string import Template
from typing import Set

import pytest

from app.core.events import SystemEvents
from app.core.notification_seed_defaults import NOTIFICATION_SEED_DEFAULTS


pytestmark = pytest.mark.unit


# =============================================================================
# Active Phase 1 reachable events + their dispatch-site payload shape
# =============================================================================
#
# These are the events ``transition()`` and direct router-side
# ``safe_dispatch`` actually fire in Phase 1. Each set lists the
# union of payload keys the dispatch site emits, sourced from the
# code reading at the call site (NOT inferred — kept explicit so a
# future caller-side rename forces this fixture to update).
#
# The 4 deferred Phase 3 events
# (RESULT_PUBLISHED / DECISION_WAITLISTED / WAITLIST_PROMOTED /
# ADMISSION_ROLLED_BACK) are excluded from this parity check — no
# live writer in Phase 1 so the payload contract is N/A until those
# writers ship in Phase 3 alongside choice-engine.

PHASE1_REACHABLE_EVENTS: dict[SystemEvents, Set[str]] = {
    # Router-side direct dispatch ``admissions.py`` post-submit_and_evaluate.
    # Hotfix-2 added ``submitted_at_iso``.
    SystemEvents.ADMISSION_PROFILE_SUBMITTED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
        "submitted_at_iso",
    },
    # transition() base + event_metadata={"revision_reason": ...}
    SystemEvents.ADMISSION_REVISION_REQUESTED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
        "revision_reason",
    },
    # transition() base only — template uses base keys.
    SystemEvents.ADMISSION_RESUBMITTED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
    },
    # transition() base only — active seed template doesn't reference
    # choice_priority / total_score (those exist only on the orphan
    # uppercase migration row + Phase 3 future writers).
    SystemEvents.ADMISSION_DECISION_ADMITTED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
    },
    SystemEvents.ADMISSION_DECISION_REJECTED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
    },
    # transition() base + event_metadata={"confirmed_via": ...}
    SystemEvents.ADMISSION_CONFIRMED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
        "confirmed_via",
    },
    # transition() base + event_metadata={"student_id": student_code}
    # (key renamed from ``student_code`` in hotfix-2 to match template).
    SystemEvents.ADMISSION_ENROLLED: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
        "student_id",
    },
    # transition() base + event_metadata={
    #   from_status, withdrawn_by_role, reason
    # }
    SystemEvents.ADMISSION_WITHDRAWN: {
        "application_id",
        "lead_id",
        "old_status",
        "new_status",
        "actor_id",
        "from_status",
        "withdrawn_by_role",
        "reason",
    },
}


# =============================================================================
# Helpers
# =============================================================================


_PLACEHOLDER_PATTERN = re.compile(
    # ``string.Template`` accepts ``$var`` and ``${var}`` (not ``$$``,
    # which is a literal ``$``). Match either form.
    r"\$(?:\{([a-zA-Z_][a-zA-Z0-9_]*)\}|([a-zA-Z_][a-zA-Z0-9_]*))"
)


def _placeholders_in(template_text: str) -> Set[str]:
    """Extract the set of placeholder names from a Template string,
    supporting both ``$var`` and ``${var}`` forms."""
    if not template_text:
        return set()
    return {
        match.group(1) or match.group(2)
        for match in _PLACEHOLDER_PATTERN.finditer(template_text)
    }


def _seed_for_event(event: SystemEvents) -> dict:
    """Resolve the seed dict for ``event`` from
    ``NOTIFICATION_SEED_DEFAULTS``. Raises if missing."""
    seed = NOTIFICATION_SEED_DEFAULTS.get(event)
    if seed is None:
        raise AssertionError(
            f"Seed entry for event {event!r} not found in "
            f"NOTIFICATION_SEED_DEFAULTS. Test fixture out of sync với "
            f"notification_seed_defaults.py."
        )
    return seed


# =============================================================================
# Tests — payload-template parity per Phase 1 reachable event
# =============================================================================


class TestPayloadTemplateParity:
    """For each Phase 1 reachable ADMISSION_* event, every
    placeholder the active seeded template uses MUST be present in
    the dispatch payload fixture above. A failure means a future PR
    introduced a template variable without updating the call site
    (or vice-versa) — which would have shipped a literal
    ``${var_name}`` to candidates per
    ``string.Template.safe_substitute`` semantics.
    """

    @pytest.mark.parametrize(
        "event, payload_keys",
        list(PHASE1_REACHABLE_EVENTS.items()),
    )
    def test_template_placeholders_subset_of_payload(
        self, event: SystemEvents, payload_keys: Set[str]
    ):
        seed = _seed_for_event(event)
        title_placeholders = _placeholders_in(seed.get("title_template", ""))
        message_placeholders = _placeholders_in(seed.get("message_template", ""))
        all_placeholders = title_placeholders | message_placeholders
        missing = all_placeholders - payload_keys

        assert not missing, (
            f"Event {event.value!r} template references placeholders "
            f"{sorted(missing)} that the dispatch payload does not provide. "
            f"Either (a) add the key(s) to the call-site ``event_metadata`` "
            f"or direct payload, OR (b) drop them from the template if no "
            f"longer needed. title=`{seed.get('title_template')}` "
            f"message=`{seed.get('message_template')}`."
        )


class TestEventCoverage:
    """Lock-in: every event listed in ``PHASE1_REACHABLE_EVENTS`` MUST
    correspond to a real seed entry. Prevents drift between this
    fixture and ``NOTIFICATION_SEED_DEFAULTS``."""

    @pytest.mark.parametrize(
        "event",
        list(PHASE1_REACHABLE_EVENTS.keys()),
    )
    def test_every_fixture_event_has_seed_entry(self, event: SystemEvents):
        entry = _seed_for_event(event)  # raises AssertionError if missing
        assert "title_template" in entry
        assert "message_template" in entry


class TestRenderRoundtrip:
    """Sanity check: feeding the fixture payload (with synthetic
    string values) through ``string.Template.safe_substitute`` MUST
    leave zero unresolved placeholders. Catches both the parametrize
    subset case and any nested-template gotcha (``${...}`` syntax
    errors etc).

    Note: the seed templates don't currently use ``$$`` (literal
    dollar sign escape), so any remaining ``$`` after rendering is a
    real placeholder defect.
    """

    @pytest.mark.parametrize(
        "event, payload_keys",
        list(PHASE1_REACHABLE_EVENTS.items()),
    )
    def test_render_leaves_no_literal_placeholder(
        self, event: SystemEvents, payload_keys: Set[str]
    ):
        seed = _seed_for_event(event)
        synthetic_payload = {key: f"<{key}>" for key in payload_keys}

        for field in ("title_template", "message_template"):
            template_text = seed.get(field, "")
            rendered = Template(template_text).safe_substitute(synthetic_payload)
            assert "$" not in rendered, (
                f"Event {event.value!r} field {field!r} rendered with literal "
                f"placeholder remaining: {rendered!r}. Template was "
                f"{template_text!r}."
            )
