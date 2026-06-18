"""Unit tests for ``app/utils/admission_status.py`` (Cold Cutover Task #15).

Pure helpers with no DB dependency. The tests lock:
1. ``is_admitted_like`` covers exactly ``{approved, overridden, admitted}``
   and excludes every other status the workflow can reach.
2. ``is_confirmation_eligible`` covers ``{approved, admitted}`` only —
   ``overridden`` is intentionally excluded because the state machine
   routes ``overridden → enrolled`` directly, bypassing the candidate
   confirmation step.
3. ``effective_status`` renames the three legacy aliases and passes through
   everything else (including the choice-engine new strings).
4. ``ADMITTED_LIKE_STATUSES`` and ``CONFIRMATION_ELIGIBLE_STATUSES`` are
   frozensets (so callers can drop them into ``Column.in_(...)`` without
   copying), and ``CONFIRMATION_ELIGIBLE_STATUSES`` is a strict subset
   of ``ADMITTED_LIKE_STATUSES``.
5. ``LEGACY_TO_NEW_STATUS_MAP`` content is locked — adding/removing
   entries without updating both call sites and this test is a
   regression risk.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.utils.admission_status import (
    ADMITTED_LIKE_STATUSES,
    CONFIRMATION_ELIGIBLE_STATUSES,
    LEGACY_TO_NEW_STATUS_MAP,
    effective_status,
    is_admitted_like,
    is_confirmation_eligible,
    is_fee_eligible,
)


def _profile(status: str) -> SimpleNamespace:
    """Tiny stand-in — helpers only read ``profile.status``."""
    return SimpleNamespace(status=status)


def _fee_profile(
    status: str,
    *,
    uses_choice_engine: bool = False,
    choices: object = "__unset__",
) -> SimpleNamespace:
    """Stand-in for ``is_fee_eligible``.

    Reads ``status`` + ``uses_choice_engine`` + ``__dict__['choices']``.
    Pass ``choices="__unset__"`` (default) to model a profile whose
    ``choices`` relationship was NOT eager-loaded (the gate must fail
    closed); pass a list (possibly empty) to model a loaded collection.
    """
    ns = SimpleNamespace(status=status, uses_choice_engine=uses_choice_engine)
    if choices != "__unset__":
        ns.choices = choices
    return ns


# ---------------------------------------------------------------------------
# is_admitted_like
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(ADMITTED_LIKE_STATUSES))
def test_is_admitted_like_true_for_admitted_set(status: str) -> None:
    assert is_admitted_like(_profile(status)) is True


@pytest.mark.parametrize(
    "status",
    [
        # Pre-decision
        "draft",
        "submitted",
        "resubmitted",
        "reviewing",
        "waitlisted",
        # Post-decision but NOT admitted-like
        "confirmed",
        "enrolled",
        # Negative outcomes
        "rejected",
        "withdrawn",
        "revision_requested",
        # Sentinel-ish
        "result_published",
        # Unknown / future garbage — must not be silently admitted.
        "",
        "ADMITTED",
        "approve",
    ],
)
def test_is_admitted_like_false_outside_set(status: str) -> None:
    assert is_admitted_like(_profile(status)) is False


def test_admitted_like_set_is_frozen_and_locked() -> None:
    """Adding a status to the admitted-equivalent class is a behavior
    change that ripples across phase derivation, fee gating, quota
    accounting, and the survey beat. Force the test to break so the
    change lands with a corresponding caller audit.
    """
    assert isinstance(ADMITTED_LIKE_STATUSES, frozenset)
    assert ADMITTED_LIKE_STATUSES == frozenset({"approved", "overridden", "admitted"})


# ---------------------------------------------------------------------------
# is_confirmation_eligible — strict subset of admitted-like, excludes
# ``overridden`` because the admin-override transition skips ``confirmed``
# and routes directly to ``enrolled``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["approved", "admitted"])
def test_is_confirmation_eligible_true_for_approved_and_admitted(status: str) -> None:
    """Both legacy ``approved`` and choice-engine ``admitted`` follow the
    same downstream contract: they MUST surface a candidate-facing
    confirmation flow before the profile can transition to
    ``confirmed → enrolled``.
    """
    assert is_confirmation_eligible(_profile(status)) is True


def test_is_confirmation_eligible_false_for_overridden() -> None:
    """``overridden`` is admitted-like for phase / fee / quota / read
    semantics — but the state machine routes ``overridden → enrolled``
    directly, bypassing ``confirmed``. Magic-link gates therefore must
    NOT surface confirmation for an admin-overridden profile, otherwise
    the candidate could redeem a token whose post-transition target
    state cannot exist (overridden has no ``confirmed`` successor).
    """
    assert is_admitted_like(_profile("overridden")) is True  # admitted-like
    assert is_confirmation_eligible(_profile("overridden")) is False  # not confirm-eligible


@pytest.mark.parametrize(
    "status",
    [
        # Pre-decision — no token to issue
        "draft", "submitted", "resubmitted", "reviewing", "waitlisted",
        # Already past confirmation
        "confirmed", "enrolled",
        # Negative outcomes
        "rejected", "withdrawn", "revision_requested",
        # Admin override skip
        "overridden",
        # Future intermediate / broadcast
        "result_published",
        # Garbage / casing
        "", "APPROVED", "Admitted",
    ],
)
def test_is_confirmation_eligible_false_outside_set(status: str) -> None:
    assert is_confirmation_eligible(_profile(status)) is False


def test_confirmation_eligible_set_is_frozen_and_locked() -> None:
    assert isinstance(CONFIRMATION_ELIGIBLE_STATUSES, frozenset)
    assert CONFIRMATION_ELIGIBLE_STATUSES == frozenset({"approved", "admitted"})


def test_confirmation_eligible_is_strict_subset_of_admitted_like() -> None:
    """``is_confirmation_eligible`` must always be tighter than
    ``is_admitted_like``; the only delta is ``overridden``. If the two
    sets ever diverge in another direction, magic-link gates and
    quota / phase / fee accounting would silently disagree.
    """
    assert CONFIRMATION_ELIGIBLE_STATUSES < ADMITTED_LIKE_STATUSES
    assert ADMITTED_LIKE_STATUSES - CONFIRMATION_ELIGIBLE_STATUSES == {"overridden"}


# ---------------------------------------------------------------------------
# effective_status
# ---------------------------------------------------------------------------


def test_effective_status_legacy_approved_to_admitted() -> None:
    assert effective_status(_profile("approved")) == "admitted"


def test_effective_status_legacy_overridden_to_admitted() -> None:
    assert effective_status(_profile("overridden")) == "admitted"


def test_effective_status_legacy_resubmitted_to_submitted() -> None:
    assert effective_status(_profile("resubmitted")) == "submitted"


@pytest.mark.parametrize(
    "status",
    [
        # Already canonical
        "draft",
        "submitted",
        "admitted",
        "confirmed",
        "enrolled",
        "rejected",
        "withdrawn",
        "revision_requested",
        # Choice-engine new vocab
        "reviewing",
        "waitlisted",
        # Future intermediate state / T6 broadcast marker — must
        # passthrough cleanly (lead sync handles it as an explicit no-op).
        "result_published",
    ],
)
def test_effective_status_passthrough(status: str) -> None:
    assert effective_status(_profile(status)) == status


def test_legacy_to_new_status_map_locked() -> None:
    assert LEGACY_TO_NEW_STATUS_MAP == {
        "approved": "admitted",
        "overridden": "admitted",
        "resubmitted": "submitted",
    }


# ---------------------------------------------------------------------------
# Integration shape — admitted-like is exactly the keys whose effective
# rename targets ``admitted``. Catches drift if someone widens
# ADMITTED_LIKE_STATUSES without touching the rename map (or vice versa).
# ---------------------------------------------------------------------------


def test_admitted_like_set_matches_effective_status_admitted_targets() -> None:
    legacy_aliases_pointing_to_admitted = {
        legacy
        for legacy, canonical in LEGACY_TO_NEW_STATUS_MAP.items()
        if canonical == "admitted"
    }
    expected = legacy_aliases_pointing_to_admitted | {"admitted"}
    assert ADMITTED_LIKE_STATUSES == frozenset(expected)


# ---------------------------------------------------------------------------
# is_fee_eligible — fee-create state gate (shared by routers/fees.py
# _fee_calc_authorized + admission_service calculate_fee permission flag).
# Post-decision states always pass; ``submitted`` passes for single-path
# (C2 prepay) AND for a multi-NV profile that has EXACTLY ONE nguyện vọng
# (ngành already determined). Multi-NV ≥2 at ``submitted`` must wait for
# publish → ``admitted``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(ADMITTED_LIKE_STATUSES))
def test_is_fee_eligible_true_for_admitted_like(status: str) -> None:
    """Post-decision admitted-like passes regardless of engine / choices —
    the resolver later prices against the admitted choice (multi-NV) or the
    profile snapshot (single-path)."""
    assert is_fee_eligible(_fee_profile(status)) is True
    assert (
        is_fee_eligible(
            _fee_profile(status, uses_choice_engine=True, choices=[object(), object()])
        )
        is True
    )


@pytest.mark.parametrize("status", ["confirmed", "enrolled"])
def test_is_fee_eligible_true_for_later_post_decision(status: str) -> None:
    assert is_fee_eligible(_fee_profile(status)) is True
    assert (
        is_fee_eligible(
            _fee_profile(status, uses_choice_engine=True, choices=[object()])
        )
        is True
    )


def test_is_fee_eligible_submitted_single_path_true() -> None:
    """Legacy single-path at ``submitted`` = C2 fast-track prepay / giữ chỗ.
    Choices are irrelevant for single-path."""
    assert is_fee_eligible(_fee_profile("submitted", uses_choice_engine=False)) is True
    # Even with a stray loaded (empty) choices list, single-path stays eligible.
    assert (
        is_fee_eligible(_fee_profile("submitted", uses_choice_engine=False, choices=[]))
        is True
    )


def test_is_fee_eligible_submitted_multinv_single_choice_true() -> None:
    """The new rule: a multi-NV profile with EXACTLY ONE nguyện vọng may
    prepay at ``submitted`` (ngành is already determined)."""
    assert (
        is_fee_eligible(
            _fee_profile("submitted", uses_choice_engine=True, choices=[object()])
        )
        is True
    )


@pytest.mark.parametrize("n_choices", [2, 3, 5])
def test_is_fee_eligible_submitted_multinv_multi_choice_false(n_choices: int) -> None:
    """Multi-NV with ≥2 NVs at ``submitted`` is NOT eligible — the admitted
    ngành is not locked until publish, so pricing now risks the wrong ngành."""
    choices = [object() for _ in range(n_choices)]
    assert (
        is_fee_eligible(
            _fee_profile("submitted", uses_choice_engine=True, choices=choices)
        )
        is False
    )


def test_is_fee_eligible_submitted_multinv_zero_choice_false() -> None:
    assert (
        is_fee_eligible(_fee_profile("submitted", uses_choice_engine=True, choices=[]))
        is False
    )


def test_is_fee_eligible_submitted_multinv_choices_not_loaded_fails_closed() -> None:
    """If ``choices`` was not eager-loaded the gate must fail closed (the
    fee-create path re-checks under a row lock; a missing eager-load must
    degrade to 'not eligible', never to a wrong-ngành fee)."""
    assert (
        is_fee_eligible(_fee_profile("submitted", uses_choice_engine=True))
        is False
    )


@pytest.mark.parametrize(
    "status",
    ["draft", "reviewing", "waitlisted", "rejected", "withdrawn",
     "revision_requested", "result_published", "resubmitted", "", "SUBMITTED"],
)
@pytest.mark.parametrize("engine", [False, True])
def test_is_fee_eligible_false_for_non_eligible_states(status: str, engine: bool) -> None:
    """Pre-decision (other than the submitted prepay carve-outs) and negative
    outcomes are never fee-eligible — even a single-choice multi-NV profile."""
    assert (
        is_fee_eligible(
            _fee_profile(status, uses_choice_engine=engine, choices=[object()])
        )
        is False
    )
