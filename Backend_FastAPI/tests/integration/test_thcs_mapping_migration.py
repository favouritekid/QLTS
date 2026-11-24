# -*- coding: utf-8 -*-
"""Công cụ ghép tên trường THCS — migration ``thcsmap20261122`` (bảng ghép) trên PostgreSQL THẬT (CSDL dùng một lần),
qua ĐÚNG ``alembic`` (tiến trình con). Khuôn + helper: ``test_gd2a_migration.py``.

Sau nâng cấp: lược đồ bảng ghép == CSDL dựng thẳng từ model. Hạ cấp FAIL-CLOSED: còn dòng ghép ⇒ dừng, không xoá gì;
cờ CHO PHÉP ``THCS_MAPPING_DOWNGRADE_DROP_DATA_ENABLED=1`` mới xoá.
"""
import asyncio
import os
import sys

import asyncpg
import pytest
import pytest_asyncio

from tests.integration.test_gd2a_migration import (
    GOC,
    _create_all,
    _phien_ban,
    _tao_db,
    _url,
    _xoa_db,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRUOC = "thcsnb20261122"
SAU = "thcsmap20261122"
CO = "THCS_MAPPING_DOWNGRADE_DROP_DATA_ENABLED"
BANG = "thcs_school_name_mapping"


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


async def _luoc_do(k):
    cot = await k.fetch(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = $1 ORDER BY 1",
        BANG,
    )
    rb = await k.fetch(
        "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid::regclass::text = $1 ORDER BY 1",
        BANG,
    )
    cm = await k.fetch("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = $1 ORDER BY 1", BANG)
    return [tuple(r) for r in cot], [tuple(r) for r in rb], [tuple(r) for r in cm]


@pytest_asyncio.fixture
async def csdl_truoc_map():
    """CSDL ở phiên bản ``thcsnb20261122``: lược đồ model hiện tại trừ bảng ghép."""
    ten = await _tao_db()
    try:
        await _create_all(ten)
        k = await asyncpg.connect(_url(ten, "postgresql"))
        try:
            await k.execute(f"DROP TABLE {BANG}")
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


async def _mot_dong_ghep(k):
    u = await k.fetchval(
        "INSERT INTO \"user\" (username, email, password_hash, role, total_lead_score) "
        "VALUES ('thcsmap_mig', 'thcsmap_mig@example.com', 'x', 'admin', 0) RETURNING id"
    )
    s = await k.fetchval(
        "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level, commune_code) "
        "VALUES ('NB000001', '048', 'THCS mig', 'P', 'THCS', '99001') RETURNING id"
    )
    await k.execute(
        f"INSERT INTO {BANG} (normalized_name, school_id, mapped_by_user_id) VALUES ('lê lợi', $1, $2)", s, u
    )


async def test_nang_cap_luoc_do_khop_model_va_rang_buoc_song(csdl_truoc_map):
    ten = csdl_truoc_map
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        assert await _phien_ban(k) == SAU
        await _mot_dong_ghep(k)
        with pytest.raises(asyncpg.PostgresError) as e:  # một tên chỉ một trường
            await k.execute(
                f"INSERT INTO {BANG} (normalized_name, school_id, mapped_by_user_id) "
                f"SELECT normalized_name, school_id, mapped_by_user_id FROM {BANG}"
            )
        assert e.value.sqlstate == "23505"
        with pytest.raises(asyncpg.PostgresError) as e:  # tên rỗng
            await k.execute(
                f"INSERT INTO {BANG} (normalized_name, school_id, mapped_by_user_id) "
                f"SELECT '  ', school_id, mapped_by_user_id FROM {BANG}"
            )
        assert e.value.sqlstate == "23514"
        with pytest.raises(asyncpg.PostgresError) as e:  # trường đang được ghép không xoá cứng được
            await k.execute("DELETE FROM vn_school")
        assert e.value.sqlstate == "23503"

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
        for i, phan in enumerate(("cột", "ràng buộc", "chỉ mục")):
            assert that[i] == mau[i], phan
            assert that[i], phan
    finally:
        await k.close()


async def test_ha_cap_con_dong_ghep_thi_dung_khong_xoa_co_cho_phep_moi_xoa(csdl_truoc_map):
    ten = csdl_truoc_map
    rc, out = await _alembic(ten, "upgrade", SAU)
    assert rc == 0, out[-3000:]
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await _mot_dong_ghep(k)
        rc, out = await _alembic(ten, "downgrade", TRUOC)
        assert rc != 0
        assert "ThcsMappingDataPresent" in out, out[-3000:]
        assert await _phien_ban(k) == SAU
        assert await k.fetchval(f"SELECT count(*) FROM {BANG}") == 1
        rc, out = await _alembic(ten, "downgrade", TRUOC, cho_phep_xoa=True)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval("SELECT to_regclass($1)", BANG) is None
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU
    finally:
        await k.close()


# ---------- bảng CÙNG TÊN đã có: so định nghĩa, lệch ⇒ dừng (rà 23-11 F3) ----------


def _mig_map():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        SAU, GOC / "alembic" / "versions" / "thcsmap20261122_thcs_school_name_mapping.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cau_tao_dung() -> list[str]:
    mig = _mig_map()
    return [mig.CREATE_TABLE, *mig.CREATE_INDEXES]


async def test_bang_da_co_dung_dinh_nghia_thi_nang_cap_qua(csdl_truoc_map):
    """Đối chứng (CLAUDE.md chung §3): bảng dựng ĐÚNG câu của migration ⇒ nhánh "đã có" KHỚP, nâng qua."""
    ten = csdl_truoc_map
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        for cau in _cau_tao_dung():
            await k.execute(cau)
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == SAU
    finally:
        await k.close()


@pytest.mark.parametrize(
    "vi_tri,thay_tu,thay_bang",
    [
        # Mỗi biến thể lệch ĐÚNG MỘT chỗ (bảng / cột / ràng buộc / khoá ngoại / chỉ mục), kiểu tinh vi nhất.
        (0, "normalized_name VARCHAR(255) NOT NULL", "normalized_name VARCHAR(200) NOT NULL"),
        (0, "CHECK (length(btrim(normalized_name)) > 0)", "CHECK (length(normalized_name) > 0)"),
        (0, "REFERENCES vn_school (id) ON DELETE RESTRICT", "REFERENCES vn_school (id) ON DELETE CASCADE"),
        (2, "ON thcs_school_name_mapping (school_id)", "ON thcs_school_name_mapping (school_id, mapped_at)"),
        # Rà Codex 23-11 F'1 — các ca bản trước cho "khớp":
        # collation khác (UNIQUE / chỉ mục vẫn in y hệt; chỉ chữ ký cột thấy được);
        (0, "normalized_name VARCHAR(255) NOT NULL", 'normalized_name VARCHAR(255) COLLATE "C" NOT NULL'),
        # bảng UNLOGGED (mất dữ liệu khi máy chủ sập; cột / ràng buộc / chỉ mục y hệt);
        (0, "CREATE TABLE thcs_school_name_mapping (", "CREATE UNLOGGED TABLE thcs_school_name_mapping ("),
        # khoá ngoại trì hoãn: đúng ca Codex nêu, và ca tinh vi hơn — DEFERRABLE nhưng INITIALLY IMMEDIATE (mặc định
        # vẫn kiểm ngay, chỉ ``SET CONSTRAINTS … DEFERRED`` mới dời) ⇒ chỉ phép so ``condeferrable`` bắt được.
        (
            0,
            "REFERENCES vn_school (id) ON DELETE RESTRICT",
            "REFERENCES vn_school (id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
        ),
        (
            0,
            'REFERENCES "user" (id) ON DELETE RESTRICT',
            'REFERENCES "user" (id) ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE',
        ),
        # hai thuộc tính đã so từ bản trước nhưng chưa có ca nào canh.
        (
            0,
            "REFERENCES vn_school (id) ON DELETE RESTRICT",
            "REFERENCES vn_school (id) ON DELETE RESTRICT ON UPDATE CASCADE",
        ),
        (0, 'REFERENCES "user" (id) ON DELETE RESTRICT', 'REFERENCES "user" (id) MATCH FULL ON DELETE RESTRICT'),
    ],
    ids=[
        "cot_do_dai",
        "check_bo_btrim",
        "khoa_ngoai_cascade",
        "chi_muc_them_cot",
        "cot_collation_c",
        "bang_unlogged",
        "khoa_ngoai_tri_hoan",
        "khoa_ngoai_co_the_tri_hoan",
        "khoa_ngoai_on_update_cascade",
        "khoa_ngoai_match_full",
    ],
)
async def test_bang_da_co_lech_dinh_nghia_thi_dung_khong_ghi_head(csdl_truoc_map, vi_tri, thay_tu, thay_bang):
    ten = csdl_truoc_map
    cau = _cau_tao_dung()
    assert thay_tu in cau[vi_tri]  # tiền đề: biến thể thật sự đổi câu
    cau[vi_tri] = cau[vi_tri].replace(thay_tu, thay_bang, 1)
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        for c in cau:
            await k.execute(c)
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc != 0
        assert "ExistingTableMismatch" in out and "QLT05" in out, out[-3000:]
        assert await _phien_ban(k) == TRUOC
    finally:
        await k.close()


# ---------- mặc định ``nextval`` của cột ``id``: so ĐÍCH DANH sequence (rà Codex 23-11 F'1) ----------

_SEQ = "thcs_school_name_mapping_id_seq"  # tên PostgreSQL đặt cho BIGSERIAL của bảng thật
_THAM_SO_SEQ = (
    "(SELECT row(seqtypid, seqstart, seqincrement, seqmin, seqmax, seqcache, seqcycle) FROM pg_sequence "
    "WHERE seqrelid = '%s'::regclass)"
)
_THUOC_COT_ID = (
    "EXISTS (SELECT 1 FROM pg_depend WHERE classid = 'pg_class'::regclass AND objid = '%s'::regclass "
    "AND refclassid = 'pg_class'::regclass AND refobjid = 'thcs_school_name_mapping'::regclass AND deptype = 'a' "
    "AND refobjsubid = (SELECT attnum FROM pg_attribute "
    "WHERE attrelid = 'thcs_school_name_mapping'::regclass AND attname = 'id'))"
)
_MAC_DINH_ID = (
    "(SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d JOIN pg_attribute a "
    "ON a.attrelid = d.adrelid AND a.attnum = d.adnum "
    "WHERE d.adrelid = 'thcs_school_name_mapping'::regclass AND a.attname = 'id')"
)


@pytest.mark.parametrize(
    "cau_sua,tien_de",
    [
        # Trỏ sang một sequence KHÁC mà cùng MỌI tham số và cũng THUỘC cột id ⇒ chữ "nextval" giống, tham số giống, sở
        # hữu giống — chỉ phép so ĐÍCH DANH (tên chuẩn + schema) bắt được. Biến thể tinh vi nhất của "trỏ nhầm".
        (
            (
                "CREATE SEQUENCE thcsmap_seq_khac AS bigint OWNED BY thcs_school_name_mapping.id",
                "ALTER TABLE thcs_school_name_mapping ALTER COLUMN id "
                "SET DEFAULT nextval('thcsmap_seq_khac'::regclass)",
            ),
            "SELECT %s = %s AND %s AND %s AND %s LIKE '%%thcsmap_seq_khac%%'"
            % (
                _THAM_SO_SEQ % "thcsmap_seq_khac",
                _THAM_SO_SEQ % _SEQ,
                _THUOC_COT_ID % "thcsmap_seq_khac",
                _THUOC_COT_ID % _SEQ,
                _MAC_DINH_ID,
            ),
        ),
        # Đúng sequence, đúng tên, đúng tham số — nhưng KHÔNG thuộc cột (DROP TABLE sẽ bỏ sót nó).
        (
            ("ALTER SEQUENCE %s OWNED BY NONE" % _SEQ,),
            "SELECT NOT %s AND %s LIKE '%%%s%%'" % (_THUOC_COT_ID % _SEQ, _MAC_DINH_ID, _SEQ),
        ),
        # Đúng sequence, đúng sở hữu — tham số khác (trần kiểu int trên cột bigint).
        (
            ("ALTER SEQUENCE %s MAXVALUE 2147483647" % _SEQ,),
            "SELECT %s AND (SELECT seqmax FROM pg_sequence WHERE seqrelid = '%s'::regclass) = 2147483647"
            % (_THUOC_COT_ID % _SEQ, _SEQ),
        ),
    ],
    ids=["tro_sequence_khac_cung_tham_so_cung_so_huu", "sequence_khong_thuoc_cot", "sequence_maxvalue_khac"],
)
async def test_bang_da_co_sequence_cua_cot_id_lech_thi_dung(csdl_truoc_map, cau_sua, tien_de):
    """Bản trước thu mọi mặc định ``nextval(...)`` về MỘT chữ ⇒ cả ba ca đều "khớp", nâng qua, ghi head. Ca đối
    chứng ``test_bang_da_co_dung_dinh_nghia_thi_nang_cap_qua`` + mọi test nâng ``create_all → head`` canh chiều ngược
    lại (phép so không được luôn lệch)."""
    ten = csdl_truoc_map
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        for c in (*_cau_tao_dung(), *cau_sua):
            await k.execute(c)
        assert await k.fetchval(tien_de) is True  # tiền đề: biến thể lệch ĐÚNG chỗ định canh, không hơn
        rc, out = await _alembic(ten, "upgrade", SAU)
        assert rc != 0
        assert "ExistingTableMismatch" in out and "QLT05" in out, out[-3000:]
        assert await _phien_ban(k) == TRUOC
    finally:
        await k.close()
