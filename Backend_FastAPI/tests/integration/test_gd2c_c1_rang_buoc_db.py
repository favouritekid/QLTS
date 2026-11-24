# -*- coding: utf-8 -*-
"""GĐ2-C C1 — ràng buộc CSDL của bảng quyền "Thư ký Hội đồng" (tầng chủ sở hữu: CHECK / UNIQUE một phần / trigger "chỉ thu
hồi" / khoá ngoại RESTRICT). Câu SQL trực tiếp, không qua dịch vụ (dịch vụ chỉ là lớp phụ). Mỗi ca MỘT ràng buộc; ca hợp lệ
đi kèm làm đối chứng. Dữ liệu GIẢ trong một giao dịch, lùi khi ra (khuôn ``test_gd2a_rang_buoc_db.py``)."""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

import app.database as csdl
from app.repositories.council_decision_repository import db_error_codes

pytestmark = pytest.mark.integration


async def _x(c, sql, **ts):
    return await c.execute(text(sql), ts)


@pytest_asyncio.fixture
async def c(setup_test_database):
    """Một kết nối + giao dịch; lùi hết khi ra. ``info``: ba người dùng giả (Cán bộ ``u``, Admin ``a``, Cán bộ ``v``)."""
    async with csdl.engine.connect() as conn:
        gd = await conn.begin()
        for ten, vai in (("u", "officer"), ("a", "admin"), ("v", "officer")):
            conn.info[ten] = (
                await _x(
                    conn,
                    "INSERT INTO \"user\" (username, email, password_hash, role, status, total_lead_score) "
                    "VALUES (:n, :e, 'x', :r, 'active', 0) RETURNING id",
                    n="gd2c_c1_rb_%s" % ten, e="gd2c_c1_rb_%s@example.com" % ten, r=vai,
                )
            ).scalar_one()
        try:
            yield conn
        finally:
            await gd.rollback()


async def _loi(c, cau, **ts):
    """Chạy ``cau`` trong một savepoint; trả (SQLSTATE, tên ràng buộc) của lỗi, hoặc None nếu KHÔNG lỗi (lùi savepoint)."""
    sp = await c.begin_nested()
    try:
        await _x(c, cau, **ts)
    except DBAPIError as e:
        await sp.rollback()
        return db_error_codes(e)
    await sp.rollback()
    return None


async def _gan(c, ai="u", ly_do="Ban thư ký đợt 1"):
    return (
        await _x(
            c,
            "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES (:u, :a, :l) "
            "RETURNING id",
            u=c.info[ai], a=c.info["a"], l=ly_do,
        )
    ).scalar_one()


THU_HOI = (
    "UPDATE admission_review_secretary_grant SET revoked_at = clock_timestamp(), revoked_by_user_id = :a, "
    "revoke_reason = 'Hết nhiệm vụ' WHERE id = :g"
)


# ── CHECK ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
async def test_ly_do_gan_rong_bi_chan(c):
    assert await _loi(
        c,
        "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES (:u, :a, '   ')",
        u=c.info["u"], a=c.info["a"],
    ) == ("23514", "ck_review_secretary_grant_reason")


async def test_ba_cot_thu_hoi_phai_di_cung_nhau(c):
    """Có lúc thu hồi + lý do mà THIẾU người thu hồi ⇒ chặn (INSERT — không qua trigger, chỉ CHECK đo)."""
    assert await _loi(
        c,
        "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason, revoked_at, revoke_reason) "
        "VALUES (:u, :a, 'x', now(), 'y')",
        u=c.info["u"], a=c.info["a"],
    ) == ("23514", "ck_review_secretary_grant_revoked_triple")


async def test_ly_do_thu_hoi_rong_bi_chan(c):
    assert await _loi(
        c,
        "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason, revoked_at, revoked_by_user_id,"
        " revoke_reason) VALUES (:u, :a, 'x', now(), :a, ' ')",
        u=c.info["u"], a=c.info["a"],
    ) == ("23514", "ck_review_secretary_grant_revoke_reason")


# ── UNIQUE một phần ───────────────────────────────────────────────────────────────────────────────────────────────────
async def test_hai_quyen_con_hieu_luc_cung_mot_nguoi_bi_chan(c):
    await _gan(c)
    assert await _loi(
        c,
        "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES (:u, :a, 'lần hai')",
        u=c.info["u"], a=c.info["a"],
    ) == ("23505", "uq_review_secretary_grant_active_user")


async def test_quyen_da_thu_hoi_khong_chan_gan_lai(c):
    """Đối chứng của ca trên: chỉ quyền CÒN hiệu lực bị giới hạn một — gán lại sau thu hồi = dòng mới."""
    g = await _gan(c)
    await _x(c, THU_HOI, a=c.info["a"], g=g)
    assert await _loi(
        c,
        "INSERT INTO admission_review_secretary_grant (user_id, granted_by_user_id, reason) VALUES (:u, :a, 'gán lại')",
        u=c.info["u"], a=c.info["a"],
    ) is None


# ── trigger "chỉ thu hồi, không xoá" ──────────────────────────────────────────────────────────────────────────────────
async def test_thu_hoi_lan_dau_hop_le(c):
    g = await _gan(c)
    assert await _loi(c, THU_HOI, a=c.info["a"], g=g) is None


async def test_xoa_dong_quyen_bi_chan(c):
    g = await _gan(c)
    assert await _loi(c, "DELETE FROM admission_review_secretary_grant WHERE id = :g", g=g) == ("QLC20", None)


async def test_xoa_dong_quyen_da_thu_hoi_cung_bi_chan(c):
    g = await _gan(c)
    await _x(c, THU_HOI, a=c.info["a"], g=g)
    assert await _loi(c, "DELETE FROM admission_review_secretary_grant WHERE id = :g", g=g) == ("QLC20", None)


async def test_thu_hoi_lan_hai_bi_chan(c):
    g = await _gan(c)
    await _x(c, THU_HOI, a=c.info["a"], g=g)
    assert await _loi(c, THU_HOI, a=c.info["a"], g=g) == ("QLC20", None)


async def test_mo_lai_quyen_da_thu_hoi_bi_chan(c):
    g = await _gan(c)
    await _x(c, THU_HOI, a=c.info["a"], g=g)
    assert await _loi(
        c,
        "UPDATE admission_review_secretary_grant SET revoked_at = NULL, revoked_by_user_id = NULL, revoke_reason = NULL "
        "WHERE id = :g",
        g=g,
    ) == ("QLC20", None)


@pytest.mark.parametrize(
    "cot, gia_tri",
    [
        ("user_id", ":v"),
        ("granted_by_user_id", ":v"),
        ("granted_at", "granted_at - interval '1 day'"),
        ("reason", "'lý do khác'"),
    ],
)
async def test_sua_cot_lan_gan_kem_thu_hoi_bi_chan(c, cot, gia_tri):
    """Ghi thu hồi lần đầu nhưng ĐỔI THÊM một cột của lần gán ⇒ chặn (ghi thu hồi thuần là hợp lệ — ca đối chứng trên)."""
    g = await _gan(c)
    ts = {"a": c.info["a"], "g": g, **({"v": c.info["v"]} if ":v" in gia_tri else {})}
    assert await _loi(
        c,
        "UPDATE admission_review_secretary_grant SET revoked_at = clock_timestamp(), revoked_by_user_id = :a, "
        "revoke_reason = 'x', %s = %s WHERE id = :g" % (cot, gia_tri),
        **ts,
    ) == ("QLC20", None)


async def test_sua_ly_do_khi_chua_thu_hoi_bi_chan(c):
    g = await _gan(c)
    assert await _loi(
        c, "UPDATE admission_review_secretary_grant SET reason = 'lý do mới' WHERE id = :g", g=g
    ) == ("QLC20", None)


# ── khoá ngoại RESTRICT (lớp phòng thủ thêm của K4) ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("ai", ["u", "a"])
async def test_xoa_nguoi_duoc_gan_hoac_nguoi_gan_bi_khoa_ngoai_chan(c, ai):
    await _gan(c)
    kq = await _loi(c, "DELETE FROM \"user\" WHERE id = :x", x=c.info[ai])
    assert kq is not None and kq[0] == "23503", kq
