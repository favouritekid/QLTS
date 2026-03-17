# -*- coding: utf-8 -*-
"""Contract tests for administrative nodes API (mode=current|legacy)."""

from datetime import date

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.models.administrative_node import AdministrativeLevel


# ---------------------------------------------------------------------------
# Shared fixture: seed a minimal dual-era dataset
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def _seed_admin_nodes():
    """Seed test provinces/districts/wards covering both eras."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Legacy provinces (valid_to set)
            session.add_all([
                models.AdministrativeNode(
                    code="10", name="Lao Cai (legacy)", level=AdministrativeLevel.PROVINCE,
                    parent_id=None, path="10", province_code="10",
                    valid_from=date(2008, 8, 1), valid_to=date(2025, 6, 30), is_active=True,
                ),
                models.AdministrativeNode(
                    code="15", name="Yen Bai", level=AdministrativeLevel.PROVINCE,
                    parent_id=None, path="15", province_code="15",
                    valid_from=date(2008, 8, 1), valid_to=date(2025, 6, 30), is_active=True,
                ),
            ])
            await session.flush()

            # Legacy district under code 10
            legacy_prov = await session.get(models.AdministrativeNode,
                (await session.execute(
                    models.AdministrativeNode.__table__.select()
                    .where(models.AdministrativeNode.code == "10")
                    .where(models.AdministrativeNode.level == AdministrativeLevel.PROVINCE)
                )).scalar_one().id
            ) if False else None  # just use raw insert for simplicity

        # Re-open to add hierarchy
        async with session.begin():
            from sqlalchemy import text
            # Legacy district
            await session.execute(text("""
                INSERT INTO administrative_nodes
                (code, name, level, path, province_code, district_code, valid_from, valid_to, is_active)
                VALUES ('10_001', 'Huyen A', 'DISTRICT', '10/10_001', '10', '10_001',
                        '2008-08-01', '2025-06-30', true)
            """))
            # Legacy ward (3-level)
            await session.execute(text("""
                INSERT INTO administrative_nodes
                (code, name, level, path, province_code, district_code, ward_code, valid_from, valid_to, is_active)
                VALUES ('00001', 'Xa Cu', 'WARD', '10/10_001/00001', '10', '10_001', '00001',
                        '2008-08-01', '2025-06-30', true)
            """))

            # Current province: code 15 reused as "Lao Cai" (merged Lao Cai + Yen Bai)
            await session.execute(text("""
                INSERT INTO administrative_nodes
                (code, name, level, path, province_code, valid_from, valid_to, is_active)
                VALUES ('15', 'Lao Cai', 'PROVINCE', '15', '15',
                        '2025-07-01', NULL, true)
            """))
            # Current ward (2-level, no district)
            await session.execute(text("""
                INSERT INTO administrative_nodes
                (code, name, level, path, province_code, ward_code, valid_from, valid_to, is_active)
                VALUES ('00001', 'Xa Moi', 'WARD', '15/00001', '15', '00001',
                        '2025-07-01', NULL, true)
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

    # Current: code 15 = "Lao Cai" (merged). Code 10 is legacy only.
    assert "15" in codes
    assert "10" not in codes

    # Response only has code + name (no valid_from/valid_to/is_current)
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

    # Legacy: both 10 and 15 (old Yen Bai)
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
    assert "10" not in codes  # legacy code not in default response


# ---------------------------------------------------------------------------
# /districts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_districts_returns_legacy_districts(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    """Districts only exist in legacy era."""
    resp = await client.get(
        "/api/administrative/districts",
        params={"province_code": "10"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["code"] == "10_001"
    assert data[0]["name"] == "Huyen A"


@pytest.mark.asyncio
async def test_districts_empty_for_current_province(
    client: AsyncClient,
    regular_user_token_headers: dict,
):
    """Current provinces have no districts (2-level structure)."""
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
    """mode=current returns 2-level wards (no district_code)."""
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
    """mode=legacy with district_code returns 3-level wards."""
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
    """mode=legacy without district_code returns empty (district required)."""
    resp = await client.get(
        "/api/administrative/wards",
        params={"province_code": "10", "mode": "legacy"},
        headers=regular_user_token_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
