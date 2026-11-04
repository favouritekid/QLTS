# -*- coding: utf-8 -*-
"""Lượt E3 — chạy ĐÚNG SQL của hai migration Hội đồng trong KIỂM TỰ ĐỘNG (Tier 5), trên CSDL test
dùng một lần (service postgres của CI / container một lần).

1. **F220** — ``hdts20261103b`` (quyền Casbin manager ĐỌC bộ văn bản): chạy ĐÚNG ``upgrade()`` /
   ``downgrade()`` của tệp migration (nạp theo đường dẫn) qua ``alembic.operations.Operations``
   trên MỘT kết nối, trong MỘT giao dịch ROLLBACK ở cuối mỗi ca (như K6). Trước lượt này test
   chỉ so template với HẰNG ``POLICIES`` — câu ``INSERT`` sinh ra (vd chèn ``manager`` thay
   ``role:manager``) chỉ bị câu ``DO`` tự kiểm của migration chặn, ngoài pytest.

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


CB = _nap("hdts20261103b_council_document_casbin.py", "hdts20261103b_f220")
TIEN_TO = "/api/admission-config/council-documents"
BA_DUONG_DOC = (
    TIEN_TO + "/sets",
    TIEN_TO + "/sets/{set_id}",
    TIEN_TO + "/sets/{set_id}/files/{thu_tu}",
)


def _chay(sync_conn, mod, ham):
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        getattr(mod, ham)()


async def _dong_casbin_module(conn):
    """Mọi dòng casbin_rule có đối tượng thuộc module văn bản Hội đồng."""
    return sorted(
        tuple(r)
        for r in (
            await conn.execute(
                text(
                    "SELECT ptype, v0, v1, v2, v3, template_id FROM casbin_rule "
                    "WHERE v1 LIKE :t"
                ),
                {"t": TIEN_TO + "%"},
            )
        ).all()
    )


async def _xoa_dong_module(conn):
    """Như CSDL production TRƯỚC migration: chưa có dòng nào của module (giao dịch ROLLBACK)."""
    await conn.execute(
        text("DELETE FROM casbin_rule WHERE v1 LIKE :t"), {"t": TIEN_TO + "%"}
    )


# ═══════════════════════════════ F220 — hdts20261103b ═══════════════════════════════════
async def test_casbin_upgrade_chen_dung_ba_dong_role_manager_doc(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa_dong_module(conn)
            await conn.run_sync(_chay, CB, "upgrade")
            assert await _dong_casbin_module(conn) == sorted(
                ("p", "role:manager", duong, "GET", "allow", CB.TEMPLATE_ID)
                for duong in BA_DUONG_DOC
            )
        finally:
            await gd.rollback()


async def test_casbin_upgrade_khong_chen_trung_dong_da_co(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa_dong_module(conn)
            await conn.execute(
                text(
                    "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id) VALUES "
                    "('p', 'role:manager', :v1, 'GET', 'allow', 'gia_template_khac')"
                ),
                {"v1": BA_DUONG_DOC[0]},
            )
            await conn.run_sync(_chay, CB, "upgrade")
            dong = await _dong_casbin_module(conn)
            assert [d for d in dong if d[2] == BA_DUONG_DOC[0]] == [
                ("p", "role:manager", BA_DUONG_DOC[0], "GET", "allow", "gia_template_khac")
            ]  # dòng có sẵn GIỮ nguyên, không chèn trùng
            assert len(dong) == 3
        finally:
            await gd.rollback()


async def test_casbin_downgrade_chi_xoa_dong_mang_template_cua_minh(setup_test_database):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _xoa_dong_module(conn)
            gia = ("p", "role:manager", TIEN_TO + "/gia-khac", "GET", "allow", "gia_khac")
            await conn.execute(
                text(
                    "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id) VALUES "
                    "(:a, :b, :c, :d, :e, :f)"
                ),
                dict(zip("abcdef", gia)),
            )
            await conn.run_sync(_chay, CB, "upgrade")
            assert len(await _dong_casbin_module(conn)) == 4
            await conn.run_sync(_chay, CB, "downgrade")
            assert await _dong_casbin_module(conn) == [gia]
        finally:
            await gd.rollback()
