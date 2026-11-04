# -*- coding: utf-8 -*-
"""Lượt E3 — chạy ĐÚNG SQL của hai migration Hội đồng trong KIỂM TỰ ĐỘNG (Tier 5), trên CSDL test
dùng một lần (service postgres của CI / container một lần).

1. **F220** — ``hdts20261103b`` (quyền Casbin manager ĐỌC bộ văn bản): chạy ĐÚNG ``upgrade()`` /
   ``downgrade()`` của tệp migration (nạp theo đường dẫn) qua ``alembic.operations.Operations``
   trên MỘT kết nối, trong MỘT giao dịch ROLLBACK ở cuối mỗi ca (như K6). Trước lượt này test
   chỉ so template với HẰNG ``POLICIES`` — câu ``INSERT`` sinh ra (vd chèn ``manager`` thay
   ``role:manager``) chỉ bị câu ``DO`` tự kiểm của migration chặn, ngoài pytest.
2. ``hdts20261104`` (vết xoá + nhật ký tải): ``upgrade()`` dựng đúng hai bảng KHÔNG khoá ngoại;
   ``downgrade()`` FAIL-CLOSED khi còn dữ liệu (cờ CHO PHÉP riêng, đúng chuỗi ``1``).

Mỗi ca vi phạm đúng MỘT bất biến (CLAUDE.md §3).
"""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

import app.database as csdl
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from app.models import council_document as m

pytestmark = pytest.mark.integration

GOC = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _nap(ten_tep, ten_module):
    spec = importlib.util.spec_from_file_location(ten_module, GOC / ten_tep)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CB = _nap("hdts20261103b_council_document_casbin.py", "hdts20261103b_f220")
VET = _nap("hdts20261104_council_document_audit.py", "hdts20261104_e3")
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


# ═══════════════════════════════ hdts20261104 — upgrade ═════════════════════════════════
HAI_BANG = (VET.XOA, VET.TAI)


async def _co_bang(conn, b):
    return (await conn.execute(text("SELECT to_regclass(:b)"), {"b": b})).scalar()


async def test_vet_upgrade_dung_hai_bang_khong_khoa_ngoai_dung_rang_buoc(
    setup_test_database,
):
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            for b in HAI_BANG:  # CSDL test dựng từ model ⇒ bỏ đi rồi dựng lại bằng MIGRATION
                await conn.execute(text('DROP TABLE "%s"' % b))
            assert [await _co_bang(conn, b) for b in HAI_BANG] == [None, None]
            await conn.run_sync(_chay, VET, "upgrade")
            for b, lop in (
                (VET.XOA, m.CouncilDocumentSetDeletion),
                (VET.TAI, m.CouncilDocumentDownloadLog),
            ):
                rb = dict(
                    (
                        await conn.execute(
                            text(
                                "SELECT conname, contype::text FROM pg_constraint "
                                "WHERE conrelid = CAST(:b AS regclass)"
                            ),
                            {"b": b},
                        )
                    ).all()
                )
                assert "f" not in rb.values(), (b, rb)  # KHÔNG khoá ngoại nào
                ten_model = {
                    c.name
                    for c in lop.__table__.constraints
                    if c.name and c.name.startswith(("ck_", "uq_"))
                }
                assert {k for k, v in rb.items() if v in ("c", "u")} == ten_model
        finally:
            await gd.rollback()


# ═══════════════════════════════ hdts20261104 — downgrade fail-closed ═════════════════
_SHA = "a" * 64


async def _chen_mot_hang(conn, bang):
    if bang == VET.XOA:
        await conn.execute(
            text(
                "INSERT INTO council_document_set_deletion (set_id, so_ho_so, so_tep, "
                "danh_sach_tep, nguoi_xoa_id, ly_do) VALUES (999999, 1, 1, "
                "CAST(:t AS jsonb), 1, 'GIA ly do')"
            ),
            {"t": '[{"thu_tu": 1, "path": "gia.docx", "sha256": "%s"}]' % _SHA},
        )
    else:
        await conn.execute(
            text(
                "INSERT INTO council_document_download_log (set_id, thu_tu, path, "
                "sha256, nguoi_tai_id) VALUES (999999, 1, 'gia.docx', :s, 1)"
            ),
            {"s": _SHA},
        )


async def _trang_thai(conn):
    out = {}
    for b in HAI_BANG:
        out[b] = (
            (await conn.execute(text('SELECT count(*) FROM "%s"' % b))).scalar_one()
            if await _co_bang(conn, b) is not None
            else None
        )
    return out


@pytest.mark.parametrize("bang", HAI_BANG)
async def test_vet_mot_bang_con_du_lieu_thi_ha_cap_dung_khong_xoa_gi(
    setup_test_database, monkeypatch, bang
):
    monkeypatch.delenv(VET.CO_CHO_PHEP_XOA, raising=False)
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _chen_mot_hang(conn, bang)
            ky_vong = {b: (1 if b == bang else 0) for b in HAI_BANG}
            assert await _trang_thai(conn) == ky_vong
            with pytest.raises(VET.ConVetVanBanHoiDong) as e:
                await conn.run_sync(_chay, VET, "downgrade")
            assert bang in str(e.value) and VET.CO_CHO_PHEP_XOA in str(e.value)
            assert await _trang_thai(conn) == ky_vong  # KHÔNG xoá gì
        finally:
            await gd.rollback()


@pytest.mark.parametrize("gia_tri", ["true", "yes", "0", "", " 1"], ids=repr)
async def test_vet_co_khong_dung_chuoi_1_thi_van_chan(
    setup_test_database, monkeypatch, gia_tri
):
    monkeypatch.setenv(VET.CO_CHO_PHEP_XOA, gia_tri)
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _chen_mot_hang(conn, VET.TAI)
            with pytest.raises(VET.ConVetVanBanHoiDong):
                await conn.run_sync(_chay, VET, "downgrade")
            assert await _trang_thai(conn) == {VET.XOA: 0, VET.TAI: 1}
        finally:
            await gd.rollback()


async def test_vet_co_cho_phep_thi_xoa_ca_hai_bang(setup_test_database, monkeypatch):
    monkeypatch.setenv(VET.CO_CHO_PHEP_XOA, "1")
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            for b in HAI_BANG:
                await _chen_mot_hang(conn, b)
            await conn.run_sync(_chay, VET, "downgrade")
            assert await _trang_thai(conn) == {b: None for b in HAI_BANG}
        finally:
            await gd.rollback()


async def test_vet_hai_bang_rong_thi_ha_cap_khong_can_co(
    setup_test_database, monkeypatch
):
    monkeypatch.delenv(VET.CO_CHO_PHEP_XOA, raising=False)
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            assert await _trang_thai(conn) == {b: 0 for b in HAI_BANG}
            await conn.run_sync(_chay, VET, "downgrade")
            assert await _trang_thai(conn) == {b: None for b in HAI_BANG}
        finally:
            await gd.rollback()


def test_co_cho_phep_rieng_va_mang_nghia_cho_phep():
    assert VET.CO_CHO_PHEP_XOA.endswith("_ENABLED")
    goc = _nap("hdts20261103_council_document_tables.py", "hdts20261103_e3")
    assert VET.CO_CHO_PHEP_XOA != goc.CO_CHO_PHEP_XOA  # bỏ VẾT ≠ bỏ bộ văn bản
