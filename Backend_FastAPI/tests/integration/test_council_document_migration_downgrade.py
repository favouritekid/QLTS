# -*- coding: utf-8 -*-
"""K6 — guard hạ cấp của migration ``hdts20261103`` (kho mẫu + bộ văn bản Hội đồng) trong
KIỂM TỰ ĐỘNG, trên CSDL test dùng một lần (service postgres của CI / container một lần).

``downgrade`` XOÁ ba bảng — tức mọi mẫu đã tải và mọi bộ văn bản đã lưu (dữ liệu cá nhân,
không dựng lại được) ⇒ FAIL-CLOSED: bảng nào còn hàng thì DỪNG, không xoá gì, trừ khi cờ CHO
PHÉP ``COUNCIL_DOCS_DOWNGRADE_DROP_DATA_ENABLED`` = ``1`` (đúng chuỗi ấy; gõ sai ⇒ vẫn chặn).

Cách đo: chạy ĐÚNG hàm ``downgrade()`` của tệp migration (nạp theo đường dẫn) qua
``alembic.operations.Operations`` trên MỘT kết nối, trong MỘT giao dịch ROLLBACK ở cuối mỗi ca
(DDL của PostgreSQL có giao dịch ⇒ bảng bị xoá ở ca "cờ bật" trở lại nguyên vẹn). Mỗi ca chỉ
cho ĐÚNG MỘT bảng có dữ liệu — ca "tệp" gỡ TẠM khoá ngoại tới bảng bộ ngay trong giao dịch ấy
(ROLLBACK trả lại) — để mỗi ca vi phạm đúng một bất biến (CLAUDE.md §3).
"""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

import app.database as csdl
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

pytestmark = pytest.mark.integration

GOC = Path(__file__).resolve().parents[2]
TEP_MIGRATION = GOC / "alembic" / "versions" / "hdts20261103_council_document_tables.py"
MAU, BO, TEP = (
    "council_document_template",
    "council_document_set",
    "council_document_set_file",
)
BA_BANG = (MAU, BO, TEP)


def _nap_migration():
    spec = importlib.util.spec_from_file_location("hdts20261103_k6", TEP_MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MIG = _nap_migration()
BYTE_GIA = "'\\x01'::bytea"


async def _chen_mot_hang(conn, bang):
    if bang == MAU:
        await conn.execute(
            text(
                "INSERT INTO council_document_template (loai, hieu_luc_tu, sha256, "
                "kich_thuoc, noi_dung) VALUES ('bien_ban', DATE '2026-01-01', "
                "encode(sha256(%s), 'hex'), 1, %s)" % (BYTE_GIA, BYTE_GIA)
            )
        )
    elif bang == BO:
        await conn.execute(
            text(
                "INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, "
                "kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung) VALUES "
                "(now(), 'Cao đẳng', 1, 1, 1, '[\"GIA1\"]', '[{}]', '{}')"
            )
        )
    else:  # TEP — gỡ TẠM khoá ngoại set_id (giao dịch ROLLBACK) để CHỈ bảng tệp có hàng
        fk = (
            await conn.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conrelid = "
                    "'council_document_set_file'::regclass AND contype = 'f'"
                )
            )
        ).scalar_one()
        await conn.execute(
            text('ALTER TABLE council_document_set_file DROP CONSTRAINT "%s"' % fk)
        )
        await conn.execute(
            text(
                "INSERT INTO council_document_set_file (set_id, thu_tu, path, sha256, "
                "kich_thuoc, noi_dung) VALUES (999999, 1, 'gia.docx', "
                "encode(sha256(%s), 'hex'), 1, %s)" % (BYTE_GIA, BYTE_GIA)
            )
        )


async def _trang_thai(conn):
    """{bảng: số hàng} cho bảng CÒN tồn tại; bảng đã xoá ⇒ None."""
    out = {}
    for b in BA_BANG:
        con = (await conn.execute(text("SELECT to_regclass(:b)"), {"b": b})).scalar()
        out[b] = (
            (await conn.execute(text('SELECT count(*) FROM "%s"' % b))).scalar_one()
            if con is not None
            else None
        )
    return out


async def _go_khoa_ngoai_cua_bang_sau(conn):
    """Gỡ TẠM (giao dịch của ca, ROLLBACK ở cuối) mọi khoá ngoại từ bảng NGOÀI ba bảng của 1103 trỏ vào chúng —
    như khi các migration SAU (lượt I ``hdts20261107``: Quyết định + dòng bộ; vòng giao diện ``hdts20261112``: lượt
    gửi) đã được hạ cấp trước, đúng thứ tự một chuỗi hạ cấp thật. CSDL test dựng bằng ``create_all`` có MỌI bảng ⇒
    thiếu bước này thì DROP của 1103 gặp ``DependentObjectsStillExistError`` — ca gãy TỪ lượt I (đo trên a3252ad9 và
    bfba3a2e, phát hiện ở hồi quy rộng lượt L). Trả số khoá ngoại đã gỡ."""
    ds = (
        await conn.execute(
            text(
                "SELECT conrelid::regclass::text, conname FROM pg_constraint WHERE contype = 'f' "
                "AND confrelid IN ('council_document_template'::regclass, 'council_document_set'::regclass, "
                "'council_document_set_file'::regclass) AND conrelid NOT IN "
                "('council_document_template'::regclass, 'council_document_set'::regclass, "
                "'council_document_set_file'::regclass)"
            )
        )
    ).all()
    for bang, ten in ds:
        await conn.execute(text('ALTER TABLE %s DROP CONSTRAINT "%s"' % (bang, ten)))
    return len(ds)


def _chay_downgrade(sync_conn):
    ctx = MigrationContext.configure(connection=sync_conn)
    with Operations.context(ctx):
        MIG.downgrade()


@pytest.mark.parametrize("bang", BA_BANG)
async def test_mot_bang_con_du_lieu_thi_ha_cap_dung_khong_xoa_gi(
    setup_test_database, monkeypatch, bang
):
    monkeypatch.delenv(MIG.CO_CHO_PHEP_XOA, raising=False)
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _chen_mot_hang(conn, bang)
            ky_vong = {b: (1 if b == bang else 0) for b in BA_BANG}
            assert await _trang_thai(conn) == ky_vong  # đúng MỘT bảng có dữ liệu
            with pytest.raises(MIG.ConDuLieuVanBanHoiDong) as e:
                await conn.run_sync(_chay_downgrade)
            assert bang in str(e.value) and MIG.CO_CHO_PHEP_XOA in str(e.value)
            assert await _trang_thai(conn) == ky_vong  # KHÔNG xoá gì, cả ba bảng còn
        finally:
            await gd.rollback()


@pytest.mark.parametrize("gia_tri", ["true", "yes", "0", "", " 1"], ids=repr)
async def test_co_khong_dung_chuoi_1_thi_van_chan(
    setup_test_database, monkeypatch, gia_tri
):
    # Cờ mang nghĩa CHO PHÉP: chỉ đúng "1" mới mở; gõ sai / giá trị lạ ⇒ rơi về CHẶN (§8).
    monkeypatch.setenv(MIG.CO_CHO_PHEP_XOA, gia_tri)
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            await _chen_mot_hang(conn, MAU)
            with pytest.raises(MIG.ConDuLieuVanBanHoiDong):
                await conn.run_sync(_chay_downgrade)
            assert await _trang_thai(conn) == {MAU: 1, BO: 0, TEP: 0}
        finally:
            await gd.rollback()


async def test_co_cho_phep_thi_xoa_ca_ba_bang_du_con_du_lieu(
    setup_test_database, monkeypatch
):
    monkeypatch.setenv(MIG.CO_CHO_PHEP_XOA, "1")
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            for b in BA_BANG:
                await _chen_mot_hang(conn, b)
            assert await _trang_thai(conn) == {MAU: 1, BO: 1, TEP: 1}
            assert await _go_khoa_ngoai_cua_bang_sau(conn) >= 1
            await conn.run_sync(_chay_downgrade)
            assert await _trang_thai(conn) == {b: None for b in BA_BANG}  # đã xoá
        finally:
            await gd.rollback()
    async with csdl.engine.connect() as conn:  # ROLLBACK trả ba bảng (rỗng) cho ca sau
        assert await _trang_thai(conn) == {b: 0 for b in BA_BANG}


async def test_ba_bang_rong_thi_ha_cap_khong_can_co(setup_test_database, monkeypatch):
    monkeypatch.delenv(MIG.CO_CHO_PHEP_XOA, raising=False)
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        try:
            assert await _trang_thai(conn) == {b: 0 for b in BA_BANG}
            assert await _go_khoa_ngoai_cua_bang_sau(conn) >= 1
            await conn.run_sync(_chay_downgrade)
            assert await _trang_thai(conn) == {b: None for b in BA_BANG}
        finally:
            await gd.rollback()
