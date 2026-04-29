"""ADM-023 (2026-04-29): cooldown ladder unit tests.

Pin the Q9 (A3) ladder so future tweaks to ``cooldown_minutes_for``
either re-bless this table or break loudly. The matching service-layer
behaviour (set ``lock_until`` vs hard lock) is exercised in
``tests/services/test_admission_confirmation_lock.py`` (separate
module to keep this one DB-free).
"""
from __future__ import annotations

import pytest

from app.services.admission_confirmation_cooldown import (
    HARD_LOCK_THRESHOLD,
    cooldown_minutes_for,
    is_hard_lock,
)


class TestLadder:
    """``attempt_count`` -> cooldown minutes table."""

    def test_zero_returns_zero(self):
        # No failure yet — caller should not set lock_until.
        assert cooldown_minutes_for(0) == 0

    @pytest.mark.parametrize("n", [1, 2])
    def test_first_tier_is_5_minutes(self, n):
        assert cooldown_minutes_for(n) == 5

    @pytest.mark.parametrize("n", [3, 4])
    def test_second_tier_is_30_minutes(self, n):
        assert cooldown_minutes_for(n) == 30

    @pytest.mark.parametrize("n", [5, 6])
    def test_third_tier_is_120_minutes(self, n):
        assert cooldown_minutes_for(n) == 120

    @pytest.mark.parametrize("n", [7, 15, 29])
    def test_fourth_tier_is_24h(self, n):
        # 7 fails through 29 — sustained brute force, last cooldown
        # before hard lock at 30.
        assert cooldown_minutes_for(n) == 1440

    @pytest.mark.parametrize("n", [30, 31, 100])
    def test_hard_lock_returns_none(self, n):
        # Sentinel: caller MUST handle None by setting locked_at +
        # incrementing lock_count, not by computing a sliding cooldown.
        assert cooldown_minutes_for(n) is None


class TestHardLockPredicate:
    """``is_hard_lock`` mirrors the ``cooldown_minutes_for`` boundary."""

    @pytest.mark.parametrize("n", [0, 1, 5, 29])
    def test_below_threshold_is_false(self, n):
        assert is_hard_lock(n) is False

    @pytest.mark.parametrize("n", [HARD_LOCK_THRESHOLD, 31, 100])
    def test_at_or_above_threshold_is_true(self, n):
        assert is_hard_lock(n) is True

    def test_threshold_constant_is_30(self):
        # Q9 decision (memory ``admission-audit-wave2-2026-04-28``).
        # If product later wants a different threshold, change this
        # constant + Q9 entry together — bumping silently breaks the
        # audit story ("attempted to brute force ≥30 times" message).
        assert HARD_LOCK_THRESHOLD == 30


class TestLadderMonotonic:
    """Cooldown never decreases as attempt_count rises."""

    def test_monotonic_through_tier_boundaries(self):
        ladder = [cooldown_minutes_for(n) for n in range(1, HARD_LOCK_THRESHOLD)]
        for prev, curr in zip(ladder, ladder[1:]):
            # ``curr`` is None only at the hard-lock boundary which
            # this loop excludes via ``range(..., HARD_LOCK_THRESHOLD)``.
            assert prev is not None and curr is not None
            assert curr >= prev, (
                f"Ladder regressed at boundary: {prev} -> {curr}"
            )
