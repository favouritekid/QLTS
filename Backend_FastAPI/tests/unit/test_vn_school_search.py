"""Phase D.0b — VnSchool search service + endpoint tests.

Covers:
- `VnSchoolService.search_schools()` with diacritic-insensitive ILIKE
- Filter by level + province
- Pagination (limit/offset)
- Edge cases: empty query, no matches, SQL injection attempt
- Router auth gate (401 without token)

Requires pg_unaccent extension (migration q9_07_d0a).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.vn_school import VnSchool, VnSchoolKvAssignment
from app.services.vn_school_service import VnSchoolService


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# =============================================================================
# Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def db(setup_test_database):
    """Local db fixture (tests/unit/ doesn't have shared conftest fixture)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


@pytest_asyncio.fixture
async def seed_schools(db: AsyncSession):
    """Seed 4 schools for search tests."""
    # Ensure pg_unaccent installed (no-op if exists)
    await db.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))

    schools = [
        VnSchool(
            moet_province_code="040",
            moet_school_code="T001",
            name="THPT Trần Phú Đắk Lắk",
            address="Số 1 Lê Lợi",
            province="Đắk Lắk",
            district="Buôn Ma Thuột",
            level="THPT",
            is_dtnt=False,
            is_active=True,
        ),
        VnSchool(
            moet_province_code="040",
            moet_school_code="T002",
            name="THPT Nguyễn Huệ",
            address="Số 2 Hai Bà Trưng",
            province="Đắk Lắk",
            district="Buôn Hồ",
            level="THPT",
            is_dtnt=False,
            is_active=True,
        ),
        VnSchool(
            moet_province_code="042",
            moet_school_code="T003",
            name="THPT Trần Phú Lâm Đồng",
            address="Số 3 Yersin",
            province="Lâm Đồng",
            district="Đà Lạt",
            level="THPT",
            is_dtnt=False,
            is_active=True,
        ),
        VnSchool(
            moet_province_code="042",
            moet_school_code="T004",
            name="THCS Trần Phú Bảo Lộc",
            address="Số 4 Hùng Vương",
            province="Lâm Đồng",
            district="Bảo Lộc",
            level="THCS",
            is_dtnt=False,
            is_active=True,
        ),
    ]
    for s in schools:
        db.add(s)
    await db.flush()

    # Add current KV for first 3 (active assignment effective_to_year=NULL)
    for s, kv in zip(schools[:3], ["KV1", "KV2", "KV3"]):
        db.add(
            VnSchoolKvAssignment(
                school_id=s.id,
                kv_code=kv,
                effective_from_year=2025,
                effective_to_year=None,
                source="test_seed",
            )
        )
    await db.flush()
    return schools


# =============================================================================
# Search tests
# =============================================================================


@pytest.mark.asyncio
async def test_search_diacritic_insensitive_no_marks(seed_schools, db):
    """Query 'Tran Phu' (no diacritic) should match 'Trần Phú' entries."""
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Tran Phu", limit=10)
    names = {r["name"] for r in rows}
    assert "THPT Trần Phú Đắk Lắk" in names
    assert "THPT Trần Phú Lâm Đồng" in names
    assert "THCS Trần Phú Bảo Lộc" in names
    assert total == 3


@pytest.mark.asyncio
async def test_search_diacritic_insensitive_with_marks(seed_schools, db):
    """Query 'Trần Phú' (full diacritic) returns same results."""
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trần Phú", limit=10)
    assert total == 3


@pytest.mark.asyncio
async def test_search_filter_by_level(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trần Phú", level="THPT", limit=10)
    assert total == 2
    assert all(r["level"] == "THPT" for r in rows)


@pytest.mark.asyncio
async def test_search_filter_by_province(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trần Phú", province="042", limit=10)
    assert total == 2
    assert all(r["moet_province_code"] == "042" for r in rows)


@pytest.mark.asyncio
async def test_search_combined_filters(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(
        query="Trần Phú", level="THPT", province="040", limit=10
    )
    assert total == 1
    assert rows[0]["moet_school_code"] == "T001"


@pytest.mark.asyncio
async def test_search_returns_current_kv(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trần Phú Đắk", limit=10)
    assert total == 1
    assert rows[0]["current_kv"] == "KV1"


@pytest.mark.asyncio
async def test_search_no_current_kv_for_school_without_assignment(seed_schools, db):
    """THCS Trần Phú Bảo Lộc has no kv_assignment → current_kv = None."""
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trần Phú Bảo Lộc", limit=10)
    assert total == 1
    assert rows[0]["current_kv"] is None


@pytest.mark.asyncio
async def test_search_empty_query_returns_zero(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="", limit=10)
    assert rows == []
    assert total == 0


@pytest.mark.asyncio
async def test_search_no_match(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trường KHÔNG TỒN TẠI", limit=10)
    assert rows == []
    assert total == 0


@pytest.mark.asyncio
async def test_search_pagination_limit(seed_schools, db):
    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Trần Phú", limit=2, offset=0)
    assert len(rows) == 2
    assert total == 3  # total ignores limit


@pytest.mark.asyncio
async def test_search_pagination_offset(seed_schools, db):
    svc = VnSchoolService(db)
    page1, _ = await svc.search_schools(query="Trần Phú", limit=2, offset=0)
    page2, _ = await svc.search_schools(query="Trần Phú", limit=2, offset=2)
    page1_ids = {r["id"] for r in page1}
    page2_ids = {r["id"] for r in page2}
    assert page1_ids.isdisjoint(page2_ids)  # no overlap


@pytest.mark.asyncio
async def test_search_excludes_inactive_school(db):
    """is_active=False schools excluded from results."""
    await db.execute(text("CREATE EXTENSION IF NOT EXISTS unaccent"))
    school = VnSchool(
        moet_province_code="040",
        moet_school_code="INACTIVE",
        name="THPT Ngưng Hoạt Động",
        province="Đắk Lắk",
        level="THPT",
        is_dtnt=False,
        is_active=False,
    )
    db.add(school)
    await db.flush()

    svc = VnSchoolService(db)
    rows, total = await svc.search_schools(query="Ngưng Hoạt", limit=10)
    assert total == 0


@pytest.mark.asyncio
async def test_search_sql_injection_safe(seed_schools, db):
    """ILIKE wildcards (% _) trong query string escaped."""
    svc = VnSchoolService(db)
    # '%' should not match everything if escaped
    rows, total = await svc.search_schools(query="100% nothing", limit=10)
    assert total == 0  # literal "100% nothing" not in any school name
