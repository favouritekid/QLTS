# -*- coding: utf-8 -*-
"""GĐ2-B (lát L1) — migration ``gd2b20261121`` trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ qua ĐÚNG ``alembic`` (tiến
trình con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn + helper: ``test_gd2a_migration.py`` (BT38).

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần GĐ2-B (``GO_GD2B`` của ``test_gd2a_migration.py`` — MỘT
danh sách cho cả hai tệp) ⇒ ở ``gd2f20261119``, mọi thứ khác y như thật. Sau nâng cấp, so lược đồ phần GĐ2-B (cột, ràng buộc, chỉ mục,
trigger, thân hàm của bốn bảng mới + ràng buộc của ``offering_admission_round``) với một CSDL dựng thẳng từ model: phép khoá
"migration = model". Hạ cấp FAIL-CLOSED khi còn dữ liệu (đúng SQLSTATE ``QLC12``); cờ CHO PHÉP đúng chữ ``1`` mới xoá. Mỗi ca kiểm
một bất biến.
"""
import asyncio
import os
import sys

import asyncpg
import pytest
import pytest_asyncio

from tests.integration.test_gd2a_migration import GO_GD2B, GOC, _create_all, _phien_ban, _tao_db, _url, _xoa_db

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRUOC = "gd2f20261119"
SAU = "gd2b20261121"
CO = "GD2B_DOWNGRADE_DROP_DATA_ENABLED"
BANG_MOI = ("admission_review_row", "admission_review_run", "admission_review_floor", "admission_review_session")
HAM = (
    "admission_review_assert_session_draft",
    "admission_review_session_guard",
    "admission_review_floor_guard",
    "admission_review_run_guard",
    "admission_review_row_guard",
)
RANG_BUOC_DOT = "uq_offering_admission_round_id_year"


async def _alembic(ten_db, lenh, dich, co=None):
    """``python -m alembic <lenh> <dich>`` trên CSDL ``ten_db``. ``co`` = giá trị đặt cho cờ CHO PHÉP hạ cấp xoá dữ liệu (``None``
    = KHÔNG đặt — kể cả khi môi trường của người chạy test có đặt)."""
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


@pytest_asyncio.fixture
async def csdl_gd2f():
    """CSDL ở phiên bản ``gd2f20261119``: lược đồ model hiện tại trừ phần GĐ2-B."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            for s in GO_GD2B:
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


async def _luoc_do(k):
    """Phần lược đồ GĐ2-B: cột, ràng buộc, chỉ mục, trigger của bốn bảng mới + ràng buộc của ``offering_admission_round``; thân
    năm hàm (chuẩn hoá khoảng trắng)."""
    bang = list(BANG_MOI)
    cot = await k.fetch(
        "SELECT table_name, column_name, data_type, is_nullable, column_default, character_maximum_length, "
        "numeric_precision, numeric_scale FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY($1) ORDER BY 1, 2",
        bang,
    )
    rb = await k.fetch(
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid::regclass::text = ANY($1) ORDER BY 1, 2",
        bang + ["offering_admission_round"],
    )
    cm = await k.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY($1) "
        "ORDER BY 1, 2",
        bang + ["offering_admission_round"],
    )
    tg = await k.fetch(
        "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
        "WHERE tgrelid::regclass::text = ANY($1) AND NOT tgisinternal ORDER BY 1, 2",
        bang,
    )
    ham = await k.fetch(
        "SELECT proname, pg_get_function_identity_arguments(oid), prosrc FROM pg_proc WHERE proname = ANY($1) ORDER BY 1",
        list(HAM),
    )
    return (
        [tuple(r) for r in cot],
        [tuple(r) for r in rb],
        [tuple(r) for r in cm],
        [tuple(r) for r in tg],
        [(r[0], r[1], " ".join(r[2].split())) for r in ham],
    )


async def _con_lai(k):
    """(số bảng mới còn, số hàm còn, ràng buộc đợt còn không)."""
    bang = 0
    for b in BANG_MOI:
        if await k.fetchval("SELECT to_regclass($1)", b) is not None:
            bang += 1
    ham = await k.fetchval("SELECT count(*) FROM pg_proc WHERE proname = ANY($1)", list(HAM))
    rb = await k.fetchval("SELECT count(*) FROM pg_constraint WHERE conname = $1", RANG_BUOC_DOT)
    return bang, ham, rb


async def _mot_lan_xet(k):
    """Dữ liệu GĐ2-B tối thiểu: người dùng, bảng chỉ tiêu 2026, đợt 2026, MỘT lần xét nháp."""
    u = await k.fetchval(
        "INSERT INTO \"user\" (username, email, password_hash, role, total_lead_score) "
        "VALUES ('gd2b_mig', 'gd2b_mig@example.com', 'x', 'admin', 0) RETURNING id"
    )
    await k.execute("INSERT INTO admission_quota_table (academic_year) VALUES (2026)")
    r = await k.fetchval(
        "INSERT INTO offering_admission_round (academic_year, round_code, round_name) VALUES (2026, 'GIA', 'Đợt giả') "
        "RETURNING id"
    )
    return await k.fetchval(
        "INSERT INTO admission_review_session (academic_year, admission_round_id, seq_no, created_by_user_id) "
        "VALUES (2026, $1, 1, $2) RETURNING id",
        r, u,
    ), u


async def test_nang_cap_tu_gd2f_luoc_do_khop_model(csdl_gd2f):
    ten = csdl_gd2f
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        assert await _phien_ban(k) == SAU
        that = await _luoc_do(k)
    finally:
        await k.close()
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
    assert all(mau), "CSDL mẫu thiếu phần GĐ2-B — model chưa được nạp?"
    for i, ten_phan in enumerate(("cột", "ràng buộc", "chỉ mục", "trigger", "thân hàm")):
        assert that[i] == mau[i], ten_phan


async def test_ha_cap_con_du_lieu_thi_dung_dung_sqlstate_khong_xoa_gi(csdl_gd2f):
    ten = csdl_gd2f
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _mot_lan_xet(k)
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc != 0
        assert "GD2BDataPresent" in out and "QLC12" in out, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT count(*) FROM admission_review_session") == 1
        assert await _con_lai(k) == (4, 5, 1)
    finally:
        await k.close()


async def test_ha_cap_co_cho_phep_khac_chu_1_van_dung(csdl_gd2f):
    """Cờ CHO PHÉP chỉ nhận ĐÚNG chữ ``1`` — ``true`` (giá trị hay gõ nhầm) vẫn rơi về CHẶN."""
    ten = csdl_gd2f
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _mot_lan_xet(k)
        rc, out = await _alembic(ten, "downgrade", TRUOC, co="true")
        assert rc != 0 and "GD2BDataPresent" in out, out[-3000:]
        assert await k.fetchval("SELECT count(*) FROM admission_review_session") == 1
    finally:
        await k.close()


async def test_ha_cap_rong_thi_go_du_va_nang_lai_duoc(csdl_gd2f):
    ten = csdl_gd2f
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await _con_lai(k) == (0, 0, 0)
        # Nâng lại được (câu DO chạy lại trên CSDL đã hạ).
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await _con_lai(k) == (4, 5, 1)
    finally:
        await k.close()


async def test_ha_cap_co_co_cho_phep_thi_xoa_ca_du_lieu_bat_bien(csdl_gd2f):
    """Cờ ``=1`` ⇒ hạ được kể cả khi có lượt ``done`` + dòng (dữ liệu trigger cấm sửa / xoá — ``DROP TABLE`` không chạy trigger
    dòng); gỡ đủ bảng, hàm, ràng buộc đợt."""
    ten = csdl_gd2f
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        sid, u = await _mot_lan_xet(k)
        rid = await k.fetchval(
            "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, started_at, "
            "inputs) VALUES ($1, 'evaluate', 'running', 'gd2b-1', $2, now(), '{}') RETURNING id",
            sid, u,
        )
        await k.execute(
            "INSERT INTO admission_review_row (run_id, profile_id, profile_status, tab, reason_codes, row_hash) "
            "VALUES ($1, 1, 'revision_requested', 'ineligible', ARRAY['status_not_in_pool'], $2)",
            rid, "a" * 64,
        )
        await k.execute(
            "UPDATE admission_review_run SET status = 'done', finished_at = now(), duration_ms = 1, summary = '{}', "
            "quota_view = '{}' WHERE id = $1",
            rid,
        )
        rc, out = await _alembic(ten, "downgrade", TRUOC, co="1")
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await _con_lai(k) == (0, 0, 0)
    finally:
        await k.close()
