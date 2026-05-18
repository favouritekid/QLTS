"""Unit tests for PriorityConfigService (Q9 #07 PR3).

CRUD + clone-from-year + seed-defaults TT 05/2021. Uses a real test
DB session via the standard ``db`` fixture so the partial UNIQUE +
CHECK constraints fire on bad inputs.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.services.priority_config_service import (
    TT_05_2021_AREA_DEFAULTS,
    TT_05_2021_OBJECT_DEFAULTS,
    PriorityConfigService,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db(setup_test_database):
    """Function-scoped async DB session bound to the test DB after the
    standard ``setup_test_database`` fixture has initialized the schema
    + truncated rows. Rollback teardown so any partial-state test
    doesn't leak into next."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


# ---------------------------------------------------------------------------
# Area CRUD
# ---------------------------------------------------------------------------


async def test_create_area_persists_with_defaults(db) -> None:
    service = PriorityConfigService(db)
    row, _cb = await service.create_area(
        {
            "academic_year": 2026,
            "area_code": "KV1",
            "area_name": "Khu vực 1",
            "bonus_points": Decimal("0.75"),
        }
    )
    await db.flush()
    assert row.id is not None
    assert row.area_code == "KV1"
    assert row.bonus_points == Decimal("0.75")
    # Server-side default for effective_from = CURRENT_DATE
    assert row.effective_from is not None


async def test_create_area_duplicate_active_raises(db) -> None:
    service = PriorityConfigService(db)
    await service.create_area(
        {
            "academic_year": 2026, "area_code": "KV1",
            "area_name": "KV1", "bonus_points": Decimal("0.75"),
        }
    )
    with pytest.raises(DuplicateResourceError):
        await service.create_area(
            {
                "academic_year": 2026, "area_code": "KV1",
                "area_name": "KV1 v2", "bonus_points": Decimal("0.50"),
            }
        )


async def test_create_area_rejects_invalid_code_via_db_check(db) -> None:
    """CHECK regex on area_code blocks 'KV2_NT' (underscore) — only
    canonical 'KV2-NT' (hyphen) per TT 05/2021."""
    service = PriorityConfigService(db)
    with pytest.raises(IntegrityError):
        await service.create_area(
            {
                "academic_year": 2026, "area_code": "KV2_NT",
                "area_name": "Bad", "bonus_points": Decimal("0.50"),
            }
        )
        await db.flush()


async def test_update_area_patches_bonus_points(db) -> None:
    service = PriorityConfigService(db)
    row, _ = await service.create_area(
        {
            "academic_year": 2026, "area_code": "KV1",
            "area_name": "KV1", "bonus_points": Decimal("0.75"),
        }
    )
    updated, _ = await service.update_area(
        row.id, {"bonus_points": Decimal("0.80")}
    )
    assert updated.bonus_points == Decimal("0.80")


async def test_update_area_404_when_missing(db) -> None:
    service = PriorityConfigService(db)
    with pytest.raises(ResourceNotFoundError):
        await service.update_area(99999, {"bonus_points": Decimal("0.50")})


async def test_retire_area_sets_effective_to_today(db) -> None:
    service = PriorityConfigService(db)
    row, _ = await service.create_area(
        {
            "academic_year": 2026, "area_code": "KV1",
            "area_name": "KV1", "bonus_points": Decimal("0.75"),
        }
    )
    retired, _ = await service.retire_area(row.id)
    assert retired.effective_to == date.today()


async def test_retire_area_idempotency_blocks_double_retire(db) -> None:
    service = PriorityConfigService(db)
    row, _ = await service.create_area(
        {
            "academic_year": 2026, "area_code": "KV1",
            "area_name": "KV1", "bonus_points": Decimal("0.75"),
        }
    )
    await service.retire_area(row.id)
    with pytest.raises(BusinessRuleViolation):
        await service.retire_area(row.id)


async def test_retire_area_then_recreate_succeeds(db) -> None:
    """Partial UNIQUE WHERE effective_to IS NULL allows new active row
    after old one is retired — supports mid-year rate change."""
    service = PriorityConfigService(db)
    old, _ = await service.create_area(
        {
            "academic_year": 2026, "area_code": "KV1",
            "area_name": "KV1 v1", "bonus_points": Decimal("0.75"),
        }
    )
    await service.retire_area(old.id)
    new_row, _ = await service.create_area(
        {
            "academic_year": 2026, "area_code": "KV1",
            "area_name": "KV1 v2 (TT mới)", "bonus_points": Decimal("0.50"),
        }
    )
    assert new_row.id != old.id
    assert new_row.bonus_points == Decimal("0.50")


# ---------------------------------------------------------------------------
# Object CRUD (same pattern, just spot-check)
# ---------------------------------------------------------------------------


async def test_create_object_persists(db) -> None:
    service = PriorityConfigService(db)
    row, _ = await service.create_object(
        {
            "academic_year": 2026, "group_code": "UT1", "sub_code": "04",
            "description": "Con liệt sĩ", "bonus_points": Decimal("2.00"),
        }
    )
    assert row.id is not None
    assert row.sub_code == "04"


async def test_create_object_rejects_invalid_sub_code_via_db_check(db) -> None:
    service = PriorityConfigService(db)
    with pytest.raises(IntegrityError):
        await service.create_object(
            {
                "academic_year": 2026, "group_code": "UT1", "sub_code": "4",
                "description": "Bad (need 2 digits)",
                "bonus_points": Decimal("2.00"),
            }
        )
        await db.flush()


# ---------------------------------------------------------------------------
# Clone-from-year
# ---------------------------------------------------------------------------


async def test_clone_copies_active_rows_only(db) -> None:
    service = PriorityConfigService(db)
    # Seed 2 active + 1 retired in 2026
    await service.create_area(
        {"academic_year": 2026, "area_code": "KV1", "area_name": "KV1", "bonus_points": Decimal("0.75")}
    )
    retired, _ = await service.create_area(
        {"academic_year": 2026, "area_code": "KV2", "area_name": "KV2", "bonus_points": Decimal("0.25")}
    )
    await service.retire_area(retired.id)
    await service.create_area(
        {"academic_year": 2026, "area_code": "KV2-NT", "area_name": "KV2-NT", "bonus_points": Decimal("0.50")}
    )

    result, _ = await service.clone_from_year(from_year=2026, to_year=2027)
    # Only the 2 active rows cloned; retired KV2 row skipped
    assert result["cloned_areas"] == 2


async def test_clone_skips_existing_in_target_year(db) -> None:
    service = PriorityConfigService(db)
    await service.create_area(
        {"academic_year": 2026, "area_code": "KV1", "area_name": "KV1", "bonus_points": Decimal("0.75")}
    )
    await service.create_area(
        {"academic_year": 2027, "area_code": "KV1", "area_name": "Already there", "bonus_points": Decimal("0.80")}
    )
    result, _ = await service.clone_from_year(from_year=2026, to_year=2027)
    # KV1 already in 2027 → skipped
    assert result["cloned_areas"] == 0


async def test_clone_same_year_raises(db) -> None:
    service = PriorityConfigService(db)
    with pytest.raises(BusinessRuleViolation):
        await service.clone_from_year(from_year=2026, to_year=2026)


# ---------------------------------------------------------------------------
# Seed defaults TT 05/2021
# ---------------------------------------------------------------------------


async def test_seed_inserts_all_baseline_rates_when_empty(db) -> None:
    service = PriorityConfigService(db)
    result, _ = await service.seed_tt_05_2021_defaults(2026)
    assert result["inserted_areas"] == len(TT_05_2021_AREA_DEFAULTS) == 4
    assert result["inserted_objects"] == len(TT_05_2021_OBJECT_DEFAULTS) == 7
    assert result["skipped_existing"] is False


async def test_seed_idempotent_skips_when_any_active_exists(db) -> None:
    service = PriorityConfigService(db)
    # Seed once
    await service.seed_tt_05_2021_defaults(2026)
    # Seed again — should skip entirely
    result, _ = await service.seed_tt_05_2021_defaults(2026)
    assert result["skipped_existing"] is True
    assert result["inserted_areas"] == 0


async def test_seed_kv_rates_match_tt_05_2021_phu_luc_01(db) -> None:
    """Lock the exact rates the engine will see — regression here would
    silently change scoring outcomes for the whole year."""
    service = PriorityConfigService(db)
    await service.seed_tt_05_2021_defaults(2026)
    rows = await service.list_areas(2026, active_only=True)
    by_code = {r.area_code: r.bonus_points for r in rows}
    assert by_code == {
        "KV1": Decimal("0.75"),
        "KV2-NT": Decimal("0.50"),
        "KV2": Decimal("0.25"),
        "KV3": Decimal("0.00"),
    }


async def test_seed_ut_rates_match_tt_05_2021_phu_luc_01(db) -> None:
    service = PriorityConfigService(db)
    await service.seed_tt_05_2021_defaults(2026)
    rows = await service.list_objects(2026, active_only=True)
    ut1 = {r.sub_code: r.bonus_points for r in rows if r.group_code == "UT1"}
    ut2 = {r.sub_code: r.bonus_points for r in rows if r.group_code == "UT2"}
    # UT1: 4 codes (01-04) all 2.00
    assert set(ut1.keys()) == {"01", "02", "03", "04"}
    assert all(v == Decimal("2.00") for v in ut1.values())
    # UT2: 3 codes (05-07) all 1.00
    assert set(ut2.keys()) == {"05", "06", "07"}
    assert all(v == Decimal("1.00") for v in ut2.values())
