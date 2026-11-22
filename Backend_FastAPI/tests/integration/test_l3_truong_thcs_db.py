# tests/integration/test_l3_truong_thcs_db.py
"""L3 (owner 22-11, ``logs-P5/cong-bo-ket-qua/gd2/l3/QUYET-DINH-OWNER-L3-TRUONG-THCS-VAO-DANH-MUC-2026-11-22.md``) trên PostgreSQL THẬT:
Admin thêm trường cấp THCS + KV (nguồn ``manual_admin``) qua ĐÚNG dịch vụ của trang Admin (``VnSchoolService``) ⇒ hồ sơ trung cấp
sau THCS tính ra KV; trước đó "KV chờ xác minh". Cờ DTNT đọc từ ``vn_school.is_dtnt``. Mỗi bước so CẢ HAI đường: từng hồ sơ
(``resolve_kv_for_profile`` — ba hàm đọc thật) và lô (``decide_kv_for_profile`` trên ``read_school_kv`` / ``read_school_dtnt`` của bộ
nạp GĐ2-B, cùng giao dịch). Dữ liệu giả, rollback cuối mỗi ca."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.database import AsyncSessionLocal
from app.repositories import admission_review_load_repository as load_repo
from app.services import priority_service as ps
from app.services.vn_school_service import VnSchoolService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TL, AT = "trung_cap", "chinh_quy"


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


def _truong(ma: str, **kw) -> dict:
    return {
        "moet_school_code": ma,
        "moet_province_code": "99",
        "name": "Trường THCS giả " + ma,
        "province": "Tỉnh giả",
        "level": "THCS",
        "is_dtnt": kw.get("is_dtnt", False),
    }


def _ho_so(lich_su):
    return SimpleNamespace(id=1, academic_year=2026, cultural_education_level="graduated_thcs", vocational_qualification="none",
                           area_resolution_basis=None, permanent_commune_code=None, academic_history=lich_su,
                           priority_resolution_snapshot=None)


def _dong(sid, tu=2018, den=2022):
    return {"level": None if sid is None else "THCS", "graduation_type": "THCS", "school_id": sid,
            "school_name": "Trường THCS giả", "year_from": tu, "year_to": den}


async def _hai_duong(db, hs):
    tung = await ps.resolve_kv_for_profile(hs, db, target_level=TL, admission_type=AT)
    conn = await db.connection()
    _xa_k, truong_k = ps.kv_lookup_keys(hs, target_level=TL, admission_type=AT)
    lo = ps.decide_kv_for_profile(
        hs,
        commune_kv={},
        school_kv=await load_repo.read_school_kv(conn, truong_k),
        school_dtnt=await load_repo.read_school_dtnt(conn, ps.kv_school_dtnt_keys(hs, target_level=TL, admission_type=AT)),
        target_level=TL,
        admission_type=AT,
    )
    assert lo == tung, (lo, tung)
    return tung


async def test_admin_them_truong_thcs_va_kv_thi_ho_so_tinh_ra_kv(db):
    s = VnSchoolService(db)
    # Dòng gõ tay ⇒ chờ xác minh "chưa có trong danh mục".
    kv, meta = await _hai_duong(db, _ho_so([_dong(None)]))
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "kv_pending_verification", "thcs_school_not_in_catalog")
    # Admin thêm trường cấp THCS (chưa có KV) và cán bộ chọn lại trường ⇒ vẫn chờ: trường chưa có KV.
    truong, _ = await s.create_school(_truong("GTHCS1"))
    await db.flush()
    hs = _ho_so([_dong(truong.id)])
    kv, meta = await _hai_duong(db, hs)
    assert (kv, meta["reason"]) == (None, "thcs_school_kv_missing")
    # Admin thêm KV của trường = KV xã hiện tại, từ năm 2000, nguồn ``manual_admin`` ⇒ tính ra KV.
    await s.add_kv_assignment(truong.id, {"kv_code": "KV2-NT", "effective_from_year": 2000, "effective_to_year": None,
                                          "source": "manual_admin", "notes": None})
    await db.flush()
    kv, meta = await _hai_duong(db, hs)
    assert (kv, meta["rule_applied"], meta["basis"]) == ("KV2-NT", "longest_duration", "LICH_SU_THCS")


async def test_kv_truong_bat_dau_sau_nam_lop_6_thi_cho_xac_minh(db):
    s = VnSchoolService(db)
    truong, _ = await s.create_school(_truong("GTHCS2"))
    await db.flush()
    await s.add_kv_assignment(truong.id, {"kv_code": "KV1", "effective_from_year": 2020, "effective_to_year": None,
                                          "source": "manual_admin", "notes": None})
    await db.flush()
    kv, meta = await _hai_duong(db, _ho_so([_dong(truong.id)]))
    assert (kv, meta["rule_applied"], meta["reason"]) == (None, "kv_pending_verification", "thcs_school_kv_missing")
    assert [m["year"] for m in meta["breakdown"]["missing_lookups"]] == [2018, 2019]


async def test_truong_thcs_dtnt_thi_cho_xac_minh(db):
    s = VnSchoolService(db)
    truong, _ = await s.create_school(_truong("GTHCS3", is_dtnt=True))
    await db.flush()
    await s.add_kv_assignment(truong.id, {"kv_code": "KV1", "effective_from_year": 2000, "effective_to_year": None,
                                          "source": "manual_admin", "notes": None})
    await db.flush()
    kv, meta = await _hai_duong(db, _ho_so([_dong(truong.id)]))
    assert (kv, meta["reason"], meta["breakdown"]["dtnt_school_ids"]) == (None, "thcs_school_dtnt", [truong.id])
