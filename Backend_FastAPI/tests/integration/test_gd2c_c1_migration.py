# -*- coding: utf-8 -*-
"""GĐ2-C C1 — migration ``gd2c20261122`` trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ qua ĐÚNG ``alembic`` (tiến trình
con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn ``test_gd2a_migration.py``.

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần C1 (bảng quyền Thư ký, hàm + trigger "chỉ thu hồi")
⇒ mọi thứ khác y như thật. Sau nâng cấp, so lược đồ phần C1 với một CSDL dựng thẳng từ model: phép khoá "migration = model".
Hạ cấp FAIL-CLOSED khi còn dòng quyền; cờ CHO PHÉP mới xoá; rỗng ⇒ hạ được và nâng lại được.
"""
import asyncio
import os
import secrets
import sys
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url

from app.config import settings
from app.models.base import Base
from tests.fixtures.database import kiem_url_csdl_test

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

GOC = Path(__file__).resolve().parents[2]
TRUOC = "gd2f20261119"
SAU = "gd2c20261122"
CO = "GD2C_C1_DOWNGRADE_DROP_DATA_ENABLED"
BANG = "admission_review_secretary_grant"
HAM = ("admission_review_secretary_grant_revoke_only",)
GO_C1 = (
    "DROP TABLE admission_review_secretary_grant",
    "DROP FUNCTION admission_review_secretary_grant_revoke_only()",
)


def _url(ten_db, driver):
    return make_url(settings.DATABASE_URL).set(drivername=driver, database=ten_db).render_as_string(hide_password=False)


async def _tao_db():
    ten = "qlts_test_gd2c_%s" % secrets.token_hex(4)
    assert kiem_url_csdl_test(_url(ten, "postgresql+asyncpg")) is None
    q = await asyncpg.connect(_url(make_url(settings.DATABASE_URL).database, "postgresql"))
    try:
        await q.execute('CREATE DATABASE "%s"' % ten)
    finally:
        await q.close()
    return ten


async def _xoa_db(ten):
    q = await asyncpg.connect(_url(make_url(settings.DATABASE_URL).database, "postgresql"))
    try:
        await q.execute('DROP DATABASE IF EXISTS "%s" WITH (FORCE)' % ten)
    finally:
        await q.close()


async def _create_all(ten):
    from types import SimpleNamespace

    from casbin_async_sqlalchemy_adapter import Base as CasbinBase

    from tests.fixtures.database import init_schema_once

    await init_schema_once(SimpleNamespace(DATABASE_URL=_url(ten, "postgresql+asyncpg")), Base, CasbinBase)


async def _alembic(ten_db, lenh, dich, cho_phep_xoa=False):
    env = dict(os.environ)
    env["DATABASE_URL"] = _url(ten_db, "postgresql+asyncpg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop(CO, None)
    if cho_phep_xoa:
        env[CO] = "1"
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", lenh, dich, cwd=str(GOC), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await asyncio.wait_for(p.communicate(), 180)
    return p.returncode, out.decode("utf-8", "replace")


async def _phien_ban(k):
    return await k.fetchval("SELECT version_num FROM alembic_version")


async def _luoc_do(k):
    """Phần lược đồ C1: cột, ràng buộc, chỉ mục, trigger của bảng mới + thân hàm."""
    cot = await k.fetch(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 ORDER BY 1",
        BANG,
    )
    rb = await k.fetch(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid::regclass::text = $1 ORDER BY 1",
        BANG,
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


@pytest_asyncio.fixture
async def csdl_truoc():
    """CSDL ở phiên bản ``gd2f20261119``: lược đồ model hiện tại trừ phần C1."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            for s in GO_C1:
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


async def _hai_nguoi(k):
    ra = []
    for ten, vai in (("gd2c_mig_u", "officer"), ("gd2c_mig_a", "admin")):
        ra.append(
            await k.fetchval(
                "INSERT INTO \"user\" (username, email, password_hash, role, total_lead_score) "
                "VALUES ($1, $1 || '@example.com', 'x', $2, 0) RETURNING id",
                ten, vai,
            )
        )
    return ra


async def test_nang_cap_luoc_do_khop_model_va_trigger_song(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        assert await _phien_ban(k) == SAU
        u, a = await _hai_nguoi(k)
        g = await k.fetchval(
            "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES ($1, $2, 'x') "
            "RETURNING id",
            u, a,
        )
        # Trigger sống sau nâng cấp: xoá dòng quyền bị chặn bằng SQLSTATE riêng.
        with pytest.raises(asyncpg.PostgresError) as e:
            await k.execute("DELETE FROM admission_review_secretary_grant WHERE id = $1", g)
        assert e.value.sqlstate == "QLC20"

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
        assert mau[0], "tiền đề: CSDL mẫu có bảng (so hai danh sách rỗng là xanh giả)"
    finally:
        await k.close()


async def test_ha_cap_con_du_lieu_thi_dung_khong_xoa_gi_rong_thi_ha_duoc_va_nang_lai_duoc(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        u, a = await _hai_nguoi(k)
        await k.execute(
            "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES ($1, $2, 'x')", u, a
        )
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc != 0
        assert "GD2CC1DataPresent" in out, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT count(*) FROM admission_review_secretary_grant") == 1
        # Rỗng ⇒ hạ được, gỡ đủ. (Trigger chặn DELETE từng dòng — dọn bằng TRUNCATE, như lệnh dọn của bộ test.)
        await k.execute("TRUNCATE admission_review_secretary_grant")
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is None
        assert await k.fetchval("SELECT count(*) FROM pg_proc WHERE proname = ANY($1)", list(HAM)) == 0
        # Nâng lại được (câu DO chạy lại trên CSDL đã hạ).
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is not None
    finally:
        await k.close()


async def test_ha_cap_co_co_cho_phep_thi_xoa(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        u, a = await _hai_nguoi(k)
        await k.execute(
            "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES ($1, $2, 'x')", u, a
        )
        rc, out = await _alembic(ten, "downgrade", TRUOC, cho_phep_xoa=True)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is None
    finally:
        await k.close()
