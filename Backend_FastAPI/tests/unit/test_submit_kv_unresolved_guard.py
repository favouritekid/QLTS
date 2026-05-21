"""Unit tests for ``_assert_kv_resolved_for_submit`` (Phase E.4 commit 5 fix-up).

Reviewer 2026-05-21: engine fail-closed signal (`address_not_normalized` /
`catalog_gap_*` / `insufficient_data` / `ambiguous_requires_manual` /
`not_resolved` + `requires_manual_override=True`) phải block submit; trước
fix-up code chỉ log warning rồi vẫn cho submit qua (vi phạm nghiệp vụ #7).

Tests pin gate logic:
  - 6 unresolved rule_applied codes → raise BadRequest
  - manual_override (admin pre-submit override) → pass
  - happy paths (longest_duration, commune_lookup) → pass
  - Snapshot empty/None → pass (defensive — không block khi engine chưa freeze)
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


def test_manual_override_passes() -> None:
    """Admin/manager đã override KV trước submit → snapshot.kv_resolved set +
    rule_applied='manual_override'. Submit phải pass."""
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "manual_override",
        "manual_override_reason": "Lớp tạo nguồn theo QĐ Bộ → KV1",
        "manual_override_by": 42,
        # MANUAL pathway từ engine cũng có requires_manual_override=False,
        # nhưng admin override flow sét manual_override_reason → snapshot
        # đại diện override hoàn tất.
    }
    # Should not raise
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_manual_override_with_requires_manual_override_false_passes() -> None:
    """Engine MANUAL pathway (admin chưa override nhưng area_basis='manual_override'
    được set, kv_resolved tồn tại). Không có requires_manual_override flag → pass."""
    snapshot = {
        "kv_resolved": "KV2",
        "rule_applied": "manual_override",
        "requires_manual_override": False,
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


# ===========================================================================
# Happy paths — engine resolve thành công
# ===========================================================================


def test_longest_duration_pass() -> None:
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "longest_duration",
        "basis": "LICH_SU_THPT",
        # Happy path không có requires_manual_override flag
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_tiebreak_graduation_school_pass() -> None:
    snapshot = {
        "kv_resolved": "KV3",
        "rule_applied": "tiebreak_graduation_school",
        "basis": "LICH_SU_THPT",
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_commune_lookup_pass() -> None:
    snapshot = {
        "kv_resolved": "KV2-NT",
        "rule_applied": "commune_lookup",
        "basis": "THUONG_TRU",
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


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


def test_unknown_rule_with_manual_override_flag_passes_defensive() -> None:
    """Defensive: rule_applied future-added chưa có trong unresolved list →
    KHÔNG block (whitelist-based block, không blacklist). Avoid false-positive
    block khi engine evolves."""
    snapshot = {
        "kv_resolved": "KV1",  # Có giá trị
        "rule_applied": "future_new_rule",
        "requires_manual_override": True,  # Engine flag (vẫn warn FE) nhưng
        # block list không match → pass.
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)


def test_unresolved_rule_without_requires_manual_override_passes() -> None:
    """Defensive: rule_applied match unresolved list NHƯNG không có flag
    requires_manual_override → pass (treat as informational, not blocking).
    Combination này không tự nhiên xảy ra từ engine nhưng phòng race."""
    snapshot = {
        "kv_resolved": "KV1",
        "rule_applied": "address_not_normalized",
        # requires_manual_override missing
    }
    _assert_kv_resolved_for_submit(snapshot, profile_id=1)
