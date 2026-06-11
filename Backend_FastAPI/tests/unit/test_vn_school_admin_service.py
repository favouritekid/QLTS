"""Unit tests for VnSchoolService admin CRUD + KV assignment (PR-B).

Mirror commune admin test: real ``db`` fixture, rollback teardown. Trọng tâm:
DELETE=deactivate giữ KV assignment (KHÔNG hard-delete), overlap năm check ở
service, CSV import idempotent.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.vn_school import VnSchool, VnSchoolKvAssignment
from app.services.vn_school_service import VnSchoolService
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


def _school(code: str = "S001", prov: str = "048", **kw) -> dict:
    return {
        "moet_school_code": code,
        "moet_province_code": prov,
        "name": kw.get("name", f"Trường {code}"),
        "province": kw.get("province", "Tỉnh Lâm Đồng"),
        "level": kw.get("level", "THPT"),
        "is_dtnt": kw.get("is_dtnt", False),
    }


def _kv(from_year: int, to_year=None, kv: str = "KV1") -> dict:
    return {
        "kv_code": kv,
        "effective_from_year": from_year,
        "effective_to_year": to_year,
        "source": "manual_admin",
    }


# --- school CRUD ---


async def test_create_and_duplicate(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S001"))
    await db.flush()
    assert school.id is not None
    assert school.is_active is True
    with pytest.raises(DuplicateResourceError):
        await s.create_school(_school("S001"))


async def test_update_keeps_identity_and_active(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S010", name="Cũ"))
    await db.flush()
    updated, _ = await s.update_school(
        school.id,
        {"name": "Mới", "moet_school_code": "HACK", "is_active": False},
    )
    await db.flush()
    assert updated.name == "Mới"
    assert updated.moet_school_code == "S010"  # KHÔNG đổi định danh
    assert updated.is_active is True  # KHÔNG deactivate qua PATCH


async def test_deactivate_keeps_kv_no_hard_delete(db) -> None:
    """Acceptance plan: DELETE=deactivate giữ KV assignment, KHÔNG hard-delete."""
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S020"))
    await db.flush()
    await s.add_kv_assignment(school.id, _kv(2025))
    await db.flush()
    await s.deactivate_school(school.id)
    await db.flush()

    still = await db.get(VnSchool, school.id)
    assert still is not None and still.is_active is False  # soft-delete
    kvs = (
        await db.execute(
            select(VnSchoolKvAssignment).where(
                VnSchoolKvAssignment.school_id == school.id
            )
        )
    ).scalars().all()
    assert len(kvs) == 1  # assignment KHÔNG bị CASCADE xoá


async def test_deactivate_double_blocks(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S021"))
    await db.flush()
    await s.deactivate_school(school.id)
    await db.flush()
    with pytest.raises(BusinessRuleViolation):
        await s.deactivate_school(school.id)


async def test_update_missing_raises(db) -> None:
    s = VnSchoolService(db)
    with pytest.raises(ResourceNotFoundError):
        await s.update_school(999999, {"name": "X"})


# --- KV assignment ---


async def test_add_kv_overlap_blocked(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S030"))
    await db.flush()
    await s.add_kv_assignment(school.id, _kv(2020, 2025, "KV1"))
    await db.flush()
    with pytest.raises(BusinessRuleViolation):
        await s.add_kv_assignment(school.id, _kv(2024, None, "KV2"))


async def test_add_kv_bad_year_range(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S031"))
    await db.flush()
    with pytest.raises(BusinessRuleViolation):
        await s.add_kv_assignment(school.id, _kv(2025, 2020, "KV1"))


async def test_add_kv_nonoverlap_ok_and_current_kv(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S032"))
    await db.flush()
    await s.add_kv_assignment(school.id, _kv(2020, 2023, "KV1"))
    await s.add_kv_assignment(school.id, _kv(2024, None, "KV2"))
    await db.flush()
    assert await s.current_kv(school.id) == "KV2"  # active mới nhất
    kvs = await s.list_kv_assignments(school.id)
    assert [k.kv_code for k in kvs] == ["KV1", "KV2"]  # order by from_year


async def test_update_kv_overlap_excludes_self(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S033"))
    await db.flush()
    await s.add_kv_assignment(school.id, _kv(2020, 2022, "KV1"))
    b, _ = await s.add_kv_assignment(school.id, _kv(2023, 2025, "KV2"))
    await db.flush()
    # Đổi b chồng a → block (validate-before-mutate: b KHÔNG hỏng).
    with pytest.raises(BusinessRuleViolation):
        await s.update_kv_assignment(b.id, {"effective_from_year": 2021})
    # Đổi kv_code (không chồng) → OK (không tự coi mình overlap).
    upd, _ = await s.update_kv_assignment(b.id, {"kv_code": "KV3"})
    await db.flush()
    assert upd.kv_code == "KV3"
    assert upd.effective_from_year == 2023  # lần update lỗi KHÔNG để lại mutate


async def test_delete_kv_assignment(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S034"))
    await db.flush()
    a, _ = await s.add_kv_assignment(school.id, _kv(2025))
    await db.flush()
    await s.delete_kv_assignment(a.id)
    await db.flush()
    assert await db.get(VnSchoolKvAssignment, a.id) is None


async def test_add_kv_missing_school_raises(db) -> None:
    s = VnSchoolService(db)
    with pytest.raises(ResourceNotFoundError):
        await s.add_kv_assignment(999999, _kv(2025))


# --- list + CSV ---


async def test_list_schools_filter_pagination(db) -> None:
    s = VnSchoolService(db)
    for i in range(4):
        await s.create_school(_school(f"S04{i}", prov="048", level="THPT"))
    await s.create_school(_school("S060", prov="040", level="THCS"))
    await db.flush()
    items, total = await s.list_schools(
        moet_province_code="048", page=1, page_size=2
    )
    assert total == 4 and len(items) == 2
    _items2, total2 = await s.list_schools(level="THCS")
    assert total2 == 1


async def test_import_csv_idempotent_and_invalid_level(db) -> None:
    s = VnSchoolService(db)
    csv_bytes = (
        b"moet_school_code,moet_province_code,name,province,level\n"
        b"S100,048,Truong A,Tinh X,THPT\n"
        b"S101,048,Truong B,Tinh X,BADLEVEL\n"
    )
    result, _ = await s.import_schools_csv(csv_bytes)
    await db.flush()
    assert result["inserted"] == 1  # S100 ok; S101 bad level → error
    assert result["skipped_existing"] == 0
    assert len(result["error_rows"]) == 1
    # Chạy lại → S100 skip (idempotent).
    result2, _ = await s.import_schools_csv(csv_bytes)
    await db.flush()
    assert result2["inserted"] == 0 and result2["skipped_existing"] == 1


async def test_current_kv_none_when_no_active_assignment(db) -> None:
    """current_kv = None nếu mọi assignment đã đóng (effective_to_year != NULL)."""
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S050"))
    await db.flush()
    assert await s.current_kv(school.id) is None  # chưa có assignment
    await s.add_kv_assignment(school.id, _kv(2020, 2023, "KV1"))  # đã đóng
    await db.flush()
    assert await s.current_kv(school.id) is None  # không có dòng to=NULL


async def test_list_active_only_false_includes_deactivated(db) -> None:
    s = VnSchoolService(db)
    school, _ = await s.create_school(_school("S055"))
    await db.flush()
    await s.deactivate_school(school.id)
    await db.flush()
    _a, total_active = await s.list_schools(active_only=True, q=None)
    assert total_active == 0  # active_only ẩn trường đã ngừng
    items_all, total_all = await s.list_schools(active_only=False)
    assert total_all == 1
    assert items_all[0]["is_active"] is False


async def test_import_csv_dedup_same_file(db) -> None:
    """2 dòng cùng (code, prov) trong 1 file → chỉ insert 1, skip 1 (không
    IntegrityError nhờ in-memory dedup)."""
    s = VnSchoolService(db)
    csv_bytes = (
        b"moet_school_code,moet_province_code,name,province,level\n"
        b"S200,048,Truong A,Tinh X,THPT\n"
        b"S200,048,Truong A bis,Tinh X,THPT\n"
    )
    result, _ = await s.import_schools_csv(csv_bytes)
    await db.flush()
    assert result["inserted"] == 1
    assert result["skipped_existing"] == 1
    assert len(result["error_rows"]) == 0
