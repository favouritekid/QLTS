# -*- coding: utf-8 -*-
"""GĐ2-C C2 — ràng buộc CSDL của bảng lựa chọn Ban thư ký, đo bằng câu SQL TRỰC TIẾP (SQL tay — không qua dịch vụ; dịch vụ chỉ là
lớp phụ). Tầng chủ sở hữu: trigger ``app/models/admission_review_selection_ddl.py`` + CHECK / UNIQUE / khoá ngoại
``app/models/admission_review_selection.py``. Thiết kế GĐ2-C 22-11 §2.2, §6 hàng C2; ĐT3 T16 ("lựa chọn chỉ ghi khi ``draft``");
owner C6 (lý do bắt buộc).

Mỗi ca kiểm MỘT bất biến; lỗi so bằng (SQLSTATE, tên ràng buộc) — không đọc chữ thông báo. Dữ liệu GIẢ (hồ sơ là số giả — bảng không
có khoá ngoại tới hồ sơ):

* ca một phiên dùng fixture ``c`` của ``test_quota_occupancy_db.py`` (một giao dịch, lùi khi ra) + hàm dựng lần xét / lượt / dòng
  của ``test_gd2b_rang_buoc_db.py`` (MỘT nguồn dữ liệu giả của GĐ2-B);
* ca HAI PHIÊN (khoá ``FOR SHARE`` của trigger) dựng nền đã commit, "chờ" đo bằng ``pg_blocking_pids`` từ phiên thứ ba.

Biến thể kiểm ngược (phải ĐỎ, mỗi lượt một):
- bỏ khối ``IF TG_OP <> 'INSERT'`` của trigger ⇒ :func:`test_lua_chon_khong_sua_duoc`, :func:`test_lua_chon_khong_xoa_duoc` đỏ;
- bỏ ``PERFORM admission_review_assert_session_draft`` ⇒ :func:`test_lan_xet_da_huy_khong_ghi_lua_chon` và ca hai phiên đỏ;
- bỏ vế ``v_row_hash IS DISTINCT FROM NEW.based_on_row_hash`` ⇒ :func:`test_ma_bam_khong_khop_dong_dua_vao` đỏ;
- bỏ CHECK ``ck_admission_review_selection_note_required`` ⇒ :func:`test_ly_do_bat_buoc_voi_loai_khoi_va_cho_bo_sung` đỏ.
"""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as csdl
from app.repositories.council_decision_repository import db_error_codes
from tests.fixtures.hoi_dong_seed import danh_muc
from tests.integration.test_gd2b_rang_buoc_db import (
    CHEN_LAN_XET,
    HUY,
    XONG,
    _bat,
    _cau_dong,
    _dong,
    _dong_dat,
    _dong_khong_du,
    _huy,
    _lan_xet,
    _loi,
    _luot,
    _nguoi,
)
from tests.integration.test_quota_occupancy_db import _x, c  # noqa: F401

pytestmark = pytest.mark.integration

NAM = 2026
QLC02 = "QLC02"  # lần xét không còn nháp (GĐ2-B — hàm kiểm chung)
QLC22 = "QLC22"  # lựa chọn bất biến / dòng dựa vào không hợp lệ (admission_review_selection_ddl.SQLSTATE_SELECTION_IMMUTABLE)
HASH_DAT = "b" * 64  # row_hash của ``_dong_dat`` (hồ sơ giả 9002, NV 11)
HASH_KHONG_DU = "a" * 64  # row_hash của ``_dong_khong_du`` (hồ sơ giả 9001, không NV)

CHEN_CHON = (
    "INSERT INTO admission_review_selection (session_id, academic_year, profile_id, kind, choice_id, based_on_run_id, "
    "based_on_row_hash, decided_by_user_id, note, supersedes_id) VALUES (:s, :y, :p, :k, :ch, :r, :h, :u, :n, :sp) RETURNING id"
)


def _ts(c, nen, **sua):
    """Tham số chèn một lựa chọn HỢP LỆ trên dòng ``auto`` của hồ sơ giả 9002 (``nen`` = (lần xét, lượt))."""
    sid, rid = nen
    ts = dict(s=sid, y=NAM, p=9002, k="admit_over_major_quota", ch=11, r=rid, h=HASH_DAT, u=c.info["d"]["nguoi"], n=None,
              sp=None)
    ts.update(sua)
    return ts


async def _chon(c, nen, **sua) -> int:
    return (await _x(c, CHEN_CHON, **_ts(c, nen, **sua))).scalar_one()


async def _nen(c, *, so=1, xong=True):
    """Lần xét nháp + một lượt có hai dòng (``auto`` 9002 NV 11 + ``ineligible`` 9001) — ``xong`` ⇒ lượt ``done``."""
    sid = await _lan_xet(c, so=so)
    rid = await _luot(c, sid)
    await _dong(c, rid, _dong_dat(c))
    await _dong(c, rid, _dong_khong_du())
    if xong:
        await _x(c, XONG, r=rid)
    return sid, rid


# ── Đối chứng: dữ liệu hợp lệ chèn được (nếu không, mọi ca "bị chặn" dưới có thể đỏ vì lý do khác) ───────────────────
async def test_doi_chung_lua_chon_hop_le_chen_duoc_va_doi_y_bang_dong_moi(c):
    nen = await _nen(c)
    a = await _chon(c, nen)
    b = await _chon(c, nen, k="exclude_this_session", n="Không đủ điều kiện ngành", sp=a)
    # Dòng không có NV được xếp: choice_id NULL, "Chờ bổ sung" có lý do.
    await _chon(c, nen, p=9001, k="defer_supplement", ch=None, h=HASH_KHONG_DU, n="Chờ giấy cư trú")
    hang = (
        await _x(c, "SELECT id, supersedes_id FROM admission_review_selection WHERE session_id = :s ORDER BY id", s=nen[0])
    ).all()
    assert [tuple(h) for h in hang][:2] == [(a, None), (b, a)] and len(hang) == 3


# ── chỉ thêm ─────────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_lua_chon_khong_sua_duoc(c):
    a = await _chon(c, await _nen(c))
    assert await _loi(c, "UPDATE admission_review_selection SET note = 'sửa' WHERE id = :a", a=a) == (QLC22, None)


async def test_lua_chon_khong_xoa_duoc(c):
    a = await _chon(c, await _nen(c))
    assert await _loi(c, "DELETE FROM admission_review_selection WHERE id = :a", a=a) == (QLC22, None)


# ── chỉ khi lần xét nháp (T16) ──────────────────────────────────────────────────────────────────────────────────────────
async def test_lan_xet_da_huy_khong_ghi_lua_chon(c):
    nen = await _nen(c)
    await _huy(c, nen[0])
    assert await _loi(c, CHEN_CHON, **_ts(c, nen)) == (QLC02, None)


# ── dòng dựa vào phải có thật ───────────────────────────────────────────────────────────────────────────────────────────
async def test_dua_vao_luot_cua_lan_xet_khac(c):
    nen = await _nen(c)
    khac = await _nen(c, so=2)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, r=khac[1])) == (QLC22, None)


async def test_dua_vao_luot_chua_xong(c):
    nen = await _nen(c, xong=False)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen)) == (QLC22, None)


async def test_ma_bam_khong_khop_dong_dua_vao(c):
    nen = await _nen(c)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, h="c" * 64)) == (QLC22, None)


async def test_ho_so_khong_co_trong_luot_dua_vao(c):
    nen = await _nen(c)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, p=9999)) == (QLC22, None)


@pytest.mark.parametrize(
    "ho_so, nv, bam",
    [(9002, 12, HASH_DAT), (9002, None, HASH_DAT), (9001, 11, HASH_KHONG_DU)],
    ids=["nv_khac", "thieu_nv", "dong_khong_nv_ma_ghi_nv"],
)
async def test_nv_phai_dung_nv_duoc_xep_cua_dong(c, ho_so, nv, bam):
    nen = await _nen(c)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, p=ho_so, ch=nv, h=bam, k="exclude_this_session", n="x")) == (QLC22, None)


# ── chuỗi thay thế ──────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_thay_dong_cua_ho_so_khac(c):
    nen = await _nen(c)
    a = await _chon(c, nen, p=9001, k="exclude_this_session", ch=None, h=HASH_KHONG_DU, n="x")
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, sp=a)) == (QLC22, None)


async def test_mot_dong_bi_thay_toi_da_mot_lan(c):
    nen = await _nen(c)
    a = await _chon(c, nen)
    await _chon(c, nen, k="consider_next_choice", sp=a)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, k="exclude_this_session", n="x", sp=a)) == (
        "23505", "uq_admission_review_selection_supersedes"
    )


async def test_goc_chuoi_thay_the_duy_nhat(c):
    nen = await _nen(c)
    await _chon(c, nen)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, k="consider_next_choice")) == ("23505", "uq_admission_review_selection_root")


async def test_dong_thay_phai_dung_sau_dong_bi_thay(c):
    """``supersedes_id < id`` — chèn tay với id CHỌN SẴN để dòng thay có id nhỏ hơn dòng bị thay."""
    nen = await _nen(c)
    cau = CHEN_CHON.replace("(session_id,", "(id, session_id,").replace("VALUES (:s,", "VALUES (:id, :s,")
    await _x(c, cau, id=2_000_000_000, **_ts(c, nen))
    assert await _loi(c, cau, id=1_999_999_999, **_ts(c, nen, k="consider_next_choice", sp=2_000_000_000)) == (
        "23514", "ck_admission_review_selection_supersedes_order"
    )


# ── CHECK ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_loai_la_bi_chan(c):
    nen = await _nen(c)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, k="admit_without_reason")) == ("23514", "ck_admission_review_selection_kind")


@pytest.mark.parametrize("loai", ["exclude_this_session", "defer_supplement"])
async def test_ly_do_bat_buoc_voi_loai_khoi_va_cho_bo_sung(c, loai):
    """Owner C6: "Loại khỏi lần này" và "Chờ bổ sung" BẮT BUỘC lý do — CSDL chặn cả SQL tay."""
    nen = await _nen(c)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, k=loai, n=None)) == ("23514", "ck_admission_review_selection_note_required")


async def test_ly_do_trang_bi_chan(c):
    nen = await _nen(c)
    assert await _loi(c, CHEN_CHON, **_ts(c, nen, k="exclude_this_session", n="   ")) == (
        "23514", "ck_admission_review_selection_note"
    )


@pytest.mark.parametrize("loai", ["admit_over_major_quota", "consider_next_choice", "admit_without_ethnic_bonus",
                                  "keep_despite_inactive"])
async def test_doi_chung_bon_loai_con_lai_khong_can_ly_do(c, loai):
    """Đối chứng của ca lý do bắt buộc: bốn loại còn lại chèn được KHÔNG lý do (CSDL không đòi thừa)."""
    nen = await _nen(c)
    await _chon(c, nen, k=loai)


async def test_check_ma_bam_dang_64_hex_khi_khong_co_trigger(c):
    """CHECK ``ck_admission_review_selection_row_hash`` là lớp dưới trigger (trigger so với dòng thật — dòng thật luôn 64 hex). Đo
    CHECK RIÊNG: tắt trigger TRONG một savepoint (lùi khi ra), chèn mã băm sai dạng ⇒ CHECK chặn."""
    nen = await _nen(c)
    sp = await c.begin_nested()
    try:
        await _x(c, "ALTER TABLE admission_review_selection DISABLE TRIGGER trg_admission_review_selection_guard")
        with pytest.raises(DBAPIError) as e:
            await _x(c, CHEN_CHON, **_ts(c, nen, h="ABC"))
    finally:
        await sp.rollback()
    assert db_error_codes(e.value) == ("23514", "ck_admission_review_selection_row_hash")


# ── người ghi (K4) ──────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_xoa_nguoi_ghi_lua_chon_bi_chan_o_dich_vu_k4(c):
    from app.services.user_deletion_policy import UserNotDeletable, assert_user_deletable

    u = await _nguoi(c, "gd2c_c2_k4_nguoi_ghi")
    await _chon(c, await _nen(c), u=u)
    async with AsyncSession(bind=c) as db:
        with pytest.raises(UserNotDeletable) as e:
            await assert_user_deletable(db, [u], actor_id=c.info["d"]["nguoi"])
    assert e.value.error_code == "USER_HAS_ACTIVITY"


async def test_xoa_nguoi_ghi_bang_sql_vap_khoa_ngoai_restrict(c):
    u = await _nguoi(c, "gd2c_c2_k4_sql")
    await _chon(c, await _nen(c), u=u)
    assert await _loi(c, 'DELETE FROM "user" WHERE id = :u', u=u) == ("23503", "fk_admission_review_selection_decided_by")


# ── Handler: QLC22 không đổi (500), QLC02 của bảng lựa chọn ⇒ 409 như điểm sàn ────────────────────────────────────────────
def _yeu_cau(path="/api/admission-config/review-sessions/1/selections/9002"):
    return SimpleNamespace(url=SimpleNamespace(path=path), method="PUT")


async def test_loi_bat_bien_qlc22_khong_doi_o_handler(c):
    from app.middleware.exception_handlers import database_error_handler

    a = await _chon(c, await _nen(c))
    loi = await _bat(c, "DELETE FROM admission_review_selection WHERE id = :a", a=a)
    assert db_error_codes(loi)[0] == QLC22
    with pytest.raises(DBAPIError) as e:
        await database_error_handler(_yeu_cau(), loi)
    assert e.value is loi


async def test_loi_khong_nhap_qua_handler_ra_409_review_session_not_draft(c):
    import json

    from app.middleware.exception_handlers import database_error_handler

    nen = await _nen(c)
    await _huy(c, nen[0])
    loi = await _bat(c, CHEN_CHON, **_ts(c, nen))
    assert db_error_codes(loi)[0] == QLC02
    r = await database_error_handler(_yeu_cau(), loi)
    than = json.loads(r.body)
    assert r.status_code == 409 and than["error_code"] == "REVIEW_SESSION_NOT_DRAFT"


# ── Hai phiên: khoá ``FOR SHARE`` của trigger ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def nen_da_commit(setup_test_database):
    """Nền ĐÃ COMMIT: danh mục giả, bảng chỉ tiêu 2026, một lần xét nháp, một lượt ``done`` có dòng ``auto`` của hồ sơ giả 9002."""
    async with csdl.engine.begin() as conn:
        d = await danh_muc(conn)
        path = d["psg"][("oto_cd", "cq", "g1")][0]
        ai, off = (
            await conn.execute(
                text(
                    "SELECT ap.academic_info_id, oai.offering_id FROM admission_path ap "
                    "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id WHERE ap.id = :p"
                ),
                {"p": path},
            )
        ).one()
        await conn.execute(text("INSERT INTO admission_quota_table (academic_year) VALUES (:y)"), {"y": NAM})
        sid = (
            await conn.execute(text(CHEN_LAN_XET), {"y": NAM, "r": d["vong"], "s": 1, "u": d["nguoi"]})
        ).scalar_one()
        rid = (
            await conn.execute(
                text(
                    "INSERT INTO admission_review_run (session_id, kind, status, rule_version, requested_by_user_id, "
                    "started_at, inputs) VALUES (:s, 'evaluate', 'running', 'gd2b-1', :u, now(), CAST('{}' AS jsonb)) "
                    "RETURNING id"
                ),
                {"s": sid, "u": d["nguoi"]},
            )
        ).scalar_one()
        conn.info["d"] = d
        conn.info["X"] = {"ai": ai, "off": off, "path": path}
        cau, ts = _cau_dong(rid, _dong_dat(conn))
        await conn.execute(text(cau), ts)
        await conn.execute(text(XONG), {"r": rid})
    return {"nguoi": d["nguoi"], "sid": sid, "rid": rid}


async def _pid(conn) -> int:
    return (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one()


async def _bi_chan_boi(pid_cho: int, pid_giu: int, viec) -> bool:
    for _ in range(100):
        await asyncio.sleep(0.05)
        if viec.done():
            return False
        async with csdl.engine.connect() as k3:
            chan = (await k3.execute(text("SELECT pg_blocking_pids(:p)"), {"p": pid_cho})).scalar_one()
        if pid_giu in (chan or []):
            return True
    return False


async def test_hai_phien_huy_dang_do_thi_ghi_lua_chon_bang_sql_tay_phai_cho_roi_bi_chan(nen_da_commit):
    """Phiên A = giao dịch huỷ lần xét (dòng lần xét ``FOR UPDATE`` → ``cancelled``), CHƯA commit. Phiên B = SQL tay chèn lựa chọn
    vào CHÍNH lần xét ấy ⇒ B phải CHỜ đúng A; A commit ⇒ B đọc lại dòng lần xét (``FOR SHARE``), thấy ``cancelled`` ⇒ ``QLC02``.
    Lần xét đã huỷ còn 0 lựa chọn."""
    n = nen_da_commit
    a, b = await csdl.engine.connect(), await csdl.engine.connect()
    viec = None
    try:
        await a.begin()
        await b.begin()
        pa = await _pid(a)
        await a.execute(text("SELECT id FROM admission_review_session WHERE id = :s FOR UPDATE"), {"s": n["sid"]})
        await a.execute(text(HUY), {"u": n["nguoi"], "s": n["sid"]})
        pb = await _pid(b)
        ts = dict(s=n["sid"], y=NAM, p=9002, k="admit_over_major_quota", ch=11, r=n["rid"], h=HASH_DAT, u=n["nguoi"], n=None,
                  sp=None)
        viec = asyncio.ensure_future(b.execute(text(CHEN_CHON), ts))
        assert await _bi_chan_boi(pb, pa, viec), "ghi lựa chọn KHÔNG chờ giao dịch huỷ đang dở"
        await a.commit()
        with pytest.raises(DBAPIError) as e:
            await viec
        assert db_error_codes(e.value)[0] == QLC02
    finally:
        for k in (a, b):
            try:
                await k.rollback()
            finally:
                await k.close()
    async with csdl.engine.connect() as k3:
        assert (
            await k3.execute(text("SELECT count(*) FROM admission_review_selection WHERE session_id = :s"), {"s": n["sid"]})
        ).scalar_one() == 0
