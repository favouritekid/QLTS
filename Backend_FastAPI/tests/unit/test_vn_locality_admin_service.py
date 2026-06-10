"""Unit tests for VnLocalityService commune KV admin CRUD (PR-A).

Mirror ``test_priority_config_service.py``: real test DB session (``db``
fixture) → CHECK constraint ``ck_vn_commune_area_map_area_code_format``
fires; temporal half-open + service-level active guard.

Lưu ý: qlts_test dùng ``create_all()`` (memory ``test-db-schema-source``) →
partial-unique ``uq_vn_commune_area_map_code_active`` (định nghĩa ở migration,
KHÔNG trong model ``__table_args__``) KHÔNG được tạo. Vì vậy dedup dựa vào
service-level ``_active_commune`` (không phải DB constraint) — đúng contract
prod (index chỉ là defense-in-depth).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.services.vn_locality_service import VnLocalityService
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
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


def _commune(code: str, area: str = "KV3", **kw) -> dict:
    return {
        "commune_code": code,
        "province": kw.get("province", "Tỉnh Lâm Đồng"),
        "district": kw.get("district", ""),
        "ward": kw.get("ward", f"Xã {code}"),
        "area_code": area,
    }


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


async def test_create_persists_with_server_default_effective_from(db) -> None:
    service = VnLocalityService(db)
    row, _cb = await service.create_commune(_commune("00001", "KV1"))
    await db.flush()
    assert row.id is not None
    assert row.commune_code == "00001"
    assert row.area_code == "KV1"
    assert row.effective_from is not None  # server_default CURRENT_DATE
    assert row.effective_to is None  # active


async def test_create_duplicate_active_raises(db) -> None:
    service = VnLocalityService(db)
    await service.create_commune(_commune("00002", "KV1"))
    with pytest.raises(DuplicateResourceError):
        await service.create_commune(_commune("00002", "KV2"))


async def test_create_rejects_invalid_area_code_via_db_check(db) -> None:
    """CHECK regex chặn 'KV2_NT' (underscore) — chỉ 'KV2-NT' (hyphen)."""
    service = VnLocalityService(db)
    with pytest.raises(IntegrityError):
        await service.create_commune(_commune("00003", "KV2_NT"))
        await db.flush()


# ---------------------------------------------------------------------------
# update (PATCH metadata) — KHÔNG đổi area_code
# ---------------------------------------------------------------------------


async def test_update_patches_metadata_only_keeps_area_code(db) -> None:
    service = VnLocalityService(db)
    row, _ = await service.create_commune(_commune("00010", "KV3", ward="Xã Cũ"))
    await db.flush()
    # Gửi kèm area_code + commune_code — service PHẢI bỏ qua 2 field này.
    updated, _ = await service.update_commune(
        row.id,
        {"ward": "Xã Mới", "area_code": "KV1", "commune_code": "HACK"},
    )
    await db.flush()
    assert updated.ward == "Xã Mới"
    assert updated.area_code == "KV3"  # KHÔNG đổi qua PATCH
    assert updated.commune_code == "00010"  # KHÔNG đổi


async def test_update_missing_raises_not_found(db) -> None:
    service = VnLocalityService(db)
    with pytest.raises(ResourceNotFoundError):
        await service.update_commune(999999, {"ward": "X"})


# ---------------------------------------------------------------------------
# replace_commune_area — temporal: retire cũ + insert mới
# ---------------------------------------------------------------------------


async def test_replace_area_creates_new_row_retires_old(db) -> None:
    service = VnLocalityService(db)
    old, _ = await service.create_commune(_commune("00020", "KV3"))
    await db.flush()
    old_id = old.id

    new_row, _ = await service.replace_commune_area(old_id, "KV1")
    await db.flush()

    # Dòng cũ bị đóng (effective_to set), dòng mới active với KV mới.
    refreshed_old = await db.get(type(old), old_id)
    assert refreshed_old.effective_to is not None
    assert new_row.id != old_id
    assert new_row.area_code == "KV1"
    assert new_row.effective_to is None
    assert new_row.commune_code == "00020"
    # lookup hiện tại trả area_code MỚI.
    assert await service.lookup_commune_kv("00020") == "KV1"


async def test_replace_area_on_retired_row_raises(db) -> None:
    service = VnLocalityService(db)
    row, _ = await service.create_commune(_commune("00021", "KV3"))
    await db.flush()
    await service.retire_commune(row.id)
    await db.flush()
    with pytest.raises(BusinessRuleViolation):
        await service.replace_commune_area(row.id, "KV1")


async def test_replace_area_missing_raises_not_found(db) -> None:
    service = VnLocalityService(db)
    with pytest.raises(ResourceNotFoundError):
        await service.replace_commune_area(999999, "KV1")


# ---------------------------------------------------------------------------
# retire — soft-close + chặn double-retire
# ---------------------------------------------------------------------------


async def test_retire_sets_effective_to(db) -> None:
    service = VnLocalityService(db)
    row, _ = await service.create_commune(_commune("00030", "KV2"))
    await db.flush()
    retired, _ = await service.retire_commune(row.id)
    await db.flush()
    assert retired.effective_to is not None
    # KHÔNG còn active → lookup trả None.
    assert await service.lookup_commune_kv("00030") is None


async def test_retire_double_blocks(db) -> None:
    service = VnLocalityService(db)
    row, _ = await service.create_commune(_commune("00031", "KV2"))
    await db.flush()
    await service.retire_commune(row.id)
    await db.flush()
    with pytest.raises(BusinessRuleViolation):
        await service.retire_commune(row.id)


# ---------------------------------------------------------------------------
# re-activate (effective_to=None) — chặn nếu đã có dòng active khác
# ---------------------------------------------------------------------------


async def test_reactivate_blocked_when_other_active_exists(db) -> None:
    service = VnLocalityService(db)
    old, _ = await service.create_commune(_commune("00040", "KV3"))
    await db.flush()
    # replace → old retired, new active cho cùng commune_code.
    await service.replace_commune_area(old.id, "KV1")
    await db.flush()
    # Re-activate old (effective_to=None) phải bị chặn (đã có new active).
    with pytest.raises(BusinessRuleViolation):
        await service.update_commune(old.id, {"effective_to": None})


# ---------------------------------------------------------------------------
# list_communes — pagination + filter
# ---------------------------------------------------------------------------


async def test_list_pagination_and_province_filter(db) -> None:
    service = VnLocalityService(db)
    for i in range(5):
        await service.create_commune(
            _commune(f"0005{i}", "KV3", province="Tỉnh Lâm Đồng", ward=f"Xã {i}")
        )
    await service.create_commune(
        _commune("00060", "KV2", province="Tỉnh Gia Lai", ward="Xã Khác")
    )
    await db.flush()

    # Lọc tỉnh Lâm Đồng → 5 dòng; page_size=2 → 2 items, total=5.
    items, total = await service.list_communes(
        province="Tỉnh Lâm Đồng", page=1, page_size=2
    )
    assert total == 5
    assert len(items) == 2

    # Search theo ward.
    items2, total2 = await service.list_communes(q="Xã Khác")
    assert total2 == 1
    assert items2[0].commune_code == "00060"
