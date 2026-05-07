"""Unit tests for #184 Wave 4 #15b hotfix — race-safe idempotency check
in ``create_profile()`` must scope to the target ``academic_year``.

Background
----------

Wave 3-E ``phase1_15a`` (PR #223 squash ``15f52c8e``) replaced the
single-profile-per-lead UNIQUE with composite ``(lead_id, academic_year)``
UNIQUE. Wave 4 PR #15b (squash ``966d5f5f``) flipped the model to
plural and updated the eligibility check, but **left the secondary
race-safe DB check inside the redis lock using the deprecated
``get_profile_by_lead_id`` method** that returns the latest year
regardless. That secondary check would incorrectly block a lead that
already has a profile for, say, 2025 from creating one for 2026.

Hotfix
------

The check now uses ``get_profile_by_lead_year(lead_id, academic_year)``
with ``academic_year`` resolved from the explicit parameter or the
``current_intake_year`` system config (mirroring the eligibility check
fallback at the same call site).

Tests target the source surface (text grep + behavior expectations)
because the full ``create_profile`` flow has a long dependency chain
(redis lock + offering + path lookup + ...) that would dwarf the
narrow hotfix surface in setup/mock complexity.
"""
from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# 1. Race-safe check uses year-aware repository method
# ---------------------------------------------------------------------------


def test_race_safe_check_calls_get_profile_by_lead_year_not_lead_id() -> None:
    """The secondary race-safe DB query must hit the composite-UNIQUE-
    keyed lookup so multi-year creates are not falsely rejected."""
    from app.services import admission_service

    src = inspect.getsource(admission_service.create_profile)

    # Find the redis-lock block — race-safe check lives inside it.
    lock_idx = src.index("acquire_redis_lock")
    eligibility_idx = src.index("check_lead_level_admission_eligibility(")
    race_block = src[lock_idx:eligibility_idx]

    # Inside the lock block, the new method must be called with both
    # lead_id and the resolved year.
    assert "get_profile_by_lead_year(" in race_block, (
        "race-safe check must call get_profile_by_lead_year (composite-"
        "UNIQUE-keyed) — not the deprecated get_profile_by_lead_id"
    )
    # And the deprecated method must NOT be reachable from the lock
    # block. (The repository class still exposes get_profile_by_lead_id
    # as a deprecated wrapper for legacy callers; create_profile must
    # not be one of them.)
    assert "get_profile_by_lead_id(" not in race_block, (
        "create_profile race-safe check still references the deprecated "
        "get_profile_by_lead_id — Wave 4 #15b hotfix incomplete"
    )


def test_race_safe_check_falls_back_to_current_intake_year_when_year_none() -> None:
    """Mirrors the eligibility-check fallback at line 2497: when a
    caller omits ``academic_year``, both checks resolve the same
    year via ``SystemConfigService.get_value("current_intake_year",
    2026)`` so the two gates agree on which year is being scoped."""
    from app.services import admission_service

    src = inspect.getsource(admission_service.create_profile)
    lock_idx = src.index("acquire_redis_lock")
    eligibility_idx = src.index("check_lead_level_admission_eligibility(")
    race_block = src[lock_idx:eligibility_idx]

    # The fallback signature mirrors lead_service._populate_lead_detail_
    # fields: SystemConfigService(db).get_value("current_intake_year",
    # 2026) + int(...) coercion when the value comes back as a string.
    assert "SystemConfigService" in race_block
    assert '"current_intake_year"' in race_block
    assert "2026" in race_block


# ---------------------------------------------------------------------------
# 2. Error message scoped to the year (operator UX)
# ---------------------------------------------------------------------------


def test_race_safe_conflict_message_scoped_to_year(monkeypatch) -> None:
    """The ``ConflictError`` raised when a duplicate is detected must
    name the academic year — operators reading the prod log shouldn't
    have to guess whether it's a multi-year edge case or a same-year
    duplicate. Mirrors the year-aware message the Wave 4 #15b
    eligibility check now emits."""
    from app.services import admission_service

    src = inspect.getsource(admission_service.create_profile)
    lock_idx = src.index("acquire_redis_lock")
    eligibility_idx = src.index("check_lead_level_admission_eligibility(")
    race_block = src[lock_idx:eligibility_idx]

    # Both ``academic year`` and a year placeholder must appear in the
    # raise statement after ``get_profile_by_lead_year``.
    raise_idx = race_block.index("ConflictError(")
    raise_block = race_block[raise_idx : raise_idx + 400]
    assert "academic year" in raise_block.lower()
    assert "{race_check_year}" in raise_block or "{year}" in raise_block, (
        "ConflictError message must f-string the resolved year so prod "
        "logs disambiguate same-year vs cross-year duplicate cases"
    )


# ---------------------------------------------------------------------------
# 3. Repository contract — both methods present (deprecated + new)
# ---------------------------------------------------------------------------


def test_repository_exposes_both_methods_during_migration_window() -> None:
    """The deprecated ``get_profile_by_lead_id`` stays callable for any
    pre-Wave-4 caller still in flight; the new
    ``get_profile_by_lead_year`` is the create-profile race-safe path."""
    from app.repositories.admission_repository import AdmissionRepository

    assert callable(getattr(AdmissionRepository, "get_profile_by_lead_id", None))
    assert callable(getattr(AdmissionRepository, "get_profile_by_lead_year", None))
