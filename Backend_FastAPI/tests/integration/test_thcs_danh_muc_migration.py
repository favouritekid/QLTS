# -*- coding: utf-8 -*-
"""Danh mục THCS — migration ``thcsnb20261122`` (mã nội bộ ``NB``) trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ
qua ĐÚNG ``alembic`` (tiến trình con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn + helper: ``test_gd2a_migration.py``.

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần của migration (chỉ mục, CHECK, sequence)
⇒ mọi thứ khác y như thật. Sau nâng cấp, lược đồ phần này == CSDL dựng thẳng từ model ("migration = model"). Hạ cấp
không xoá dòng nào; nâng lại thì sequence NỐI TIẾP số lớn nhất đã cấp (không cấp trùng mã).
"""
import asyncpg
import pytest
import pytest_asyncio

from tests.integration.test_gd2a_migration import (
    _alembic,
    _create_all,
    _phien_ban,
    _tao_db,
    _url,
    _xoa_db,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRUOC = "gd2f20261119"
NB = "thcsnb20261122"
GO_NB = (
    # Bảng ghép (``thcsmap20261122``, nối SAU revision này) cũng gỡ — ``upgrade head`` sẽ tạo lại.
    "DROP TABLE thcs_school_name_mapping",
    "DROP INDEX uq_vn_school_internal_code",
    "ALTER TABLE vn_school DROP CONSTRAINT ck_vn_school_internal_code_format",
    "DROP SEQUENCE vn_school_internal_code_seq",
)


async def _luoc_do_nb(k):
    rb = await k.fetch(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'vn_school'::regclass AND conname = 'ck_vn_school_internal_code_format'"
    )
    cm = await k.fetch(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'vn_school' "
        "AND indexname = 'uq_vn_school_internal_code'"
    )
    sq = await k.fetch(
        "SELECT sequencename, start_value, min_value, max_value, increment_by, cycle FROM pg_sequences "
        "WHERE sequencename = 'vn_school_internal_code_seq'"
    )
    return [tuple(r) for r in rb], [tuple(r) for r in cm], [tuple(r) for r in sq]


@pytest_asyncio.fixture
async def csdl_truoc_nb():
    """CSDL ở phiên bản ``gd2f20261119``: lược đồ model hiện tại trừ phần mã nội bộ."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            for s in GO_NB:
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


async def _chen_nb(k, ma, xa="99001"):
    return await k.fetchval(
        "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level, commune_code) "
        "VALUES ($1, '048', 'THCS mig', 'P', 'THCS', $2) RETURNING id",
        ma, xa,
    )


async def test_nang_cap_luoc_do_khop_model_va_rang_buoc_song(csdl_truoc_nb):
    ten = csdl_truoc_nb
    rc, out = await _alembic(ten, "upgrade", NB)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        assert await _phien_ban(k) == NB
        assert await k.fetchval("SELECT nextval('vn_school_internal_code_seq')") == 1
        # CHECK sống: NB thiếu xã / sai khuôn ⇒ 23514.
        for cau in (
            "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level) "
            "VALUES ('NB000001', '048', 'X', 'P', 'THCS')",
            "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level, commune_code) "
            "VALUES ('NB12', '048', 'X', 'P', 'THCS', '99001')",
        ):
            with pytest.raises(asyncpg.PostgresError) as e:
                await k.execute(cau)
            assert e.value.sqlstate == "23514", cau
        # Chỉ mục duy nhất sống: cùng mã NB ở tỉnh khác, kể cả đã ngừng ⇒ 23505.
        await _chen_nb(k, "NB000005")
        await k.execute("UPDATE vn_school SET is_active = false WHERE moet_school_code = 'NB000005'")
        with pytest.raises(asyncpg.PostgresError) as e:
            await k.execute(
                "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level, commune_code) "
                "VALUES ('NB000005', '040', 'Y', 'P', 'THCS', '99001')"
            )
        assert e.value.sqlstate == "23505"

        # Lược đồ phần mã nội bộ == lược đồ dựng thẳng từ model.
        rc, out = await _alembic(ten, "upgrade", "head")
        assert rc == 0, out[-3000:]
        ten_mau = await _tao_db()
        try:
            await _create_all(ten_mau)
            km = await asyncpg.connect(_url(ten_mau, "postgresql"))
            try:
                mau = await _luoc_do_nb(km)
            finally:
                await km.close()
        finally:
            await _xoa_db(ten_mau)
        that = await _luoc_do_nb(k)
        for i, phan in enumerate(("ràng buộc", "chỉ mục", "sequence")):
            assert that[i] == mau[i], phan
            assert that[i], phan  # có thật, không phải hai bên cùng rỗng
    finally:
        await k.close()


async def test_ha_cap_giu_dong_nang_lai_noi_tiep_so_thu_tu(csdl_truoc_nb):
    ten = csdl_truoc_nb
    rc, out = await _alembic(ten, "upgrade", NB)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _chen_nb(k, "NB000041")
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT count(*) FROM vn_school WHERE moet_school_code = 'NB000041'") == 1
        assert await k.fetchval("SELECT to_regclass('vn_school_internal_code_seq')") is None
        assert await k.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_vn_school_internal_code_format'"
        ) == 0
        rc, out = await _alembic(ten, "upgrade", NB)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == NB
        # Số kế tiếp = 42, KHÔNG phải 1 (nếu là 1 thì về sau sẽ cấp lại NB000041).
        assert await k.fetchval("SELECT nextval('vn_school_internal_code_seq')") == 42
    finally:
        await k.close()


async def test_nang_cap_dung_khi_co_ma_NB_sai_khuon_khong_con_gi_do_dang(csdl_truoc_nb):
    ten = csdl_truoc_nb
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute(
            "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level) "
            "VALUES ('NB1', '048', 'Cũ', 'P', 'THPT')"
        )
        rc, out = await _alembic(ten, "upgrade", NB)
        assert rc != 0
        assert await _phien_ban(k) == TRUOC
        # Câu DO rollback trọn: sequence cũng không còn.
        assert await k.fetchval("SELECT to_regclass('vn_school_internal_code_seq')") is None
    finally:
        await k.close()
