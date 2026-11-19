# -*- coding: utf-8 -*-
"""GĐ2-F1 luật B — migration ``gd2f20261119`` trên PostgreSQL THẬT (CSDL dùng một lần), qua ĐÚNG ``alembic`` (tiến trình con).
Lượt nâng ``gd2a20261118`` → ``gd2f20261119`` → hạ về ``gd2a20261118`` → nâng lại: mỗi bước đo HÀNH VI trigger (SQL tay,
không qua dịch vụ) và so thân hàm / định nghĩa trigger với ảnh chụp tương ứng. Khuôn + helper: ``test_gd2a_migration.py``.

Dòng học vụ dựng ở chế độ replica (bỏ khoá ngoại ⇒ trigger cũng không chạy lúc DỰNG). ``INSERT`` để đo nhánh R1 không có
ngành thật ⇒ khi trigger CHO qua, lỗi kế tiếp là khoá ngoại ``23503``; khi trigger chặn là ``QLC01`` — phân biệt bằng SQLSTATE.
"""
import asyncpg
import pytest

from tests.integration.test_gd2a_migration import (  # noqa: F401 — fixture dùng qua tên
    SAU as GD2A,
    _alembic,
    _hoc_vu,
    _phien_ban,
    _url,
    csdl_truoc,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

F1 = "gd2f20261119"
TRIGGER = "trg_chan_sua_chi_tieu_nganh_khi_bang_khoa"
HAM = "chan_sua_chi_tieu_nganh_khi_bang_khoa"


async def _anh(k):
    tg = await k.fetchval(
        "SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname = $1 AND tgrelid = 'offering_academic_info'::regclass",
        TRIGGER,
    )
    than = await k.fetchval("SELECT prosrc FROM pg_proc WHERE proname = $1", HAM)
    return tg, " ".join(than.split())


async def _sqlstate(k, cau, *ts):
    """SQLSTATE của câu (None nếu chạy được)."""
    try:
        await k.execute(cau, *ts)
    except asyncpg.PostgresError as e:
        return e.sqlstate
    return None


async def _khoa_bang(k, nam):
    await k.execute("INSERT INTO admission_quota_table (academic_year) VALUES ($1)", nam)
    u = await k.fetchval(
        "INSERT INTO \"user\" (username, email, password_hash, role, total_lead_score) "
        "VALUES ('gd2f_mig', 'gd2f_mig@example.com', 'x', 'admin', 0) RETURNING id"
    )
    await k.execute(
        "UPDATE admission_quota_table SET status = 'locked', locked_by_user_id = $1, locked_at = now() "
        "WHERE academic_year = $2",
        u, nam,
    )


CHEN_CO_CHI_TIEU = (
    "INSERT INTO offering_academic_info (academic_year, is_published, is_deleted, offering_id, annual_admission_quota, "
    "created_at, updated_at) VALUES (2026, false, false, 987654321, 7, now(), now())"
)


async def test_nang_ha_nang_trigger_luat_b(csdl_truoc):
    ten = csdl_truoc
    rc, out = await _alembic(ten, "upgrade", GD2A)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        anh_gd2a = await _anh(k)
        x = await _hoc_vu(k, 2026)  # chỉ tiêu 10, năm sẽ khoá
        await _khoa_bang(k, 2026)

        rc, out = await _alembic(ten, "upgrade", F1)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == F1
        anh_f1 = await _anh(k)
        assert anh_f1 != anh_gd2a
        assert "BEFORE INSERT OR UPDATE OF annual_admission_quota, academic_year" in anh_f1[0], anh_f1[0]
        # R1: tạo học vụ CÓ chỉ tiêu cho năm khoá ⇒ trigger chặn trước cả khoá ngoại.
        assert await _sqlstate(k, CHEN_CO_CHI_TIEU) == "QLC01"
        # R3: chỉ đổi năm (chỉ tiêu giữ nguyên) RA khỏi năm khoá ⇒ chặn.
        assert await _sqlstate(k, "UPDATE offering_academic_info SET academic_year = 2025 WHERE id = $1", x) == "QLC01"

        rc, out = await _alembic(ten, "downgrade", GD2A)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == GD2A
        assert await _anh(k) == anh_gd2a
        # Trigger GĐ2-A: INSERT không chạy trigger ⇒ lỗi kế tiếp là khoá ngoại; đổi năm thuần lọt qua.
        assert await _sqlstate(k, CHEN_CO_CHI_TIEU) == "23503"
        assert await _sqlstate(k, "UPDATE offering_academic_info SET academic_year = 2025 WHERE id = $1", x) is None

        rc, out = await _alembic(ten, "upgrade", F1)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == F1
        assert await _anh(k) == anh_f1
        assert await _sqlstate(k, CHEN_CO_CHI_TIEU) == "QLC01"
        # x đang ở 2025 (lọt qua lúc hạ cấp): chuyển VÀO năm khoá ⇒ chặn lại.
        assert await _sqlstate(k, "UPDATE offering_academic_info SET academic_year = 2026 WHERE id = $1", x) == "QLC01"
        assert await k.fetchval("SELECT academic_year FROM offering_academic_info WHERE id = $1", x) == 2025
    finally:
        await k.close()
