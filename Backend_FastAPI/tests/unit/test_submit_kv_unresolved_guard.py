"""Unit tests for ``_assert_kv_resolved_for_submit`` (Phase E.4 commit 5 fix-up).

Reviewer 2026-05-21 — DEFAULT-BLOCK pattern (whitelist success rules + kv_resolved):

Pre-fix (commit 5 v1): block khi `requires_manual_override=True` + rule_applied
∈ blacklist 6 codes. Sai hướng fail-closed: unknown future rule pass mặc định;
`not_resolved` không có flag cũng pass.

Post-fix (commit 5 v2): chỉ pass khi rule trong WHITELIST success
{longest_duration, tiebreak_graduation_school, commune_lookup, manual_override}
VÀ kv_resolved != None. Mọi case khác → block.

Tests pin gate logic:
  - 6 fail-closed rules block (address_not_normalized, catalog_gap_*, ...)
  - manual_override với kv_resolved set → pass
  - 3 happy paths (longest_duration, commune_lookup, ...) → pass
  - Snapshot empty/None → pass defensive (engine T1 freeze fail infra)
  - Default-block edge cases: unknown rule, kv_resolved None + success rule, etc.
"""
from __future__ import annotations

import pytest

from app.services.admission_service import _assert_kv_resolved_for_submit
from app.utils.exceptions import BadRequest


pytestmark = pytest.mark.unit


# ===========================================================================
# 6 unresolved rule_applied codes → block
# ===========================================================================


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
def test_blocks_when_unresolved_with_requires_manual_override(
    rule_applied: str, reason: str,
) -> None:
    snapshot = {
        "kv_resolved": None,
        "rule_applied": rule_applied,
        "reason": reason,
        "requires_manual_override": True,
    }
    with pytest.raises(BadRequest) as exc:
        _assert_kv_resolved_for_submit(snapshot, profile_id=1)
    assert "KV_UNRESOLVED" in str(exc.value)
    assert rule_applied in str(exc.value)
    assert reason in str(exc.value)


# ===========================================================================
# Manual override (admin pre-submit override KV) → pass
# ===========================================================================


def test_manual_override_with_kv_resolved_passes() -> None:
    """Admin/manager đã override KV trước submit → snapshot.kv_resolved set +
    rule_applied='manual_override'. Submit phải pass."""
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "manual_override",
        "manual_override_reason": "Lớp tạo nguồn theo QĐ Bộ → KV1",
        "manual_override_by": 42,
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_manual_override_without_kv_resolved_blocks() -> None:
    """Engine MANUAL pathway emit khi area_basis='manual_override' nhưng admin
    chưa thực sự override KV → kv_resolved=None + rule_applied='manual_override'.
    Fail-closed: block vì không có giá trị KV thực."""
    snapshot = {
        "kv_resolved": None,
        "rule_applied": "manual_override",
        "requires_manual_override": False,
    }
    with pytest.raises(BadRequest) as exc:
        _assert_kv_resolved_for_submit(snapshot, profile_id=1)
    assert "KV_UNRESOLVED" in str(exc.value)


# ===========================================================================
# Happy paths — engine resolve thành công
# ===========================================================================


def test_longest_duration_with_kv_resolved_passes() -> None:
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "longest_duration",
        "basis": "LICH_SU_THPT",
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_tiebreak_graduation_school_with_kv_resolved_passes() -> None:
    snapshot = {
        "kv_resolved": "KV3",
        "rule_applied": "tiebreak_graduation_school",
        "basis": "LICH_SU_THPT",
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_commune_lookup_with_kv_resolved_passes() -> None:
    snapshot = {
        "kv_resolved": "KV2-NT",
        "rule_applied": "commune_lookup",
        "basis": "THUONG_TRU",
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_longest_duration_without_kv_resolved_blocks() -> None:
    """Defensive: rule success nhưng kv_resolved=None — fail-closed block."""
    snapshot = {
        "kv_resolved": None,
        "rule_applied": "longest_duration",
        "basis": "LICH_SU_THPT",
    }
    with pytest.raises(BadRequest) as exc:
        _assert_kv_resolved_for_submit(snapshot, profile_id=1)
    assert "KV_UNRESOLVED" in str(exc.value)


# ===========================================================================
# Defensive: empty/None snapshot
# ===========================================================================


def test_empty_snapshot_passes_defensive() -> None:
    """Snapshot rỗng (vd engine T1 freeze fail do infra) → KHÔNG block submit.
    Block path chỉ khi engine explicit signal unresolved; empty là failure
    mode khác (đã log warning ở freeze try/except)."""
    _assert_kv_resolved_for_submit({}, profile_id=1)


def test_none_snapshot_passes_defensive() -> None:
    _assert_kv_resolved_for_submit(None, profile_id=1)


# ===========================================================================
# Edge: requires_manual_override=True nhưng rule_applied không match list
# ===========================================================================


def test_unknown_rule_blocks_default_fail_closed() -> None:
    """Reviewer P1 2026-05-21 fix-up — DEFAULT BLOCK fail-closed: rule_applied
    không trong success whitelist → block, kể cả không có flag
    requires_manual_override. Pre-fix-up code pass (blacklist) — flip now."""
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "future_new_rule",
        # Không có requires_manual_override flag
    }
    with pytest.raises(BadRequest) as exc:
        _assert_kv_resolved_for_submit(snapshot, profile_id=1)
    assert "KV_UNRESOLVED" in str(exc.value)


def test_not_resolved_without_flag_blocks() -> None:
    """Reviewer P1 fix-up: rule_applied=not_resolved BLOCK kể cả không có flag
    requires_manual_override. Pre-fix-up: pass khi flag false → vi phạm fail-closed."""
    snapshot = {
        "kv_resolved": None,
        "rule_applied": "not_resolved",
        "reason": "cultural_not_set",
        # requires_manual_override KHÔNG có (engine emit False khi NOT_RESOLVED)
    }
    with pytest.raises(BadRequest) as exc:
        _assert_kv_resolved_for_submit(snapshot, profile_id=1)
    assert "KV_UNRESOLVED" in str(exc.value)


def test_address_not_normalized_with_kv_resolved_set_still_blocks() -> None:
    """Edge: rule_applied = address_not_normalized nhưng kv_resolved có giá trị
    (race state không tự nhiên xảy ra). Fail-closed: chỉ rule success whitelist
    + kv_resolved set mới pass; address_not_normalized không trong list → block."""
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "address_not_normalized",
        # Force-set kv (race) — vẫn fail vì rule sai
    }
    with pytest.raises(BadRequest) as exc:
        _assert_kv_resolved_for_submit(snapshot, profile_id=1)
    assert "KV_UNRESOLVED" in str(exc.value)
