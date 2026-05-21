"""Unit tests for ``_kv_unresolved_error_message`` helper (Phase E.4 v4 fix-up).

Reviewer 2026-05-21 v4 deadlock: submit raise BadRequest → router rollback
snapshot → manager/admin override draft KHÔNG thấy ``requires_manual_override``
signal → deadlock với draft override gate.

Fix v4: helper trả error message string (not raise) cho submit collect vào
``validation_errors`` list. Submit return ``{status: 'draft', validation_errors}``
+ ``db.flush()`` snapshot → router commit → snapshot persist → admin/manager
override draft sees real signal.

Tests pin extract semantics: helper trả None khi pass, message string khi fail.
"""
from __future__ import annotations

import pytest

from app.services.admission_service import _kv_unresolved_error_message


pytestmark = pytest.mark.unit


# ===========================================================================
# Pass paths — helper trả None
# ===========================================================================


@pytest.mark.parametrize(
    "rule_applied",
    [
        "longest_duration",
        "tiebreak_graduation_school",
        "commune_lookup",
        "manual_override",
    ],
)
def test_success_rule_with_kv_resolved_returns_none(rule_applied: str) -> None:
    snapshot = {
        "rule_applied": rule_applied,
        "kv_resolved": "KV1",
        "basis": "LICH_SU_THPT",
    }
    assert _kv_unresolved_error_message(snapshot, profile_id=1) is None


# ===========================================================================
# Block paths — helper trả message string
# ===========================================================================


def test_empty_snapshot_returns_error_message() -> None:
    msg = _kv_unresolved_error_message({}, profile_id=1)
    assert msg is not None
    assert "KV_UNRESOLVED" in msg
    assert "no_snapshot_present" in msg


def test_none_snapshot_returns_error_message() -> None:
    msg = _kv_unresolved_error_message(None, profile_id=1)
    assert msg is not None
    assert "KV_UNRESOLVED" in msg
    assert "no_snapshot_present" in msg


@pytest.mark.parametrize(
    "rule_applied,reason",
    [
        ("address_not_normalized", "profile_missing_permanent_commune_code"),
        ("catalog_gap_commune", "commune_code_not_in_catalog"),
        ("catalog_gap_school", "all_school_lookups_failed"),
        ("insufficient_data", "no_qualifying_thpt_history_entries"),
        ("ambiguous_requires_manual", "tied_graduation_year_and_grade"),
        ("not_resolved", "cultural_not_set"),
    ],
)
def test_unresolved_rule_returns_error_message(rule_applied: str, reason: str) -> None:
    snapshot = {
        "rule_applied": rule_applied,
        "reason": reason,
        "requires_manual_override": True,
        "kv_resolved": None,
    }
    msg = _kv_unresolved_error_message(snapshot, profile_id=1)
    assert msg is not None
    assert "KV_UNRESOLVED" in msg
    assert rule_applied in msg
    assert reason in msg


def test_success_rule_without_kv_resolved_returns_error_message() -> None:
    """Race: rule trong success whitelist nhưng kv_resolved=None → block."""
    snapshot = {
        "rule_applied": "longest_duration",
        "kv_resolved": None,
    }
    msg = _kv_unresolved_error_message(snapshot, profile_id=1)
    assert msg is not None
    assert "KV_UNRESOLVED" in msg


def test_unknown_future_rule_returns_error_message() -> None:
    """Fail-closed default: rule không trong whitelist → block."""
    snapshot = {
        "rule_applied": "future_new_rule",
        "kv_resolved": "KV1",
    }
    msg = _kv_unresolved_error_message(snapshot, profile_id=1)
    assert msg is not None
    assert "KV_UNRESOLVED" in msg
    assert "future_new_rule" in msg
