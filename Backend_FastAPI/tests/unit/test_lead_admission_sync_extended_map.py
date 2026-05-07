"""Unit tests for the choice-engine extension of ``ADMISSION_TO_LEAD_STATUS_MAP``
and the floor / ``result_published`` rules introduced in Cold Cutover Task #15.

Pure tests — no DB. Locks:
1. New entries (``admitted`` / ``reviewing`` / ``waitlisted``) point at the
   right consultation status ids.
2. ``result_published`` is intentionally absent from the map. It is a
   future intermediate state / T6 broadcast marker; the sync function
   short-circuits it as an explicit no-op for lead sync so a state
   machine that lands the string transiently on ``profile.status`` does
   NOT trigger a "Unknown admission status" warning nor mutate the
   lead pipeline.
3. ``_should_apply_admission_floor`` only runs the floor check on
   ``reviewing`` / ``waitlisted`` and lets every other status fall through.
4. The floor preserves any lead already past sts07 (admission, fee,
   enrolled, terminal), and lets pre-application leads (NULL +
   consultation phase) progress.
"""
from __future__ import annotations

import pytest

from app.services.lead_admission_sync import (
    ADMISSION_TO_LEAD_STATUS_MAP,
    FLOOR_FROM_PROFILE_STATUSES,
    PRE_APPLICATION_LEAD_STATUSES,
    _RESULT_PUBLISHED_NO_OP,
    _should_apply_admission_floor,
)


# ---------------------------------------------------------------------------
# MAP extension content lock
# ---------------------------------------------------------------------------


def test_map_admitted_resolves_to_sts09() -> None:
    """``admitted`` is the choice-engine equivalent of legacy ``approved``
    — must land on the same consultation status id (sts09 — Đủ điều kiện).
    """
    assert ADMISSION_TO_LEAD_STATUS_MAP["admitted"] == "sts09"


def test_map_admitted_matches_legacy_approved() -> None:
    """If they ever diverge, downstream readers branching on
    ``effective_status(profile)`` would observe two different lead-status
    targets for what is supposed to be the same admission outcome.
    """
    assert (
        ADMISSION_TO_LEAD_STATUS_MAP["admitted"]
        == ADMISSION_TO_LEAD_STATUS_MAP["approved"]
        == ADMISSION_TO_LEAD_STATUS_MAP["overridden"]
    )


def test_map_reviewing_resolves_to_sts07_floor() -> None:
    """``reviewing`` keeps the lead inside the admission phase
    (``sts07`` — Đã tiếp nhận hồ sơ). It must NOT regress a lead to the
    consultation phase (sts06) — that is what made the PLAN proposal
    incorrect; floor-up only.
    """
    assert ADMISSION_TO_LEAD_STATUS_MAP["reviewing"] == "sts07"


def test_map_waitlisted_resolves_to_sts07_floor() -> None:
    assert ADMISSION_TO_LEAD_STATUS_MAP["waitlisted"] == "sts07"


def test_map_does_not_contain_result_published() -> None:
    """``result_published`` is a future intermediate state / T6 broadcast
    marker — explicit no-op for lead sync. The sync function
    short-circuits it via ``_RESULT_PUBLISHED_NO_OP`` and the
    corresponding branch in ``sync_lead_from_admission``. If a future
    PR adds a key here, the short-circuit becomes dead code and the
    lead pipeline would get silently mutated by every transition that
    lands the string on ``profile.status``.
    """
    assert "result_published" not in ADMISSION_TO_LEAD_STATUS_MAP
    assert _RESULT_PUBLISHED_NO_OP == "result_published"


def test_map_legacy_entries_preserved() -> None:
    """Cold cutover scope only ADDS choice-engine entries — it does not
    re-map any existing legacy value. Lock the pre-existing rows so a
    typo in the diff does not silently re-route prod leads.
    """
    legacy_expected = {
        "draft": "sts06",
        "submitted": "sts07",
        "resubmitted": "sts07",
        "approved": "sts09",
        "confirmed": "sts09",
        "overridden": "sts09",
        "rejected": "sts16",
        "revision_requested": "sts17",
        "enrolled": "sts11",
        "withdrawn": "sts08",
    }
    for status, expected_sts in legacy_expected.items():
        assert ADMISSION_TO_LEAD_STATUS_MAP[status] == expected_sts


def test_map_choice_engine_entries_total() -> None:
    """Lock the exact set of new entries. Adding a fourth choice-engine
    status without updating this test forces the author to think through
    the floor / no-op semantics for the new value.
    """
    new_entries = set(ADMISSION_TO_LEAD_STATUS_MAP.keys()) - {
        "draft", "submitted", "resubmitted", "approved",
        "confirmed", "overridden", "rejected", "revision_requested",
        "enrolled", "withdrawn",
    }
    assert new_entries == {"admitted", "reviewing", "waitlisted"}


# ---------------------------------------------------------------------------
# Floor decision rule
# ---------------------------------------------------------------------------


def test_floor_set_locked() -> None:
    """``approved`` / ``confirmed`` / ``enrolled`` MUST NOT slip into the
    floor set — those are mutating transitions and need to set the lead
    even when it is already past sts07.
    """
    assert FLOOR_FROM_PROFILE_STATUSES == frozenset({"reviewing", "waitlisted"})


def test_pre_application_lead_set_locked() -> None:
    """The floor allows progression only for leads still in consultation
    phase or with NULL status. Universal statuses (sts01/sts15/sts19) and
    every admission/fee/enrolled status are intentionally absent.
    """
    assert PRE_APPLICATION_LEAD_STATUSES == frozenset({
        None, "sts00", "sts02", "sts03", "sts04", "sts05", "sts06",
    })


@pytest.mark.parametrize("profile_status", ["reviewing", "waitlisted"])
@pytest.mark.parametrize(
    "lead_cs",
    [None, "sts00", "sts02", "sts03", "sts04", "sts05", "sts06"],
)
def test_floor_allows_upgrade_from_pre_application(
    profile_status: str, lead_cs
) -> None:
    """Lead is in consultation phase or NULL — flooring up to sts07
    (the choice-engine reviewing/waitlisted target) is correct."""
    assert _should_apply_admission_floor(profile_status, lead_cs) is True


@pytest.mark.parametrize("profile_status", ["reviewing", "waitlisted"])
@pytest.mark.parametrize(
    "lead_cs",
    [
        # Admission phase — already at or past target
        "sts07", "sts17", "sts13", "sts09", "sts16", "sts08",
        # Fee phase
        "sts14", "sts10", "sts18",
        # Enrolled phase (terminal)
        "sts11", "sts12",
        # Universal statuses (overlay an underlying pipeline_stage that may
        # be at sts07+; flooring would overwrite the underlying state).
        "sts01", "sts15", "sts19",
    ],
)
def test_floor_blocks_downgrade(profile_status: str, lead_cs: str) -> None:
    """Lead has already advanced past pre-application — preserving its
    state is correct; flooring would regress it."""
    assert _should_apply_admission_floor(profile_status, lead_cs) is False


@pytest.mark.parametrize(
    "profile_status",
    [
        # Every non-floor value the admission column can hold today (legacy)
        # plus the choice-engine new values that are NOT floor-only.
        "draft", "submitted", "resubmitted", "approved", "confirmed",
        "overridden", "rejected", "revision_requested", "enrolled",
        "withdrawn", "admitted",
    ],
)
@pytest.mark.parametrize(
    "lead_cs",
    [None, "sts00", "sts06", "sts07", "sts09", "sts10", "sts11", "sts12"],
)
def test_floor_no_op_for_non_floor_statuses(
    profile_status: str, lead_cs
) -> None:
    """Non-floor statuses must always allow the existing fall-through —
    helper short-circuits to True regardless of the lead state. Without
    this, refactoring the function would accidentally veto valid
    transitions (e.g. approve from any prior lead state)."""
    assert _should_apply_admission_floor(profile_status, lead_cs) is True
