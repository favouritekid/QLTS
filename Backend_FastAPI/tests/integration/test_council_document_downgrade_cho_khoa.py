# -*- coding: utf-8 -*-
"""F227 (Codex lần 7, lượt G) — trần chờ khoá của hạ cấp hai migration Hội đồng, trên PostgreSQL
THẬT, HAI PHIÊN, qua ĐÚNG ``alembic/env.py`` (``python -m alembic downgrade`` trong tiến trình con
⇒ đúng AUTOCOMMIT). Cùng khuôn ``test_council_document_downgrade_dong_thoi.py`` (dùng lại helper).

Kịch bản: phiên GHI mở giao dịch + INSERT (chưa commit) và GIỮ lâu hơn trần ⇒ hạ cấp phải tự dừng
sau ~``TRAN_CHO_KHOA`` (không chờ vô hạn), thoát khác 0 với lỗi miền nói rõ do chờ khoá; sau đó
phiên GHI commit ⇒ bảng còn, dòng đã có trước + dòng vừa ghi còn, phiên bản không đổi. Ca CÓ cờ cho
phép xoá: vẫn không xoá gì (trần thắng cờ). Sau khi hạ cấp dừng, lượt đọc mới KHÔNG bị chặn.
Đo ở tầng CSDL từ phiên khác (CLAUDE.md §10).
"""
import asyncio
import time

import asyncpg
import pytest

from tests.integration.test_council_document_downgrade_dong_thoi import (  # noqa: F401
    BO_VB,
    VET,
    _dung_1103,
    _dung_1104,
    _ghi_dong_nhat_ky,
    _ha_cap,
    _phien_ban,
    _so_dong,
    _tao_mot_bo,
    _url,
    csdl_rieng,  # noqa: F401 — fixture CSDL dùng một lần
)

pytestmark = pytest.mark.integration

TRAN_GIAY = 10.0  # = TRAN_CHO_KHOA "10s" (ca dưới khoá hai migration cùng giá trị)
GIU_KHOA_GIAY = TRAN_GIAY + 8.0  # phiên ghi giữ khoá LÂU HƠN trần


def test_hai_migration_cung_tran_10_giay():
    assert BO_VB.TRAN_CHO_KHOA == VET.TRAN_CHO_KHOA == "10s"


async def _cho_toi_khi_bi_chan(k, pid_ghi, p, giay=60.0):
    """Mốc (monotonic) lúc tiến trình hạ cấp bắt đầu bị phiên ghi chặn; None nếu nó kết thúc
    trước đó."""
    het = time.monotonic() + giay
    while time.monotonic() < het:
        if p.returncode is not None:
            return None
        n = await k.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
            "AND $1 = ANY(pg_blocking_pids(pid))",
            pid_ghi,
        )
        if n:
            return time.monotonic()
        await asyncio.sleep(0.05)
    return None


async def _giu_khoa_qua_tran(ten_db, chen, dich, co=None):
    """Phiên GHI: BEGIN + ``chen`` (CHƯA commit) → hạ cấp → đo lúc bị chặn → GIỮ tới khi hạ cấp
    tự thoát hoặc quá ``GIU_KHOA_GIAY`` → (đo lượt đọc mới khi phiên ghi CÒN giữ) → COMMIT.
    Trả (kết nối kiểm, (đã bị chặn, giây từ lúc bị chặn tới lúc thoát | None, mã thoát, đầu ra),
    lượt đọc mới đọc được)."""
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
        luc_chan = await _cho_toi_khi_bi_chan(k, pid, p)
        try:
            out, _ = await asyncio.wait_for(p.communicate(), GIU_KHOA_GIAY)
            thoat = time.monotonic()
        except asyncio.TimeoutError:
            out, thoat = b"", None
        # Phiên ghi VẪN giữ khoá: lượt đọc mới không được bị chặn (hạ cấp đã buông hàng chờ).
        doc = await asyncpg.connect(url)
        try:
            await doc.execute("SET statement_timeout = '3s'")
            bang = VET.TAI if dich == "hdts20261103b" else BO_VB.BO
            await doc.fetchval('SELECT count(*) FROM "%s"' % bang)
            doc_duoc = True
        except asyncpg.PostgresError:
            doc_duoc = False
        finally:
            await doc.close()
        if thoat is None:
            # Chờ vô hạn: huỷ phiên CSDL của tiến trình hạ cấp TRƯỚC khi phiên ghi commit (không để
            # câu DO chạy tiếp và xoá bảng sau commit) rồi mới giết tiến trình ⇒ đỏ ĐÚNG lý do
            # "không tự dừng", không lẫn với "mất dữ liệu".
            await k.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = "
                "current_database() AND $1 = ANY(pg_blocking_pids(pid))",
                pid,
            )
            p.kill()
            await p.wait()
        await gd.commit()
        if thoat is None:
            return k, (luc_chan is not None, None, None, ""), doc_duoc
        cho = None if luc_chan is None else thoat - luc_chan
        return (
            k,
            (luc_chan is not None, cho, p.returncode, out.decode("utf-8", "replace")),
            doc_duoc,
        )
    except BaseException:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await k.close()
        raise
    finally:
        await ghi.close()


def _kiem_dung_tran(do, ten_loi="HaCapChoKhoaQuaTran"):
    bi_chan, cho, rc, out = do
    assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi (%r)" % (
        out[-400:],
    )
    assert cho is not None, "hạ cấp KHÔNG tự dừng khi chờ khoá quá trần (chờ vô hạn)"
    assert rc != 0 and ten_loi in out and "chờ khoá" in out, (rc, out[-800:])
    assert TRAN_GIAY - 1.5 <= cho <= TRAN_GIAY + 5.0, (
        "dừng sau %.1f s — không phải trần" % cho
    )


# ═══════════════════════════════ hdts20261104 ═══════════════════════════════════════════════
async def test_1104_giu_khoa_qua_tran_thi_dung_khong_mat_gi(csdl_rieng):  # noqa: F811
    await _dung_1104(csdl_rieng)
    k0 = await asyncpg.connect(_url(csdl_rieng, "postgresql"))
    try:
        await _ghi_dong_nhat_ky(k0)  # một dòng ĐÃ commit từ trước
    finally:
        await k0.close()
    k, do, doc_duoc = await _giu_khoa_qua_tran(
        csdl_rieng, _ghi_dong_nhat_ky, "hdts20261103b"
    )
    try:
        assert (await _so_dong(k, VET.TAI), await _so_dong(k, VET.XOA)) == (2, 0)
        assert await _phien_ban(k) == "hdts20261104"
        _kiem_dung_tran(do)
        assert doc_duoc, "lượt đọc mới vẫn bị chặn sau khi hạ cấp dừng"
    finally:
        await k.close()


async def test_1104_co_cho_phep_xoa_van_khong_xoa_khi_qua_tran(
    csdl_rieng,
):  # noqa: F811
    await _dung_1104(csdl_rieng)
    k, do, _ = await _giu_khoa_qua_tran(
        csdl_rieng, _ghi_dong_nhat_ky, "hdts20261103b", (VET.CO_CHO_PHEP_XOA, "1")
    )
    try:
        assert (await _so_dong(k, VET.TAI), await _so_dong(k, VET.XOA)) == (1, 0)
        assert await _phien_ban(k) == "hdts20261104"
        _kiem_dung_tran(do)
    finally:
        await k.close()


# ═══════════════════════════════ hdts20261103 ═══════════════════════════════════════════════
async def test_1103_giu_khoa_qua_tran_thi_dung_khong_mat_gi(csdl_rieng):  # noqa: F811
    await _dung_1103(csdl_rieng)
    k, do, doc_duoc = await _giu_khoa_qua_tran(
        csdl_rieng, _tao_mot_bo, "v3circ20261011c"
    )
    try:
        assert [await _so_dong(k, b) for b in (BO_VB.MAU, BO_VB.BO, BO_VB.TEP)] == [
            0,
            1,
            1,
        ]
        assert await _phien_ban(k) == "hdts20261103"
        _kiem_dung_tran(do)
        assert doc_duoc, "lượt đọc mới vẫn bị chặn sau khi hạ cấp dừng"
    finally:
        await k.close()


async def test_1103_co_cho_phep_xoa_van_khong_xoa_khi_qua_tran(
    csdl_rieng,
):  # noqa: F811
    await _dung_1103(csdl_rieng)
    k, do, _ = await _giu_khoa_qua_tran(
        csdl_rieng, _tao_mot_bo, "v3circ20261011c", (BO_VB.CO_CHO_PHEP_XOA, "1")
    )
    try:
        assert [await _so_dong(k, b) for b in (BO_VB.MAU, BO_VB.BO, BO_VB.TEP)] == [
            0,
            1,
            1,
        ]
        assert await _phien_ban(k) == "hdts20261103"
        _kiem_dung_tran(do)
    finally:
        await k.close()
