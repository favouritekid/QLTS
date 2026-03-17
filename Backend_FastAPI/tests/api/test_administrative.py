# -*- coding: utf-8 -*-
"""Contract tests for administrative nodes API (mode=current|legacy).

Tests use the shared test DB (via setup_test_database → client chain).
Seed data is inserted via the db session AFTER truncation, BEFORE requests.
"""

from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.database import AsyncSessionLocal


# ---------------------------------------------------------------------------
# Fixture: seed a minimal dual-era dataset into the (already-truncated) test DB
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def _seed_admin_nodes(setup_test_database):
    """
    Seed test provinces/districts/wards for both eras.

    Depends on setup_test_database to ensure tables are truncated first.
    Uses raw SQL to avoid ORM session conflicts with the test client.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("""
                INSERT INTO administrative_nodes
                    (code, name, level, path, province_code, valid_from, valid_to, is_active)
                VALUES
                    -- Legacy provinces
                    ('10', 'Lao Cai (legacy)', 'PROVINCE', '10', '10', '2008-08-01', '2025-06-30', true),
                    ('15', 'Yen Bai',          'PROVINCE', '15', '15', '2008-08-01', '2025-06-30', true),
                    -- Current province (code 15 reused with new name)
                    ('15', 'Lao Cai',          'PROVINCE', '15', '15', '2025-07-01', NULL,         true)
            """))
            await session.execute(text("""
                INSERT INTO administrative_nodes
                    (code, name, level, path, province_code, district_code, valid_from, valid_to, is_active)
                VALUES
                    -- Legacy district under code 10
                    ('10_001', 'Huyen A', 'DISTRICT', '10/10_001', '10', '10_001', '2008-08-01', '2025-06-30', true)
            """))
            await session.execute(text("""
                INSERT INTO administrative_nodes
                    (code, name, level, path, province_code, district_code, ward_code, valid_from, valid_to, is_active)
                VALUES
                    -- Legacy ward (3-level)
                    ('00001', 'Xa Cu',  'WARD', '10/10_001/00001', '10', '10_001', '00001', '2008-08-01', '2025-06-30', true),
                    -- Current ward (2-level, no district)
                    ('00001', 'Xa Moi', 'WARD', '15/00001',       '15', NULL,     '00001', '2025-07-01', NULL,         true)
            """))


# ---------------------------------------------------------------------------
# /provinces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provinces_current_returns_only_current(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    """mode=current returns only provinces with valid_to IS NULL."""
    resp = await client.get(
        "/api/administrative/provinces",
        params={"mode": "current"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    codes = {p["code"] for p in data}

    assert "15" in codes  # Current "Lao Cai"
    assert "10" not in codes  # Legacy only

    for p in data:
        assert set(p.keys()) == {"code", "name"}


@pytest.mark.asyncio
async def test_provinces_legacy_returns_only_legacy(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    """mode=legacy returns only provinces with valid_to IS NOT NULL."""
    resp = await client.get(
        "/api/administrative/provinces",
        params={"mode": "legacy"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    codes = {p["code"] for p in data}

    assert "10" in codes
    assert "15" in codes

    lc = next(p for p in data if p["code"] == "10")
    assert lc["name"] == "Lao Cai (legacy)"

    yb = next(p for p in data if p["code"] == "15")
    assert yb["name"] == "Yen Bai"


@pytest.mark.asyncio
async def test_provinces_default_mode_is_current(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    """Calling /provinces without mode param defaults to current."""
    resp = await client.get(
        "/api/administrative/provinces",
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    codes = {p["code"] for p in resp.json()}
    assert "10" not in codes


# ---------------------------------------------------------------------------
# /districts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_districts_returns_legacy_districts(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    resp = await client.get(
        "/api/administrative/districts",
        params={"province_code": "10"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["code"] == "10_001"


@pytest.mark.asyncio
async def test_districts_empty_for_current_province(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    resp = await client.get(
        "/api/administrative/districts",
        params={"province_code": "15"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# /wards
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_wards_current_returns_2level(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    resp = await client.get(
        "/api/administrative/wards",
        params={"province_code": "15", "mode": "current"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Xa Moi"
    assert data[0]["district_code"] is None


@pytest.mark.asyncio
async def test_wards_legacy_returns_3level(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    resp = await client.get(
        "/api/administrative/wards",
        params={"province_code": "10", "mode": "legacy", "district_code": "10_001"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Xa Cu"
    assert data[0]["district_code"] == "10_001"


@pytest.mark.asyncio
async def test_wards_legacy_without_district_returns_empty(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    resp = await client.get(
        "/api/administrative/wards",
        params={"province_code": "10", "mode": "legacy"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
