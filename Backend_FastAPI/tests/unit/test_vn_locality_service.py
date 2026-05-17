"""Unit tests for VnLocalityService (Q9 #07 PR4).

CSV import (commune + high_school) + sample seed + search dropdown.
Idempotent behavior + malformed-row collection are the main contracts.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import AsyncSessionLocal
from app.services.vn_locality_service import (
    SAMPLE_HIGH_SCHOOLS,
    VnLocalityService,
)


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
# High school CSV import
# ---------------------------------------------------------------------------


async def test_high_school_import_inserts_valid_rows(db) -> None:
    csv = (
        b"name,province,district,ward,kv_code\n"
        b"THPT A,Ha Noi,Ha Dong,Phuong 1,KV3\n"
        b"THPT B,Ha Noi,Cau Giay,Phuong 2,KV3\n"
    )
    service = VnLocalityService(db)
    result, _ = await service.import_high_school_csv(csv)
    assert result["inserted"] == 2


async def test_high_school_import_skips_existing_by_name_province(db) -> None:
    csv = b"name,province,district,ward,kv_code\nTHPT A,Ha Noi,Ha Dong,Phuong 1,KV3\n"
    service = VnLocalityService(db)
    await service.import_high_school_csv(csv)
    r2, _ = await service.import_high_school_csv(csv)
    assert r2["inserted"] == 0
    assert r2["skipped_existing"] == 1


async def test_high_school_kv_code_optional(db) -> None:
    """MOET CSV may not always include kv_code — admin will fill later
    via priority backfill UI. Should accept None."""
    csv = b"name,province,district,ward,kv_code\nTHPT C,Ha Noi,,,\n"
    service = VnLocalityService(db)
    result, _ = await service.import_high_school_csv(csv)
    assert result["inserted"] == 1


# ---------------------------------------------------------------------------
# Sample seed
# ---------------------------------------------------------------------------


async def test_seed_sample_inserts_5_rows(db) -> None:
    service = VnLocalityService(db)
    result, _ = await service.seed_sample_high_schools()
    assert result["inserted"] == 5
    assert result["total_in_seed"] == len(SAMPLE_HIGH_SCHOOLS)


async def test_seed_sample_idempotent(db) -> None:
    service = VnLocalityService(db)
    await service.seed_sample_high_schools()
    r2, _ = await service.seed_sample_high_schools()
    # Second run: all 5 already exist → 0 inserted
    assert r2["inserted"] == 0


# ---------------------------------------------------------------------------
# Search dropdown
# ---------------------------------------------------------------------------


async def test_search_high_school_prefix_match(db) -> None:
    """CR-M3 fix: prefix ilike (not substring). Candidate types from
    the start of the school name (canonical form 'THPT <name>'). Index-
    friendly + cleaner UX vs substring 'L' matching everything with L."""
    service = VnLocalityService(db)
    await service.seed_sample_high_schools()
    # Realistic flow: candidate types "THPT Lê" → dropdown filters
    results = await service.search_high_schools("thpt lê", limit=10)
    assert len(results) >= 1
    assert any("Lê Quý Đôn" in r.name for r in results)


async def test_search_high_school_prefix_does_not_match_midname(db) -> None:
    """Lock the prefix-vs-substring change: 'Lê' alone (without THPT
    prefix) should NOT match — old substring behavior would have."""
    service = VnLocalityService(db)
    await service.seed_sample_high_schools()
    results = await service.search_high_schools("Lê Quý", limit=10)
    # All seeded names start with "THPT", so "Lê Quý" prefix matches zero
    assert results == []


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


async def test_high_school_csv_missing_header_column_raises_validation(db) -> None:
    """F.5 fix: same upfront-header-check for HS import."""
    from app.utils.exceptions import ValidationError as DomainValidationError

    # Header missing 'name' (required) — kv_code/district/ward are optional
    bad_csv = b"province,district,ward,kv_code\nHa Noi,Ha Dong,Phuong 1,KV3\n"
    service = VnLocalityService(db)
    with pytest.raises(DomainValidationError, match="name"):
        await service.import_high_school_csv(bad_csv)


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


async def test_search_respects_is_active(db) -> None:
    """Soft-deleted rows (is_active=false) must NOT appear in search."""
    service = VnLocalityService(db)
    await service.seed_sample_high_schools()
    # Soft-delete one row
    from sqlalchemy import update

    from app.models.vn_locality import VnHighSchool

    await db.execute(
        update(VnHighSchool)
        .where(VnHighSchool.name == "THPT Lê Quý Đôn")
        .values(is_active=False)
    )
    await db.flush()
    results = await service.search_high_schools("Lê Quý Đôn", limit=10)
    assert not any(r.name == "THPT Lê Quý Đôn" for r in results)


# ---------------------------------------------------------------------------
# Commune lookup (PR5 special-case KV resolution)
# ---------------------------------------------------------------------------


async def test_lookup_commune_kv_returns_area_code(db) -> None:
    csv = b"commune_code,province,district,ward,area_code\nC001,DL,BMT,W1,KV1\n"
    service = VnLocalityService(db)
    await service.import_commune_csv(csv)
    kv = await service.lookup_commune_kv("C001")
    assert kv == "KV1"


async def test_lookup_commune_kv_missing_returns_none(db) -> None:
    service = VnLocalityService(db)
    kv = await service.lookup_commune_kv("NONEXISTENT")
    assert kv is None
