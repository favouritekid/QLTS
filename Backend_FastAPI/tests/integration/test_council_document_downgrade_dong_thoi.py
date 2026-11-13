# -*- coding: utf-8 -*-
"""F222 (Codex lần 6) + nhánh anh em ``hdts20261103`` — hạ cấp hai migration Hội đồng khi có GHI
CHEN, trên PostgreSQL THẬT, HAI PHIÊN, chạy migration qua ĐÚNG ``alembic/env.py`` (dòng lệnh
``python -m alembic downgrade …`` trong tiến trình con ⇒ đúng chế độ AUTOCOMMIT của env.py).

Kịch bản (Codex): kiểm "bảng rỗng" → một GET tải tệp INSERT … COMMIT một dòng nhật ký → migration
xoá bảng ⇒ mất vết dù cờ chưa bật. Cách đo tất định: phiên GHI mở giao dịch và INSERT (chưa
commit) TRƯỚC khi chạy hạ cấp; đợi tới khi tiến trình hạ cấp bị chính phiên GHI chặn
(``pg_blocking_pids``) rồi mới COMMIT. Khuôn cũ (kiểm rồi xoá, tách câu): kiểm không thấy dòng
chưa commit → DROP đợi khoá → COMMIT → DROP chạy ⇒ MẤT DÒNG (đo: ``do_khoa_e4.py`` biến thể A).
Khuôn mới (một câu ``DO`` khoá → kiểm → xoá): khoá đợi → COMMIT → kiểm thấy dòng ⇒ dừng, không
xoá gì.

CSDL DÙNG MỘT LẦN cho từng ca (tên có ``test``) trên cùng máy chủ PostgreSQL của bộ test — không
chạm CSDL ``qlts_test`` chung. Lược đồ tối thiểu: ĐÚNG ``upgrade()`` của revision cần hạ (nạp theo
đường dẫn, như K6) + bảng ``alembic_version``; với ``hdts20261103`` thêm hai bảng ĐÍCH tối thiểu
(``user``, ``organization_unit`` chỉ cột ``id``) cho khoá ngoại. Kiểm bất biến DỮ LIỆU trước (còn
bảng + còn dòng), rồi mới tới mã thoát / phiên bản (đỏ phải đỏ đúng lý do — CLAUDE.md §3).
"""
import asyncio
import importlib.util
import json
import os
import secrets
import sys
import time
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from app.config import settings
from tests.fixtures.database import kiem_url_csdl_test
from tests.fixtures.hoi_dong_seed import ma_gia

pytestmark = pytest.mark.integration

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI (có alembic.ini)


def _nap(ten_tep, ten_module):
    spec = importlib.util.spec_from_file_location(
        ten_module, GOC / "alembic" / "versions" / ten_tep
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BO_VB = _nap("hdts20261103_council_document_tables.py", "hdts20261103_e4_dong_thoi")
VET = _nap("hdts20261104_council_document_audit.py", "hdts20261104_e4_dong_thoi")
HAI_CO = (BO_VB.CO_CHO_PHEP_XOA, VET.CO_CHO_PHEP_XOA)


def _url(ten_db, driver):
    return (
        make_url(settings.DATABASE_URL)
        .set(drivername=driver, database=ten_db)
        .render_as_string(hide_password=False)
    )


def _chay(sync_conn, mod):
    with Operations.context(MigrationContext.configure(connection=sync_conn)):
        mod.upgrade()


@pytest_asyncio.fixture
async def csdl_rieng():
    """Tên CSDL dùng một lần; dựng trước ca, xoá (FORCE) sau ca."""
    ten = "qlts_test_e4_%s" % secrets.token_hex(4)
    assert kiem_url_csdl_test(_url(ten, "postgresql+asyncpg")) is None
    q = await asyncpg.connect(
        _url(make_url(settings.DATABASE_URL).database, "postgresql")
    )
    try:
        await q.execute('CREATE DATABASE "%s"' % ten)
        yield ten
    finally:
        await q.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % ten)
        await q.close()


async def _dung(ten_db, mod, phien_ban, them=()):
    eng = create_async_engine(_url(ten_db, "postgresql+asyncpg"), poolclass=NullPool)
    try:
        async with eng.begin() as conn:
            for s in them:
                await conn.execute(text(s))
            await conn.run_sync(_chay, mod)
            await conn.execute(
                text(
                    "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            await conn.execute(
                text("INSERT INTO alembic_version VALUES (:v)"), {"v": phien_ban}
            )
    finally:
        await eng.dispose()


async def _dung_1104(ten_db):
    await _dung(ten_db, VET, "hdts20261104")


async def _dung_1103(ten_db):
    await _dung(
        ten_db,
        BO_VB,
        "hdts20261103",
        (
            'CREATE TABLE "user" (id serial PRIMARY KEY)',
            "CREATE TABLE organization_unit (id serial PRIMARY KEY)",
        ),
    )


async def _ghi_dong_nhat_ky(c):
    await c.execute(
        "INSERT INTO council_document_download_log (set_id, thu_tu, path, sha256, "
        "nguoi_tai_id) VALUES (999999, 1, 'gia.docx', repeat('a', 64), 1)"
    )


async def _ghi_vet_xoa(c):
    """Như luồng Admin xoá bộ: MỘT dòng vết xoá (CSDL dùng một lần của 1104 không có bảng bộ)."""
    await c.execute(
        "INSERT INTO council_document_set_deletion (set_id, so_ho_so, so_tep, danh_sach_tep, "
        "nguoi_xoa_id, ly_do) VALUES (999999, 1, 1, $1::jsonb, 1, 'GIA ly do')",
        json.dumps([{"thu_tu": 1, "path": "gia.docx", "sha256": "a" * 64}]),
    )


async def _tai_mot_mau(c):
    """Như luồng tải mẫu lên: MỘT dòng ở bảng mẫu (chỉ bảng mẫu — không bộ, không tệp)."""
    await c.execute(
        "INSERT INTO council_document_template (loai, hieu_luc_tu, sha256, kich_thuoc, "
        "noi_dung) VALUES ('bien_ban', DATE '2026-01-01', encode(sha256('GIA'::bytea), "
        "'hex'), 3, 'GIA'::bytea)"
    )


async def _tao_mot_bo(c):
    """Như luồng tạo bộ: một bộ + một tệp của nó trong CÙNG giao dịch (dữ liệu GIẢ)."""
    await c.execute(
        "WITH bo AS (INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, "
        "kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung) VALUES (now(), "
        "'GIA', 1, 1, 3, $1::jsonb, '[{}]'::jsonb, '{}'::jsonb) RETURNING id) "
        "INSERT INTO council_document_set_file (set_id, thu_tu, path, sha256, kich_thuoc, "
        "noi_dung) SELECT bo.id, 1, 'gia.docx', encode(sha256('GIA'::bytea), 'hex'), 3, "
        "'GIA'::bytea FROM bo",
        json.dumps([ma_gia(1)]),
    )


async def _ha_cap(ten_db, dich, co=None):
    """``python -m alembic downgrade <dich>`` (tiến trình con, ĐÚNG env.py) trên CSDL ``ten_db``.
    ``co`` = (tên cờ, giá trị) hoặc None (mọi cờ cho phép xoá đều BỎ khỏi môi trường).
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(ten_db, "postgresql+asyncpg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in HAI_CO:
        env.pop(k, None)
    if co is not None:
        env[co[0]] = co[1]
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "downgrade",
        dich,
        cwd=str(GOC),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def _doi_bi_chan(k, pid_ghi, p, giay=40.0):
    """True khi một phiên của CSDL bị phiên GHI (``pid_ghi``) chặn; False nếu tiến trình hạ cấp
    đã kết thúc trước đó (không đợi khoá) hoặc quá ``giay``."""
    het = time.monotonic() + giay
    while time.monotonic() < het:
        if p.returncode is not None:
            return False
        n = await k.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND $1 = ANY(pg_blocking_pids(pid))",
            pid_ghi,
        )
        if n:
            return True
        await asyncio.sleep(0.1)
    return False


async def _xong(p):
    out, _ = await asyncio.wait_for(p.communicate(), 50)
    return p.returncode, out.decode("utf-8", "replace")


async def _so_dong(k, bang):
    """Số dòng của ``bang``; bảng đã bị xoá ⇒ None."""
    if await k.fetchval("SELECT to_regclass($1)", bang) is None:
        return None
    return await k.fetchval('SELECT count(*) FROM "%s"' % bang)


async def _phien_ban(k):
    return await k.fetchval("SELECT version_num FROM alembic_version")


async def _chen_roi_ha_cap(ten_db, chen, dich, ket_thuc="commit", co=None):
    """Phiên GHI: BEGIN + ``chen`` (CHƯA commit) → chạy hạ cấp → đợi bị chặn → ``ket_thuc``.
    Trả (kết nối kiểm, đã bị chặn, mã thoát, đầu ra)."""
    url = _url(ten_db, "postgresql")
    ghi = await asyncpg.connect(url)
    k = await asyncpg.connect(url)
    p = None
    try:
        gd = ghi.transaction()
        await gd.start()
        await chen(ghi)
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        p = await _ha_cap(ten_db, dich, co)
        bi_chan = await _doi_bi_chan(k, pid, p)
        await (gd.commit() if ket_thuc == "commit" else gd.rollback())
        rc, out = await _xong(p)
    except BaseException:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await k.close()
        raise
    finally:
        await ghi.close()
    return k, bi_chan, rc, out


# ═══════════════════════════════ hdts20261104 — vết xoá + nhật ký tải ═══════════════════════
async def test_1104_ghi_nhat_ky_chen_vao_khi_ha_cap_thi_khong_mat_dong(csdl_rieng):
    await _dung_1104(csdl_rieng)
    k, bi_chan, rc, out = await _chen_roi_ha_cap(
        csdl_rieng, _ghi_dong_nhat_ky, "hdts20261103b"
    )
    try:
        dong = await _so_dong(k, VET.TAI)
        assert (
            dong == 1
        ), "MẤT DÒNG nhật ký tải đã COMMIT khi cờ chưa bật: bảng %s %s" % (
            VET.TAI,
            "đã bị xoá" if dong is None else "còn %d dòng" % dong,
        )
        assert await _so_dong(k, VET.XOA) == 0
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc != 0 and "ConVetVanBanHoiDong" in out, (rc, out[-600:])
        assert await _phien_ban(k) == "hdts20261104"
    finally:
        await k.close()


async def test_1104_ghi_vet_xoa_chen_vao_khi_ha_cap_thi_khong_mat_vet(csdl_rieng):
    # Bảng THỨ HAI của 1104 (người điều phối nêu 04-11): Admin xoá bộ ghi vết xoá chen giữa.
    await _dung_1104(csdl_rieng)
    k, bi_chan, rc, out = await _chen_roi_ha_cap(
        csdl_rieng, _ghi_vet_xoa, "hdts20261103b"
    )
    try:
        dong = await _so_dong(k, VET.XOA)
        assert dong == 1, "MẤT VẾT XOÁ đã COMMIT khi cờ chưa bật: bảng %s %s" % (
            VET.XOA,
            "đã bị xoá" if dong is None else "còn %d dòng" % dong,
        )
        assert await _so_dong(k, VET.TAI) == 0
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc != 0 and "ConVetVanBanHoiDong" in out, (rc, out[-600:])
        assert await _phien_ban(k) == "hdts20261104"
    finally:
        await k.close()


async def test_1104_phien_ghi_huy_thi_ha_cap_van_xoa_bang_rong(csdl_rieng):
    # ĐỐI CHỨNG: dòng chen bị ROLLBACK ⇒ sau khoá bảng thật sự rỗng ⇒ hạ cấp xoá được mà không
    # cần cờ (không chặn thừa; phép kiểm dùng ảnh chụp SAU khoá, không phải trước).
    await _dung_1104(csdl_rieng)
    k, bi_chan, rc, out = await _chen_roi_ha_cap(
        csdl_rieng, _ghi_dong_nhat_ky, "hdts20261103b", ket_thuc="rollback"
    )
    try:
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc == 0, out[-600:]
        assert (await _so_dong(k, VET.TAI), await _so_dong(k, VET.XOA)) == (None, None)
        assert await _phien_ban(k) == "hdts20261103b"
    finally:
        await k.close()


async def test_1104_co_cho_phep_thi_van_xoa_duoc(csdl_rieng):
    await _dung_1104(csdl_rieng)
    k = await asyncpg.connect(_url(csdl_rieng, "postgresql"))
    try:
        await _ghi_dong_nhat_ky(k)  # đã COMMIT trước khi hạ cấp
        rc, out = await _xong(
            await _ha_cap(csdl_rieng, "hdts20261103b", (VET.CO_CHO_PHEP_XOA, "1"))
        )
        assert rc == 0, out[-600:]
        assert (await _so_dong(k, VET.TAI), await _so_dong(k, VET.XOA)) == (None, None)
        assert await _phien_ban(k) == "hdts20261103b"
    finally:
        await k.close()


async def test_1104_muc_co_lap_repeatable_read_thi_tu_choi_khong_mat_dong(csdl_rieng):
    # Ở REPEATABLE READ ảnh chụp của câu DO chốt TRƯỚC khoá ⇒ kiểm sau khoá vẫn "rỗng" (đo:
    # do_khoa_e4.py biến thể C mất dòng) ⇒ câu DO phải TỪ CHỐI chạy.
    await _dung_1104(csdl_rieng)
    q = await asyncpg.connect(_url(csdl_rieng, "postgresql"))
    try:
        await q.execute(
            "ALTER DATABASE \"%s\" SET default_transaction_isolation TO 'repeatable read'"
            % csdl_rieng
        )
    finally:
        await q.close()
    k, _bi_chan, rc, out = await _chen_roi_ha_cap(
        csdl_rieng, _ghi_dong_nhat_ky, "hdts20261103b"
    )
    try:
        dong = await _so_dong(k, VET.TAI)
        assert (
            dong == 1
        ), "MẤT DÒNG nhật ký tải đã COMMIT ở REPEATABLE READ: bảng %s %s" % (
            VET.TAI,
            "đã bị xoá" if dong is None else "còn %d dòng" % dong,
        )
        assert rc != 0 and "HaCapCanReadCommitted" in out, (rc, out[-600:])
        assert await _phien_ban(k) == "hdts20261104"
    finally:
        await k.close()


# ═══════════════════════════════ hdts20261103 — kho mẫu + bộ văn bản ═══════════════════════
async def test_1103_tao_bo_chen_vao_khi_ha_cap_thi_khong_mat_bo(csdl_rieng):
    await _dung_1103(csdl_rieng)
    k, bi_chan, rc, out = await _chen_roi_ha_cap(
        csdl_rieng, _tao_mot_bo, "v3circ20261011c"
    )
    try:
        bo, tep = await _so_dong(k, BO_VB.BO), await _so_dong(k, BO_VB.TEP)
        assert (bo, tep) == (1, 1), (
            "MẤT bộ văn bản đã COMMIT khi cờ chưa bật: (bộ, tệp) = %r (None = bảng đã bị xoá)"
            % ((bo, tep),)
        )
        assert await _so_dong(k, BO_VB.MAU) == 0
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc != 0 and "ConDuLieuVanBanHoiDong" in out, (rc, out[-600:])
        assert await _phien_ban(k) == "hdts20261103"
    finally:
        await k.close()


async def test_1103_tai_mau_chen_vao_khi_ha_cap_thi_khong_mat_mau(csdl_rieng):
    # Bảng THỨ BA của 1103 (người điều phối nêu 04-11): tải mẫu lên chỉ ghi bảng MẪU.
    await _dung_1103(csdl_rieng)
    k, bi_chan, rc, out = await _chen_roi_ha_cap(
        csdl_rieng, _tai_mot_mau, "v3circ20261011c"
    )
    try:
        dong = await _so_dong(k, BO_VB.MAU)
        assert dong == 1, "MẤT MẪU đã COMMIT khi cờ chưa bật: bảng %s %s" % (
            BO_VB.MAU,
            "đã bị xoá" if dong is None else "còn %d dòng" % dong,
        )
        assert (await _so_dong(k, BO_VB.BO), await _so_dong(k, BO_VB.TEP)) == (0, 0)
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc != 0 and "ConDuLieuVanBanHoiDong" in out, (rc, out[-600:])
        assert await _phien_ban(k) == "hdts20261103"
    finally:
        await k.close()


async def test_1103_co_cho_phep_thi_van_xoa_duoc(csdl_rieng):
    await _dung_1103(csdl_rieng)
    k = await asyncpg.connect(_url(csdl_rieng, "postgresql"))
    try:
        await _tao_mot_bo(k)  # đã COMMIT trước khi hạ cấp
        rc, out = await _xong(
            await _ha_cap(csdl_rieng, "v3circ20261011c", (BO_VB.CO_CHO_PHEP_XOA, "1"))
        )
        assert rc == 0, out[-600:]
        assert [await _so_dong(k, b) for b in (BO_VB.MAU, BO_VB.BO, BO_VB.TEP)] == [
            None,
            None,
            None,
        ]
        assert await _phien_ban(k) == "v3circ20261011c"
    finally:
        await k.close()
