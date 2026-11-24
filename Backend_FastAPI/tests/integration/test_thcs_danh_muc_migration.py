# -*- coding: utf-8 -*-
"""Danh mục THCS — migration ``thcsnb20261122`` (mã nội bộ ``NB``) trên PostgreSQL THẬT (CSDL dùng một lần), nâng / hạ
qua ĐÚNG ``alembic`` (tiến trình con ⇒ đúng ``env.py`` AUTOCOMMIT). Khuôn + helper: ``test_gd2a_migration.py``.

CSDL trước nâng cấp = ``create_all()`` của model HIỆN TẠI rồi gỡ ĐÚNG phần của migration (chỉ mục, CHECK, sequence)
⇒ mọi thứ khác y như thật. Sau nâng cấp, lược đồ phần này == CSDL dựng thẳng từ model ("migration = model"). Hạ cấp
không xoá dòng nào; nâng lại thì sequence NỐI TIẾP số lớn nhất đã cấp (không cấp trùng mã).
"""
import importlib.util

import asyncpg
import pytest
import pytest_asyncio

from tests.integration.test_gd2a_migration import (
    GOC,
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


# ---------- đối tượng CÙNG TÊN đã có: so định nghĩa, lệch ⇒ dừng (rà 23-11 F3) ----------


def _mig_nb():
    spec = importlib.util.spec_from_file_location(
        NB, GOC / "alembic" / "versions" / "thcsnb20261122_vn_school_internal_code.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ba_doi_tuong_dung():
    """Ba câu tạo ĐÚNG như migration (sequence, CHECK, chỉ mục)."""
    mig = _mig_nb()
    return {
        "seq": mig.SQL_CREATE_SEQUENCE,
        "ck": "ALTER TABLE vn_school ADD CONSTRAINT ck_vn_school_internal_code_format CHECK (%s)" % mig.SQL_CK_INTERNAL_CODE,
        "cm": "CREATE UNIQUE INDEX uq_vn_school_internal_code ON vn_school (moet_school_code) WHERE %s"
        % mig.SQL_UQ_INTERNAL_CODE_WHERE,
    }


async def test_doi_tuong_da_co_dung_dinh_nghia_thi_nang_cap_qua(csdl_truoc_nb):
    """Đối chứng (CLAUDE.md chung §3): ba đối tượng dựng ĐÚNG câu của migration ⇒ nhánh "đã có" KHỚP, nâng qua — nên
    các ca lệch bên dưới đỏ vì biến thể, không phải vì phép so luôn đỏ."""
    ten = csdl_truoc_nb
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        for cau in _ba_doi_tuong_dung().values():
            await k.execute(cau)
        rc, out = await _alembic(ten, "upgrade", NB)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == NB
    finally:
        await k.close()


@pytest.mark.parametrize(
    "phan,thay_tu,thay_bang,ma",
    [
        # Mỗi biến thể lệch ĐÚNG MỘT đối tượng, kiểu tinh vi nhất (cùng tên, gần như cùng câu).
        ("seq", "MAXVALUE 999999", "MAXVALUE 9999999", "QLT02"),
        # Rà Codex 23-11 F'1 (cùng lớp "gộp mất thông tin"): CACHE > 1 ⇒ mỗi phiên giữ trước 20 số; OWNED BY ⇒ xoá cột
        # kéo theo xoá sequence. Model khai sequence ĐỘC LẬP, cache 1.
        ("seq", "START WITH 1 NO CYCLE", "START WITH 1 CACHE 20 NO CYCLE", "QLT02"),
        ("seq", " NO CYCLE", " NO CYCLE OWNED BY vn_school.moet_school_code", "QLT02"),
        ("ck", " AND commune_code IS NOT NULL", "", "QLT03"),  # NB… không còn bắt buộc mã xã
        ("cm", "CREATE UNIQUE INDEX", "CREATE INDEX", "QLT04"),  # mất tính duy nhất
    ],
    ids=[
        "sequence_maxvalue",
        "sequence_cache",
        "sequence_thuoc_cot",
        "check_bo_dieu_kien_ma_xa",
        "chi_muc_khong_duy_nhat",
    ],
)
async def test_doi_tuong_da_co_lech_dinh_nghia_thi_dung_khong_ghi_head(csdl_truoc_nb, phan, thay_tu, thay_bang, ma):
    ten = csdl_truoc_nb
    cau = _ba_doi_tuong_dung()
    assert thay_tu in cau[phan]  # tiền đề: biến thể thật sự đổi câu
    cau[phan] = cau[phan].replace(thay_tu, thay_bang, 1)
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        for c in cau.values():
            await k.execute(c)
        rc, out = await _alembic(ten, "upgrade", NB)
        assert rc != 0
        assert "ExistingObjectMismatch" in out and ma in out, out[-3000:]  # đỏ ĐÚNG lý do, đúng đối tượng
        assert await _phien_ban(k) == TRUOC
    finally:
        await k.close()


# ---------- ``setval`` không hoàn tác theo giao dịch: phải là câu ghi CUỐI, chỉ tiến (rà Codex 23-11 F'1) ----------

_DOC_SEQ = "SELECT last_value, is_called FROM vn_school_internal_code_seq"


@pytest.mark.parametrize(
    "lam_hong,dau_hieu",
    [
        ("lech_check", "QLT03"),  # đối tượng ĐÃ có lệch ⇒ RAISE ở pha kiểm
        ("lech_chi_muc", "QLT04"),  # cùng thế, đối tượng kiểm SAU CÙNG
        # CHECK chưa có + dòng cũ sai khuôn ⇒ ``ALTER TABLE … ADD CONSTRAINT`` đổ ở pha TẠO (sau mọi phép kiểm).
        ("tao_check_do", "sqlstate=23514"),
    ],
    ids=["lech_check", "lech_chi_muc", "tao_check_do"],
)
async def test_cau_do_do_thi_sequence_da_co_giu_nguyen_gia_tri(csdl_truoc_nb, lam_hong, dau_hieu):
    """Sequence ĐÃ có (đúng định nghĩa) + có trường ``NB000041`` ⇒ migration CẦN đưa sequence tới 41. Một đối tượng
    khác lệch, hoặc một câu tạo đổ ⇒ câu ``DO`` lùi; ``setval`` thì KHÔNG lùi theo giao dịch ⇒ sequence phải giữ
    NGUYÊN (``last_value``, ``is_called``). Bản trước gọi ``setval`` ngay sau phép kiểm sequence, TRƯỚC phép kiểm
    CHECK / chỉ mục ⇒ cả ba ca đỏ; bản gọi ``setval`` sau pha kiểm nhưng TRƯỚC pha tạo ⇒ ca ``tao_check_do`` đỏ."""
    ten = csdl_truoc_nb
    cau = _ba_doi_tuong_dung()
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute(cau["seq"])
        await _chen_nb(k, "NB000041")
        if lam_hong == "lech_check":
            sai = cau["ck"].replace(" AND commune_code IS NOT NULL", "", 1)
            assert sai != cau["ck"]
            await k.execute(sai)
        elif lam_hong == "lech_chi_muc":
            sai = cau["cm"].replace("CREATE UNIQUE INDEX", "CREATE INDEX", 1)
            assert sai != cau["cm"]
            await k.execute(sai)
        else:
            await k.execute(
                "INSERT INTO vn_school (moet_school_code, moet_province_code, name, province, level) "
                "VALUES ('NB1', '048', 'Cũ', 'P', 'THPT')"
            )
        truoc = tuple(await k.fetchrow(_DOC_SEQ))
        # Tiền đề: số kế tiếp (1) ≤ số lớn nhất đã cấp (41) ⇒ một ``setval`` chạy sớm chắc chắn ĐỔI giá trị.
        assert truoc == (1, False)
        rc, out = await _alembic(ten, "upgrade", NB)
        assert rc != 0
        assert dau_hieu in out, out[-3000:]  # đổ ĐÚNG chỗ
        if dau_hieu.startswith("QLT"):
            assert "ExistingObjectMismatch" in out, out[-3000:]
        assert await _phien_ban(k) == TRUOC
        assert tuple(await k.fetchrow(_DOC_SEQ)) == truoc
        # Không đối tượng nào được tạo (chỉ còn đúng thứ đã dựng tay trước khi nâng).
        assert await k.fetchval(
            "SELECT count(*) FROM pg_constraint WHERE conname = 'ck_vn_school_internal_code_format'"
        ) == (1 if lam_hong == "lech_check" else 0)
        co_chi_muc = await k.fetchval("SELECT to_regclass('uq_vn_school_internal_code')") is not None
        assert co_chi_muc == (lam_hong == "lech_chi_muc")
    finally:
        await k.close()


@pytest.mark.parametrize(
    "dat_truoc,so_ke_tiep",
    [
        (None, 42),  # sequence (1, chưa gọi) đi SAU số lớn nhất 41 ⇒ tiến tới 41
        (100, 101),  # sequence đã ở 100 (đi TRƯỚC) ⇒ giữ nguyên, KHÔNG lùi về 41 (lùi ⇒ cấp lại 42..100)
    ],
    ids=["di_sau_thi_tien_toi_so_lon_nhat", "di_truoc_thi_giu_nguyen"],
)
async def test_sequence_da_co_khop_chi_tien_khong_lui(csdl_truoc_nb, dat_truoc, so_ke_tiep):
    """Đối chứng đường XANH của pha 3: sequence ĐÃ có, khớp định nghĩa; mọi kiểm qua ⇒ ``setval`` chỉ khi số kế tiếp
    ≤ số lớn nhất đã cấp. Bản "chỉ ``setval`` khi tự tạo sequence" ⇒ ca đầu đỏ (kế tiếp = 1); bản ``setval`` vô điều
    kiện (cho lùi, như bản trước) ⇒ ca sau đỏ (kế tiếp = 42)."""
    ten = csdl_truoc_nb
    k = await asyncpg.connect(_url(ten, "postgresql"))
    try:
        await k.execute(_ba_doi_tuong_dung()["seq"])
        if dat_truoc is not None:
            await k.execute("SELECT setval('vn_school_internal_code_seq', $1, true)", dat_truoc)
        await _chen_nb(k, "NB000041")
        rc, out = await _alembic(ten, "upgrade", NB)
        assert rc == 0, out[-3000:]
        assert await _phien_ban(k) == NB
        assert await k.fetchval("SELECT nextval('vn_school_internal_code_seq')") == so_ke_tiep
    finally:
        await k.close()
