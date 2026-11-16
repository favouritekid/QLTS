# -*- coding: utf-8 -*-
"""K-2 — migration ``hdts20261111`` (cài trigger khoá cấu hình) trên PostgreSQL THẬT, CSDL dùng một lần, qua ĐÚNG
``alembic`` (tiến trình con ⇒ đúng ``env.py`` AUTOCOMMIT). Đặc tả vòng giao diện bản 3 mục 2.5.1 (F274).

CSDL tối giản ở ``hdts20261105`` (khuôn ``test_council_decision_migration.py``) + hai bảng cấu hình tối giản
(``offering_academic_info`` có ràng buộc duy nhất ngành + năm, ``admission_path``) ⇒ ``alembic upgrade hdts20261107``
(bảng Quyết định) ⇒ dữ liệu một Quyết định còn hiệu lực có khoá đếm KHỚP cấu hình ⇒ các ca nâng lên ``hdts20261111``.

* ``sach`` — cài đủ 2 hàm + 2 trigger, phiên bản đổi, trigger chặn sửa năm học thật;
* ``sua_dang_mo`` — phiên sửa cấu hình (làm LỆCH, chưa commit) đang mở khi nâng cấp ⇒ nâng cấp CHỜ khoá bảng, phiên
  kia commit, rồi phép đếm (chạy SAU khoá) thấy lệch ⇒ đỏ, không cài gì, phiên bản không đổi;
* ``loi_trigger_thu_hai`` — câu cài thứ hai lỗi ⇒ KHÔNG còn hàm / trigger thứ nhất (một câu ``DO`` = một giao dịch);
* ``chay_lai`` — chết giữa câu ``DO`` và câu cập nhật phiên bản ⇒ chạy lại vẫn xanh, không trùng trigger;
* ``qua_tran_cho`` — phiên giữ khoá ghi quá trần ⇒ đỏ ``55P03``, không cài gì;
* ``ha_cap`` — gỡ hết hàm + trigger;
* ``repeatable_read_sua_dang_mo`` (F280, Codex lần 19+20) — cùng lịch với ``sua_dang_mo`` nhưng CSDL đặt mặc định REPEATABLE
  READ: ảnh chụp của câu ``DO`` chốt TRƯỚC khoá nên phép đếm sau khoá đọc dữ liệu CŨ (chưa lệch) ⇒ nếu không chặn thì trigger
  được cài dù phiên kia đã commit bản lệch. Câu ``DO`` phải TỪ CHỐI ``QLK2C``, không cài gì, phiên bản không đổi.
"""
import asyncpg
import pytest

from tests.integration.test_council_decision_migration import (  # noqa: F401
    _alembic,
    _chay_xong,
    _dung_1105,
    _ket_noi,
)
from tests.integration.test_council_document_downgrade_dong_thoi import (  # noqa: F401
    _doi_bi_chan,
    _phien_ban,
    _url,
    _xong,
    csdl_rieng,
)

pytestmark = pytest.mark.integration

DICH = "hdts20261111"
HAM = ("chan_sua_hoc_vu_da_tham_chieu", "chan_sua_duong_xet_da_tham_chieu")
TRIG = ("trg_chan_sua_hoc_vu_da_tham_chieu", "trg_chan_sua_duong_xet_da_tham_chieu")


async def _dung_1107_co_qd(ten_db):
    """CSDL ở ``hdts20261107`` + một Quyết định còn hiệu lực, dòng bộ có khoá đếm KHỚP cấu hình. Trả id học vụ X."""
    await _dung_1105(ten_db)
    k = await _ket_noi(ten_db)
    try:
        await k.execute(
            "CREATE TABLE offering_academic_info (id serial PRIMARY KEY, offering_id integer NOT NULL, "
            "academic_year integer NOT NULL, CONSTRAINT uq_offering_academic_year UNIQUE (offering_id, academic_year))"
        )
        await k.execute("CREATE TABLE admission_path (id serial PRIMARY KEY, academic_info_id integer)")
    finally:
        await k.close()
    rc, out = await _chay_xong(ten_db, "upgrade", "hdts20261107")
    assert rc == 0, out[-800:]
    k = await _ket_noi(ten_db)
    try:
        await k.execute('INSERT INTO "user" DEFAULT VALUES')
        uid = await k.fetchval('SELECT max(id) FROM "user"')
        pid = await k.fetchval("INSERT INTO admission_profile (status) VALUES ('approved') RETURNING id")
        x = await k.fetchval(
            "INSERT INTO offering_academic_info (offering_id, academic_year) VALUES (10, 2026) RETURNING id"
        )
        p = await k.fetchval("INSERT INTO admission_path (academic_info_id) VALUES ($1) RETURNING id", x)
        sid = await k.fetchval(
            "INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, kich_thuoc_tong, "
            "ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung) VALUES (now(), 'Cao đẳng', 1, 1, 1, "
            "'[\"GIA\"]'::jsonb, '[{}]'::jsonb, '{}') RETURNING id"
        )
        rid = await k.fetchval(
            "INSERT INTO council_document_set_row (set_id, stt, profile_id, academic_year, status_luc_dung, "
            "admission_path_id, academic_info_id, offering_id) VALUES ($1, 1, $2, 2026, 'approved', $3, $4, 10) "
            "RETURNING id",
            sid,
            pid,
            p,
            x,
        )
        qd = await k.fetchval(
            "INSERT INTO council_decision (loai, can_bo, set_id, so_quyet_dinh, ngay_ky, pham_vi_so, trang_thai, "
            "so_ho_so, ghi_nhan_boi_id) VALUES ('trung_tuyen', true, $1, '501', DATE '2026-09-08', 2026, "
            "'hieu_luc', 1, $2) RETURNING id",
            sid,
            uid,
        )
        await k.execute(
            "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, profile_id, stt) "
            "VALUES ($1, 'hieu_luc', $2, $3, $4, 1)",
            qd,
            sid,
            rid,
            pid,
        )
    finally:
        await k.close()
    return x


def _dong_loi(out):
    """Các dòng lỗi thật trong đầu ra alembic (bỏ nhiễu khởi động của app)."""
    return [x for x in out.splitlines() if "Error" in x or "K2" in x or "SQLSTATE" in x or "sqlstate" in x][-8:]


async def _da_cai(k):
    ham = await k.fetchval("SELECT count(*) FROM pg_proc WHERE proname = ANY($1::text[])", list(HAM))
    trig = await k.fetchval(
        "SELECT count(*) FROM pg_trigger WHERE tgname = ANY($1::text[]) AND NOT tgisinternal", list(TRIG)
    )
    return ham, trig


async def test_k2_mig_sach(csdl_rieng):  # noqa: F811
    x = await _dung_1107_co_qd(csdl_rieng)
    rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
    assert rc == 0, out[-800:]
    k = await _ket_noi(csdl_rieng)
    try:
        assert await _da_cai(k) == (2, 2)
        assert await _phien_ban(k) == DICH
        with pytest.raises(asyncpg.PostgresError) as bat:
            await k.execute("UPDATE offering_academic_info SET academic_year = 2031 WHERE id = $1", x)
        assert bat.value.sqlstate == "QLK02"
        await k.execute("UPDATE offering_academic_info SET academic_year = 2026 WHERE id = $1", x)  # không đổi ⇒ qua
    finally:
        await k.close()


async def test_k2_mig_sua_dang_mo(csdl_rieng):  # noqa: F811
    x = await _dung_1107_co_qd(csdl_rieng)
    url = _url(csdl_rieng, "postgresql")
    b = await asyncpg.connect(url)
    k = await asyncpg.connect(url)
    p = None
    try:
        gd = b.transaction()
        await gd.start()
        await b.execute("UPDATE offering_academic_info SET academic_year = 2031 WHERE id = $1", x)  # LỆCH, chưa commit
        pid_b = await b.fetchval("SELECT pg_backend_pid()")
        p = await _alembic(csdl_rieng, "upgrade", DICH)
        bi_chan = await _doi_bi_chan(k, pid_b, p)
        await gd.commit()
        rc, out = await _xong(p)
        assert bi_chan, "phép đo không hợp lệ: nâng cấp không chờ phiên sửa cấu hình"
        # Lớp che log của app in lỗi CSDL dạng ``DBError[… sqlstate=…]`` (không in chữ thông báo) ⇒ đo theo SQLSTATE
        # riêng của bước "đếm thấy lệch" (QLK2M — khác QLK02 của trigger).
        assert rc != 0 and "sqlstate=QLK2M" in out, (rc, _dong_loi(out))
        assert await _da_cai(k) == (0, 0)
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await b.close()
        await k.close()


async def test_k2_mig_repeatable_read_sua_dang_mo_thi_tu_choi(csdl_rieng):  # noqa: F811
    # F280: ở REPEATABLE READ, câu đầu tiên trong DO chốt ảnh chụp TRƯỚC khi có khoá ⇒ phép đếm sau khoá không thấy bản
    # lệch mà phiên sửa cấu hình commit trong lúc nâng cấp chờ ⇒ nếu không chặn, trigger được cài trên dữ liệu ĐÃ lệch.
    x = await _dung_1107_co_qd(csdl_rieng)
    q = await _ket_noi(csdl_rieng)
    try:
        await q.execute(
            "ALTER DATABASE \"%s\" SET default_transaction_isolation TO 'repeatable read'" % csdl_rieng
        )
    finally:
        await q.close()
    url = _url(csdl_rieng, "postgresql")
    b = await asyncpg.connect(url)
    k = await asyncpg.connect(url)
    p = None
    try:
        assert await k.fetchval("SHOW transaction_isolation") == "repeatable read", "phép đo không hợp lệ: CSDL chưa ở RR"
        gd = b.transaction()
        await gd.start()
        await b.execute("UPDATE offering_academic_info SET academic_year = 2031 WHERE id = $1", x)  # LỆCH, chưa commit
        pid_b = await b.fetchval("SELECT pg_backend_pid()")
        p = await _alembic(csdl_rieng, "upgrade", DICH)
        # Có chặn: câu DO dừng NGAY (không chờ khoá). Không chặn: nó chờ khoá của phiên sửa ⇒ commit để lịch lỗi xảy ra.
        await _doi_bi_chan(k, pid_b, p)
        await gd.commit()
        rc, out = await _xong(p)
        # Thứ tự khẳng định: dữ liệu (đã lệch thật) → không cài gì → phiên bản → mã thoát + SQLSTATE.
        assert await k.fetchval("SELECT academic_year FROM offering_academic_info WHERE id = $1", x) == 2031, (
            "phép đo không hợp lệ: bản lệch của phiên sửa cấu hình không được commit"
        )
        assert await _da_cai(k) == (0, 0), "CÀI TRIGGER dù dữ liệu đã lệch ở REPEATABLE READ (F280)"
        assert await _phien_ban(k) == "hdts20261107"
        assert rc != 0 and "sqlstate=QLK2C" in out, (rc, _dong_loi(out))
    finally:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await b.close()
        await k.close()


async def test_k2_mig_loi_trigger_thu_hai(csdl_rieng):  # noqa: F811
    await _dung_1107_co_qd(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        # Hàm cùng tên + chữ ký nhưng KHÁC kiểu trả về ⇒ CREATE OR REPLACE FUNCTION thứ hai lỗi (không đổi được
        # kiểu trả về) — SAU khi hàm thứ nhất đã tạo trong cùng câu DO.
        await k.execute(
            "CREATE FUNCTION chan_sua_duong_xet_da_tham_chieu() RETURNS integer AS 'SELECT 1' LANGUAGE sql"
        )
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        assert rc != 0, out[-800:]
        assert await k.fetchval("SELECT count(*) FROM pg_proc WHERE proname = $1", HAM[0]) == 0, (
            "hàm thứ nhất còn lại sau khi câu thứ hai lỗi — phần cài không nguyên tử"
        )
        assert await _da_cai(k) == (1, 0)  # chỉ còn hàm GIẢ do ca này tạo
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        await k.close()


async def test_k2_mig_chay_lai(csdl_rieng):  # noqa: F811
    await _dung_1107_co_qd(csdl_rieng)
    rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
    assert rc == 0, out[-800:]
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute("UPDATE alembic_version SET version_num = 'hdts20261107'")  # chết trước câu cập nhật phiên bản
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        assert rc == 0, out[-800:]
        assert await _da_cai(k) == (2, 2)
        assert await _phien_ban(k) == DICH
    finally:
        await k.close()


async def test_k2_mig_qua_tran_cho(csdl_rieng):  # noqa: F811
    await _dung_1107_co_qd(csdl_rieng)
    url = _url(csdl_rieng, "postgresql")
    b = await asyncpg.connect(url)
    k = await asyncpg.connect(url)
    try:
        gd = b.transaction()
        await gd.start()
        await b.execute("LOCK TABLE admission_path IN ROW EXCLUSIVE MODE")  # như một phiên đang ghi, giữ quá trần
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        await gd.rollback()
        assert rc != 0 and "sqlstate=55P03" in out, (rc, _dong_loi(out))
        assert await _da_cai(k) == (0, 0)
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        await b.close()
        await k.close()


async def test_k2_mig_ha_cap(csdl_rieng):  # noqa: F811
    await _dung_1107_co_qd(csdl_rieng)
    rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
    assert rc == 0, out[-800:]
    rc, out = await _chay_xong(csdl_rieng, "downgrade", "hdts20261107")
    assert rc == 0, out[-800:]
    k = await _ket_noi(csdl_rieng)
    try:
        assert await _da_cai(k) == (0, 0)
        assert await _phien_ban(k) == "hdts20261107"
    finally:
        await k.close()
