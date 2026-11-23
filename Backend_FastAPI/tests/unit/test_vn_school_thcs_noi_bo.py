# -*- coding: utf-8 -*-
"""Danh mục THCS đúng chuẩn (owner 22-11, đề xuất Phần A) — phần chạy trên CSDL thật.

Bốn bất biến, mỗi bất biến có ca riêng (CLAUDE.md chung §3 — một ca chỉ vi phạm MỘT bất biến):

1. **Mã nội bộ** — trường THCS / liên cấp bỏ trống mã ⇒ máy sinh ``NB`` + 6 số từ sequence, không trùng; mã ``NB…``
   không nhập tay; cấp THCS không có mã Bộ.
2. **Bộ nạp danh mục Bộ không bao giờ khớp / sửa / xoá trường ``NB…``** — CSV Admin, ``import_moet_schools_3_provinces``
   (tra + ghi), ``rebuild_school_kv_from_xls`` (xoá cứng theo vùng), ``dedup_temporal_split`` (gom cặp).
3. **Mã xã** — trường nội bộ bắt buộc mã xã còn hiệu lực trong bảng xã → KV.
4. **KV chép từ xã + câu kiểm lệch** — KV do máy chủ chép (nguồn ``xa_hien_hanh``, dành riêng); câu kiểm đếm trường
   có KV ``xa_hien_hanh`` khác KV hiện hành của xã.

Phần không cần CSDL: ``test_vn_school_thcs_noi_bo_ddl.py``.
"""
from __future__ import annotations

import re
from collections import Counter

import pytest
import pytest_asyncio
from sqlalchemy import delete, literal, select, text, update

from app.database import AsyncSessionLocal
from app.models.vn_locality import VnCommuneAreaMap
from app.models.vn_school import VnSchool, VnSchoolKvAssignment
from app.models.vn_school_internal_code import (
    KV_COMMUNE_EFFECTIVE_FROM_YEAR,
    KV_SOURCE_COMMUNE_CURRENT,
    internal_code_sql,
    is_internal_school_code,
)
from app.scripts.dedup_temporal_split import detect_clusters
from app.scripts.import_moet_schools_3_provinces import (
    find_existing_moet_school,
    upsert_one,
)
from app.scripts.rebuild_school_kv_from_xls import (
    ProtectedRegionSchools,
    guard_no_protected_region_schools,
    protected_region_filter,
    protected_rows_in_dump,
    region_school_filter,
)
from app.services.vn_locality_service import VnLocalityService
from app.services.vn_school_service import VnSchoolService
from app.utils.exceptions import BusinessRuleViolation
from app.utils.exceptions import ValidationError as DomainValidationError

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

MA_NB = re.compile(r"^NB[0-9]{6}$")


@pytest_asyncio.fixture
async def db(setup_test_database):
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()


async def _xa(db, ma="99001", kv="KV1", ward="Xã Thử Một", province="Tỉnh Thử") -> VnCommuneAreaMap:
    row = VnCommuneAreaMap(commune_code=ma, province=province, district="", ward=ward, area_code=kv)
    db.add(row)
    await db.flush()
    return row


def _thcs(**kw) -> dict:
    d = {
        "moet_province_code": kw.pop("prov", "048"),
        "name": kw.pop("name", "THCS Thử"),
        "province": kw.pop("province", "Tỉnh Thử"),
        "level": kw.pop("level", "THCS"),
        "commune_code": kw.pop("commune_code", "99001"),
        "is_dtnt": kw.pop("is_dtnt", False),
    }
    d.update(kw)
    return d


async def _truong_noi_bo(db, **kw) -> VnSchool:
    school, _ = await VnSchoolService(db).create_school(_thcs(**kw))
    await db.flush()
    return school


# =====================================================================================================================
# 1. Mã nội bộ
# =====================================================================================================================


async def test_thcs_bo_trong_ma_thi_may_sinh_NB_sau_so_khong_trung(db) -> None:
    await _xa(db)
    a = await _truong_noi_bo(db, name="THCS A")
    b = await _truong_noi_bo(db, name="THCS B")
    assert MA_NB.match(a.moet_school_code), a.moet_school_code
    assert MA_NB.match(b.moet_school_code), b.moet_school_code
    assert a.moet_school_code != b.moet_school_code
    assert a.commune_code == "99001"


async def test_lien_cap_bo_trong_ma_cung_duoc_ma_noi_bo(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db, level="THCS_THPT")
    assert MA_NB.match(s.moet_school_code)


async def test_lien_cap_go_ma_bo_thi_giu_ma_bo_khong_bat_buoc_xa(db) -> None:
    s, _ = await VnSchoolService(db).create_school(
        _thcs(level="THCS_THPT", moet_school_code="040777", commune_code=None)
    )
    await db.flush()
    assert s.moet_school_code == "040777"
    assert s.commune_code is None


async def test_cap_thcs_go_ma_thi_tu_choi(db) -> None:
    await _xa(db)
    with pytest.raises(DomainValidationError, match="không có mã của Bộ"):
        await VnSchoolService(db).create_school(_thcs(moet_school_code="040123"))


@pytest.mark.parametrize("ma", ["NB000001", "nb000001", " NB123456 "])
async def test_go_tay_ma_NB_thi_tu_choi_moi_cap(db, ma) -> None:
    with pytest.raises(DomainValidationError, match="mã nội bộ do máy tự sinh"):
        await VnSchoolService(db).create_school(
            {"moet_school_code": ma, "moet_province_code": "048", "name": "X", "province": "P", "level": "THPT"}
        )


async def test_cap_thpt_bo_trong_ma_thi_tu_choi(db) -> None:
    with pytest.raises(DomainValidationError, match="phải có mã trường của Bộ"):
        await VnSchoolService(db).create_school(
            {"moet_province_code": "048", "name": "THPT X", "province": "P", "level": "THPT"}
        )


async def test_csdl_chan_ma_NB_sai_khuon_hoac_thieu_xa_khi_ghi_thang(db) -> None:
    """Lớp phòng thủ thêm (CHECK) — đường ghi KHÔNG qua service."""
    from sqlalchemy.exc import IntegrityError

    db.add(VnSchool(moet_school_code="NB000001", moet_province_code="048", name="X", province="P", level="THCS"))
    with pytest.raises(IntegrityError, match="ck_vn_school_internal_code_format"):
        await db.flush()


# =====================================================================================================================
# 3. Mã xã bắt buộc, phải còn hiệu lực
# =====================================================================================================================


async def test_noi_bo_thieu_ma_xa_thi_tu_choi(db) -> None:
    with pytest.raises(DomainValidationError, match="bắt buộc chọn xã"):
        await VnSchoolService(db).create_school(_thcs(commune_code=None))


async def test_noi_bo_ma_xa_khong_co_trong_bang_thi_tu_choi(db) -> None:
    await _xa(db, ma="99001")
    with pytest.raises(DomainValidationError, match="không có trong bảng xã"):
        await VnSchoolService(db).create_school(_thcs(commune_code="99999"))


async def test_noi_bo_ma_xa_da_het_hieu_luc_thi_tu_choi(db) -> None:
    xa = await _xa(db, ma="99002")
    await VnLocalityService(db).retire_commune(xa.id)
    await db.flush()
    with pytest.raises(DomainValidationError, match="không có trong bảng xã"):
        await VnSchoolService(db).create_school(_thcs(commune_code="99002"))


async def test_sua_noi_bo_khong_xoa_trong_ma_xa_va_khong_doi_sang_cap_thpt(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    with pytest.raises(DomainValidationError, match="bắt buộc chọn xã"):
        await svc.update_school(s.id, {"commune_code": None})
    with pytest.raises(DomainValidationError, match="chỉ ở cấp THCS"):
        await svc.update_school(s.id, {"level": "THPT"})
    await db.refresh(s)
    assert s.commune_code == "99001" and s.level == "THCS"


async def test_sua_noi_bo_doi_xa_hop_le_thi_duoc_xa_sai_thi_khong_doi_gi(db) -> None:
    await _xa(db, ma="99001")
    await _xa(db, ma="99003", kv="KV2")
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    with pytest.raises(DomainValidationError):
        await svc.update_school(s.id, {"commune_code": "88888", "name": "Tên mới"})
    assert s.name == "THCS Thử"  # kiểm trước, gán sau: không dở dang
    upd, _ = await svc.update_school(s.id, {"commune_code": "99003"})
    assert upd.commune_code == "99003"


async def test_truong_ma_bo_khong_chuyen_sang_cap_thcs(db) -> None:
    s, _ = await VnSchoolService(db).create_school(
        {"moet_school_code": "040555", "moet_province_code": "048", "name": "THPT Y", "province": "P", "level": "THPT"}
    )
    await db.flush()
    with pytest.raises(DomainValidationError, match="không chuyển sang cấp THCS"):
        await VnSchoolService(db).update_school(s.id, {"level": "THCS"})
    upd, _ = await VnSchoolService(db).update_school(s.id, {"level": "THCS_THPT"})
    assert upd.level == "THCS_THPT"  # liên cấp có mã Bộ: được


# =====================================================================================================================
# 2. Bộ nạp danh mục Bộ không bao giờ khớp / sửa / xoá trường NB…
# =====================================================================================================================


async def test_vi_tu_sql_va_python_cho_cung_ket_qua(db) -> None:
    """Một nguồn: ``internal_code_sql`` (SQL) == ``is_internal_school_code`` (Python)."""
    for ma in ("NB000001", "nb000001", " NB12", "Nb", "040123", "N B1", "XNB1", ""):
        sql = (await db.execute(select(internal_code_sql(literal(ma))))).scalar_one()
        assert bool(sql) is is_internal_school_code(ma), ma


async def test_csv_dong_ma_NB_bi_tu_choi_va_truong_noi_bo_khong_bi_cham(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db, name="THCS Gốc")
    csv_bytes = (
        "moet_school_code,moet_province_code,name,province,level\n"
        f"{s.moet_school_code},048,Ten De,Tinh X,THCS_THPT\n"
    ).encode("utf-8")
    kq, _ = await VnSchoolService(db).import_schools_csv(csv_bytes)
    await db.flush()
    assert kq["inserted"] == 0
    assert kq["skipped_existing"] == 0  # KHÔNG được coi là "đã có" ⇒ không khớp
    assert len(kq["error_rows"]) == 1 and "mã nội bộ" in kq["error_rows"][0]["error"]
    await db.refresh(s)
    assert s.name == "THCS Gốc" and s.level == "THCS"


async def test_csv_dong_cap_thcs_bi_tu_choi(db) -> None:
    csv_bytes = (
        b"moet_school_code,moet_province_code,name,province,level\n"
        b"777,048,THCS X,Tinh X,THCS\n"
    )
    kq, _ = await VnSchoolService(db).import_schools_csv(csv_bytes)
    assert kq["inserted"] == 0 and len(kq["error_rows"]) == 1
    assert "cấp THCS" in kq["error_rows"][0]["error"]


async def test_nap_moet_tra_truong_co_san_khong_bao_gio_tra_truong_NB(db) -> None:
    """Lớp lọc ở CÂU TRA (``find_existing_moet_school``) — mã nguồn trùng y mã nội bộ vẫn không khớp."""
    await _xa(db)
    s = await _truong_noi_bo(db)
    assert await find_existing_moet_school(db, s.moet_province_code, s.moet_school_code) is None


async def test_nap_moet_dong_ma_NB_bo_qua_khong_ghi_gi(db) -> None:
    """Lớp ở ĐƯỜNG GHI (``upsert_one``): dòng mang mã NB… không sửa trường nội bộ, không tạo trường mới."""
    await _xa(db)
    s = await _truong_noi_bo(db, name="THCS Gốc")
    truoc = (await db.execute(select(VnSchool.id))).scalars().all()
    thong_ke: Counter = Counter()
    row = {
        "moet_province_code": s.moet_province_code,
        "moet_district_code": None,
        "moet_school_code": s.moet_school_code,
        "name": "THPT Đè",
        "address": None,
        "province": "Đắk Lắk",
        "district": None,
        "level": "THPT",
        "is_dtnt": False,
        "kv_code": "KV3",
        "is_special": False,
    }
    assert await upsert_one(db, row, thong_ke) == (None, False)
    await db.flush()
    assert thong_ke["skipped_internal_code"] == 1
    await db.refresh(s)
    assert (s.name, s.level, s.province) == ("THCS Gốc", "THCS", "Tỉnh Thử")
    assert (await db.execute(select(VnSchool.id))).scalars().all() == truoc
    kv = (await db.execute(select(VnSchoolKvAssignment).where(VnSchoolKvAssignment.school_id == s.id))).scalars().all()
    assert kv == []


async def test_nap_lai_xls_xoa_cung_theo_vung_khong_xoa_truong_NB(db) -> None:
    await _xa(db)
    moet, _ = await VnSchoolService(db).create_school(
        {"moet_school_code": "002", "moet_province_code": "040", "name": "THPT Cũ", "province": "Đắk Lắk",
         "level": "THPT"}
    )
    nb = await _truong_noi_bo(db, province="Đắk Lắk")
    await db.flush()
    await db.execute(delete(VnSchool).where(*region_school_filter(["Đắk Lắk"])))
    await db.flush()
    con = set((await db.execute(select(VnSchool.id).where(VnSchool.province == "Đắk Lắk"))).scalars().all())
    assert con == {nb.id}, "trường nội bộ phải còn, trường Bộ cũ phải bị xoá"
    assert moet.id not in con


async def test_gom_cap_trung_ten_khong_gom_truong_NB(db) -> None:
    """``dedup_temporal_split.detect_clusters`` gom theo (mã tỉnh, tên) cấp THPT — trường NB… (ghi thẳng, bỏ qua luật
    cấp của service) không bao giờ vào cụm (``int(moet_school_code)`` sẽ vỡ, và nó không thuộc danh mục Bộ)."""
    await _xa(db)
    db.add(VnSchool(moet_school_code="010", moet_province_code="040", name="THPT Trùng", province="Đắk Lắk",
                    level="THPT"))
    db.add(VnSchool(moet_school_code="NB999990", moet_province_code="040", name="THPT Trùng", province="Đắk Lắk",
                    level="THPT", commune_code="99001"))
    await db.flush()
    cum = await detect_clusters(db)
    assert all(not any(is_internal_school_code(x.moet_school_code) for x in c) for c in cum)


# =====================================================================================================================
# 4. KV gợi ý từ xã + nguồn dành riêng + câu kiểm lệch
# =====================================================================================================================


async def test_kv_goi_y_bang_kv_hien_hanh_cua_xa(db) -> None:
    await _xa(db, kv="KV2-NT", ward="Xã Gợi Ý")
    s = await _truong_noi_bo(db)
    g = await VnSchoolService(db).suggest_kv_from_commune(s.id)
    assert g["suggested_kv"] == "KV2-NT" and g["reason"] is None
    assert g["commune_ward"] == "Xã Gợi Ý" and g["is_internal_code"] is True


async def test_kv_goi_y_xa_het_hieu_luc_thi_khong_goi_y(db) -> None:
    xa = await _xa(db)
    s = await _truong_noi_bo(db)
    await VnLocalityService(db).retire_commune(xa.id)
    await db.flush()
    g = await VnSchoolService(db).suggest_kv_from_commune(s.id)
    assert g["suggested_kv"] is None and g["reason"] == "commune_not_active"


async def test_kv_goi_y_truong_ma_bo_thi_khong_goi_y(db) -> None:
    s, _ = await VnSchoolService(db).create_school(
        {"moet_school_code": "040556", "moet_province_code": "048", "name": "THPT Z", "province": "P", "level": "THPT"}
    )
    await db.flush()
    g = await VnSchoolService(db).suggest_kv_from_commune(s.id)
    assert g["suggested_kv"] is None and g["reason"] == "not_internal_school"


async def test_xac_nhan_kv_goi_y_chep_kv_cua_xa_tu_nam_2000_khong_nam_ket_thuc(db) -> None:
    """Owner 22-11 (L3-a câu 2): KV trường THCS "từ năm 2000, phủ mọi hồ sơ" — máy tự điền, Admin không nhập năm.
    Năm / KV client gửi kèm bị BỎ QUA."""
    await _xa(db, kv="KV1")
    s = await _truong_noi_bo(db)
    row, _ = await VnSchoolService(db).confirm_kv_from_commune(
        s.id, {"effective_from_year": 2024, "effective_to_year": 2025, "kv_code": "KV3"}
    )
    await db.flush()
    assert (row.kv_code, row.source, row.effective_from_year, row.effective_to_year) == (
        "KV1", KV_SOURCE_COMMUNE_CURRENT, 2000, None,
    )
    assert KV_COMMUNE_EFFECTIVE_FROM_YEAR == 2000
    assert "99001" in row.notes
    assert await VnSchoolService(db).current_kv(s.id) == "KV1"


async def test_xac_nhan_kv_goi_y_truong_ma_bo_bi_chan(db) -> None:
    await _xa(db)
    s, _ = await VnSchoolService(db).create_school(
        {"moet_school_code": "040557", "moet_province_code": "048", "name": "THPT W", "province": "P",
         "level": "THPT", "commune_code": "99001"}
    )
    await db.flush()
    with pytest.raises(BusinessRuleViolation, match="Chỉ trường mã nội bộ"):
        await VnSchoolService(db).confirm_kv_from_commune(s.id, {})


async def test_xac_nhan_kv_goi_y_lan_hai_chong_nam_bi_chan(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    await svc.confirm_kv_from_commune(s.id, {})
    await db.flush()
    with pytest.raises(BusinessRuleViolation, match="chồng lấn"):
        await svc.confirm_kv_from_commune(s.id, {})


async def test_nguon_xa_hien_hanh_khong_nhap_tay_qua_duong_chung(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db)
    with pytest.raises(DomainValidationError, match="xa_hien_hanh"):
        await VnSchoolService(db).add_kv_assignment(
            s.id, {"kv_code": "KV3", "effective_from_year": 2020, "source": "xa_hien_hanh"}
        )


async def test_dong_kv_chep_tu_xa_khong_sua_kv_bang_tay_chi_sua_nam(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    row, _ = await svc.confirm_kv_from_commune(s.id, {})
    await db.flush()
    with pytest.raises(BusinessRuleViolation, match="không sửa KV"):
        await svc.update_kv_assignment(row.id, {"kv_code": "KV3"})
    with pytest.raises(BusinessRuleViolation, match="không sửa KV"):
        await svc.update_kv_assignment(row.id, {"source": "manual_admin"})
    upd, _ = await svc.update_kv_assignment(row.id, {"effective_to_year": 2030})
    assert (upd.kv_code, upd.effective_to_year) == ("KV1", 2030)


async def test_dong_kv_tay_khong_doi_thanh_nguon_xa_hien_hanh(db) -> None:
    await _xa(db)
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    row, _ = await svc.add_kv_assignment(s.id, {"kv_code": "KV3", "effective_from_year": 2020, "source": "manual_admin"})
    await db.flush()
    with pytest.raises(DomainValidationError, match="xa_hien_hanh"):
        await svc.update_kv_assignment(row.id, {"source": "xa_hien_hanh"})


async def test_cau_kiem_lech_dem_1_khi_xa_doi_kv(db) -> None:
    xa = await _xa(db, kv="KV1")
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    await svc.confirm_kv_from_commune(s.id, {})
    await db.flush()
    kq = await svc.internal_kv_mismatch()
    assert (kq["mismatch_count"], kq["commune_inactive_count"]) == (0, 0)
    # Xã đổi KV (dòng cũ đóng, dòng mới mở) ⇒ trường chép KV cũ ⇒ LỆCH.
    await VnLocalityService(db).replace_commune_area(xa.id, "KV2")
    await db.flush()
    kq = await svc.internal_kv_mismatch()
    assert (kq["mismatch_count"], kq["commune_inactive_count"]) == (1, 0)
    assert kq["items"][0]["school_id"] == s.id
    assert (kq["items"][0]["school_kv"], kq["items"][0]["commune_kv"]) == ("KV1", "KV2")


async def test_cau_kiem_lech_xa_het_hieu_luc_dem_rieng(db) -> None:
    xa = await _xa(db, kv="KV1")
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    await svc.confirm_kv_from_commune(s.id, {})
    await VnLocalityService(db).retire_commune(xa.id)
    await db.flush()
    kq = await svc.internal_kv_mismatch()
    assert (kq["mismatch_count"], kq["commune_inactive_count"]) == (0, 1)


async def test_cau_kiem_lech_bo_qua_dong_kv_da_dong_va_dong_tay(db) -> None:
    """Chỉ dòng ``xa_hien_hanh`` ĐANG áp dụng (``effective_to_year`` trống) mới được so."""
    xa = await _xa(db, kv="KV1")
    s = await _truong_noi_bo(db)
    svc = VnSchoolService(db)
    row, _ = await svc.confirm_kv_from_commune(s.id, {})
    await svc.update_kv_assignment(row.id, {"effective_to_year": 2019})  # đóng dòng chép từ xã
    await svc.add_kv_assignment(s.id, {"kv_code": "KV3", "effective_from_year": 2020, "source": "manual_admin"})
    await VnLocalityService(db).replace_commune_area(xa.id, "KV2")
    await db.flush()
    kq = await svc.internal_kv_mismatch()
    assert (kq["mismatch_count"], kq["commune_inactive_count"]) == (0, 0)
    assert row.kv_code == "KV1"



# =====================================================================================================================
# 5. Bộ nạp danh mục Bộ KHÔNG hạ cấp liên cấp do Admin đặt (owner 22-11, QUYET-DINH-OWNER-THCS-CONG-CU-GHEP câu 3)
# =====================================================================================================================


async def _truong_bo_lien_cap(db, ma="002", prov="040", province="Đắk Lắk") -> VnSchool:
    """Trường của Bộ nạp ở cấp THPT, Admin sửa thành liên cấp (đúng đường owner chốt)."""
    svc = VnSchoolService(db)
    s, _ = await svc.create_school(
        {"moet_school_code": ma, "moet_province_code": prov, "name": "THCS-THPT Liên Cấp", "province": province,
         "level": "THPT"}
    )
    await db.flush()
    s, _ = await svc.update_school(s.id, {"level": "THCS_THPT"})
    await db.flush()
    return s


def _dong_moet(s: VnSchool, **kw) -> dict:
    d = {
        "moet_province_code": s.moet_province_code, "moet_district_code": None, "moet_school_code": s.moet_school_code,
        "name": "THPT Liên Cấp (tên Bộ mới)", "address": None, "province": s.province, "district": None,
        "level": "THPT", "is_dtnt": False, "kv_code": "KV1", "is_special": False,
    }
    d.update(kw)
    return d


async def test_nap_moet_cap_nhat_truong_co_san_khong_ha_lien_cap_ve_thpt(db) -> None:
    s = await _truong_bo_lien_cap(db)
    thong_ke: Counter = Counter()
    await upsert_one(db, _dong_moet(s), thong_ke)
    await db.flush()
    await db.refresh(s)
    assert s.name == "THPT Liên Cấp (tên Bộ mới)"  # các cột khác vẫn cập nhật theo nguồn
    assert s.level == "THCS_THPT"  # cấp do Admin đặt giữ nguyên
    assert thong_ke["school_updated"] == 1


async def test_nap_moet_cap_khong_bao_ve_van_theo_nguon(db) -> None:
    s, _ = await VnSchoolService(db).create_school(
        {"moet_school_code": "800", "moet_province_code": "040", "name": "Học ở nước ngoài", "province": "Đắk Lắk",
         "level": "THPT"}
    )
    await db.flush()
    await upsert_one(db, _dong_moet(s, level="OTHER"), Counter())
    await db.flush()
    await db.refresh(s)
    assert s.level == "OTHER"


async def test_nap_lai_xls_dung_khi_vung_co_truong_lien_cap_admin_dat(db) -> None:
    await _truong_bo_lien_cap(db, province="Đắk Lắk")
    with pytest.raises(ProtectedRegionSchools, match="liên cấp"):
        await guard_no_protected_region_schools(db, ["Đắk Lắk"])
    # Vùng khác không có ⇒ không chặn.
    await guard_no_protected_region_schools(db, ["Gia Lai"])


async def test_nap_lai_xls_truong_noi_bo_lien_cap_khong_tinh_vao_chot(db) -> None:
    """Trường NB… liên cấp đã được loại khỏi xoá (``region_school_filter``) ⇒ không làm chốt dừng."""
    await _xa(db)
    await _truong_noi_bo(db, level="THCS_THPT", province="Đắk Lắk")
    await guard_no_protected_region_schools(db, ["Đắk Lắk"])


async def test_chot_lien_cap_dang_python_cua_chay_thu_khop_dang_sql(db) -> None:
    """Rà 23-11 F1: chạy thử kiểm chốt trên DUMP bằng ``protected_rows_in_dump``; --apply kiểm bằng SQL
    ``protected_region_filter``. Hai dạng của MỘT chốt (CLAUDE.md chung §7) ⇒ khoá bằng nhau trên CÙNG dữ liệu: dump dựng
    từ chính bảng (đúng các cột ``SCHOOL_DUMP_COLS``, kiểu chuỗi như ``\\copy … CSV``)."""
    await _xa(db)
    lien_cap_bo = await _truong_bo_lien_cap(db, ma="031", province="Đắk Lắk")  # bị chặn
    await _truong_bo_lien_cap(db, ma="032", province="Gia Lai")  # ngoài vùng
    noi_bo = await _truong_noi_bo(db, level="THCS_THPT", province="Đắk Lắk")  # mã NB ⇒ không chặn
    await VnSchoolService(db).create_school(
        {"moet_school_code": "033", "moet_province_code": "040", "name": "THPT Thường", "province": "Đắk Lắk",
         "level": "THPT"}
    )  # cấp không được bảo vệ
    await db.flush()
    ten_cu = ["Đắk Lắk", "Phú Yên"]

    tap_sql = {str(i) for i in (await db.scalars(select(VnSchool.id).where(*protected_region_filter(ten_cu)))).all()}
    dong = (
        await db.execute(
            select(VnSchool.id, VnSchool.name, VnSchool.province, VnSchool.moet_school_code, VnSchool.level,
                   VnSchool.is_active)
        )
    ).all()
    dump = [
        {"id": str(r.id), "name": r.name or "", "province": r.province or "", "moet_school_code": r.moet_school_code or "",
         "level": r.level or "", "is_active": "t" if r.is_active else "f"}
        for r in dong
    ]
    tap_python = {r["id"] for r in protected_rows_in_dump(dump, ten_cu)}

    assert tap_python == tap_sql
    # Tiền đề (so hai tập rỗng là xanh giả): tập có đúng trường cần chặn và không có trường NB.
    assert str(lien_cap_bo.id) in tap_sql and str(noi_bo.id) not in tap_sql


async def test_csv_truong_lien_cap_co_san_khong_bi_ha_cap(db) -> None:
    s = await _truong_bo_lien_cap(db, ma="040778", prov="048")
    csv_bytes = (
        b"moet_school_code,moet_province_code,name,province,level\n"
        b"040778,048,THPT Ghi De,Tinh X,THPT\n"
    )
    kq, _ = await VnSchoolService(db).import_schools_csv(csv_bytes)
    await db.flush()
    assert (kq["inserted"], kq["skipped_existing"]) == (0, 1)
    await db.refresh(s)
    assert s.level == "THCS_THPT"


async def test_gom_cap_trung_ten_khong_dung_truong_lien_cap(db) -> None:
    """``dedup_temporal_split`` chỉ gom cấp THPT và KHÔNG ghi cột ``level`` ⇒ trường liên cấp không bị đụng."""
    await _truong_bo_lien_cap(db, ma="011", prov="040")
    db.add(VnSchool(moet_school_code="012", moet_province_code="040", name="THCS-THPT Liên Cấp", province="Đắk Lắk",
                    level="THPT"))
    await db.flush()
    cum = await detect_clusters(db)
    assert all(all(x.level == "THPT" for x in c) for c in cum)
