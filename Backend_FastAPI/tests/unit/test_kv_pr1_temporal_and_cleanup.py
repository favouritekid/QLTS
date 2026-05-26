"""PR-1 anchors: temporal commune-KV (as-of academic_year) + SMOKE cleanup.

Covers:
* _lookup_commune_kv resolves the KV row effective for the given year (a
  mid-year reclassification, recorded as expire-old + insert-new, must NOT
  bleed across years) — the prod blocker the user flagged.
* SMOKE_* placeholder cleanup predicate removes all + leaves real rows.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.models.vn_locality import VnCommuneAreaMap
from app.services.priority_service import _lookup_commune_kv

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as s:
        try:
            yield s
        finally:
            await s.rollback()
            await s.close()


async def test_lookup_commune_kv_resolves_by_year(db) -> None:
    """Xã 99001 đổi KV giữa 2026: KV1 đến 01/06/2026, KV2 sau đó.
    Lookup phải trả KV ĐÚNG THEO NĂM tuyển sinh (không lấy mù 'now')."""
    db.add(VnCommuneAreaMap(
        commune_code="99001", province="P", district="", ward="W",
        area_code="KV1", effective_from=date(2024, 1, 1),
        effective_to=date(2026, 6, 1),
    ))
    db.add(VnCommuneAreaMap(
        commune_code="99001", province="P", district="", ward="W",
        area_code="KV2", effective_from=date(2026, 6, 1), effective_to=None,
    ))
    await db.flush()

    assert await _lookup_commune_kv(db, "99001", 2025) == "KV1"
    assert await _lookup_commune_kv(db, "99001", 2026) == "KV2"
    assert await _lookup_commune_kv(db, "99001", 2027) == "KV2"
    # commune not in catalog → graceful None
    assert await _lookup_commune_kv(db, "00000", 2026) is None


async def test_smoke_cleanup_predicate_removes_all_and_keeps_real(db) -> None:
    """Predicate của migration kv_smoke_cleanup_20260526 xóa hết SMOKE_*,
    giữ nguyên dòng thật, và assert còn 0 SMOKE."""
    db.add(VnCommuneAreaMap(
        commune_code="SMOKE_DLK_01", province="P", district="D", ward="W",
        area_code="KV1", effective_from=date(2026, 1, 1),
    ))
    db.add(VnCommuneAreaMap(
        commune_code="21609", province="Tỉnh Gia Lai", district="", ward="Xã An Lão",
        area_code="KV1", effective_from=date(2026, 1, 1),
    ))
    await db.flush()

    await db.execute(text(
        "DELETE FROM vn_commune_area_map WHERE commune_code LIKE 'SMOKE%'"
    ))
    n_smoke = (await db.execute(text(
        "SELECT count(*) FROM vn_commune_area_map WHERE commune_code LIKE 'SMOKE%'"
    ))).scalar()
    n_real = (await db.execute(text(
        "SELECT count(*) FROM vn_commune_area_map WHERE commune_code='21609'"
    ))).scalar()

    assert n_smoke == 0, "migration phải xóa hết SMOKE_*"
    assert n_real == 1, "dòng thật KHÔNG được đụng"
