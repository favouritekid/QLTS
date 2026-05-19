"""Lock the ``LEGACY_STATUS_TO_EVENT`` mapping + the deferred set
+ the coverage-script anchor docstring (Cold Cutover #16).

The contract this test enforces:

  1. The exact 9 mapping rows (8 distinct events) are present —
     ``approved`` and ``overridden`` both fire ADMISSION_DECISION_
     ADMITTED, the rest map 1:1 to their T-numbered event.
  2. The exact 4 deferred events match the user's chốt set; growing
     or shrinking either side without touching the test forces the
     change to land alongside an explicit audit.
  3. Mapping + deferred sets are disjoint — a status cannot be both
     mapped (writer exists) and deferred (writer missing).
  4. The dispatch-anchor docstring (``_DISPATCH_ANCHORS``) lists each
     mapped event's literal ``event=SystemEvents.<NAME>`` form so the
     coverage script's grep picks them up; deferred events are NOT
     in the anchor block (they intentionally show as
     ``no-dispatch-site`` until Phase 3 wires the writers).
"""
from __future__ import annotations

import re

import pytest

from app.core.events import SystemEvents
from app.services import admission_state_service as state_service


# ---------------------------------------------------------------------------
# Mapping content
# ---------------------------------------------------------------------------


def test_legacy_status_to_event_locked_set() -> None:
    """Adding / removing a row here is a behaviour change — every
    addition must come with the matching legacy write site refactor
    + caller refactor + dispatch-anchor docstring update.

    Phase 3 PR-3B Sub-2 extension: 12 rows total, 10 distinct events.
    - ``approved`` and ``overridden`` both fire T7 (override site adds
      ``override=True`` payload metadata)
    - ``approved`` and ``admitted`` both fire T7 (multi-NV alias)
    - T6/T8 wired (RESULT_PUBLISHED, DECISION_WAITLISTED)
    - T10 NOT here (source-aware via TRANSITION_PAIR_TO_EVENT)
    """
    assert state_service.LEGACY_STATUS_TO_EVENT == {
        "submitted":          SystemEvents.ADMISSION_PROFILE_SUBMITTED,        # T1
        "revision_requested": SystemEvents.ADMISSION_REVISION_REQUESTED,       # T3/T4
        "resubmitted":        SystemEvents.ADMISSION_RESUBMITTED,              # T5
        "approved":           SystemEvents.ADMISSION_DECISION_ADMITTED,        # T7
        "overridden":         SystemEvents.ADMISSION_DECISION_ADMITTED,        # T7 + override=True
        "rejected":           SystemEvents.ADMISSION_DECISION_REJECTED,        # T9
        "confirmed":          SystemEvents.ADMISSION_CONFIRMED,                # T12
        "enrolled":           SystemEvents.ADMISSION_ENROLLED,                 # T13
        "withdrawn":          SystemEvents.ADMISSION_WITHDRAWN,                # T14/T15/T16
        # Phase 3 PR-3B Sub-2 — multi-NV path
        "result_published":   SystemEvents.ADMISSION_RESULT_PUBLISHED,         # T6
        "admitted":           SystemEvents.ADMISSION_DECISION_ADMITTED,        # T7 (multi-NV alias)
        "waitlisted":         SystemEvents.ADMISSION_DECISION_WAITLISTED,      # T8
    }


def test_legacy_status_to_event_has_10_distinct_events() -> None:
    """Catches the case where someone breaks the approved↔overridden↔admitted
    aliasing by re-pointing one of them at a different event.

    Phase 3 PR-3B Sub-2: 12 rows / 10 distinct events.
    3 rows alias to ADMISSION_DECISION_ADMITTED: approved/overridden/admitted.
    """
    distinct = set(state_service.LEGACY_STATUS_TO_EVENT.values())
    assert len(distinct) == 10


def test_transition_pair_to_event_locked_set() -> None:
    """Phase 3 source-aware mapping locked. 13 pair entries total:

    - T10 (waitlisted → admitted) → ADMISSION_WAITLIST_PROMOTED (PR-3B Sub-2)
    - T11 (waitlisted → rejected) → ADMISSION_WAITLIST_REJECTED (Wave 5 2026-05-16)
    - T17 (11 source states → draft) → ADMISSION_ROLLED_BACK (PR-3C Sub-3.5)

    Adding new pair entries requires same audit discipline as
    LEGACY_STATUS_TO_EVENT changes.
    """
    assert state_service.TRANSITION_PAIR_TO_EVENT == {
        # T10
        ("waitlisted", "admitted"): SystemEvents.ADMISSION_WAITLIST_PROMOTED,
        # T11 (Wave 5) — distinguish manual waitlist rejection from cascade rejection
        ("waitlisted", "rejected"): SystemEvents.ADMISSION_WAITLIST_REJECTED,
        # T17 — 11 pair entries (one per non-final non-WITHDRAWN/ENROLLED source)
        ("submitted",          "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("reviewing",          "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("revision_requested", "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("resubmitted",        "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("result_published",   "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("admitted",           "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("waitlisted",         "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("rejected",           "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("approved",           "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("overridden",         "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
        ("confirmed",          "draft"): SystemEvents.ADMISSION_ROLLED_BACK,
    }


def test_approved_and_overridden_share_admitted_event() -> None:
    """Locks the user's chốt § 2 — ``overridden`` fires T7 with
    ``override=True`` metadata, NOT T17 ROLLED_BACK (different
    semantic). Phase 3 will introduce a dedicated rollback event +
    writer when the choice-engine ships."""
    assert (
        state_service.LEGACY_STATUS_TO_EVENT["approved"]
        == state_service.LEGACY_STATUS_TO_EVENT["overridden"]
        == SystemEvents.ADMISSION_DECISION_ADMITTED
    )


# ---------------------------------------------------------------------------
# Deferred set
# ---------------------------------------------------------------------------


def test_deferred_admission_events_locked_set() -> None:
    """Q9 #07 Phase E Wave 1 (2026-05-19) added 3 PRIORITY_* events to
    catalog seed; dispatch sites ship Wave 2 (override_kv) + Wave 3
    (verify/reject evidence). Tracked here until those waves merge.
    """
    assert state_service.DEFERRED_ADMISSION_EVENTS == frozenset({
        "PRIORITY_KV_OVERRIDDEN",
        "PRIORITY_OBJECT_VERIFIED",
        "PRIORITY_OBJECT_REJECTED",
    })


def test_deferred_set_is_frozenset() -> None:
    assert isinstance(state_service.DEFERRED_ADMISSION_EVENTS, frozenset)


def test_deferred_events_all_exist_in_systemevents() -> None:
    """Catches the case where an enum is renamed or removed without
    updating the deferred set."""
    enum_names = {member.name for member in SystemEvents}
    for name in state_service.DEFERRED_ADMISSION_EVENTS:
        assert name in enum_names, f"Deferred event {name!r} not in SystemEvents"


# ---------------------------------------------------------------------------
# Mapping ↔ Deferred disjointness
# ---------------------------------------------------------------------------


def test_mapping_and_deferred_are_disjoint() -> None:
    """A status cannot be both ``deferred`` (writer missing) and
    ``mapped`` (writer present). If both sets ever overlap, either
    the deferred set should drop the row OR the mapping should drop
    the row — coverage and lint contracts get inconsistent otherwise.
    """
    mapped_event_names = {ev.name for ev in state_service.LEGACY_STATUS_TO_EVENT.values()}
    overlap = mapped_event_names & set(state_service.DEFERRED_ADMISSION_EVENTS)
    assert overlap == set(), f"Events both mapped and deferred: {overlap!r}"


def test_total_admission_events_is_16() -> None:
    """Catalog ships 16 admission-tracked events post-Q9 #07 Phase E Wave 1:
    - 10 distinct events via LEGACY_STATUS_TO_EVENT (target-keyed)
    - 2 source-aware via TRANSITION_PAIR_TO_EVENT (T10 PROMOTED + T11 WAITLIST_REJECTED)
    - 1 source-aware via TRANSITION_PAIR_TO_EVENT (T17 ROLLED_BACK — 11 pair entries
      collapse to single event name)
    - 3 Q9 #07 Phase E PRIORITY_* events deferred (dispatch ships Wave 2+3)

    Wave 5 added T11 ADMISSION_WAITLIST_REJECTED to distinguish manual
    waitlist rejection from generic engine cascade rejection.

    Q9 #07 Phase E Wave 1 (2026-05-19) added 3 PRIORITY_* events:
    PRIORITY_KV_OVERRIDDEN / PRIORITY_OBJECT_VERIFIED / PRIORITY_OBJECT_REJECTED.
    """
    mapped = {ev.name for ev in state_service.LEGACY_STATUS_TO_EVENT.values()}
    pair = {ev.name for ev in state_service.TRANSITION_PAIR_TO_EVENT.values()}
    deferred = set(state_service.DEFERRED_ADMISSION_EVENTS)
    total = len(mapped | pair | deferred)
    assert total == 16


# ---------------------------------------------------------------------------
# Dispatch-anchor docstring parity
# ---------------------------------------------------------------------------


_ANCHOR_PATTERN = re.compile(r"event\s*=\s*SystemEvents\.([A-Z_][A-Z0-9_]*)")


def test_dispatch_anchors_match_mapping() -> None:
    """The anchor docstring is what makes the coverage script's grep
    detect dispatch sites — every event with a writer (LEGACY map OR
    PAIR map) MUST appear; deferred events MUST NOT.

    Phase 3 PR-3B Sub-2: anchor block now includes TRANSITION_PAIR
    events (T10 WAITLIST_PROMOTED) alongside LEGACY events.
    """
    anchor_text = state_service._DISPATCH_ANCHORS
    found = set(_ANCHOR_PATTERN.findall(anchor_text))

    expected_legacy = {ev.name for ev in state_service.LEGACY_STATUS_TO_EVENT.values()}
    expected_pair = {ev.name for ev in state_service.TRANSITION_PAIR_TO_EVENT.values()}
    expected_all = expected_legacy | expected_pair
    assert found == expected_all, (
        f"Dispatch anchor docstring out of sync with mapping union.\n"
        f"  Expected (legacy ∪ pair): {sorted(expected_all)}\n"
        f"  Found in anchors:        {sorted(found)}\n"
        "Fix: edit _DISPATCH_ANCHORS in admission_state_service.py to add "
        "or remove ``event=SystemEvents.<NAME>`` lines so they match the "
        "mapping union. Without parity the coverage script will misreport "
        "no-dispatch-site for events the runtime actually dispatches."
    )


def test_deferred_events_not_in_anchor_block() -> None:
    """Deferred events must NOT appear in the anchor block — adding
    them would mark them as ``ok`` in the coverage script and silence
    the gap that ``--allow-deferred`` is meant to surface."""
    anchor_text = state_service._DISPATCH_ANCHORS
    found = set(_ANCHOR_PATTERN.findall(anchor_text))
    overlap = found & set(state_service.DEFERRED_ADMISSION_EVENTS)
    assert overlap == set(), (
        f"Deferred events present in dispatch anchor block: {overlap!r}. "
        "Remove them — the coverage script must keep reporting them as "
        "no-dispatch-site until Phase 3 ships the writers."
    )
