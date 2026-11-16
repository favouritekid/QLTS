# -*- coding: utf-8 -*-
"""Migration ``hdts20261112`` (bảng lượt gửi ghi nhận) trên PostgreSQL THẬT, CSDL dùng một lần, qua ĐÚNG ``alembic`` (tiến
trình con ⇒ đúng ``env.py`` AUTOCOMMIT). Phiên song song B (qlts-c3) phát hiện: trước tệp này 1112 KHÔNG có phép đo nào qua
Alembic thật (chỉ so chuỗi model ↔ migration). Khuôn ``test_council_config_lock_migration.py``.

* ``sach`` — đủ bảng, 13 ràng buộc ĐÚNG TÊN, 2 chỉ mục; CHECK / UNIQUE một phần chạy thật; phiên bản = 1112;
* ``chay_lai`` — chết giữa câu ``DO`` và câu cập nhật phiên bản ⇒ chạy lại xanh, không trùng gì;
* ``loi_giua_chung`` — câu tạo chỉ mục lỗi SAU khi bảng đã tạo trong cùng câu ``DO`` (event trigger chặn CREATE INDEX) ⇒
  KHÔNG còn bảng (một câu = một giao dịch);
* ``bang_co_san_du_cot_thieu_rang_buoc`` — bảng cùng tên có sẵn đủ cột cho chỉ mục nhưng thiếu ràng buộc ⇒ ``IF NOT
  EXISTS`` bỏ qua, bước KIỂM HÌNH chặn ⇒ đỏ ``QLLG2`` (trước bản vá: xanh im lặng); ``…_thieu_cot`` — thiếu cột ⇒ đỏ
  ``42703`` ngay ở câu tạo chỉ mục;
* ``qua_tran_cho`` — phiên giữ khoá ghi bảng bộ (đích khoá ngoại) quá trần ⇒ đỏ ``55P03``, không có bảng;
* ``ha_cap_rong`` / ``ha_cap_con_dong`` — hạ cấp xoá bảng rỗng; còn dòng ⇒ đỏ ``QLLG1``, bảng + dòng còn nguyên.
* F277 (Codex lần 18) — HAI PHIÊN: phiên ghi INSERT một lượt CHƯA commit → hạ cấp qua alembic thật → đợi tới khi tiến
  trình hạ cấp bị CHÍNH phiên ghi chặn (``pg_blocking_pids``) → commit ⇒ bảng + dòng còn, đỏ ``QLLG1`` (khuôn cũ đếm
  trước khi khoá: đếm 0 → DROP chờ → commit → DROP chạy ⇒ MẤT dòng); đối chứng phiên ghi huỷ ⇒ hạ cấp xoá bảng rỗng;
  REPEATABLE READ (ảnh chụp chốt trước khoá) ⇒ đỏ ``QLLG3``, không xoá gì.

Lớp che log của app in lỗi CSDL dạng ``DBError[… sqlstate=…]`` ⇒ đo đầu ra theo ``sqlstate=``.
"""
import asyncpg
import pytest

from tests.integration.test_council_config_lock_migration import _dung_1107_co_qd, _dong_loi  # noqa: F401
from tests.integration.test_council_decision_migration import _alembic, _chay_xong, _ket_noi  # noqa: F401
from tests.integration.test_council_document_downgrade_dong_thoi import (  # noqa: F401
    _doi_bi_chan,
    _phien_ban,
    _url,
    _xong,
    csdl_rieng,
)

pytestmark = pytest.mark.integration

DICH = "hdts20261112"
TRUOC = "hdts20261111"
BANG = "council_decision_submission"
RANG_BUOC = {
    "council_decision_submission_pkey",
    "fk_council_decision_submission_set",
    "fk_council_decision_submission_decision",
    "fk_council_decision_submission_nguoi_tao",
    "uq_council_decision_submission_ma",
    "uq_council_decision_submission_decision",
    "ck_council_decision_submission_trang_thai",
    "ck_council_decision_submission_qd",
    "ck_council_decision_submission_sha",
    "ck_council_decision_submission_sha_hex",
    "ck_council_decision_submission_ket_thuc",
    "ck_council_decision_submission_cho_co_bo",
    "ck_council_decision_submission_bo_khop",
}
CHI_MUC = {"uq_council_decision_submission_cho_gui", "ix_council_decision_submission_set_id_luc_tao"}


async def _len_1111(ten_db):
    await _dung_1107_co_qd(ten_db)
    rc, out = await _chay_xong(ten_db, "upgrade", TRUOC)
    assert rc == 0, _dong_loi(out)


async def _hinh(k):
    co = await k.fetchval("SELECT to_regclass($1) IS NOT NULL", BANG)
    if not co:
        return False, set(), set()
    rb = {r["conname"] for r in await k.fetch("SELECT conname FROM pg_constraint WHERE conrelid = to_regclass($1)", BANG)}
    cm = {r["indexname"] for r in await k.fetch("SELECT indexname FROM pg_indexes WHERE tablename = $1", BANG)}
    return True, rb, cm


async def _bo_id(k):
    return await k.fetchval("SELECT min(id) FROM council_document_set")


async def test_lg_mig_sach(csdl_rieng):  # noqa: F811
    await _len_1111(csdl_rieng)
    rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
    assert rc == 0, _dong_loi(out)
    k = await _ket_noi(csdl_rieng)
    try:
        co, rb, cm = await _hinh(k)
        assert co and RANG_BUOC <= rb and CHI_MUC <= cm, (rb, cm)
        assert await _phien_ban(k) == DICH
        s, u = await _bo_id(k), await k.fetchval('SELECT min(id) FROM "user"')
        await k.execute(
            "INSERT INTO council_decision_submission (ma, set_id, set_id_luc_tao, trang_thai, nguoi_tao_id) "
            "VALUES (gen_random_uuid(), $1, $1, 'cho_gui', $2)", s, u
        )
        with pytest.raises(asyncpg.UniqueViolationError):  # mỗi bộ tối đa một lượt chưa rõ
            await k.execute(
                "INSERT INTO council_decision_submission (ma, set_id, set_id_luc_tao, trang_thai, nguoi_tao_id) "
                "VALUES (gen_random_uuid(), $1, $1, 'cho_gui', $2)", s, u
            )
        with pytest.raises(asyncpg.CheckViolationError):  # da_ghi mà không có văn bản
            await k.execute(
                "INSERT INTO council_decision_submission (ma, set_id, set_id_luc_tao, trang_thai, nguoi_tao_id, "
                "ket_thuc_luc) VALUES (gen_random_uuid(), $1, $1, 'da_ghi', $2, now())", s, u
            )
    finally:
        await k.close()


async def test_lg_mig_chay_lai(csdl_rieng):  # noqa: F811
    await _len_1111(csdl_rieng)
    assert (await _chay_xong(csdl_rieng, "upgrade", DICH))[0] == 0
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute("UPDATE alembic_version SET version_num = $1", TRUOC)
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        assert rc == 0, _dong_loi(out)
        co, rb, cm = await _hinh(k)
        assert co and RANG_BUOC <= rb and CHI_MUC <= cm
        assert await _phien_ban(k) == DICH
    finally:
        await k.close()


async def test_lg_mig_loi_giua_chung_khong_de_lai_bang(csdl_rieng):  # noqa: F811
    await _len_1111(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute(
            "CREATE FUNCTION gia_chan_tao_chi_muc() RETURNS event_trigger AS $$ BEGIN "
            "RAISE EXCEPTION 'gia: chan tao chi muc'; END $$ LANGUAGE plpgsql"
        )
        await k.execute(
            "CREATE EVENT TRIGGER gia_et_chan_chi_muc ON ddl_command_start WHEN TAG IN ('CREATE INDEX') "
            "EXECUTE FUNCTION gia_chan_tao_chi_muc()"
        )
        try:
            rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        finally:
            await k.execute("DROP EVENT TRIGGER gia_et_chan_chi_muc")
        assert rc != 0, _dong_loi(out)
        assert (await _hinh(k))[0] is False, "bảng còn lại sau khi câu tạo chỉ mục lỗi — phần tạo không nguyên tử"
        assert await _phien_ban(k) == TRUOC
    finally:
        await k.close()


async def test_lg_mig_bang_co_san_du_cot_thieu_rang_buoc_thi_dung(csdl_rieng):  # noqa: F811
    # Ca IM LẶNG thật: bảng cùng tên có sẵn CÓ đủ cột mà hai chỉ mục cần (set_id, trang_thai, set_id_luc_tao) nhưng KHÔNG
    # có ràng buộc ⇒ CREATE TABLE IF NOT EXISTS bỏ qua, hai CREATE INDEX vẫn chạy được ⇒ không có bước KIỂM HÌNH thì
    # migration "xanh" với một bảng không CHECK / không khoá ngoại. Bước kiểm hình ⇒ đỏ QLLG2, cả câu lùi.
    await _len_1111(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute(
            "CREATE TABLE council_decision_submission (id serial PRIMARY KEY, ma uuid, set_id integer, "
            "set_id_luc_tao integer, trang_thai varchar(16))"
        )
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        assert rc != 0 and "sqlstate=QLLG2" in out, (rc, _dong_loi(out))
        assert await _phien_ban(k) == TRUOC
        co, rb, cm = await _hinh(k)
        assert co and rb == {"council_decision_submission_pkey"} and not (CHI_MUC & cm), (rb, cm)  # chỉ mục đã lùi
    finally:
        await k.close()


async def test_lg_mig_bang_co_san_thieu_cot_thi_dung(csdl_rieng):  # noqa: F811
    # Bảng cùng tên khác hình THIẾU cột ⇒ câu tạo chỉ mục lỗi 42703 (cột không có) TRƯỚC bước kiểm hình — cũng dừng,
    # không ghi nhận phiên bản (đo trên lượt chạy đầu, khi ca trên còn dựng bảng thiếu cột).
    await _len_1111(csdl_rieng)
    k = await _ket_noi(csdl_rieng)
    try:
        await k.execute("CREATE TABLE council_decision_submission (id serial PRIMARY KEY, ghi_chu text)")
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        assert rc != 0 and "sqlstate=42703" in out, (rc, _dong_loi(out))
        assert await _phien_ban(k) == TRUOC
        assert await k.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = $1", BANG
        ) == 2  # bảng giả còn nguyên hình cũ
    finally:
        await k.close()


async def test_lg_mig_qua_tran_cho(csdl_rieng):  # noqa: F811
    await _len_1111(csdl_rieng)
    url = _url(csdl_rieng, "postgresql")
    b = await asyncpg.connect(url)
    k = await asyncpg.connect(url)
    try:
        gd = b.transaction()
        await gd.start()
        await b.execute("LOCK TABLE council_document_set IN ROW EXCLUSIVE MODE")  # như một phiên đang ghi bảng bộ
        rc, out = await _chay_xong(csdl_rieng, "upgrade", DICH)
        await gd.rollback()
        assert rc != 0 and "sqlstate=55P03" in out, (rc, _dong_loi(out))
        assert (await _hinh(k))[0] is False
        assert await _phien_ban(k) == TRUOC
    finally:
        await b.close()
        await k.close()


async def test_lg_mig_ha_cap_rong(csdl_rieng):  # noqa: F811
    await _len_1111(csdl_rieng)
    assert (await _chay_xong(csdl_rieng, "upgrade", DICH))[0] == 0
    rc, out = await _chay_xong(csdl_rieng, "downgrade", TRUOC)
    assert rc == 0, _dong_loi(out)
    k = await _ket_noi(csdl_rieng)
    try:
        assert (await _hinh(k))[0] is False
        assert await _phien_ban(k) == TRUOC
    finally:
        await k.close()


async def test_lg_mig_ha_cap_con_dong_thi_dung(csdl_rieng):  # noqa: F811
    await _len_1111(csdl_rieng)
    assert (await _chay_xong(csdl_rieng, "upgrade", DICH))[0] == 0
    k = await _ket_noi(csdl_rieng)
    try:
        s, u = await _bo_id(k), await k.fetchval('SELECT min(id) FROM "user"')
        await k.execute(
            "INSERT INTO council_decision_submission (ma, set_id, set_id_luc_tao, trang_thai, nguoi_tao_id, "
            "ket_thuc_luc) VALUES (gen_random_uuid(), $1, $1, 'da_chan', $2, now())", s, u
        )
        rc, out = await _chay_xong(csdl_rieng, "downgrade", TRUOC)
        assert rc != 0 and "sqlstate=QLLG1" in out, (rc, _dong_loi(out))
        assert (await _hinh(k))[0] is True
        assert await k.fetchval("SELECT count(*) FROM council_decision_submission") == 1
        assert await _phien_ban(k) == DICH
    finally:
        await k.close()


# ═══════════════════════════════ F277 (Codex lần 18) — hạ cấp khi có lượt CHƯA commit, hai phiên ═══════════════
SQL_CHEN_CHO_GUI = (
    "INSERT INTO council_decision_submission (ma, set_id, set_id_luc_tao, trang_thai, nguoi_tao_id) "
    "VALUES (gen_random_uuid(), $1, $1, 'cho_gui', $2)"
)


async def _chen_chua_commit_roi_ha_cap(ten_db, ket_thuc):
    """Phiên GHI: BEGIN + INSERT một lượt ``cho_gui`` (CHƯA commit) → ``alembic downgrade`` (tiến trình con, đúng env.py)
    → đợi tới khi tiến trình hạ cấp bị CHÍNH phiên ghi chặn → ``ket_thuc`` (commit / rollback).
    Trả (kết nối kiểm, đã bị chặn, mã thoát, đầu ra)."""
    url = _url(ten_db, "postgresql")
    ghi = await asyncpg.connect(url)
    k = await asyncpg.connect(url)
    p = None
    try:
        s, u = await _bo_id(k), await k.fetchval('SELECT min(id) FROM "user"')
        gd = ghi.transaction()
        await gd.start()
        await ghi.execute(SQL_CHEN_CHO_GUI, s, u)
        pid = await ghi.fetchval("SELECT pg_backend_pid()")
        p = await _alembic(ten_db, "downgrade", TRUOC)
        bi_chan = await _doi_bi_chan(k, pid, p)
        await (gd.commit() if ket_thuc == "commit" else gd.rollback())
        rc, out = await _xong(p)
    except BaseException:
        if p is not None and p.returncode is None:
            p.kill()
            await p.wait()
        await k.close()
        raise
    finally:
        await ghi.close()
    return k, bi_chan, rc, out


async def _len_1112(ten_db):
    await _len_1111(ten_db)
    rc, out = await _chay_xong(ten_db, "upgrade", DICH)
    assert rc == 0, _dong_loi(out)


async def test_lg_mig_ha_cap_luot_chua_commit_thi_cho_roi_dung_giu_dong(csdl_rieng):  # noqa: F811
    await _len_1112(csdl_rieng)
    k, bi_chan, rc, out = await _chen_chua_commit_roi_ha_cap(csdl_rieng, "commit")
    try:
        # Bất biến DỮ LIỆU trước (đỏ phải đỏ đúng lý do), rồi mới tới tính hợp lệ của phép đo và mã thoát.
        assert (await _hinh(k))[0] is True, "MẤT BẢNG lượt gửi cùng dòng vừa COMMIT — hạ cấp đếm trước khi khoá (F277)"
        assert await k.fetchval("SELECT count(*) FROM council_decision_submission WHERE trang_thai = 'cho_gui'") == 1
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc != 0 and "sqlstate=QLLG1" in out, (rc, _dong_loi(out))
        assert await _phien_ban(k) == DICH
    finally:
        await k.close()


async def test_lg_mig_ha_cap_phien_ghi_huy_thi_xoa_bang_rong(csdl_rieng):  # noqa: F811
    # Đối chứng: khoá chờ phiên ghi KHÔNG làm hạ cấp hỏng khi phiên ghi huỷ — bảng rỗng thật ⇒ xoá, rc 0.
    await _len_1112(csdl_rieng)
    k, bi_chan, rc, out = await _chen_chua_commit_roi_ha_cap(csdl_rieng, "rollback")
    try:
        assert bi_chan, "phép đo không hợp lệ: hạ cấp không đợi phiên ghi"
        assert rc == 0, _dong_loi(out)
        assert (await _hinh(k))[0] is False
        assert await _phien_ban(k) == TRUOC
    finally:
        await k.close()


async def test_lg_mig_ha_cap_repeatable_read_thi_tu_choi_giu_dong(csdl_rieng):  # noqa: F811
    # Ở REPEATABLE READ ảnh chụp của câu DO chốt TRƯỚC khoá ⇒ đếm sau khoá vẫn có thể "rỗng" ⇒ câu DO phải TỪ CHỐI chạy.
    await _len_1112(csdl_rieng)
    q = await _ket_noi(csdl_rieng)
    try:
        await q.execute(
            "ALTER DATABASE \"%s\" SET default_transaction_isolation TO 'repeatable read'" % csdl_rieng
        )
    finally:
        await q.close()
    k, _bi_chan, rc, out = await _chen_chua_commit_roi_ha_cap(csdl_rieng, "commit")
    try:
        assert (await _hinh(k))[0] is True, "MẤT BẢNG lượt gửi ở REPEATABLE READ"
        assert await k.fetchval("SELECT count(*) FROM council_decision_submission") == 1
        assert rc != 0 and "sqlstate=QLLG3" in out, (rc, _dong_loi(out))
        assert await _phien_ban(k) == DICH
    finally:
        await k.close()
