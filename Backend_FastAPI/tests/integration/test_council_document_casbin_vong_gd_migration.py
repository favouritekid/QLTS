# -*- coding: utf-8 -*-
"""Migration ``hdts20261113`` (quyền Casbin Quản lý cho hai route ĐỌC mới của vòng giao diện: tải cả bộ + người tạo bộ) —
chạy ĐÚNG ``upgrade()`` / ``downgrade()`` của tệp migration trên CSDL test, cùng khuôn F220 (``hdts20261103b``) ở
``test_council_document_migrations_e3.py``: nạp tệp theo đường dẫn, chạy qua ``alembic.operations.Operations`` trên MỘT kết
nối, trong MỘT giao dịch ROLLBACK cuối mỗi ca.

Trước tệp này chỉ có test so tập dòng ``POLICIES`` ↔ mẫu Casbin + chuỗi revision (``test_council_document_models.py``):
câu ``DO`` thật chưa từng chạy trong pytest (phiên B chỉ ra 11-11). Câu tự kiểm của ``DO`` đếm ``COUNT(DISTINCT …)`` nên
KHÔNG bắt được dòng trùng — chỉ ca "chạy lại / dòng có sẵn" ở đây canh ``WHERE NOT EXISTS``.

Mỗi ca vi phạm đúng MỘT bất biến (CLAUDE.md §3).
"""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

import app.database as csdl
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

pytestmark = pytest.mark.integration

GOC = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _nap(ten_tep, ten_module):
    spec = importlib.util.spec_from_file_location(ten_module, GOC / ten_tep)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _nap("hdts20261113_council_document_casbin_vong_gd.py", "hdts20261113_vong_gd")
TIEN_TO = "/api/admission-config/council-documents"
TAI_CA_BO = TIEN_TO + "/sets/{set_id}/tai-ca-bo"
NGUOI_TAO = TIEN_TO + "/nguoi-tao-bo"
#: các dòng mong đợi — viết TAY (không đọc lại ``MIG.POLICIES``) để ca này bắt được cả lỗi ở hằng
TID = "_hdts20261113_council_document_vong_gd"
DONG_TAI = ("p", "role:manager", TAI_CA_BO, "GET", "allow", TID)
DONG_NGUOI_TAO = ("p", "role:manager", NGUOI_TAO, "GET", "allow", TID)
MONG = sorted([DONG_TAI, DONG_NGUOI_TAO])


def _chay(sync_conn, ham):
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        getattr(MIG, ham)()


async def _dong(conn, *duong):
    """Mọi dòng casbin_rule (ptype, v0..v3, template_id) có v1 thuộc ``duong``."""
    return sorted(
        tuple(r)
        for r in (
            await conn.execute(
                text(
                    "SELECT ptype, v0, v1, v2, v3, template_id FROM casbin_rule WHERE v1 = ANY(:d)"
                ),
                {"d": list(duong)},
            )
        ).all()
    )


async def _xoa(conn):
    """Như production TRƯỚC migration: chưa có dòng nào của hai route (giao dịch ROLLBACK)."""
    await conn.execute(
        text("DELETE FROM casbin_rule WHERE v1 = ANY(:d)"), {"d": [TAI_CA_BO, NGUOI_TAO]}
    )


async def _chen(conn, dong):
    await conn.execute(
        text(
            "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id) VALUES (:a, :b, :c, :d, :e, :f)"
        ),
        dict(zip("abcdef", dong)),
    )


async def test_upgrade_chen_dung_hai_dong_role_manager_get_allow(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa(conn)
            await conn.run_sync(_chay, "upgrade")
            assert await _dong(conn, TAI_CA_BO, NGUOI_TAO) == MONG
        finally:
            await gd.rollback()


async def test_upgrade_chay_lai_khong_chen_trung(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa(conn)
            await conn.run_sync(_chay, "upgrade")
            await conn.run_sync(_chay, "upgrade")
            assert await _dong(conn, TAI_CA_BO, NGUOI_TAO) == MONG
        finally:
            await gd.rollback()


async def test_upgrade_dong_giong_het_co_san_thi_giu_nguyen_khong_chen_them(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa(conn)
            co_san = ("p", "role:manager", TAI_CA_BO, "GET", "allow", "gia_template_khac")
            await _chen(conn, co_san)
            await conn.run_sync(_chay, "upgrade")
            assert await _dong(conn, TAI_CA_BO) == [co_san]  # dòng có sẵn GIỮ nguyên, không chèn trùng
            assert await _dong(conn, NGUOI_TAO) == [DONG_NGUOI_TAO]
        finally:
            await gd.rollback()


async def test_downgrade_chi_xoa_dong_mang_template_cua_minh(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa(conn)
            # dòng GIỐNG HỆT (ptype, v0..v3) một dòng của migration nhưng template khác + một dòng khác của module
            giong_het = ("p", "role:manager", TAI_CA_BO, "GET", "allow", "gia_template_khac")
            khac = ("p", "role:manager", NGUOI_TAO, "POST", "allow", "gia_khac")
            await _chen(conn, giong_het)
            await _chen(conn, khac)
            await conn.run_sync(_chay, "upgrade")
            assert len(await _dong(conn, TAI_CA_BO, NGUOI_TAO)) == 3
            await conn.run_sync(_chay, "downgrade")
            assert await _dong(conn, TAI_CA_BO, NGUOI_TAO) == sorted([giong_het, khac])
        finally:
            await gd.rollback()
