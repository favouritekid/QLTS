# -*- coding: utf-8 -*-
"""Lượt I (F230) — migration ``hdts20261107`` trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ qua
ĐÚNG ``alembic`` (tiến trình con ⇒ đúng ``env.py`` AUTOCOMMIT), HAI PHIÊN, đo ở tầng CSDL từ phiên khác
(CLAUDE.md §10). Khuôn ``test_council_document_downgrade_dong_thoi.py`` / ``…_cho_khoa.py`` (F222, F227).

CSDL dựng tối giản: ``user`` + ``organization_unit`` + ``admission_profile`` (khoá ngoại đích) + đúng
``upgrade()`` của ``hdts20261103`` (bảng bộ) ⇒ ``alembic_version`` = ``hdts20261105`` ⇒ ``alembic upgrade
hdts20261107`` chỉ chạy migration của lượt I.
"""
import asyncio
import os
import sys
import time

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import council_document as m
from tests.integration.test_council_document_downgrade_dong_thoi import (  # noqa: F401
    BO_VB,
    GOC,
    HAI_CO,
    _chay,
    _doi_bi_chan,
    _nap,
    _phien_ban,
    _so_dong,
    _url,
    _xong,
    csdl_rieng,
)

pytestmark = pytest.mark.integration

MIG = _nap("hdts20261107_council_decision.py", "hdts20261107_tich_hop")
BANG = MIG.BANG_MOI_THU_TU_XOA
TRAN_GIAY = 10.0


async def _dung_1105(ten_db):
    """CSDL ở phiên bản ``hdts20261105`` (chỉ những bảng migration lượt I cần)."""
    eng = create_async_engine(_url(ten_db, "postgresql+asyncpg"), poolclass=NullPool)
    try:
        async with eng.begin() as conn:
            for s in (
                'CREATE TABLE "user" (id serial PRIMARY KEY)',
                "CREATE TABLE organization_unit (id serial PRIMARY KEY)",
                "CREATE TABLE admission_profile (id serial PRIMARY KEY, status varchar(32))",
            ):
                await conn.execute(text(s))
            await conn.run_sync(_chay, BO_VB)
            await conn.execute(
                text(
                    "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL, "
                    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                )
            )
            await conn.execute(text("INSERT INTO alembic_version VALUES ('hdts20261105')"))
    finally:
        await eng.dispose()


async def _alembic(ten_db, lenh, dich, co=None):
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(ten_db, "postgresql+asyncpg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in HAI_CO + (MIG.CO_CHO_PHEP_XOA,):
        env.pop(k, None)
    if co is not None:
        env[co[0]] = co[1]
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        lenh,
        dich,
        cwd=str(GOC),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )


async def _chay_xong(ten_db, lenh, dich, co=None):
    return await _xong(await _alembic(ten_db, lenh, dich, co))


async def _len_1107(ten_db):
    await _dung_1105(ten_db)
    rc, out = await _chay_xong(ten_db, "upgrade", "hdts20261107")
    assert rc == 0, out[-800:]


async def _ket_noi(ten_db):
    return await asyncpg.connect(_url(ten_db, "postgresql"))


async def _co_cot(k, cot):
    return await k.fetchval(
        "SELECT count(*) FROM information_schema.columns WHERE table_name = "
        "'council_document_set' AND column_name = $1",
        cot,
    )


async def _chen_su_kien(k):
    await k.execute(
        "INSERT INTO council_document_event (loai, so_lieu) VALUES ('ghi_nhan', '{}')"
    )


async def _kiem_du_rang_buoc(k):
    """Mọi ràng buộc có tên + chỉ mục ``uq_`` của sáu lớp mới đều có trên CSDL thật."""
    ten = {
        r["conname"]
        for r in await k.fetch(
            "SELECT conname FROM pg_constraint WHERE conname LIKE 'ck\\_council\\_%' "
            "OR conname LIKE 'uq\\_council\\_%' OR conname LIKE 'fk\\_council\\_%'"
        )
    } | {
        r["indexname"]
        for r in await k.fetch(
            "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'uq\\_council\\_%'"
        )
    }
    can = set()
    for lop in (
        m.CouncilDocumentSetRow,
        m.CouncilDecision,
        m.CouncilDecisionRow,
        m.CouncilDecisionScan,
        m.CouncilDecisionHold,
        m.CouncilDocumentEvent,
    ):
        can |= {c.name for c in lop.__table__.constraints if c.name}
        can |= {i.name for i in lop.__table__.indexes if i.name.startswith("uq_")}
    assert "ck_council_decision_row_k5c" in can  # F257
    assert can <= ten, sorted(can - ten)
    # Biểu thức chỉ mục U3 trên CSDL thật = hằng của model (PostgreSQL chuẩn hoá chữ).
    dinh_nghia = await k.fetchval(
        "SELECT pg_get_indexdef('uq_council_decision_row_u3_ho_so'::regclass)"
    )
    assert "trang_thai_cha" in dinh_nghia and "bi_bo_boi_id IS NULL" in dinh_nghia


async def _luoc_do(k):
    """Ảnh chụp LƯỢC ĐỒ (không dữ liệu): phiên bản Alembic, bốn cột mới của bộ, sáu bảng mới, số ràng buộc
    ``*_council_decision*`` — để ghi trạng thái nâng cấp dở vào log."""
    return {
        "phien_ban": await _phien_ban(k),
        "cot_moi": {c: await _co_cot(k, c) for c in MIG.COT_MOI_CUA_BO},
        "bang_moi": {
            b: (await k.fetchval("SELECT to_regclass($1)", b)) is not None for b in BANG
        },
        "so_rang_buoc_qd": await k.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE conname LIKE '%council\\_decision%'"
        ),
    }


# ═══════════════════════════════ nâng cấp ═══════════════════════════════════════════════════
async def test_nang_cap_tao_du_bang_rang_buoc_va_chay_lai_khong_loi(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        assert await _phien_ban(k) == "hdts20261107"
        for b in BANG:
            assert await _so_dong(k, b) == 0, b
        for cot in MIG.COT_MOI_CUA_BO:
            assert await _co_cot(k, cot) == 1, cot
        await _kiem_du_rang_buoc(k)
    finally:
        await k.close()
    # chạy lại phần câu DO của nâng cấp (IF NOT EXISTS) ⇒ không lỗi, không trùng ràng buộc
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute(MIG._sql_them_cot_bo())
        assert (
            await k.fetchval(
                "SELECT count(*) FROM pg_constraint WHERE conname = "
                "'ck_council_document_set_ban_ky_du'"
            )
            == 1
        )
    finally:
        await k.close()


async def test_nang_cap_cho_khoa_bang_bo_qua_tran_thi_dung_khong_doi_gi(csdl_rieng):  # noqa: F811
    await _dung_1105(csdl_rieng)
    ghi = await _ket_noi(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    p = None
    try:
        gd = ghi.transaction()
        await gd.start()
        await ghi.execute("LOCK TABLE council_document_set IN ROW EXCLUSIVE MODE")
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        t0 = time.monotonic()
        p = await _alembic(csdl_rieng, "upgrade", "hdts20261107")
        assert await _doi_bi_chan(k, pid, p), "phép đo không hợp lệ: nâng cấp không bị chặn"
        rc, out = await asyncio.wait_for(_xong(p), 60)
        troi = time.monotonic() - t0
        await gd.rollback()
        assert rc != 0 and "NangCapChoKhoaQuaTran" in out, (rc, out[-800:])
        assert TRAN_GIAY - 1 <= troi <= TRAN_GIAY + 25, troi
        assert await _phien_ban(k) == "hdts20261105"
        assert await _co_cot(k, "ban_ky_ngay") == 0
        assert await _so_dong(k, "council_decision") is None
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await ghi.close()
        await k.close()


async def test_nang_cap_cho_khoa_bang_ho_so_qua_tran_thi_dung_roi_chay_lai_toi_head(  # noqa: F811
    csdl_rieng,
):
    """F258 — qua ĐÚNG ``alembic`` (tiến trình con, ``env.py`` AUTOCOMMIT): phiên khác giữ ROW EXCLUSIVE trên
    ``admission_profile`` (giao dịch GHI đang mở) ⇒ ``CREATE TABLE`` có khoá ngoại tới hồ sơ phải dừng
    trong trần (mã thoát ≠ 0, không treo); nhả khoá ⇒ chạy lại tới head, lược đồ đủ. Ca có trần thời gian
    RIÊNG (``_xong``: 50 s) ⇒ mã gỡ trần thì ca ĐỎ vì hết giờ, không treo cả lượt."""
    await _dung_1105(csdl_rieng)
    ghi = await _ket_noi(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    p = None
    try:
        gd = ghi.transaction()
        await gd.start()
        await ghi.execute("INSERT INTO admission_profile (status) VALUES ('draft')")
        assert (
            await ghi.fetchval(
                "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND granted AND "
                "mode = 'RowExclusiveLock' AND relation = 'admission_profile'::regclass"
            )
            == 1
        ), "phép đo không hợp lệ: phiên ghi không giữ ROW EXCLUSIVE trên admission_profile"
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        t0 = time.monotonic()
        p = await _alembic(csdl_rieng, "upgrade", "hdts20261107")
        assert await _doi_bi_chan(k, pid, p), "phép đo không hợp lệ: nâng cấp không chờ khoá hồ sơ"
        rc, out = await asyncio.wait_for(_xong(p), 60)
        troi = time.monotonic() - t0
        giua = await _luoc_do(k)
        print("F258-NANG-CAP-DO rc=%s troi=%.1fs luoc_do=%s" % (rc, troi, giua))
        assert rc != 0 and "NangCapChoKhoaQuaTran" in out, (rc, out[-800:])
        assert "chạy lại" in out, out[-800:]
        assert TRAN_GIAY - 1 <= troi <= TRAN_GIAY + 25, troi
        # Trạng thái nâng cấp DỞ (ghi rõ): phiên bản chưa đổi; câu DO (bốn cột) đã commit; bảng mới đầu tiên
        # (khoá ngoại tới hồ sơ) chưa tạo.
        assert giua["phien_ban"] == "hdts20261105"
        assert all(v == 1 for v in giua["cot_moi"].values()), giua
        assert not any(giua["bang_moi"].values()), giua
        assert await ghi.fetchval("SELECT count(*) FROM admission_profile") == 1  # phiên ghi không bị huỷ
        await gd.rollback()
        rc2, out2 = await _chay_xong(csdl_rieng, "upgrade", "hdts20261107")
        sau = await _luoc_do(k)
        print("F258-CHAY-LAI rc=%s luoc_do=%s" % (rc2, sau))
        assert rc2 == 0, out2[-800:]
        assert sau["phien_ban"] == "hdts20261107"
        assert all(sau["bang_moi"].values()) and all(v == 1 for v in sau["cot_moi"].values()), sau
        await _kiem_du_rang_buoc(k)
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await ghi.close()
        await k.close()


#: Mốc thời gian (KHÔNG phải khoá): trigger sự kiện DDL làm lệnh tạo bảng mới THỨ BA (``council_decision_row``)
#: NGỦ ở đầu lệnh (``ddl_command_start`` — trước khi lệnh lấy khoá nào) ⇒ cửa sổ xác định để phiên GHI lấy khoá
#: trên bảng mới thứ HAI (``council_decision``) SAU khi nó đã commit. Khoá chặn là của phiên GHI thật.
_TRIGGER_NGU = (
    "CREATE OR REPLACE FUNCTION f258_ngu_truoc_bang_thu_ba() RETURNS event_trigger LANGUAGE plpgsql AS $f$\n"
    "BEGIN\n"
    "    IF current_query() ILIKE '%CREATE TABLE IF NOT EXISTS council_decision_row (%' THEN\n"
    "        PERFORM pg_sleep(4);\n"
    "    END IF;\n"
    "END $f$;\n"
    "CREATE EVENT TRIGGER f258_ngu_truoc_bang_thu_ba ON ddl_command_start WHEN TAG IN ('CREATE TABLE')\n"
    "    EXECUTE FUNCTION f258_ngu_truoc_bang_thu_ba();"
)


async def _kiem_du_chi_muc(k):
    """MỌI chỉ mục (có tên) của sáu lớp mới đều có trên CSDL thật — chạy lại sau khi dừng giữa chừng không bỏ sót
    chỉ mục của bảng đã tạo ở lần trước (``IF NOT EXISTS`` từng lệnh)."""
    co = {r["indexname"] for r in await k.fetch("SELECT indexname FROM pg_indexes")}
    can = set()
    for lop in (
        m.CouncilDocumentSetRow,
        m.CouncilDecision,
        m.CouncilDecisionRow,
        m.CouncilDecisionScan,
        m.CouncilDecisionHold,
        m.CouncilDocumentEvent,
    ):
        can |= {i.name for i in lop.__table__.indexes if i.name}
    assert len(can) >= 15, sorted(can)
    assert can <= co, sorted(can - co)


async def test_nang_cap_dung_sau_hai_bang_moi_da_commit_roi_chay_lai_toi_head(csdl_rieng):  # noqa: F811
    """F258 bổ sung (Codex lần 15 câu 4) — qua ĐÚNG ``alembic`` (tiến trình con, ``env.py`` AUTOCOMMIT): nâng cấp
    dừng SAU KHI hai bảng mới (``council_document_set_row``, ``council_decision``) + chỉ mục của chúng đã COMMIT,
    vì phiên GHI giữ ROW EXCLUSIVE trên ``council_decision`` (khuôn một giao dịch đang ghi bảng ấy) chặn bước
    tạo bảng thứ ba (khoá ngoại tới ``council_decision`` cần SHARE ROW EXCLUSIVE) ⇒ quá trần ⇒ mã thoát ≠ 0. Nhả
    khoá ⇒ chạy lại tới head; lược đồ ĐỦ (mọi ràng buộc + mọi chỉ mục) — bằng chứng cho ``IF NOT EXISTS`` ở mọi
    lệnh của phần đã tạo. Trần thời gian riêng (``_xong``: 50 s)."""
    await _dung_1105(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    ghi = await _ket_noi(csdl_rieng)
    p = None
    gd = None
    try:
        await k.execute(_TRIGGER_NGU)
        p = await _alembic(csdl_rieng, "upgrade", "hdts20261107")
        het = time.monotonic() + 40
        ngu = 0
        while time.monotonic() < het and p.returncode is None:
            ngu = await k.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event = 'PgSleep' AND query ILIKE '%council_decision_row (%'"
            )
            if ngu:
                break
            await asyncio.sleep(0.05)
        assert ngu, "phép đo không hợp lệ: nâng cấp không tới bước tạo bảng thứ ba"
        truoc = await _luoc_do(k)
        assert sorted(b for b, co in truoc["bang_moi"].items() if co) == sorted(
            ["council_document_set_row", "council_decision"]
        ), truoc
        gd = ghi.transaction()
        await gd.start()
        await ghi.execute("LOCK TABLE council_decision IN ROW EXCLUSIVE MODE")
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        assert await _doi_bi_chan(k, pid, p), "phép đo không hợp lệ: bước tạo bảng thứ ba không chờ phiên ghi"
        rc, out = await asyncio.wait_for(_xong(p), 60)
        giua = await _luoc_do(k)
        print("F258-DUNG-SAU-HAI-BANG rc=%s luoc_do=%s" % (rc, giua))
        assert rc != 0 and "NangCapChoKhoaQuaTran" in out, (rc, out[-800:])
        assert giua["phien_ban"] == "hdts20261105"
        assert sorted(b for b, co in giua["bang_moi"].items() if co) == sorted(
            ["council_document_set_row", "council_decision"]
        ), giua
        await gd.rollback()
        gd = None
        await k.execute("DROP EVENT TRIGGER f258_ngu_truoc_bang_thu_ba")
        rc2, out2 = await _chay_xong(csdl_rieng, "upgrade", "hdts20261107")
        sau = await _luoc_do(k)
        print("F258-CHAY-LAI-SAU-HAI-BANG rc=%s luoc_do=%s" % (rc2, sau))
        assert rc2 == 0, out2[-800:]
        assert sau["phien_ban"] == "hdts20261107"
        assert all(sau["bang_moi"].values()) and all(v == 1 for v in sau["cot_moi"].values()), sau
        await _kiem_du_rang_buoc(k)
        await _kiem_du_chi_muc(k)
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        if gd is not None:
            await gd.rollback()
        await k.execute("DROP EVENT TRIGGER IF EXISTS f258_ngu_truoc_bang_thu_ba")
        await ghi.close()
        await k.close()


# ═══════════════════════════════ hạ cấp fail-closed ═════════════════════════════════════════
async def test_ha_cap_bang_moi_con_hang_thi_dung_khong_xoa_gi(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await _chen_su_kien(k)
        rc, out = await _chay_xong(csdl_rieng, "downgrade", "hdts20261105")
        assert rc != 0 and "ConDuLieuQuyetDinh" in out, (rc, out[-800:])
        assert await _so_dong(k, "council_document_event") == 1
        assert all([await _so_dong(k, b) is not None for b in BANG])
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        await k.close()


async def test_ha_cap_cot_moi_cua_bo_con_gia_tri_thi_dung(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute(
            "INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, "
            "kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung, "
            "cho_quyet_dinh_goc_id) VALUES (now(), 'Cao đẳng', 1, 1, 1, '[\"GIA\"]', '[{}]', "
            "'{}', 7)"
        )
        rc, out = await _chay_xong(csdl_rieng, "downgrade", "hdts20261105")
        assert rc != 0 and "ConDuLieuQuyetDinh" in out, (rc, out[-800:])
        assert await _co_cot(k, "cho_quyet_dinh_goc_id") == 1
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        await k.close()


async def test_ha_cap_co_cho_phep_sai_chu_van_dung(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await _chen_su_kien(k)
        for gt in ("true", "yes", " 1"):
            rc, out = await _chay_xong(
                csdl_rieng, "downgrade", "hdts20261105", (MIG.CO_CHO_PHEP_XOA, gt)
            )
            assert rc != 0 and "ConDuLieuQuyetDinh" in out, (gt, rc, out[-400:])
        assert await _so_dong(k, "council_document_event") == 1
    finally:
        await k.close()


async def test_ha_cap_co_cho_phep_thi_xoa_bang_va_cot(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await _chen_su_kien(k)
        rc, out = await _chay_xong(
            csdl_rieng, "downgrade", "hdts20261105", (MIG.CO_CHO_PHEP_XOA, "1")
        )
        assert rc == 0, out[-800:]
        assert all([await _so_dong(k, b) is None for b in BANG])
        for cot in MIG.COT_MOI_CUA_BO:
            assert await _co_cot(k, cot) == 0, cot
        assert await _phien_ban(k) == "hdts20261105"
        assert await _so_dong(k, "council_document_set") == 0  # bảng cũ còn
    finally:
        await k.close()


async def test_ha_cap_rong_thi_xoa_va_nang_lai_duoc(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    rc, out = await _chay_xong(csdl_rieng, "downgrade", "hdts20261105")
    assert rc == 0, out[-800:]
    rc, out = await _chay_xong(csdl_rieng, "upgrade", "hdts20261107")
    assert rc == 0, out[-800:]
    k = await _ket_noi(csdl_rieng)
    try:
        assert await _phien_ban(k) == "hdts20261107"
        assert all([await _so_dong(k, b) == 0 for b in BANG])
    finally:
        await k.close()


async def test_ha_cap_repeatable_read_thi_tu_choi_khong_mat_gi(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute(
            "ALTER DATABASE \"%s\" SET default_transaction_isolation TO 'repeatable read'"
            % csdl_rieng
        )
        rc, out = await _chay_xong(
            csdl_rieng, "downgrade", "hdts20261105", (MIG.CO_CHO_PHEP_XOA, "1")
        )
        assert rc != 0 and "HaCapCanReadCommitted" in out, (rc, out[-800:])
        assert all([await _so_dong(k, b) is not None for b in BANG])
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        await k.close()


async def test_ha_cap_ghi_chen_vao_thi_khong_mat_dong(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    ghi = await _ket_noi(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    p = None
    try:
        gd = ghi.transaction()
        await gd.start()
        await _chen_su_kien(ghi)
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        p = await _alembic(csdl_rieng, "downgrade", "hdts20261105")
        bi_chan = await _doi_bi_chan(k, pid, p)
        await gd.commit()
        rc, out = await _xong(p)
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không chờ phiên ghi"
        assert await _so_dong(k, "council_document_event") == 1, "MẤT dòng đã commit"
        assert rc != 0 and "ConDuLieuQuyetDinh" in out, (rc, out[-800:])
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await ghi.close()
        await k.close()


async def test_ha_cap_cho_khoa_qua_tran_thi_dung_ke_ca_co_cho_phep(csdl_rieng):  # noqa: F811
    await _len_1107(csdl_rieng)
    ghi = await _ket_noi(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    p = None
    try:
        gd = ghi.transaction()
        await gd.start()
        await _chen_su_kien(ghi)
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        t0 = time.monotonic()
        p = await _alembic(
            csdl_rieng, "downgrade", "hdts20261105", (MIG.CO_CHO_PHEP_XOA, "1")
        )
        assert await _doi_bi_chan(k, pid, p), "phép đo không hợp lệ"
        rc, out = await asyncio.wait_for(_xong(p), 60)
        troi = time.monotonic() - t0
        await gd.commit()
        assert rc != 0 and "HaCapChoKhoaQuaTran" in out, (rc, out[-800:])
        assert TRAN_GIAY - 1 <= troi <= TRAN_GIAY + 25, troi
        assert await _so_dong(k, "council_document_event") == 1
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await ghi.close()
        await k.close()
