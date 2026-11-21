# -*- coding: utf-8 -*-
"""GĐ2-A — ràng buộc CSDL của bảng chỉ tiêu (tầng chủ sở hữu: CHECK / UNIQUE / khoá ngoại ghép), mỗi ca MỘT ràng buộc, câu
SQL trực tiếp (không qua dịch vụ — dịch vụ chỉ là lớp phụ). Dữ liệu GIẢ trong một giao dịch, lùi khi ra (fixture ``c`` của
``test_quota_occupancy_db.py``: hai học vụ X / Y năm 2026)."""
import pytest
from sqlalchemy.exc import DBAPIError

from app.repositories.council_decision_repository import db_error_codes
from tests.integration.test_quota_occupancy_db import _x, c  # noqa: F401

pytestmark = pytest.mark.integration


async def _bang(c, nam=2026):
    await _x(c, "INSERT INTO admission_quota_table (academic_year) VALUES (:y)", y=nam)


async def _nhom(c, ma="N1", tran=10, nam=2026):
    return (
        await _x(
            c,
            "INSERT INTO admission_quota_group (academic_year, code, name, ceiling) VALUES (:y, :m, 'Nhóm', :t) RETURNING id",
            y=nam, m=ma, t=tran,
        )
    ).scalar_one()


async def _loi(c, cau, **ts):
    """Chạy ``cau`` trong một savepoint; trả (SQLSTATE, tên ràng buộc) của lỗi, hoặc None nếu KHÔNG lỗi."""
    sp = await c.begin_nested()
    try:
        await _x(c, cau, **ts)
    except DBAPIError as e:
        await sp.rollback()
        return db_error_codes(e)
    await sp.rollback()
    return None


async def test_tran_nhom_am_bi_chan(c):
    await _bang(c)
    assert await _loi(
        c, "INSERT INTO admission_quota_group (academic_year, code, name, ceiling) VALUES (2026, 'N1', 'X', -1)"
    ) == ("23514", "ck_admission_quota_group_ceiling")


async def test_ma_nhom_trung_trong_nam_bi_chan(c):
    await _bang(c)
    await _nhom(c, "N1")
    assert await _loi(
        c, "INSERT INTO admission_quota_group (academic_year, code, name, ceiling) VALUES (2026, 'N1', 'Y', 1)"
    ) == ("23505", "uq_admission_quota_group_year_code")


async def test_mot_nganh_hai_nhom_bi_chan(c):
    await _bang(c)
    g1, g2 = await _nhom(c, "N1"), await _nhom(c, "N2")
    ai = c.info["X"]["ai"]
    await _x(c, "INSERT INTO admission_quota_group_member (group_id, offering_academic_info_id, academic_year) "
                "VALUES (:g, :a, 2026)", g=g1, a=ai)
    assert await _loi(
        c,
        "INSERT INTO admission_quota_group_member (group_id, offering_academic_info_id, academic_year) "
        "VALUES (:g, :a, 2026)",
        g=g2, a=ai,
    ) == ("23505", "uq_admission_quota_group_member_oai")


async def test_thanh_vien_khac_nam_hoc_vu_bi_chan(c):
    """Nhóm năm 2027, học vụ năm 2026: khoá ngoại GHÉP (học vụ, năm) chặn."""
    await _bang(c, 2027)
    g = await _nhom(c, "N1", nam=2027)
    assert await _loi(
        c,
        "INSERT INTO admission_quota_group_member (group_id, offering_academic_info_id, academic_year) "
        "VALUES (:g, :a, 2027)",
        g=g, a=c.info["X"]["ai"],
    ) == ("23503", "fk_admission_quota_group_member_oai")


async def test_thanh_vien_khac_nam_nhom_bi_chan(c):
    """Nhóm năm 2026 nhưng dòng thành viên khai năm 2027: khoá ngoại GHÉP (nhóm, năm) chặn."""
    await _bang(c)
    g = await _nhom(c, "N1")
    assert (
        await _loi(
            c,
            "INSERT INTO admission_quota_group_member (group_id, offering_academic_info_id, academic_year) "
            "VALUES (:g, :a, 2027)",
            g=g, a=c.info["X"]["ai"],
        )
    )[0] == "23503"


async def test_khoa_thieu_nguoi_khoa_bi_chan(c):
    await _bang(c)
    assert await _loi(
        c, "UPDATE admission_quota_table SET status = 'locked' WHERE academic_year = 2026"
    ) == ("23514", "ck_admission_quota_table_locked_by")


async def test_trang_thai_la_bi_chan(c):
    await _bang(c)
    assert await _loi(
        c, "UPDATE admission_quota_table SET status = 'open' WHERE academic_year = 2026"
    ) == ("23514", "ck_admission_quota_table_status")
