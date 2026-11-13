# -*- coding: utf-8 -*-
"""Lượt I (F230) — ràng buộc CSDL của ghi nhận Quyết định đã ký, đo THẲNG bằng SQL trên CSDL test
(dựng từ model bằng ``create_all``), KHÔNG qua service (CLAUDE.md §10). Đặc tả mục 4.3.

Luật cô lập (CLAUDE.md §3, Codex lần 10 §G câu 5): ca của guard X dựng dữ liệu sao cho MỌI guard khác
của cùng thao tác không thể bắn; đối chứng cùng ca, chỉ khác đúng điều kiện X canh, phải THÀNH CÔNG. Vd
K4 đo bằng văn bản KHÔNG có dòng (có dòng thì K5b chặn trước — đo PG16 lượt I chặng 1, T9b); K2 đo bằng
hồ sơ không ở văn bản nào khác (không thì U3 bắn trước — T4e).
"""
import json
from datetime import date, datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database as csdl
from app.repositories.council_decision_repository import ma_loi_csdl
from tests.fixtures.hoi_dong_seed import danh_muc, ho_so, ma_gia

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def c(setup_test_database):
    """Một kết nối + giao dịch; lùi hết khi ra (dữ liệu giả không còn lại)."""
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        conn.info["d"] = await danh_muc(conn)
        conn.info["so"] = 100
        try:
            yield conn
        finally:
            await gd.rollback()


async def _hs(c, n=1):
    """``n`` hồ sơ TỐI GIẢN (lead + hồ sơ, không học phí / nguyện vọng / giấy) — xoá được nếu
    không có ràng buộc nào của F230 giữ."""
    out = []
    for _ in range(n):
        c.info["so"] += 1
        out.append(await ho_so(c, c.info["d"], cccd=ma_gia(70000 + c.info["so"])))
    return out


async def _bo(c, pids):
    sid = (
        await c.execute(
            text(
                "INSERT INTO council_document_set (moc_chup, trinh_do, so_ho_so, so_tep, "
                "kich_thuoc_tong, ma_ho_so_dau_vao, snapshot_dto, thong_tin_dung) VALUES "
                "(now(), 'Cao đẳng', :n, 1, 1, CAST(:ma AS jsonb), CAST(:dto AS jsonb), '{}') "
                "RETURNING id"
            ),
            {
                "n": len(pids),
                "ma": json.dumps(["GIA"] * len(pids)),
                "dto": json.dumps([{}] * len(pids)),
            },
        )
    ).scalar_one()
    dong = []
    for i, p in enumerate(pids, 1):
        dong.append(
            (
                await c.execute(
                    text(
                        "INSERT INTO council_document_set_row (set_id, stt, profile_id, "
                        "academic_year, status_luc_dung) VALUES (:s, :i, :p, 2026, 'approved') "
                        "RETURNING id"
                    ),
                    {"s": sid, "i": i, "p": p},
                )
            ).scalar_one()
        )
    return sid, dong


def _so(c):
    c.info["so"] += 1
    return str(c.info["so"])


async def _qd(c, set_id, *, loai="trung_tuyen", goc_id=None, huy_qd_id=None, can_bo=None):
    if can_bo is None:
        can_bo = set_id is not None
    return (
        await c.execute(
            text(
                "INSERT INTO council_decision (loai, can_bo, set_id, goc_id, huy_qd_id, "
                "so_quyet_dinh, ngay_ky, pham_vi_so, trang_thai, so_ho_so, ghi_nhan_boi_id) "
                "VALUES (:l, :cb, :s, :g, :h, :so, DATE '2026-09-08', 2026, 'hieu_luc', 0, 1) "
                "RETURNING id"
            ),
            {"l": loai, "cb": can_bo, "s": set_id, "g": goc_id, "h": huy_qd_id, "so": _so(c)},
        )
    ).scalar_one()


async def _dong(c, qd, set_id, set_row_id, pid, stt=1):
    return (
        await c.execute(
            text(
                "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, "
                "set_row_id, profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, :t) RETURNING id"
            ),
            {"d": qd, "s": set_id, "r": set_row_id, "p": pid, "t": stt},
        )
    ).scalar_one()


async def _het_hieu_luc(c, qd):
    h = await _qd(c, None, loai="van_ban_huy", huy_qd_id=qd, can_bo=False)
    await c.execute(
        text(
            "UPDATE council_decision SET trang_thai = 'het_hieu_luc', het_hieu_luc_boi_id = :h "
            "WHERE id = :x"
        ),
        {"h": h, "x": qd},
    )
    return h


async def _huy_ghi_nhan(c, qd):
    await c.execute(
        text(
            "UPDATE council_decision SET trang_thai = 'huy_ghi_nhan', huy_ghi_nhan_boi_id = 1, "
            "huy_ghi_nhan_luc = now(), ly_do_huy_ghi_nhan = 'GIA nhap sai' WHERE id = :x"
        ),
        {"x": qd},
    )


async def _thu(c, cau, **ts):
    """Chạy ``cau`` trong SAVEPOINT; lỗi ⇒ (sqlstate, ràng buộc) và lùi SAVEPOINT; được ⇒ None."""
    sp = await c.begin_nested()
    try:
        await c.execute(text(cau), ts)
    except DBAPIError as e:
        await sp.rollback()
        return ma_loi_csdl(e)
    await sp.commit()
    return None


async def _gia_tri(c, cau, **ts):
    return (await c.execute(text(cau), ts)).scalar_one()


# ═══════════════════════════════ K4 — xoá bộ của văn bản còn / hết hiệu lực ═══════════════════
@pytest.mark.parametrize("trang_thai", ["hieu_luc", "het_hieu_luc"])
async def test_k4_xoa_bo_cua_van_ban_khong_dong(c, trang_thai):
    sid, _ = await _bo(c, await _hs(c))
    qd = await _qd(c, sid)  # KHÔNG dòng QĐ ⇒ chỉ K4 có thể chặn
    if trang_thai == "het_hieu_luc":
        await _het_hieu_luc(c, qd)
    assert await _thu(c, "DELETE FROM council_document_set WHERE id = :s", s=sid) == (
        "23514",
        "ck_council_decision_k4",
    )


async def test_k4_doi_chung_ban_ghi_huy_ghi_nhan_xoa_bo_duoc(c):
    sid, _ = await _bo(c, await _hs(c))
    qd = await _qd(c, sid)
    await _huy_ghi_nhan(c, qd)
    assert await _thu(c, "DELETE FROM council_document_set WHERE id = :s", s=sid) is None
    assert await _gia_tri(c, "SELECT set_id FROM council_decision WHERE id = :x", x=qd) is None


async def test_k4_dieu_chinh_co_bo_khong_con_mien_tru(c):
    sa, _ = await _bo(c, await _hs(c))
    goc = await _qd(c, sa)
    sd, _ = await _bo(c, await _hs(c))
    dc = await _qd(c, sd, loai="dieu_chinh", goc_id=goc)  # can_bo = true, 0 dòng
    assert await _thu(c, "DELETE FROM council_document_set WHERE id = :s", s=sd) == (
        "23514",
        "ck_council_decision_k4",
    )
    await _huy_ghi_nhan(c, dc)  # đối chứng cùng ca
    assert await _thu(c, "DELETE FROM council_document_set WHERE id = :s", s=sd) is None


@pytest.mark.parametrize(
    "loai, sai, dung, rang_buoc",
    [
        # (can_bo, có bộ) của bản SAI và bản ĐÚNG (đối chứng chỉ đổi đúng cặp ấy)
        ("dieu_chinh", (False, True), (False, False), "ck_council_decision_k4b"),
        ("trung_tuyen", (False, False), (True, True), "ck_council_decision_k4c"),
        ("van_ban_huy", (True, True), (False, False), "ck_council_decision_k4d"),
    ],
)
async def test_k4b_k4c_k4d_moi_cap_sai(c, loai, sai, dung, rang_buoc):
    sa, _ = await _bo(c, await _hs(c))
    goc = await _qd(c, sa)
    cau = (
        "INSERT INTO council_decision (loai, can_bo, set_id, goc_id, huy_qd_id, so_quyet_dinh, "
        "ngay_ky, pham_vi_so, trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES (:l, :cb, :s, :g, "
        ":h, :so, DATE '2026-09-08', 2026, 'hieu_luc', 0, 1)"
    )
    for (cb, co_bo), ky_vong in ((dung, None), (sai, ("23514", rang_buoc))):
        sid = (await _bo(c, await _hs(c)))[0] if co_bo else None
        ts = dict(
            l=loai,
            cb=cb,
            s=sid,
            g=goc if loai == "dieu_chinh" else None,
            h=None,
            so=_so(c),
        )
        if loai == "van_ban_huy":
            ts["h"] = await _qd(c, (await _bo(c, await _hs(c)))[0])  # văn bản đích riêng (U4)
        assert await _thu(c, cau, **ts) == ky_vong, (cb, co_bo)


# ═══════════════════════════════ K5a / K5b — giữ liên kết hồ sơ / dòng bộ ═══════════════════
async def test_k5b_xoa_thang_dong_bo_cua_van_ban_hieu_luc(c):
    (p,) = await _hs(c)
    sid, (sr,) = await _bo(c, [p])
    qd = await _qd(c, sid)
    await _dong(c, qd, sid, sr, p)
    assert await _thu(c, "DELETE FROM council_document_set_row WHERE id = :r", r=sr) == (
        "23514",
        "ck_council_decision_row_k5b",
    )
    await _huy_ghi_nhan(c, qd)  # đối chứng cùng ca
    assert await _thu(c, "DELETE FROM council_document_set_row WHERE id = :r", r=sr) is None


@pytest.mark.parametrize("trang_thai", ["hieu_luc", "het_hieu_luc"])
async def test_k5a_xoa_ho_so_dang_nhap_co_ten_trong_van_ban(c, trang_thai):
    (p,) = await _hs(c)
    await c.execute(text("UPDATE admission_profile SET status = 'draft' WHERE id = :p"), {"p": p})
    sid, (sr,) = await _bo(c, [p])
    qd = await _qd(c, sid)
    await _dong(c, qd, sid, sr, p)
    if trang_thai == "het_hieu_luc":
        await _het_hieu_luc(c, qd)
    assert await _thu(c, "DELETE FROM admission_profile WHERE id = :p", p=p) == (
        "23514",
        "ck_council_decision_row_k5a",
    )


async def test_k5a_doi_chung_ho_so_chi_o_bo_nhap_hoac_ban_ghi_huy_xoa_duoc(c):
    a, b = await _hs(c, 2)
    sid, (sa_, sb_) = await _bo(c, [a, b])
    assert await _thu(c, "DELETE FROM admission_profile WHERE id = :p", p=a) is None
    assert (
        await _gia_tri(c, "SELECT profile_id FROM council_document_set_row WHERE id = :r", r=sa_)
        is None
    )
    s2, (sr2,) = await _bo(c, [b])
    qd = await _qd(c, s2)
    await _dong(c, qd, s2, sr2, b)
    await _huy_ghi_nhan(c, qd)
    assert await _thu(c, "DELETE FROM admission_profile WHERE id = :p", p=b) is None


# ═══════════════════════════════ K5c (F257) — set_id NULL ở dòng chưa huỷ ghi nhận ═══════════
# ``set_id`` của dòng nằm trong HAI khoá ngoại ghép; MATCH SIMPLE bỏ qua khoá ngoại có cột NULL ⇒ chỉ CHECK
# K5c giữ. Mỗi ca: dòng ĐÚNG nguồn (đúng dòng bộ + đúng hồ sơ của dòng bộ) chỉ khác ``set_id`` NULL ⇒ K5a /
# K5b có giá trị, hai khoá ngoại ghép không kiểm, U3 / U5 không trùng ⇒ chỉ K5c có thể bắn.
_CHEN_DONG = (
    "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
    "profile_id, stt) VALUES (:d, :t, :s, :r, :p, 1)"
)
_K5C = ("23514", "ck_council_decision_row_k5c")


@pytest.mark.parametrize("trang_thai", ["hieu_luc", "het_hieu_luc"])
async def test_k5c_chen_dong_set_id_null(c, trang_thai):
    (p,) = await _hs(c)
    sid, (sr,) = await _bo(c, [p])
    qd = await _qd(c, sid)
    if trang_thai == "het_hieu_luc":
        await _het_hieu_luc(c, qd)
    assert await _thu(c, _CHEN_DONG, d=qd, t=trang_thai, s=None, r=sr, p=p) == _K5C
    # đối chứng cùng ca: cùng dòng, ``set_id`` = bộ của văn bản ⇒ chèn được
    assert await _thu(c, _CHEN_DONG, d=qd, t=trang_thai, s=sid, r=sr, p=p) is None


@pytest.mark.parametrize("trang_thai", ["hieu_luc", "het_hieu_luc"])
async def test_k5c_cap_nhat_set_id_null(c, trang_thai):
    (p,) = await _hs(c)
    sid, (sr,) = await _bo(c, [p])
    qd = await _qd(c, sid)
    d = await _dong(c, qd, sid, sr, p)
    if trang_thai == "het_hieu_luc":
        await _het_hieu_luc(c, qd)
    assert await _thu(c, "UPDATE council_decision_row SET set_id = NULL WHERE id = :d", d=d) == _K5C
    assert await _gia_tri(c, "SELECT set_id FROM council_decision_row WHERE id = :d", d=d) == sid


async def test_k5c_doi_chung_dong_huy_ghi_nhan_mang_null_duoc(c):
    # Chỉ khác điều kiện K5c canh: văn bản đã huỷ ghi nhận ⇒ dòng được mang ``set_id`` NULL (chèn + cập nhật).
    a, b = await _hs(c, 2)
    sa, (ra,) = await _bo(c, [a])
    qa = await _qd(c, sa)
    da = await _dong(c, qa, sa, ra, a)
    await _huy_ghi_nhan(c, qa)
    assert await _thu(c, "UPDATE council_decision_row SET set_id = NULL WHERE id = :d", d=da) is None
    sb, (rb,) = await _bo(c, [b])
    qb = await _qd(c, sb)
    await _huy_ghi_nhan(c, qb)
    assert await _thu(c, _CHEN_DONG, d=qb, t="huy_ghi_nhan", s=None, r=rb, p=b) is None


@pytest.mark.parametrize("van_ban", ["trung_tuyen", "van_ban_huy"])
async def test_k5c_sai_nguon_set_id_null_dong_bo_cua_ho_so_khac(c, van_ban):
    # Kịch bản F257: dòng còn hiệu lực ``set_id`` NULL + ``set_row_id`` R (của hồ sơ A) + hồ sơ B KHÁC — trước
    # F257 vượt cả ``fk_council_decision_row_bo`` lẫn ``fk_council_decision_row_dong_bo`` (MATCH SIMPLE) và
    # K5a / K5b. ``van_ban_huy``: văn bản KHÔNG có bộ (``set_id`` NULL theo K4b) — cũng không được có dòng.
    a, b = await _hs(c, 2)
    sid, (ra,) = await _bo(c, [a])
    qd = await _qd(c, sid)
    dich = qd
    if van_ban == "van_ban_huy":
        dich = await _qd(c, None, loai="van_ban_huy", huy_qd_id=qd, can_bo=False)
    assert await _thu(c, _CHEN_DONG, d=dich, t="hieu_luc", s=None, r=ra, p=b) == _K5C
    if van_ban == "trung_tuyen":
        # đối chứng: cùng dòng sai nguồn nhưng ``set_id`` có giá trị ⇒ khoá ngoại ghép bắt (lỗ chỉ là NULL)
        assert await _thu(c, _CHEN_DONG, d=dich, t="hieu_luc", s=sid, r=ra, p=b) == (
            "23503",
            "fk_council_decision_row_dong_bo",
        )


async def test_xoa_bo_cua_ban_ghi_huy_co_dong_thi_duoc_va_giu_so(c):
    (p,) = await _hs(c)
    sid, (sr,) = await _bo(c, [p])
    qd = await _qd(c, sid)
    d = await _dong(c, qd, sid, sr, p)
    await _huy_ghi_nhan(c, qd)
    assert await _thu(c, "DELETE FROM council_document_set WHERE id = :s", s=sid) is None
    hang = (
        await c.execute(
            text("SELECT set_id, set_row_id, profile_id FROM council_decision_row WHERE id = :d"),
            {"d": d},
        )
    ).one()
    # set_id ⇒ NULL (khoá ngoại ghép theo văn bản lan xuống); hồ sơ giữ. ``set_row_id`` ⇒ NULL HOẶC trỏ
    # một dòng bộ KHÔNG còn: thứ tự hai hành động tham chiếu do PostgreSQL quyết, MATCH SIMPLE không
    # kiểm khoá ngoại có cột NULL — đo lượt I chặng 2a: trên CSDL dựng bằng create_all thứ tự khác bản
    # nguyên mẫu chặng 1 (T6b). Service dọn hẳn trước khi xoá bộ (``xoa_bo_van_ban``).
    assert hang[0] is None and hang[2] == p
    if hang[1] is not None:
        assert (
            await _gia_tri(
                c, "SELECT count(*) FROM council_document_set_row WHERE id = :r", r=hang[1]
            )
            == 0
        )
    assert await _gia_tri(c, "SELECT so_quyet_dinh FROM council_decision WHERE id = :x", x=qd)


# ═══════════════════════════════ K2 — cờ con theo cha ═══════════════════════════════════════
async def test_k2_doi_cha_lan_xuong_moi_con(c):
    a, b = await _hs(c, 2)
    sid, (r1, r2) = await _bo(c, [a, b])
    qd = await _qd(c, sid)
    await _dong(c, qd, sid, r1, a, 1)
    await _dong(c, qd, sid, r2, b, 2)
    await _het_hieu_luc(c, qd)
    con = (
        await c.execute(
            text("SELECT array_agg(trang_thai_cha) FROM council_decision_row WHERE decision_id = :d"),
            {"d": qd},
        )
    ).scalar_one()
    assert con == ["het_hieu_luc", "het_hieu_luc"]


async def test_k2_con_khong_tu_doi_trang_thai_khac_cha(c):
    (p,) = await _hs(c)  # em không ở văn bản nào khác ⇒ U3 không thể bắn
    sid, (sr,) = await _bo(c, [p])
    qd = await _qd(c, sid)
    d = await _dong(c, qd, sid, sr, p)
    await _het_hieu_luc(c, qd)
    assert await _thu(
        c, "UPDATE council_decision_row SET trang_thai_cha = 'hieu_luc' WHERE id = :d", d=d
    ) == ("23503", "fk_council_decision_row_k2")


# ═══════════════════════════════ U1–U5 ═════════════════════════════════════════════════════
async def test_u3_hai_dong_hieu_luc_cung_ho_so(c):
    (p,) = await _hs(c)
    s1, (r1,) = await _bo(c, [p])
    s2, (r2,) = await _bo(c, [p])
    await _dong(c, await _qd(c, s1), s1, r1, p)
    q2 = await _qd(c, s2)
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=q2,
        s=s2,
        r=r2,
        p=p,
    ) == ("23505", "uq_council_decision_row_u3_ho_so")


async def test_u3_bat_lai_van_ban_khi_em_da_o_van_ban_khac(c):
    (p,) = await _hs(c)
    s1, (r1,) = await _bo(c, [p])
    q1 = await _qd(c, s1)
    await _dong(c, q1, s1, r1, p)
    h = await _het_hieu_luc(c, q1)
    s2, (r2,) = await _bo(c, [p])
    q2 = await _qd(c, s2)
    await _dong(c, q2, s2, r2, p)
    await _huy_ghi_nhan(c, h)
    assert await _thu(
        c,
        "UPDATE council_decision SET trang_thai = 'hieu_luc', het_hieu_luc_boi_id = NULL "
        "WHERE id = :x",
        x=q1,
    ) == ("23505", "uq_council_decision_row_u3_ho_so")


async def test_u3_dong_bi_bo_khong_tinh_hieu_luc(c):
    (p,) = await _hs(c)
    s1, (r1,) = await _bo(c, [p])
    q1 = await _qd(c, s1)
    d1 = await _dong(c, q1, s1, r1, p)
    sd, (rd,) = await _bo(c, [p])
    dc = await _qd(c, sd, loai="dieu_chinh", goc_id=q1)
    await c.execute(
        text("UPDATE council_decision_row SET bi_bo_boi_id = :dc WHERE id = :d"),
        {"dc": dc, "d": d1},
    )
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=dc,
        s=sd,
        r=rd,
        p=p,
    ) is None


async def test_u1_so_cua_van_ban_het_hieu_luc_van_la_so_da_dung(c):
    s1, _ = await _bo(c, await _hs(c))
    q1 = await _qd(c, s1)
    await _het_hieu_luc(c, q1)
    so = await _gia_tri(c, "SELECT so_quyet_dinh FROM council_decision WHERE id = :x", x=q1)
    # Bản SỐNG cùng số + cùng năm ⇒ U1 (số của văn bản hết hiệu lực vẫn là số đã dùng — C1).
    s2, _ = await _bo(c, await _hs(c))
    assert await _thu(
        c,
        "INSERT INTO council_decision (loai, can_bo, set_id, so_quyet_dinh, ngay_ky, pham_vi_so, "
        "trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES ('trung_tuyen', true, :s, :so, "
        "DATE '2026-12-01', 2026, 'hieu_luc', 0, 1)",
        s=s2,
        so=so,
    ) == ("23505", "uq_council_decision_u1_so")
    assert await _thu(
        c,
        "INSERT INTO council_decision (loai, can_bo, set_id, so_quyet_dinh, ngay_ky, pham_vi_so, "
        "trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES ('trung_tuyen', true, :s, :so, "
        "DATE '2027-01-05', 2027, 'hieu_luc', 0, 1)",
        s=s2,
        so=so,
    ) is None  # năm khác ⇒ được (C1)


async def test_u1_ban_ghi_huy_ghi_nhan_tra_lai_so(c):
    s1, _ = await _bo(c, await _hs(c))
    q1 = await _qd(c, s1)
    so = await _gia_tri(c, "SELECT so_quyet_dinh FROM council_decision WHERE id = :x", x=q1)
    await _huy_ghi_nhan(c, q1)
    s2, _ = await _bo(c, await _hs(c))
    assert await _thu(
        c,
        "INSERT INTO council_decision (loai, can_bo, set_id, so_quyet_dinh, ngay_ky, pham_vi_so, "
        "trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES ('trung_tuyen', true, :s, :so, "
        "DATE '2026-12-01', 2026, 'hieu_luc', 0, 1)",
        s=s2,
        so=so,
    ) is None


async def test_u2_bo_ghi_nhan_hai_lan_ke_ca_khi_ban_dau_het_hieu_luc(c):
    s1, _ = await _bo(c, await _hs(c))
    q1 = await _qd(c, s1)
    await _het_hieu_luc(c, q1)
    assert await _thu(
        c,
        "INSERT INTO council_decision (loai, can_bo, set_id, so_quyet_dinh, ngay_ky, pham_vi_so, "
        "trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES ('trung_tuyen', true, :s, '991', "
        "DATE '2026-12-01', 2026, 'hieu_luc', 0, 1)",
        s=s1,
    ) == ("23505", "uq_council_decision_u2_bo")


async def test_u4_hai_van_ban_huy_song_cung_mot_van_ban(c):
    s1, _ = await _bo(c, await _hs(c))
    q1 = await _qd(c, s1)
    await _qd(c, None, loai="van_ban_huy", huy_qd_id=q1, can_bo=False)
    assert await _thu(
        c,
        "INSERT INTO council_decision (loai, can_bo, huy_qd_id, so_quyet_dinh, ngay_ky, "
        "pham_vi_so, trang_thai, so_ho_so, ghi_nhan_boi_id) VALUES ('van_ban_huy', false, :x, "
        "'992', DATE '2026-12-01', 2026, 'hieu_luc', 0, 1)",
        x=q1,
    ) == ("23505", "uq_council_decision_u4_huy")


# ═══════════════════════════════ dòng QĐ khớp ĐÚNG bộ / hồ sơ nguồn ═════════════════════════
async def test_fk_dong_bo_lay_dong_cua_bo_khac(c):
    a, b = await _hs(c, 2)
    s1, _ = await _bo(c, [a])
    s2, (r2,) = await _bo(c, [b])
    qd = await _qd(c, s1)
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=qd,
        s=s1,
        r=r2,
        p=b,
    ) == ("23503", "fk_council_decision_row_dong_bo")


async def test_fk_dong_bo_ho_so_khac_ho_so_cua_dong_bo(c):
    a, b = await _hs(c, 2)
    s1, (r1,) = await _bo(c, [a])
    qd = await _qd(c, s1)
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=qd,
        s=s1,
        r=r1,
        p=b,
    ) == ("23503", "fk_council_decision_row_dong_bo")


async def test_fk_bo_dong_ghi_set_khac_bo_cua_van_ban(c):
    a, b = await _hs(c, 2)
    s1, _ = await _bo(c, [a])
    s2, (r2,) = await _bo(c, [b])
    qd = await _qd(c, s1)
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=qd,
        s=s2,
        r=r2,
        p=b,
    ) == ("23503", "fk_council_decision_row_bo")


async def test_dong_bo_mat_ho_so_thi_khong_ghi_nhan_duoc(c):
    (p,) = await _hs(c)
    s1, (r1,) = await _bo(c, [p])
    await c.execute(text("DELETE FROM admission_profile WHERE id = :p"), {"p": p})
    qd = await _qd(c, s1)
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, :p, 1)",
        d=qd,
        s=s1,
        r=r1,
        p=p,
    ) == ("23503", "fk_council_decision_row_dong_bo")
    assert await _thu(
        c,
        "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, set_row_id, "
        "profile_id, stt) VALUES (:d, 'hieu_luc', :s, :r, NULL, 1)",
        d=qd,
        s=s1,
        r=r1,
    ) == ("23514", "ck_council_decision_row_k5a")


async def test_chen_dong_tu_bo_trong_mot_cau_khop_dong_bo(c):
    from app.repositories.council_decision_repository import CouncilDecisionRepository
    from sqlalchemy.ext.asyncio import AsyncSession

    a, b = await _hs(c, 2)
    s1, (r1, r2) = await _bo(c, [a, b])
    qd = await _qd(c, s1)
    async with AsyncSession(bind=c) as db:
        n = await CouncilDecisionRepository(db).chen_dong_tu_bo(qd, s1)
    assert n == 2
    hang = (
        await c.execute(
            text(
                "SELECT stt, set_row_id, profile_id FROM council_decision_row WHERE decision_id = "
                ":d ORDER BY stt"
            ),
            {"d": qd},
        )
    ).all()
    assert [tuple(h) for h in hang] == [(1, r1, a), (2, r2, b)]


# ═══════════════════════════════ K3 / K6 ═══════════════════════════════════════════════════
_CHEN = (
    "INSERT INTO council_decision (loai, can_bo, set_id, goc_id, huy_qd_id, het_hieu_luc_boi_id, "
    "so_quyet_dinh, ngay_ky, pham_vi_so, trang_thai, so_ho_so, ghi_nhan_boi_id, "
    "huy_ghi_nhan_boi_id, huy_ghi_nhan_luc, ly_do_huy_ghi_nhan) VALUES (:loai, :cb, NULL, :goc, "
    ":huy, NULL, :so, :ngay, :pv, :tt, 0, 1, :hb, :hl, :ld)"
)


@pytest.mark.parametrize(
    "sua, rang_buoc",
    [
        ({"loai": "bo_sung", "goc": None}, "ck_council_decision_k3_goc"),
        ({"huy": "GOC"}, "ck_council_decision_k3_huy"),
        ({"tt": "huy_ghi_nhan", "hb": 1, "hl": None, "ld": "x"}, "ck_council_decision_k3_hgn"),
        ({"so": "12a"}, "ck_council_decision_k3_so"),
        # 7 chữ số bị cột varchar(6) chặn TRƯỚC (22001 — đo lượt I) ⇒ ca CHECK dùng chuỗi rỗng.
        ({"so": ""}, "ck_council_decision_k3_so"),
        ({"pv": 2027}, "ck_council_decision_k3_pham_vi"),
        (
            {"tt": "huy_ghi_nhan", "hb": 1, "hl": "2026-10-01", "ld": "   "},
            "ck_council_decision_k3_ly_do",
        ),
        ({"tt": "het_hieu_luc"}, "ck_council_decision_k3_het"),
    ],
)
async def test_k3_mot_check_mot_ca_tren_ban_ghi_bo_sung_hop_le(c, sua, rang_buoc):
    s1, _ = await _bo(c, await _hs(c))
    goc = await _qd(c, s1)
    ts = dict(
        loai="bo_sung",
        cb=True,
        goc=goc,
        huy=None,
        so=_so(c),
        ngay=date(2026, 9, 8),
        pv=2026,
        tt="hieu_luc",
        hb=None,
        hl=None,
        ld=None,
    )
    cau = _CHEN.replace("VALUES (:loai, :cb, NULL,", "VALUES (:loai, :cb, :s,")
    s2, _ = await _bo(c, await _hs(c))
    assert await _thu(c, cau, s=s2, **ts) is None  # đối chứng: bản đúng chèn được
    s3, _ = await _bo(c, await _hs(c))
    sai = dict(ts)
    sai["so"] = _so(c)
    sai.update(sua)
    if sai.get("huy") == "GOC":
        sai["huy"] = goc
    if sai.get("hl"):
        sai["hl"] = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert await _thu(c, cau, s=s3, **sai) == ("23514", rang_buoc)


async def test_k3_tu_tro_chinh_minh(c):
    s1, _ = await _bo(c, await _hs(c))
    qd = await _qd(c, s1)
    assert await _thu(
        c, "UPDATE council_decision SET goc_id = id, loai = 'bo_sung' WHERE id = :x", x=qd
    ) == ("23514", "ck_council_decision_k3_tu_tro")


async def test_k3_van_ban_huy_khong_the_het_hieu_luc(c):
    s1, _ = await _bo(c, await _hs(c))
    qd = await _qd(c, s1)
    h = await _qd(c, None, loai="van_ban_huy", huy_qd_id=qd, can_bo=False)
    h2 = await _qd(c, None, loai="van_ban_huy", huy_qd_id=h, can_bo=False)
    assert await _thu(
        c,
        "UPDATE council_decision SET trang_thai = 'het_hieu_luc', het_hieu_luc_boi_id = :h2 "
        "WHERE id = :h",
        h=h,
        h2=h2,
    ) == ("23514", "ck_council_decision_k3_vbh")


async def test_k6_het_hieu_luc_boi_van_ban_huy_cua_van_ban_khac(c):
    s1, _ = await _bo(c, await _hs(c))
    s2, _ = await _bo(c, await _hs(c))
    x = await _qd(c, s1)
    y = await _qd(c, s2)
    h_y = await _qd(c, None, loai="van_ban_huy", huy_qd_id=y, can_bo=False)
    assert await _thu(
        c,
        "UPDATE council_decision SET trang_thai = 'het_hieu_luc', het_hieu_luc_boi_id = :h "
        "WHERE id = :x",
        h=h_y,
        x=x,
    ) == ("23503", "fk_council_decision_k6")


# ═══════════════════════════════ nhóm chờ (H1–H4) ═══════════════════════════════════════════
async def _muc_cho(c, *, trang_thai="cho_quyet", pid=None, them=None):
    (p,) = (pid,) if pid else await _hs(c)
    s1, (r1,) = await _bo(c, [p])
    x = await _qd(c, s1)
    d = await _dong(c, x, s1, r1, p)
    h = await _het_hieu_luc(c, x)
    cot = dict(
        profile_id=p,
        decision_row_id=d,
        van_ban_huy_id=h,
        ly_do_vao="qd_bi_huy",
        trang_thai=trang_thai,
    )
    cot.update(them or {})
    ten = ", ".join(cot)
    gt = ", ".join(":" + k for k in cot)
    return p, d, h, "INSERT INTO council_decision_hold (%s) VALUES (%s)" % (ten, gt), cot


async def test_h1_mot_em_mot_muc_cho_dang_mo(c):
    p, _, _, cau, cot = await _muc_cho(c)
    assert await _thu(c, cau, **cot) is None
    _, _, _, cau2, cot2 = await _muc_cho(c, pid=None)
    cot2["profile_id"] = p
    assert await _thu(c, cau2, **cot2) == ("23505", "uq_council_decision_hold_h1_cho")


@pytest.mark.parametrize(
    "them, rang_buoc",
    [
        ({"trang_thai": "da_cho_xet_lai"}, "ck_council_decision_hold_h4_xl"),
        ({"quyet_luc": datetime(2026, 10, 1, tzinfo=timezone.utc)}, "ck_council_decision_hold_h4_cq"),
        ({"trang_thai": "vo_hieu"}, "ck_council_decision_hold_h4_vh"),
        ({"ly_do_vao": "khac"}, "ck_council_decision_hold_ly_do_vao"),
        ({"profile_id": None}, "ck_council_decision_hold_h3"),
    ],
)
async def test_h3_h4_moi_check_mot_ca(c, them, rang_buoc):
    _, _, _, cau, cot = await _muc_cho(c)
    assert await _thu(c, cau, **cot) is None  # đối chứng
    _, _, _, cau2, cot2 = await _muc_cho(c, them=them)
    assert await _thu(c, cau2, **cot2) == ("23514", rang_buoc)


# ═══════════════════════════════ sự kiện + ba chế độ của bộ ═════════════════════════════════
async def test_su_kien_loai_va_so_lieu(c):
    assert await _thu(
        c, "INSERT INTO council_document_event (loai, so_lieu) VALUES ('ghi_nhan', '{}')"
    ) is None
    assert await _thu(
        c, "INSERT INTO council_document_event (loai, so_lieu) VALUES ('la', '{}')"
    ) == ("23514", "ck_council_document_event_loai")
    assert await _thu(
        c, "INSERT INTO council_document_event (loai, so_lieu) VALUES ('ghi_nhan', '[]')"
    ) == ("23514", "ck_council_document_event_so_lieu")


@pytest.mark.parametrize(
    "dat, rang_buoc",
    [
        ("ban_ky_so_quyet_dinh = '12'", "ck_council_document_set_ban_ky_du"),
        ("ban_ky_so_quyet_dinh = '1a', ban_ky_ngay = DATE '2026-09-08'", "ck_council_document_set_so_ban_ky"),
        (
            "ban_ky_so_quyet_dinh = '12', ban_ky_ngay = DATE '2026-09-08', cho_quyet_dinh_goc_id = 1",
            "ck_council_document_set_mot_che_do",
        ),
        ("dung_lai_tu_set_id = id", "ck_council_document_set_dung_lai_ban_ky"),
    ],
)
async def test_ba_che_do_cua_bo(c, dat, rang_buoc):
    s1, _ = await _bo(c, await _hs(c))
    assert await _thu(
        c,
        "UPDATE council_document_set SET ban_ky_so_quyet_dinh = '12', ban_ky_ngay = "
        "DATE '2026-09-08' WHERE id = :s",
        s=s1,
    ) is None  # đối chứng
    s2, _ = await _bo(c, await _hs(c))
    assert await _thu(
        c, "UPDATE council_document_set SET %s WHERE id = :s" % dat, s=s2
    ) == ("23514", rang_buoc)
