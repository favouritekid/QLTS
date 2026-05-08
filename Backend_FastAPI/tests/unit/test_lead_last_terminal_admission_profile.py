"""Unit tests for ``Lead.last_terminal_admission_profile`` helper (FU.5).

Covers PLAN line 903 contract:
* Returns most recent profile in truly terminal states
  (enrolled / rejected / withdrawn)
* Returns None if no terminal profiles
* Picks highest ``academic_year`` when multiple terminals
* Excludes non-terminal states (draft / submitted / approved / overridden
  / revision_requested / reviewing / result_published / admitted /
  waitlisted / resubmitted / confirmed)
* Walks in-memory list without issuing query (eager-load contract)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _profile(status: str, year: int):
    """Lightweight stub matching the attributes the helper reads."""
    return SimpleNamespace(status=status, academic_year=year)


def _last_terminal(profiles):
    """Invoke ``Lead.last_terminal_admission_profile`` against an in-memory
    profile list via the unbound property descriptor — bypasses SQLAlchemy
    instance state machinery while exercising the live function logic."""
    from app.models.lead import Lead

    stub = type("LeadStub", (), {"admission_profiles": profiles})()
    return Lead.last_terminal_admission_profile.fget(stub)


# --- truly-terminal returns ---


def test_enrolled_profile_returned():
    result = _last_terminal([_profile("enrolled", 2026)])
    assert result is not None
    assert result.status == "enrolled"
    assert result.academic_year == 2026


def test_rejected_profile_returned():
    result = _last_terminal([_profile("rejected", 2026)])
    assert result is not None
    assert result.status == "rejected"


def test_withdrawn_profile_returned():
    result = _last_terminal([_profile("withdrawn", 2026)])
    assert result is not None
    assert result.status == "withdrawn"


# --- non-terminal exclusions ---


@pytest.mark.parametrize(
    "non_terminal_state",
    [
        "draft",
        "submitted",
        "approved",
        "overridden",
        "revision_requested",
        "resubmitted",
        "reviewing",
        "result_published",
        "admitted",
        "waitlisted",
        "confirmed",
    ],
)
def test_non_terminal_state_excluded(non_terminal_state):
    """States that may still transition further must NOT be treated as
    terminal — caller wants 'completed admission' lookup."""
    result = _last_terminal([_profile(non_terminal_state, 2026)])
    assert result is None


# --- empty + None semantics ---


def test_empty_profiles_returns_none():
    assert _last_terminal([]) is None


# --- year selection — highest wins ---


def test_picks_highest_year_when_multiple_terminals():
    result = _last_terminal([
        _profile("rejected", 2025),
        _profile("enrolled", 2027),
        _profile("withdrawn", 2026),
    ])
    assert result is not None
    assert result.academic_year == 2027
    assert result.status == "enrolled"


def test_skips_non_terminal_picks_terminal_even_if_lower_year():
    """Non-terminal at higher year does NOT prevent picking terminal at
    lower year."""
    result = _last_terminal([
        _profile("submitted", 2027),  # higher year, not terminal
        _profile("enrolled", 2026),   # lower year, terminal — should win
    ])
    assert result is not None
    assert result.academic_year == 2026
    assert result.status == "enrolled"


# --- mixed shape ---


def test_mixed_terminal_and_non_terminal_picks_highest_terminal():
    result = _last_terminal([
        _profile("draft", 2027),       # excluded
        _profile("rejected", 2025),    # terminal but lower year
        _profile("approved", 2026),    # excluded
        _profile("withdrawn", 2026),   # terminal, picked (highest terminal year)
    ])
    assert result is not None
    assert result.academic_year == 2026
    assert result.status == "withdrawn"


# --- contract docstring lock ---


def test_helper_contract_locked():
    """Anchor — fail if someone refactors the terminal-state set."""
    import inspect
    from app.models.lead import Lead

    src = inspect.getsource(Lead.last_terminal_admission_profile.fget)
    # All 3 truly terminal states must be locked in the helper
    for terminal in ("enrolled", "rejected", "withdrawn"):
        assert f'"{terminal}"' in src, (
            f"Terminal state {terminal!r} must remain in "
            f"Lead.last_terminal_admission_profile — see PLAN line 903"
        )
