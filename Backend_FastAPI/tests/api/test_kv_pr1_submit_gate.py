"""PR-1 anchor: Gap #3 current-era ward gate logic.

The submit gate's novel decision — "permanent_ward must be a CURRENT-era node,
not merely present" — is extracted into ``_is_current_era_ward`` and unit-tested
directly here. A full submit_and_evaluate integration (reach the gate + assert
status='draft') additionally needs a config-complete profile to pass the
upstream CONFIG_GAP_TARGET_LEVEL eligibility gate (the pre-existing #337
fixture-seed debt) — tracked as a follow-up.

NOTE: the gate WIRING (full_name / phone / permanent_province / permanent_ward
presence + this current-era check) is in submit_and_evaluate just before
``if errors:``; presence checks are trivial string-empty guards.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

from app.database import AsyncSessionLocal
from app.models.administrative_node import AdministrativeLevel, AdministrativeNode
from app.services.admission_service import _is_current_era_ward

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as s:
        try:
            yield s
        finally:
            await s.rollback()
            await s.close()


async def test_is_current_era_ward_gate(db) -> None:
    """current-era ward → True; legacy / missing / empty / None → False
    (Gap #3 fail-closed: chỉ chấp nhận xã địa giới hiện hành)."""
    db.add(AdministrativeNode(
        code="CUR01", name="Phường Hiện Hành", level=AdministrativeLevel.WARD,
        path="99/CUR01", province_code="99", ward_code="CUR01",
        valid_from=date(2025, 7, 1), valid_to=None, is_active=True,
    ))
    db.add(AdministrativeNode(
        code="LEG01", name="Xã Cũ", level=AdministrativeLevel.WARD,
        path="99/99_001/LEG01", province_code="99", district_code="99_001",
        ward_code="LEG01", valid_from=date(2010, 1, 1),
        valid_to=date(2025, 7, 1), is_active=True,  # valid_to set = legacy
    ))
    await db.flush()

    assert await _is_current_era_ward(db, "CUR01") is True   # current → pass
    assert await _is_current_era_ward(db, "LEG01") is False  # legacy → reject
    assert await _is_current_era_ward(db, "NOPE") is False   # missing → reject
    assert await _is_current_era_ward(db, "") is False       # empty → reject
    assert await _is_current_era_ward(db, None) is False     # None → reject
