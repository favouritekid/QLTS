# -*- coding: utf-8 -*-
"""GĐ2-A — migration ``gd2a20261118`` trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ qua ĐÚNG ``alembic`` (tiến trình
con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn ``test_gd1b_migration.py``.

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần GĐ2-A (3 bảng, 4 hàm + 4 trigger, ràng buộc
``uq_offering_academic_info_id_year``) ⇒ mọi thứ khác y như thật. Sau nâng cấp, so lược đồ phần GĐ2-A với một CSDL dựng
thẳng từ model: đó là phép khoá "migration = model". Hạ cấp FAIL-CLOSED khi còn dữ liệu; cờ CHO PHÉP mới xoá.
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
TRUOC = "gd1b20261117"
SAU = "gd2a20261118"
CO = "GD2A_DOWNGRADE_DROP_DATA_ENABLED"
BANG_MOI = ("admission_quota_group_member", "admission_quota_group", "admission_quota_table")
HAM = (
    "admission_quota_assert_table_unlocked",
    "chan_sua_chi_tieu_nganh_khi_bang_khoa",
    "chan_sua_nhom_chi_tieu_khi_bang_khoa",
    "chan_xoa_bang_chi_tieu_da_khoa",
)
GO_GD2A = (
    "DROP TRIGGER trg_chan_sua_chi_tieu_nganh_khi_bang_khoa ON offering_academic_info",
    "DROP TABLE admission_quota_group_member, admission_quota_group, admission_quota_table",
    "DROP FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa(), chan_sua_nhom_chi_tieu_khi_bang_khoa(), "
    "chan_xoa_bang_chi_tieu_da_khoa(), admission_quota_assert_table_unlocked(integer)",
    "ALTER TABLE offering_academic_info DROP CONSTRAINT uq_offering_academic_info_id_year",
)


def _url(ten_db, driver):
    return make_url(settings.DATABASE_URL).set(drivername=driver, database=ten_db).render_as_string(hide_password=False)


async def _tao_db():
    ten = "qlts_test_gd2a_%s" % secrets.token_hex(4)
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


async def _casbin_gd2(k):
    """Số dòng Casbin mang ``template_id`` GĐ2-0 của migration (route ghi nhận minh chứng ưu tiên bằng bản giấy)."""
    return await k.fetchval(
        "SELECT count(*) FROM casbin_rule WHERE ptype = 'p' AND template_id = '_gd2a20261118_priority_paper'"
    )


async def _luoc_do(k):
    """Phần lược đồ GĐ2-A: cột, ràng buộc, chỉ mục của 3 bảng mới + ràng buộc / trigger của ``offering_academic_info``,
    thân 4 hàm."""
    bang = list(BANG_MOI)
    cot = await k.fetch(
        "SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY($1) ORDER BY 1, 2",
        bang,
    )
    rb = await k.fetch(
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid::regclass::text = ANY($1) ORDER BY 1, 2",
        bang + ["offering_academic_info"],
    )
    cm = await k.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY($1) "
        "ORDER BY 1, 2",
        bang + ["offering_academic_info"],
    )
    tg = await k.fetch(
        "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
        "WHERE tgrelid::regclass::text = ANY($1) AND NOT tgisinternal ORDER BY 1, 2",
        bang + ["offering_academic_info"],
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
    """CSDL ở phiên bản ``gd1b20261117``: lược đồ model hiện tại trừ phần GĐ2-A."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            for s in GO_GD2A:
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


async def _hoc_vu(k, nam=2026):
    """Một học vụ tối thiểu (chế độ replica: bỏ khoá ngoại để khỏi dựng ngành / hình thức)."""
    await k.execute("SET session_replication_role = replica")
    try:
        return await k.fetchval(
            "INSERT INTO offering_academic_info (academic_year, is_published, is_deleted, offering_id, "
            "annual_admission_quota, created_at, updated_at) VALUES ($1, false, false, $2, 10, now(), now()) RETURNING id",
            nam,
            990000 + int(secrets.token_hex(2), 16),
        )
    finally:
        await k.execute("SET session_replication_role = origin")


async def test_nang_cap_luoc_do_khop_model_va_trigger_song(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        assert await _phien_ban(k) == SAU
        # GĐ2-0: hai dòng Casbin của route ghi nhận bản giấy (cán bộ allow, kế toán deny).
        assert await _casbin_gd2(k) == 2
        assert {tuple(r) for r in await k.fetch(
            "SELECT v0, v3 FROM casbin_rule WHERE template_id = '_gd2a20261118_priority_paper'"
        )} == {("role:officer", "allow"), ("role:accountant", "deny")}
        # Trigger sống sau nâng cấp: bảng khoá ⇒ sửa chỉ tiêu ngành bị chặn bằng SQLSTATE riêng.
        ai = await _hoc_vu(k)
        await k.execute("INSERT INTO admission_quota_table (academic_year) VALUES (2026)")
        g = await k.fetchval(
            "INSERT INTO admission_quota_group (academic_year, code, name, ceiling) VALUES (2026, 'N1', 'Nhóm 1', 5) "
            "RETURNING id"
        )
        await k.execute(
            "INSERT INTO admission_quota_group_member (group_id, offering_academic_info_id, academic_year) "
            "VALUES ($1, $2, 2026)",
            g, ai,
        )
        u = await k.fetchval(
            "INSERT INTO \"user\" (username, email, password_hash, role, total_lead_score) "
            "VALUES ('gd2a_mig', 'gd2a_mig@example.com', 'x', 'admin', 0) RETURNING id"
        )
        await k.execute(
            "UPDATE admission_quota_table SET status = 'locked', locked_by_user_id = $1, locked_at = now()", u
        )
        with pytest.raises(asyncpg.PostgresError) as e:
            await k.execute("UPDATE offering_academic_info SET annual_admission_quota = 11 WHERE id = $1", ai)
        assert e.value.sqlstate == "QLC01"

        # Lược đồ GĐ2-A sau nâng cấp == lược đồ dựng thẳng từ model.
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
    finally:
        await k.close()


async def test_ha_cap_con_du_lieu_thi_dung_khong_xoa_gi_rong_thi_ha_duoc_va_nang_lai_duoc(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute("INSERT INTO admission_quota_table (academic_year) VALUES (2026)")
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc != 0
        assert "GD2ADataPresent" in out, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval("SELECT count(*) FROM admission_quota_table") == 1
        assert await _casbin_gd2(k) == 2  # dừng ⇒ Casbin cũng còn nguyên
        # Rỗng ⇒ hạ được, gỡ đủ.
        await k.execute("DELETE FROM admission_quota_table")
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        for bang in BANG_MOI:
            assert await k.fetchval("SELECT to_regclass($1)", bang) is None, bang
        assert await k.fetchval("SELECT count(*) FROM pg_proc WHERE proname = ANY($1)", list(HAM)) == 0
        assert await k.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'uq_offering_academic_info_id_year'"
        ) == 0
        assert await _casbin_gd2(k) == 0
        # Nâng lại được (câu DO chạy lại trên CSDL đã hạ).
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await _casbin_gd2(k) == 2
    finally:
        await k.close()


async def test_ha_cap_co_co_cho_phep_thi_xoa(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute("INSERT INTO admission_quota_table (academic_year) VALUES (2026)")
        rc, out = await _alembic(ten, "downgrade", TRUOC, cho_phep_xoa=True)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT to_regclass('admission_quota_table')") is None
    finally:
        await k.close()
