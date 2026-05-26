"""Unit tests for VnLocalityService (Q9 #07 PR4 — commune CSV import only).

Scope updated 2026-05-18 (phase1_09 v1.3 redesign):
* VnHighSchool tests REMOVED (table dropped, replaced by VnSchool family
  with Phase B.1 import script ``app/scripts/import_moet_schools_2025.py``)
* Kept: commune CSV import (idempotent + malformed-row collection +
  F.5 header validation + N2 UTF-8 fallback + CR-M2 BOM strip)
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import AsyncSessionLocal
from app.services.vn_locality_service import VnLocalityService


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


# ---------------------------------------------------------------------------
# Commune CSV import
# ---------------------------------------------------------------------------


async def test_commune_import_inserts_valid_rows(db) -> None:
    csv = (
        b"commune_code,province,district,ward,area_code\n"
        b"C001,Ha Noi,Ha Dong,Phuong A,KV3\n"
        b"C002,Dak Lak,Buon Ma Thuot,Phuong B,KV1\n"
    )
    service = VnLocalityService(db)
    result, _ = await service.import_commune_csv(csv)
    assert result["inserted"] == 2
    assert result["skipped_existing"] == 0
    assert result["error_rows"] == []


async def test_commune_import_accepts_empty_district_2tier(db) -> None:
    """2-tier model (post-2025 sáp nhập): current-era communes have NO
    district, so the importer MUST accept district="". This was rejected by
    a stale ``min_length=1`` on ``VnCommuneAreaMapRow.district`` which blocked
    100% of real rows (anchor for the 2026-05-26 relax). commune_code = raw
    ward.code (e.g. '21609') — matches FE ``permanent_commune_code``."""
    csv = (
        b"commune_code,province,district,ward,area_code\n"
        b"21609,Tinh Gia Lai,,Xa An Lao,KV1\n"
    )
    service = VnLocalityService(db)
    result, _ = await service.import_commune_csv(csv)
    assert result["inserted"] == 1, result["error_rows"]
    assert result["error_rows"] == []
    # raw commune_code resolves through the same opaque-equality lookup
    assert await service.lookup_commune_kv("21609") == "KV1"


async def test_commune_import_skips_duplicate_active_row(db) -> None:
    csv = (
        b"commune_code,province,district,ward,area_code\n"
        b"C001,Ha Noi,Ha Dong,Phuong A,KV3\n"
    )
    service = VnLocalityService(db)
    # First import — insert
    r1, _ = await service.import_commune_csv(csv)
    assert r1["inserted"] == 1
    # Second import — skipped (idempotent)
    r2, _ = await service.import_commune_csv(csv)
    assert r2["inserted"] == 0
    assert r2["skipped_existing"] == 1


async def test_commune_import_collects_malformed_rows(db) -> None:
    csv = (
        b"commune_code,province,district,ward,area_code\n"
        b"C001,Ha Noi,Ha Dong,Phuong A,KV3\n"          # OK
        b"C002,Ha Noi,Ha Dong,Phuong B,KV2_NT\n"        # bad: underscore form
        b"C003,Ha Noi,Ha Dong,Phuong C,INVALID\n"       # bad: not KV*
    )
    service = VnLocalityService(db)
    result, _ = await service.import_commune_csv(csv)
    assert result["inserted"] == 1
    assert len(result["error_rows"]) == 2
    # Each error carries row_num (1=header, so first data row = 2)
    assert all("row_num" in e and "error" in e for e in result["error_rows"])


# ---------------------------------------------------------------------------
# CSV validation
# ---------------------------------------------------------------------------


async def test_commune_csv_missing_header_column_raises_validation(db) -> None:
    """F.5 fix: CSV with header missing a required column must raise
    a single clear DomainValidationError up-front instead of silently
    inserting 0 rows with N per-row Pydantic errors (admin tưởng OK)."""
    from app.utils.exceptions import ValidationError as DomainValidationError

    # Header missing 'area_code'
    bad_csv = (
        b"commune_code,province,district,ward\n"
        b"C001,Ha Noi,Ha Dong,Phuong A\n"
    )
    service = VnLocalityService(db)
    with pytest.raises(DomainValidationError, match="area_code"):
        await service.import_commune_csv(bad_csv)


async def test_csv_decode_non_utf8_raises_friendly_validation_error(db) -> None:
    """N2 fix: bytes that can't decode as UTF-8 (vd: CP1258 Excel-VN
    export) must raise a domain ValidationError with admin-friendly
    hint instead of opaque 500 from UnicodeDecodeError."""
    from app.utils.exceptions import ValidationError as DomainValidationError

    # Bytes 0xE9 (é in latin1/cp1258) is invalid as UTF-8 lead byte
    bad_csv = b"commune_code,province,district,ward,area_code\nC1,H\xe9 Noi,X,Y,KV3\n"
    service = VnLocalityService(db)
    with pytest.raises(DomainValidationError, match="UTF-8"):
        await service.import_commune_csv(bad_csv)


async def test_csv_decode_strips_utf8_bom(db) -> None:
    """CR-M2 fix: Excel-exported CSVs often start with UTF-8 BOM
    (\\xef\\xbb\\xbf). Without utf-8-sig decode, first header column
    becomes '\\ufeffcommune_code' and every row fails Pydantic parse."""
    csv_with_bom = (
        b"\xef\xbb\xbf"  # UTF-8 BOM
        b"commune_code,province,district,ward,area_code\n"
        b"C001,Ha Noi,Ha Dong,Phuong A,KV3\n"
    )
    service = VnLocalityService(db)
    result, _ = await service.import_commune_csv(csv_with_bom)
    assert result["inserted"] == 1
    assert result["error_rows"] == []


# ---------------------------------------------------------------------------
# lookup_commune_kv (used by priority_service for 4 special cases + fallback)
# ---------------------------------------------------------------------------


async def test_lookup_commune_kv_returns_active_row(db) -> None:
    """Service uses this for permanent_address_special bypass + TC commune_fallback."""
    csv = b"commune_code,province,district,ward,area_code\nKV1_TEST,Dak Lak,Buon Ma Thuot,X,KV1\n"
    service = VnLocalityService(db)
    await service.import_commune_csv(csv)
    kv = await service.lookup_commune_kv("KV1_TEST")
    assert kv == "KV1"


async def test_lookup_commune_kv_returns_none_for_missing(db) -> None:
    """Missing commune → None (caller falls back to manual_override)."""
    service = VnLocalityService(db)
    kv = await service.lookup_commune_kv("NONEXISTENT")
    assert kv is None
