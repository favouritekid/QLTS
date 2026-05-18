"""Unit tests for ``priority_service.calculate_priority_bonus``.

Q9 #07 PR2a — pure-logic tests of the bonus calculation engine. Mocks
the DB via AsyncMock so the test stays independent of alembic + seed.
The 12 cases cover the contract that PR3 admin CRUD + PR5 candidate
FE must respect.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.priority_service import calculate_priority_bonus


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# DB mock helpers — engine reads via 2 select() calls (area, object)
# ---------------------------------------------------------------------------


def _make_db(area_rate=None, object_rows=None):
    """Return AsyncMock DB that dispatches by stmt text — so a test
    where only one toggle fires still picks the right result regardless
    of call order. Use None area_rate to simulate "missing config row"."""
    area_result = MagicMock()
    area_result.scalar_one_or_none = MagicMock(return_value=area_rate)

    object_result = MagicMock()
    object_result.all = MagicMock(return_value=object_rows or [])

    async def _dispatch(stmt, *args, **kwargs):
        sql_str = str(stmt)
        if "priority_area_config" in sql_str:
            return area_result
        if "priority_object_config" in sql_str:
            return object_result
        raise AssertionError(f"Unexpected query to: {sql_str}")

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_dispatch)
    return db


def _profile(**kwargs):
    """Build a SimpleNamespace profile stub with the 3 fields the
    engine reads."""
    defaults = {
        "high_school_kv_resolved": None,
        "priority_object_codes": [],
        "priority_object_evidence": {},
        "area_resolution_basis": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


_RULE_BOTH_ON = {
    "apply_area_bonus": True,
    "apply_object_bonus": True,
    "max_total_bonus": None,
}


# ---------------------------------------------------------------------------
# 1. NULL rule → bonus disabled (legacy paths without method default)
# ---------------------------------------------------------------------------


async def test_null_rule_returns_zero_zero() -> None:
    db = _make_db(area_rate=Decimal("0.75"))
    profile = _profile(high_school_kv_resolved="KV1")
    area, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=None, academic_year=2026,
    )
    assert area == Decimal("0.00")
    assert obj == Decimal("0.00")
    assert snap["rule"] is None
    # DB never queried when rule is None — early exit avoids round-trip.
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Both toggles False → returns zero but still records snapshot
# ---------------------------------------------------------------------------


async def test_both_toggles_off_returns_zero_with_snapshot() -> None:
    db = _make_db()
    profile = _profile(high_school_kv_resolved="KV1")
    rule = {
        "apply_area_bonus": False,
        "apply_object_bonus": False,
        "max_total_bonus": None,
    }
    area, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=rule, academic_year=2026,
    )
    assert area == Decimal("0.00")
    assert obj == Decimal("0.00")
    # Snapshot still records the rule for audit replay
    assert snap["rule"] == rule
    db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Area: NULL kv_resolved → 0 (graceful for legacy 315 profiles)
# ---------------------------------------------------------------------------


async def test_area_null_kv_returns_zero() -> None:
    db = _make_db(area_rate=Decimal("0.75"))
    profile = _profile(high_school_kv_resolved=None)
    area, _, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert area == Decimal("0.00")
    assert snap["area_code"] is None


# ---------------------------------------------------------------------------
# 4. Area: KV1 looked up + applied
# ---------------------------------------------------------------------------


async def test_area_kv1_resolves_rate() -> None:
    db = _make_db(area_rate=Decimal("0.75"))
    profile = _profile(high_school_kv_resolved="KV1")
    area, _, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert area == Decimal("0.75")
    assert snap["area_code"] == "KV1"
    assert snap["area_rate"] == "0.75"


# ---------------------------------------------------------------------------
# 5. Area: KV2-NT canonical (hyphen) — make sure engine doesn't choke
# ---------------------------------------------------------------------------


async def test_area_kv2_nt_canonical_hyphen() -> None:
    db = _make_db(area_rate=Decimal("0.50"))
    profile = _profile(high_school_kv_resolved="KV2-NT")
    area, _, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert area == Decimal("0.50")
    assert snap["area_code"] == "KV2-NT"


# ---------------------------------------------------------------------------
# 6. Area: missing rate for year → 0 (admin chưa seed)
# ---------------------------------------------------------------------------


async def test_area_missing_rate_returns_zero() -> None:
    db = _make_db(area_rate=None)
    profile = _profile(high_school_kv_resolved="KV1")
    area, _, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2099,
    )
    assert area == Decimal("0.00")
    # Snapshot records the code so audit shows "candidate khai KV1
    # nhưng rate chưa config cho 2099"
    assert snap["area_code"] == "KV1"
    assert snap["area_rate"] is None


# ---------------------------------------------------------------------------
# 7. Object: empty codes → 0
# ---------------------------------------------------------------------------


async def test_object_empty_codes_returns_zero() -> None:
    db = _make_db(object_rows=[])
    profile = _profile(priority_object_codes=[], priority_object_evidence={})
    _, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert obj == Decimal("0.00")
    assert snap["verified_codes"] == []


# ---------------------------------------------------------------------------
# 8. Object: codes present but ALL unverified → 0 (evidence gate)
# ---------------------------------------------------------------------------


async def test_object_all_unverified_returns_zero() -> None:
    db = _make_db(object_rows=[("04", Decimal("2.00"))])
    profile = _profile(
        priority_object_codes=["04", "06"],
        priority_object_evidence={
            "04": {"status": "pending"},
            "06": {"status": "rejected"},
        },
    )
    _, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert obj == Decimal("0.00")
    assert snap["verified_codes"] == []


# ---------------------------------------------------------------------------
# 9. Object: multi-UT verified → MAX wins (per TT 05/2021 "1 diện cao nhất")
# ---------------------------------------------------------------------------


async def test_object_multi_ut_picks_max() -> None:
    db = _make_db(
        object_rows=[
            ("04", Decimal("2.00")),  # UT1
            ("06", Decimal("1.00")),  # UT2
        ]
    )
    profile = _profile(
        priority_object_codes=["04", "06"],
        priority_object_evidence={
            "04": {"status": "verified", "verified_by": 5},
            "06": {"status": "verified", "verified_by": 5},
        },
    )
    _, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert obj == Decimal("2.00")
    assert snap["object_max_code"] == "04"
    assert snap["object_rate"] == "2.00"
    # Snapshot records BOTH verified codes for audit even though only
    # the max was applied
    assert sorted(snap["verified_codes"]) == ["04", "06"]


# ---------------------------------------------------------------------------
# 10. Object: only verified subset counts (partial verification)
# ---------------------------------------------------------------------------


async def test_object_partial_verified_counts_only_verified() -> None:
    db = _make_db(
        object_rows=[
            ("06", Decimal("1.00")),  # only 06 returned since 04 not verified
        ]
    )
    profile = _profile(
        priority_object_codes=["04", "06"],
        priority_object_evidence={
            "04": {"status": "pending"},
            "06": {"status": "verified", "verified_by": 5},
        },
    )
    _, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=_RULE_BOTH_ON, academic_year=2026,
    )
    assert obj == Decimal("1.00")
    assert snap["verified_codes"] == ["06"]


# ---------------------------------------------------------------------------
# 11. Combined cap: area + object > max_total_bonus → proportional clip
# ---------------------------------------------------------------------------


async def test_cap_proportional_clip() -> None:
    db = _make_db(
        area_rate=Decimal("0.75"),
        object_rows=[("04", Decimal("2.00"))],
    )
    profile = _profile(
        high_school_kv_resolved="KV1",
        priority_object_codes=["04"],
        priority_object_evidence={"04": {"status": "verified"}},
    )
    rule = {
        "apply_area_bonus": True,
        "apply_object_bonus": True,
        "max_total_bonus": 1.0,  # cap below 0.75+2.0=2.75
    }
    area, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=rule, academic_year=2026,
    )
    # Proportional clip keeps the area/object ratio:
    #   total=2.75, cap=1.0, ratio=1.0/2.75 ≈ 0.3636
    #   area=0.75*ratio ≈ 0.27, object=2.00*ratio ≈ 0.73
    assert area + obj <= Decimal("1.00")
    assert snap["cap_applied"] == "1.0"


# ---------------------------------------------------------------------------
# 12. Apply toggles independent: area on, object off → skip object lookup
# ---------------------------------------------------------------------------


async def test_apply_object_off_skips_object_lookup() -> None:
    db = _make_db(area_rate=Decimal("0.75"))
    profile = _profile(
        high_school_kv_resolved="KV1",
        priority_object_codes=["04"],
        priority_object_evidence={"04": {"status": "verified"}},
    )
    rule = {
        "apply_area_bonus": True,
        "apply_object_bonus": False,
        "max_total_bonus": None,
    }
    area, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=rule, academic_year=2026,
    )
    assert area == Decimal("0.75")
    assert obj == Decimal("0.00")
    # Snapshot for object stays empty since lookup was skipped
    assert snap["verified_codes"] == []
    # Only the area select fired
    assert db.execute.await_count == 1


# ---------------------------------------------------------------------------
# 13. Apply area off, object on → skip area lookup
# ---------------------------------------------------------------------------


async def test_apply_area_off_skips_area_lookup() -> None:
    db = _make_db(
        area_rate=Decimal("0.75"),
        object_rows=[("04", Decimal("2.00"))],
    )
    profile = _profile(
        high_school_kv_resolved="KV1",
        priority_object_codes=["04"],
        priority_object_evidence={"04": {"status": "verified"}},
    )
    rule = {
        "apply_area_bonus": False,
        "apply_object_bonus": True,
        "max_total_bonus": None,
    }
    area, obj, snap = await calculate_priority_bonus(
        db=db, profile=profile, rule=rule, academic_year=2026,
    )
    assert area == Decimal("0.00")
    assert obj == Decimal("2.00")
    assert snap["area_code"] is None
    # Only the object select fired
    assert db.execute.await_count == 1
