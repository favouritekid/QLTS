# -*- coding: utf-8 -*-
"""GĐ2-A — ``quota_occupancy_service.count_by_group`` trên PostgreSQL thật (dữ liệu GIẢ trong một giao dịch, lùi khi ra;
fixture + hồ sơ giả của ``test_quota_occupancy_db.py``). Đặc tả GĐ2 bản 3 §6; ca biên B21.

Số kỳ vọng VIẾT TAY; ngoài ra khoá "Σ theo thành viên" bằng ĐÚNG các hàm đếm một ô đã có (một nguồn) và "MỘT câu SQL".
"""
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as csdl
from app.services import quota_occupancy_service as qos
from tests.integration.test_quota_occupancy_db import _ghi_nhan, _hs, _x, c  # noqa: F401

pytestmark = pytest.mark.integration


async def _nhom(c, ten, *o_list, nam=2026):
    """Bảng chỉ tiêu năm (nếu chưa có) + một nhóm mang các ô ``o_list`` (X / Y) làm thành viên."""
    await _x(c, "INSERT INTO admission_quota_table (academic_year) VALUES (:y) ON CONFLICT DO NOTHING", y=nam)
    g = (
        await _x(
            c,
            "INSERT INTO admission_quota_group (academic_year, code, name, ceiling) VALUES (:y, :c, :c, 100) RETURNING id",
            y=nam, c=ten,
        )
    ).scalar_one()
    for o in o_list:
        await _x(
            c,
            "INSERT INTO admission_quota_group_member (group_id, offering_academic_info_id, academic_year) "
            "VALUES (:g, :ai, :y)",
            g=g, ai=c.info[o]["ai"], y=nam,
        )
    return g


async def _dem_nhom(c, g):
    async with AsyncSession(bind=c) as db:
        return await qos.count_by_group(db, group_id=g)


async def _sigma_mot_o(c, o_list, nam=2026):
    """Σ của ĐÚNG hai hàm đếm một ô đã có trên các thành viên."""
    async with AsyncSession(bind=c) as db:
        cong_bo = sum([await qos.count_by_academic_info(db, academic_info_id=c.info[o]["ai"]) for o in o_list])
        phe_duyet = sum(
            [await qos.count_by_offering_year(db, offering_id=c.info[o]["off"], academic_year=nam) for o in o_list]
        )
    return cong_bo, phe_duyet


async def test_nhom_khong_thanh_vien_bang_0(c):
    g = await _nhom(c, "RONG")
    assert await _dem_nhom(c, g) == {"publish_count": 0, "approved_count": 0, "used": 0}


async def test_hai_cach_dem_lech_lay_so_lon_hon_va_bang_sigma_tung_o(c):
    """Nhóm chỉ có X. Hai em NV trúng ở X nhưng lead ở Y ⇒ công bố 2, Phê duyệt cũ 0. Một em lead X, NV trúng ở Y ⇒
    Phê duyệt cũ 1. Một em có QĐ hiệu lực chụp X ⇒ +1 cả hai cách. ⇒ công bố 3, Phê duyệt cũ 2, đã dùng 3."""
    g = await _nhom(c, "NX", "X")
    await _hs(c, "approved", o="Y", nv="X")
    await _hs(c, "confirmed", o="Y", nv="X")
    await _hs(c, "approved", o="X", nv="Y")
    p = await _hs(c, "submitted")
    await _ghi_nhan(c, [p], "X")
    dem = await _dem_nhom(c, g)
    assert dem == {"publish_count": 3, "approved_count": 2, "used": 3}
    assert (dem["publish_count"], dem["approved_count"]) == await _sigma_mot_o(c, ["X"])


async def test_nhom_hai_nganh_bang_sigma_tung_o_va_khong_dem_ho_so_rut(c):
    g = await _nhom(c, "NXY", "X", "Y")
    await _hs(c, "approved", o="X", nv="X")
    await _hs(c, "approved", o="Y", kieu_cu="Y")
    await _hs(c, "submitted", o="X", nv="X")  # không chiếm chỗ
    rut = await _hs(c, "withdrawn")
    cho = await _hs(c, "withdrawal_pending")
    await _ghi_nhan(c, [rut, cho], "Y")  # rút hẳn trả chỗ; chờ hoàn vẫn giữ
    dem = await _dem_nhom(c, g)
    assert dem == {"publish_count": 3, "approved_count": 3, "used": 3}
    assert (dem["publish_count"], dem["approved_count"]) == await _sigma_mot_o(c, ["X", "Y"])


async def test_mot_cau_sql(c):
    """F260: cả hai cách đếm trong MỘT câu ⇒ một ảnh chụp READ COMMITTED."""
    g = await _nhom(c, "N1CAU", "X", "Y")
    cau = []

    def _ghi(conn, cursor, statement, parameters, context, executemany):
        cau.append(statement)

    event.listen(csdl.engine.sync_engine, "before_cursor_execute", _ghi)
    try:
        await _dem_nhom(c, g)
    finally:
        event.remove(csdl.engine.sync_engine, "before_cursor_execute", _ghi)
    assert len(cau) == 1, cau
