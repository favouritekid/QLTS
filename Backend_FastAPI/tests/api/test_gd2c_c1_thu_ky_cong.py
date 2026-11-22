"""GĐ2-C C1 — cổng ``deps.require_review_secretary`` (thiết kế GĐ2-C §4; ĐT3 T17: "Ban thư ký không quyền ⇒ 404; thu hồi giữa
hai lần bấm ⇒ chặn").

C1 chưa có route Ban thư ký thật (C2 mở). Đo bằng ứng dụng thử ``gd2c_thu_ky_tro_giup.ung_dung_cong``: ĐÚNG dependency thật
(xác thực thật, ``database.get_db`` thật, bộ xử lý lỗi thật), route ghi một dòng trên CÙNG phiên rồi commit — hình dạng route
ghi của Ban thư ký. Casbin thay bằng bộ cho-qua (lớp vai ở C2); ở đây đo lớp QUYỀN GÁN.

Hai phiên PostgreSQL + phiên thứ ba (``pg_blocking_pids``) đo thứ tự THẬT:

- lần bấm của Thư ký ĐANG ghi (giữ quyền ``FOR SHARE``) ⇒ Admin thu hồi phải CHỜ đúng lần bấm ấy; thả ⇒ cả hai xong, lần bấm
  SAU bị 404;
- Admin thu hồi ĐANG giữ dòng quyền ⇒ lần bấm của Thư ký phải CHỜ; Admin commit ⇒ lần bấm ấy 404 và KHÔNG ghi gì;
- tự thu hồi (Admin khoá tài khoản Thư ký) trong lúc Thư ký đang ghi ⇒ không bế tắc, 0 lỗi CSDL.

Biến thể kiểm ngược (phải ĐỎ): bỏ ``with_for_update(read=True)`` trong ``review_secretary_repository.lock_active_grant_share``
(đọc thường) ⇒ ca "thu hồi chờ" đỏ (``xong`` thay vì ``chan``) và ca "lần bấm chờ rồi 404" đỏ (200); đọc quyền bằng phiên RIÊNG
⇒ ca "khoá trong giao dịch của route" đỏ; bỏ lớp cổng (trả người dùng không kiểm) ⇒ ma trận 404 đỏ.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

import app.database as csdl
from app.repositories import review_secretary_repository as sec_repo
from tests.api.gd1b_cheo_tro_giup import THAN_404, bi_chan_boi_pid, tao_nguoi
from tests.api.gd1b_lo_tro_giup import Diem, PidTheoNhan, boc, dang_nhap, goi
from tests.api.gd2c_thu_ky_tro_giup import (
    DUONG_GHI_THU,
    P,
    dong_quyen,
    gan,
    so_lan_ghi_thu,
    thu_hoi,
    ung_dung_cong,
)
from tests.fixtures.constants import AdminURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _client_cong(nguoi: dict, diem=None):
    """Client tới ứng dụng thử, mang token THẬT của ``nguoi`` (đăng nhập qua ứng dụng thật). Trả (client thử, client thật)."""
    that, h = await dang_nhap(nguoi)
    thu = AsyncClient(transport=ASGITransport(app=ung_dung_cong(diem)), base_url="http://test", headers=h)
    return thu, that


class _LoiCsdl:
    """SQLSTATE mọi lỗi CSDL trong lúc đo (khuôn ``test_gd1b_xoa_tai_khoan_hai_phien._LoiCsdl``) — "0 lỗi CSDL" đo được."""

    def __init__(self):
        self.loi = []

    def __enter__(self):
        event.listen(csdl.engine.sync_engine, "handle_error", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(csdl.engine.sync_engine, "handle_error", self._ghi)

    def _ghi(self, ctx):
        from app.repositories.council_decision_repository import db_error_codes

        self.loi.append(db_error_codes(ctx.sqlalchemy_exception or ctx.original_exception)[0])


@pytest.fixture
async def thu_ky(seed_lead_dependencies):
    return await tao_nguoi("gd2c_c1_thuky", "officer", seed_lead_dependencies["unit_id"])


# ═════════════════════════════════════════════ không có quyền ⇒ 404 ══════════════════════════════════════════════════
@pytest.mark.parametrize("ca", ["can_bo_chua_gan", "quan_ly_chua_gan", "admin", "ke_toan", "da_thu_hoi"])
async def test_khong_co_quyen_con_hieu_luc_thi_404_khong_ghi(client, admin_user_in_db, seed_lead_dependencies, ca):
    unit = seed_lead_dependencies["unit_id"]
    if ca == "admin":
        nguoi = admin_user_in_db
    else:
        vai = {"can_bo_chua_gan": "officer", "quan_ly_chua_gan": "manager", "ke_toan": "accountant"}.get(ca, "officer")
        nguoi = await tao_nguoi("gd2c_c1_404_%s" % ca, vai, unit)
    if ca == "da_thu_hoi":
        g = (await gan(client, admin_user_in_db, nguoi["id"]))["id"]
        await thu_hoi(client, admin_user_in_db, g)
    thu, that = await _client_cong(nguoi)
    try:
        r = await thu.post(DUONG_GHI_THU)
    finally:
        await thu.aclose()
        await that.aclose()
    assert r.status_code == 404 and r.json() == THAN_404, (ca, r.text)
    assert await so_lan_ghi_thu(nguoi["id"]) == 0


@pytest.mark.parametrize("vai", ["officer", "manager"])
async def test_co_quyen_con_hieu_luc_thi_qua_cong_va_ghi(client, admin_user_in_db, seed_lead_dependencies, vai):
    nguoi = await tao_nguoi("gd2c_c1_qua_%s" % vai, vai, seed_lead_dependencies["unit_id"])
    await gan(client, admin_user_in_db, nguoi["id"])
    thu, that = await _client_cong(nguoi)
    try:
        r = await thu.post(DUONG_GHI_THU)
    finally:
        await thu.aclose()
        await that.aclose()
    assert r.status_code == 200, r.text
    assert await so_lan_ghi_thu(nguoi["id"]) == 1


async def test_cong_khoa_quyen_trong_chinh_giao_dich_cua_route(client, admin_user_in_db, thu_ky):
    """Phiên của route (đo TRƯỚC câu ghi) đang giữ ``ROW SHARE`` trên bảng quyền = dấu vết CSDL của ``SELECT … FOR SHARE``
    mà cổng chạy trong CHÍNH giao dịch ấy (cổng và route dùng chung ``database.get_db``)."""
    await gan(client, admin_user_in_db, thu_ky["id"])
    thu, that = await _client_cong(thu_ky)
    try:
        r = await thu.post(DUONG_GHI_THU)
    finally:
        await thu.aclose()
        await that.aclose()
    assert r.status_code == 200 and r.json() == {"khoa_quyen": True}, r.text


# ═════════════════════════════════════════════ T17 — hai phiên ═══════════════════════════════════════════════════════
@pytest.mark.parametrize("cach", ["thu_hoi_tay", "khoa_tai_khoan"])
async def test_thu_ky_dang_ghi_thi_thu_hoi_phai_cho_roi_lan_bam_sau_404(client, admin_user_in_db, thu_ky, cach):
    """B = lần bấm của Thư ký, dừng SAU cổng, TRƯỚC câu ghi (giữ quyền ``FOR SHARE``). C = Admin thu hồi tay / khoá tài khoản
    (tự thu hồi). C phải bị ĐÚNG phiên B chặn; thả ⇒ B ghi xong (200), C xong (200), quyền đã thu hồi; lần bấm SAU ⇒ 404.
    0 lỗi CSDL."""
    g = (await gan(client, admin_user_in_db, thu_ky["id"]))["id"]
    diem = Diem()
    thu, that_b = await _client_cong(thu_ky, diem)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            viec_b = asyncio.create_task(goi("B", lambda: thu.post(DUONG_GHI_THU)))
            viec_c = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                pid_b = set(ghi.pid.get("B", ()))
                assert pid_b, "tiền đề: đã ghi được PID của lần bấm B"
                if cach == "thu_hoi_tay":
                    viec_c = asyncio.create_task(goi("C", lambda: ca.post(
                        f"{P}/{g}/revoke", headers=ha, json={"reason": "Thu hồi khi đang bấm"})))
                else:
                    viec_c = asyncio.create_task(goi("C", lambda: ca.put(
                        AdminURLs.USER_DETAIL(thu_ky["id"]), headers=ha, data={"status": "inactive"})))
                tt = await bi_chan_boi_pid(viec_c, ghi, "C", pid_b)
            finally:
                diem.di.set()
                if viec_c is None:
                    await asyncio.gather(viec_b, return_exceptions=True)
            r_b = await asyncio.wait_for(viec_b, 60)
            r_c = await asyncio.wait_for(viec_c, 60)
    finally:
        await thu.aclose()
        await that_b.aclose()
        await ca.aclose()
    assert tt == "chan", f"thu hồi ({cach}) phải CHỜ lần bấm đang giữ quyền FOR SHARE ({tt})"
    assert (r_b.status_code, r_c.status_code, loi.loi) == (200, 200, []), (r_b.text, r_c.text)
    assert await so_lan_ghi_thu(thu_ky["id"]) == 1
    assert (await dong_quyen(g))["revoked_at"] is not None
    if cach == "thu_hoi_tay":  # tài khoản bị khoá thì không đăng nhập lại được để bấm lần sau
        thu2, that2 = await _client_cong(thu_ky)
        try:
            r = await thu2.post(DUONG_GHI_THU)
        finally:
            await thu2.aclose()
            await that2.aclose()
        assert r.status_code == 404 and r.json() == THAN_404, r.text
        assert await so_lan_ghi_thu(thu_ky["id"]) == 1


async def test_admin_dang_thu_hoi_thi_lan_bam_phai_cho_roi_404_khong_ghi(client, monkeypatch, admin_user_in_db, thu_ky):
    """C = Admin thu hồi, dừng SAU khi khoá dòng quyền ``FOR UPDATE``, CHƯA commit. B = lần bấm của Thư ký: phải bị ĐÚNG phiên
    C chặn ở cổng; C commit ⇒ PostgreSQL xét lại ``revoked_at IS NULL`` trên bản dòng mới ⇒ B 404, KHÔNG ghi gì."""
    g = (await gan(client, admin_user_in_db, thu_ky["id"]))["id"]
    diem = Diem()
    boc(monkeypatch, sec_repo, "lock_grant_for_update", diem)
    thu, that_b = await _client_cong(thu_ky)
    ca, ha = await dang_nhap(admin_user_in_db)
    try:
        with PidTheoNhan() as ghi, _LoiCsdl() as loi:
            viec_c = asyncio.create_task(goi("C", lambda: ca.post(
                f"{P}/{g}/revoke", headers=ha, json={"reason": "Thu hồi trước"})))
            viec_b = None
            try:
                await asyncio.wait_for(diem.toi.wait(), 30)
                pid_c = set(ghi.pid.get("C", ()))
                assert pid_c, "tiền đề: đã ghi được PID của lệnh thu hồi C"
                viec_b = asyncio.create_task(goi("B", lambda: thu.post(DUONG_GHI_THU)))
                tt = await bi_chan_boi_pid(viec_b, ghi, "B", pid_c)
            finally:
                diem.di.set()
                if viec_b is None:
                    await asyncio.gather(viec_c, return_exceptions=True)
            r_c = await asyncio.wait_for(viec_c, 60)
            r_b = await asyncio.wait_for(viec_b, 60)
    finally:
        await thu.aclose()
        await that_b.aclose()
        await ca.aclose()
    assert tt == "chan", f"lần bấm của Thư ký phải CHỜ lệnh thu hồi đang giữ dòng quyền ({tt})"
    assert r_c.status_code == 200, r_c.text
    assert r_b.status_code == 404 and r_b.json() == THAN_404, r_b.text
    assert loi.loi == []
    assert await so_lan_ghi_thu(thu_ky["id"]) == 0
