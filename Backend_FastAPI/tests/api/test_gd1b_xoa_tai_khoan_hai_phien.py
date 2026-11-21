"""GĐ1b K4 — xoá tài khoản LẺ qua HTTP thật, hai phiên PostgreSQL + phiên thứ ba đo (đặc tả bản 3.6 §4.3, §4.5 mục 4, §9
"Hai lệnh xoá admin chéo ⇒ không bế tắc, guard admin cuối đúng"; xác minh Codex F1, 20-11).

Bản cũ của ``DELETE /api/admin/users/{id}`` ghi nhật ký (INSERT ``user_activity_log`` — khoá ngoại tới dòng người bị xoá VÀ
dòng Admin bấm ⇒ PostgreSQL giữ ``FOR KEY SHARE`` hai dòng ấy tới hết giao dịch) TRƯỚC khi K4 khoá ``FOR UPDATE``:

- ca 1 — lệnh A đã khoá K4, lệnh B (cùng U) chờ ở câu ghi nhật ký; A commit ⇒ B gặp ``23503`` ⇒ 500 thay vì 404;
- ca 2 — cả hai lệnh cùng U đã qua bước ghi nhật ký rồi mới khoá ⇒ bế tắc ``40P01`` ⇒ 500;
- ca 3 — hai Admin xoá hai Admin khác nhau: mỗi bên giữ khoá khoá-ngoại trên dòng Admin mà câu khoá K4 (khoá MỌI admin
  đang hoạt động) của bên kia cần ⇒ bế tắc ⇒ 500.

Test cũ ``tests/services/test_user.py::test_concurrent_delete_admins_serialized_by_lock`` gọi thẳng dịch vụ (bỏ qua bước ghi
nhật ký của route) nên không thấy. Mỗi người thao tác một ``AsyncClient`` riêng (User-Agent khác nhau ⇒ hai "thiết bị" — đăng
nhập lại trên cùng thiết bị thu hồi phiên cũ); "bị chặn" đo bằng ``pg_blocking_pids`` từ kết nối khác, đúng PID từng yêu cầu.

Kiểm ngược (bản chép ngoài kho): trả route về thứ tự cũ (ghi nhật ký trước) ⇒ ca 1 đỏ vì 500 ``ForeignKeyViolationError``,
ca 2 và ca 3 đỏ vì 500 ``DeadlockDetectedError``; ca 4 (nhật ký) XANH ở cả bản cũ lẫn bản mới — dữ liệu lưu y hệt.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event, func, select, text

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from app.repositories.council_decision_repository import db_error_codes
from app.security import get_password_hash
from tests.api.gd1b_lo_tro_giup import NHAN, Diem, PidTheoNhan, bi_chan_boi, boc, dang_nhap, goi
from tests.fixtures.constants import AdminURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class _LoiCsdl:
    """Lỗi CSDL (lớp lỗi asyncpg + SQLSTATE) theo nhãn yêu cầu — để thông báo của ca đỏ nói ĐÚNG lý do (bế tắc / khoá
    ngoại), không chỉ "500"."""

    def __init__(self):
        self.loi = {}

    def __enter__(self):
        event.listen(csdl.engine.sync_engine, "handle_error", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(csdl.engine.sync_engine, "handle_error", self._ghi)

    def _ghi(self, ctx):
        goc = ctx.original_exception
        lop = type(getattr(goc, "__cause__", None) or goc).__name__
        sqlstate, _ = db_error_codes(ctx.sqlalchemy_exception or goc)
        self.loi.setdefault(NHAN.get() or "?", []).append(f"{lop}/{sqlstate}")


async def _tao_nguoi(ten: str, role: str = "officer") -> int:
    """Tài khoản CHƯA từng thao tác gì (K4 cho xoá) — không vai Casbin, không đăng nhập."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            u = models.User(
                username=ten, email=f"{ten}@example.com", password_hash=get_password_hash("MatKhauThu!F1x9"),
                full_name=ten, role=role, status="active",
            )
            s.add(u)
            await s.flush()
            return u.id


async def _admin_dang_nhap_duoc(ten: str) -> dict:
    """Admin có vai Casbin (đăng nhập + gọi route xoá được), chưa từng thao tác gì."""
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

    from app.main import fastapi_app
    from tests.fixtures.users import create_user_with_role

    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": ten, "email": f"{ten}@example.com", "password": "AdminF1Password!123",
            "role": "admin", "status": "active",
        },
        casbin_role="role:admin",
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )


async def _con(uid: int) -> bool:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(func.count()).select_from(models.User).where(models.User.id == uid))).scalar() == 1


async def _admin_dang_hoat_dong() -> set:
    async with AsyncSessionLocal() as s:
        return set(
            (await s.execute(text("SELECT id FROM \"user\" WHERE role = 'admin' AND status = 'active'"))).scalars()
        )


async def _hai_lenh_xoa(monkeypatch, chu, ten, *, truoc: bool, a, b):
    """A tới điểm dừng (bọc ``chu.ten``) rồi CHỜ; B chạy; đo B có bị A chặn; thả A. ``a`` / ``b`` = ``(client, headers,
    id cần xoá)``. Trả ``(ra, rb, trạng thái đo chặn, lỗi CSDL theo nhãn)``."""
    diem = Diem()
    boc(monkeypatch, chu, ten, diem, truoc=truoc)
    (ca, ha, ua), (cb, hb, ub) = a, b
    with PidTheoNhan() as ghi, _LoiCsdl() as loi:
        ta = asyncio.create_task(goi("A", lambda: ca.delete(AdminURLs.USER_DETAIL(ua), headers=ha)))
        tb = None
        try:
            await asyncio.wait_for(diem.toi.wait(), 30)
            tb = asyncio.create_task(goi("B", lambda: cb.delete(AdminURLs.USER_DETAIL(ub), headers=hb)))
            tt = await bi_chan_boi(tb, ghi)
        finally:
            diem.di.set()
            if tb is None:  # A không tới điểm dừng: vẫn chờ A xong để không bỏ lại tác vụ treo
                await asyncio.gather(ta, return_exceptions=True)
        ra, rb = await asyncio.gather(ta, tb)
    return ra, rb, tt, loi.loi


# --------------------------------------------------------------------------------------------------------------------
# Ca 1 — hai lệnh xoá CÙNG tài khoản (bấm đúp / hai tab), A đang GIỮ khoá K4 ⇒ B chờ ⇒ A 200, B 404 (không 500).
# --------------------------------------------------------------------------------------------------------------------
async def test_hai_lenh_xoa_cung_tai_khoan_lenh_sau_cho_khoa_k4_roi_404(client, monkeypatch, admin_user_in_db):
    from app.services import user_deletion_policy

    u = await _tao_nguoi("f1_cung_u")
    ca, ha = await dang_nhap(admin_user_in_db)
    cb, hb = await dang_nhap(admin_user_in_db)  # tab thứ hai của CÙNG Admin
    try:
        # A dừng NGAY SAU ``assert_user_deletable``: đã khoá ``FOR UPDATE`` dòng U + kiểm K4 đạt, CHƯA xoá / commit.
        ra, rb, tt, loi = await _hai_lenh_xoa(
            monkeypatch, user_deletion_policy, "assert_user_deletable", truoc=False, a=(ca, ha, u), b=(cb, hb, u)
        )
    finally:
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", f"lệnh xoá thứ hai (B) phải CHỜ khoá K4 mà lệnh đầu (A) đang giữ ({tt})"
    assert (ra.status_code, rb.status_code) == (200, 404), (ra.status_code, rb.status_code, rb.text, loi)
    assert not await _con(u)


# --------------------------------------------------------------------------------------------------------------------
# Ca 2 — hai lệnh xoá CÙNG tài khoản, A đã qua kiểm quyền nhưng CHƯA tới bước khoá K4 ⇒ không bế tắc: đúng một 200 + một 404.
# --------------------------------------------------------------------------------------------------------------------
async def test_hai_lenh_xoa_cung_tai_khoan_chua_toi_buoc_khoa_khong_be_tac(client, monkeypatch, admin_user_in_db):
    from app.services import user_service

    u = await _tao_nguoi("f1_be_tac_u")
    ca, ha = await dang_nhap(admin_user_in_db)
    cb, hb = await dang_nhap(admin_user_in_db)
    try:
        # A dừng ở ĐẦU ``delete_user`` (sau kiểm quyền; thứ tự cũ: sau cả câu ghi nhật ký giữ KEY SHARE dòng U).
        ra, rb, tt, loi = await _hai_lenh_xoa(
            monkeypatch, user_service, "delete_user", truoc=True, a=(ca, ha, u), b=(cb, hb, u)
        )
    finally:
        await ca.aclose()
        await cb.aclose()
    # A chưa giữ khoá nào trên U ⇒ B xoá xong trước (200); A tới bước khoá thì U không còn ⇒ 404.
    assert (ra.status_code, rb.status_code) == (404, 200), (ra.status_code, rb.status_code, ra.text, rb.text, tt, loi)
    assert not await _con(u)


# --------------------------------------------------------------------------------------------------------------------
# Ca 3 — hai Admin xoá hai Admin khác nhau cùng lúc ⇒ không 500, guard "admin cuối" đúng.
#   - ``hai_dich_rieng``: X xoá T1, Y xoá T2 (4 admin đang hoạt động) ⇒ cả hai 200, còn X, Y.
#   - ``xoa_cheo``: X xoá Y, Y xoá X (2 admin đang hoạt động) ⇒ đúng một 200; bên sau chạm guard admin cuối ⇒ 400; còn 1.
# --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ca_xoa", ["hai_dich_rieng", "xoa_cheo"])
async def test_hai_admin_xoa_hai_admin_khac_nhau_khong_be_tac_giu_admin_cuoi(ca_xoa, client, monkeypatch):
    from app.services import user_service

    x = await _admin_dang_nhap_duoc(f"f1_x_{ca_xoa}")
    y = await _admin_dang_nhap_duoc(f"f1_y_{ca_xoa}")
    if ca_xoa == "hai_dich_rieng":
        dich_x = await _tao_nguoi(f"f1_t1_{ca_xoa}", role="admin")
        dich_y = await _tao_nguoi(f"f1_t2_{ca_xoa}", role="admin")
        mong_doi, con_lai = (200, 200), {x["id"], y["id"]}
    else:
        dich_x, dich_y = y["id"], x["id"]
        mong_doi, con_lai = (400, 200), {y["id"]}
    assert await _admin_dang_hoat_dong() == {x["id"], y["id"], dich_x, dich_y}
    cx, hx = await dang_nhap(x)
    cy, hy = await dang_nhap(y)
    try:
        # A (X) dừng ở ĐẦU ``delete_user`` — thứ tự cũ: đã ghi nhật ký (KEY SHARE dòng X + dòng đích của X).
        ra, rb, tt, loi = await _hai_lenh_xoa(
            monkeypatch, user_service, "delete_user", truoc=True, a=(cx, hx, dich_x), b=(cy, hy, dich_y)
        )
    finally:
        await cx.aclose()
        await cy.aclose()
    assert (ra.status_code, rb.status_code) == mong_doi, (ra.status_code, rb.status_code, ra.text, rb.text, tt, loi)
    assert await _admin_dang_hoat_dong() == con_lai


# --------------------------------------------------------------------------------------------------------------------
# Ca 4 — dòng nhật ký ``delete_user`` sau commit: đủ cột, ``target_user_id`` NULL, id người bị xoá ở ``resource_id``.
# Ca này XANH cả ở thứ tự cũ (cột ``target_user_id`` bị gán NULL lúc xoá) ⇒ đổi thứ tự không đổi dữ liệu lưu.
# --------------------------------------------------------------------------------------------------------------------
async def test_nhat_ky_xoa_tai_khoan_luu_du_cot_nhu_truoc(client, admin_user_in_db):
    u = await _tao_nguoi("f1_nhat_ky_u")
    c, h = await dang_nhap(admin_user_in_db)
    try:
        r = await c.delete(AdminURLs.USER_DETAIL(u), headers=h)
        ua = c.headers["user-agent"]
    finally:
        await c.aclose()
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        dong = (
            await s.execute(
                text(
                    "SELECT actor_id, target_user_id, action, resource_type, resource_id, description, changes::text AS changes,"
                    " ip_address, user_agent FROM user_activity_log WHERE action = 'delete_user' AND resource_id = :u"
                ),
                {"u": u},
            )
        ).mappings().all()
    assert [dict(d) for d in dong] == [
        {
            "actor_id": admin_user_in_db["id"],
            "target_user_id": None,
            "action": "delete_user",
            "resource_type": "user",
            "resource_id": u,
            "description": "Admin deleted user: f1_nhat_ky_u",
            "changes": "null",  # cột JSON: ``None`` của ORM lưu thành JSON ``null`` (không phải SQL NULL) — như bản cũ
            "ip_address": "127.0.0.1",
            "user_agent": ua,
        }
    ]
