# -*- coding: utf-8 -*-
"""GĐ2-C C2 — migration ``gd2cs20261122`` trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ qua ĐÚNG ``alembic`` (tiến trình
con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn + helper: ``test_gd2a_migration.py`` / ``test_gd2c_c1_migration.py``.

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần C2 (``GO_GD2C_C2`` của ``test_gd2a_migration.py`` — MỘT
danh sách) ⇒ ở ``gd2c20261122``, mọi thứ khác y như thật. Sau nâng cấp, so lược đồ phần C2 (cột, ràng buộc, chỉ mục, trigger, thân
hàm) với CSDL dựng thẳng từ model: phép khoá "migration = model". Dòng Casbin của route Ban thư ký có mặt ĐÚNG bộ. Hạ cấp
FAIL-CLOSED khi còn lựa chọn (đúng lớp lỗi ``GD2CC2DataPresent``); cờ CHO PHÉP đúng chữ ``1`` mới xoá; rỗng ⇒ hạ được (gỡ cả dòng
Casbin) và nâng lại được. Mỗi ca kiểm một bất biến.
"""
import asyncio
import importlib.util
import os
import sys

import asyncpg
import pytest
import pytest_asyncio

from tests.integration.test_gd2a_migration import GO_GD2C_C2, GOC, _create_all, _phien_ban, _tao_db, _url, _xoa_db

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRUOC = "gd2c20261122"
SAU = "gd2cs20261122"
CO = "GD2C_C2_DOWNGRADE_DROP_DATA_ENABLED"
BANG = "admission_review_selection"
HAM = ("admission_review_selection_guard",)
NAM = 2026


def _mig():
    spec = importlib.util.spec_from_file_location(
        "_gd2c_c2_mig_tich_hop", GOC / "alembic" / "versions" / "gd2cs20261122_review_selection.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def _alembic(ten_db, lenh, dich, co=None):
    """``python -m alembic <lenh> <dich>`` trên CSDL ``ten_db``. ``co`` = giá trị cờ CHO PHÉP hạ cấp xoá dữ liệu (``None`` = KHÔNG
    đặt — kể cả khi môi trường của người chạy test có đặt)."""
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(ten_db, "postgresql+asyncpg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop(CO, None)
    if co is not None:
        env[CO] = co
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", lenh, dich, cwd=str(GOC), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(p.communicate(), 180)
    return p.returncode, out.decode("utf-8", "replace")


async def _luoc_do(k):
    """Phần lược đồ C2: cột, ràng buộc, chỉ mục, trigger của bảng mới + thân hàm."""
    cot = await k.fetch(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 ORDER BY 1",
        BANG,
    )
    rb = await k.fetch(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid::regclass::text = $1 ORDER BY 1", BANG
    )
    cm = await k.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = $1 ORDER BY 1", BANG
    )
    tg = await k.fetch(
        "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE tgrelid::regclass::text = $1 AND NOT tgisinternal "
        "ORDER BY 1",
        BANG,
    )
    ham = await k.fetch("SELECT proname, prosrc FROM pg_proc WHERE proname = ANY($1) ORDER BY 1", list(HAM))
    return (
        [tuple(r) for r in cot],
        [tuple(r) for r in rb],
        [tuple(r) for r in cm],
        [tuple(r) for r in tg],
        [(r[0], " ".join(r[1].split())) for r in ham],
    )


async def _casbin(k):
    return {
        tuple(r)
        for r in await k.fetch(
            "SELECT v0, v1, v2, v3 FROM casbin_rule WHERE ptype = 'p' AND template_id = $1", _mig().CASBIN_TEMPLATE_ID
        )
    }


@pytest_asyncio.fixture
async def csdl_truoc():
    """CSDL ở phiên bản ``gd2c20261122``: lược đồ model hiện tại trừ phần C2."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            for s in GO_GD2C_C2:
                await k.execute(s)
            await k.execute(
                "CREATE TABLE alembic_version (version_num varchar(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await k.execute("INSERT INTO alembic_version VALUES ($1)", TRUOC)
        finally:
            await k.close()
        yield ten
    finally:
        await _xoa_db(ten)


async def _mot_lua_chon(k) -> int:
    """Dữ liệu giả tối thiểu: người, bảng chỉ tiêu, đợt, lần xét nháp, một lượt ``done`` có một dòng ``ineligible`` (hồ sơ giả 9001),
    rồi MỘT lựa chọn "Loại khỏi lần này" (có lý do) dựa đúng dòng ấy. Trả id lựa chọn."""
    u = await k.fetchval(
        "INSERT INTO \"user\" (username, email, password_hash, role, total_lead_score) "
        "VALUES ('gd2c_c2_mig', 'gd2c_c2_mig@example.com', 'x', 'admin', 0) RETURNING id"
    )
    await k.execute("INSERT INTO admission_quota_table (academic_year) VALUES ($1)", NAM)
    dot = await k.fetchval(
        "INSERT INTO offering_admission_round (academic_year, round_code, round_name) VALUES ($1, 'GIA-C2', 'Đợt giả') "
        "RETURNING id",
        NAM,
    )
    sid = await k.fetchval(
        "INSERT INTO admission_review_session (academic_year, admission_round_id, seq_no, created_by_user_id) "
        "VALUES ($1, $2, 1, $3) RETURNING id",
        NAM, dot, u,
    )
    rid = await k.fetchval(
        "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, started_at, inputs) "
        "VALUES ($1, 'evaluate', 'running', 'gd2b-1', $2, now(), CAST('{}' AS jsonb)) RETURNING id",
        sid, u,
    )
    await k.execute(
        "INSERT INTO admission_review_row (run_id, profile_id, profile_status, tab, reason_codes, row_hash) "
        "VALUES ($1, 9001, 'revision_requested', 'ineligible', ARRAY['status_not_in_pool'], $2)",
        rid, "a" * 64,
    )
    await k.execute(
        "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 5, "
        "summary = CAST('{}' AS jsonb), quota_view = CAST('{}' AS jsonb) WHERE id = $1",
        rid,
    )
    return await k.fetchval(
        "INSERT INTO admission_review_selection (session_id, academic_year, profile_id, kind, based_on_run_id, "
        "based_on_row_hash, decided_by_user_id, note) VALUES ($1, $2, 9001, 'exclude_this_session', $3, $4, $5, 'Lý do giả') "
        "RETURNING id",
        sid, NAM, rid, "a" * 64, u,
    )


async def test_nang_cap_luoc_do_khop_model_trigger_song_va_dong_casbin(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        assert await _phien_ban(k) == SAU
        # Trigger sống sau nâng cấp: chèn lựa chọn vào lần xét không có ⇒ hàm kiểm "nháp" của GĐ2-B chặn TRƯỚC khoá ngoại.
        with pytest.raises(asyncpg.PostgresError) as e:
            await k.execute(
                "INSERT INTO admission_review_selection (session_id, academic_year, profile_id, kind, based_on_run_id, "
                "based_on_row_hash, decided_by_user_id) VALUES (999999, 2026, 1, 'consider_next_choice', 1, $1, 1)",
                "a" * 64,
            )
        assert e.value.sqlstate == "QLC02"
        assert await _casbin(k) == set(_mig().CASBIN_POLICIES)

        ten_mau = await _tao_db()
        try:
            await _create_all(ten_mau)
            km = await asyncpg.connect(_url(ten_mau, "postgresql"))
            try:
                mau = await _luoc_do(km)
            finally:
                await km.close()
        finally:
            await _xoa_db(ten_mau)
        that = await _luoc_do(k)
        for i, ten_phan in enumerate(("cột", "ràng buộc", "chỉ mục", "trigger", "thân hàm")):
            assert that[i] == mau[i], ten_phan
        assert mau[0] and mau[3], "tiền đề: CSDL mẫu có bảng + trigger (so hai danh sách rỗng là xanh giả)"
    finally:
        await k.close()


async def test_ha_cap_con_lua_chon_thi_dung_khong_xoa_gi_rong_thi_ha_duoc_va_nang_lai_duoc(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _mot_lua_chon(k)
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc != 0
        assert "GD2CC2DataPresent" in out, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT count(*) FROM admission_review_selection") == 1
        assert await _casbin(k) == set(_mig().CASBIN_POLICIES)  # dừng ⇒ Casbin cũng còn nguyên
        # Rỗng ⇒ hạ được, gỡ đủ. (Trigger chặn DELETE từng dòng — dọn bằng TRUNCATE, như lệnh dọn của bộ test.)
        await k.execute("TRUNCATE admission_review_selection")
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is None
        assert await k.fetchval("SELECT count(*) FROM pg_proc WHERE proname = ANY($1)", list(HAM)) == 0
        assert await _casbin(k) == set()
        # Nâng lại được (câu DO chạy lại trên CSDL đã hạ).
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is not None
        assert await _casbin(k) == set(_mig().CASBIN_POLICIES)
    finally:
        await k.close()


@pytest.mark.parametrize("gia_tri", ["true", "0"])
async def test_co_ha_cap_khac_chu_1_van_dung(csdl_truoc, gia_tri):
    """Cờ CHO PHÉP chỉ nhận ĐÚNG chữ ``1`` — ``true`` / ``0`` vẫn là KHÔNG cho phép (fail-closed)."""
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _mot_lua_chon(k)
        rc, out = await _alembic(ten, "downgrade", TRUOC, co=gia_tri)
        assert rc != 0 and "GD2CC2DataPresent" in out, out[-3000:]
        assert await k.fetchval("SELECT count(*) FROM admission_review_selection") == 1
    finally:
        await k.close()


async def test_ha_cap_co_co_cho_phep_thi_xoa(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _mot_lua_chon(k)
        rc, out = await _alembic(ten, "downgrade", TRUOC, co="1")
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is None
    finally:
        await k.close()
