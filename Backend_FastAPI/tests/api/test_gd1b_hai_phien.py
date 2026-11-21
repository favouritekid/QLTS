"""GĐ1b V1 — hai phiên PostgreSQL thật trên mã lõi (đặc tả bản 3.6 §4.5, §9 "Thứ tự khoá", "K4 + khoá", "ghi giấy phải khoá
hồ sơ trước", §16 V1).

Mỗi người thao tác một ``AsyncClient`` riêng (ứng dụng ưu tiên cookie — dùng chung client sẽ lẫn danh tính). Điểm dừng: bọc
hàm của lõi để phiên A dừng khi ĐANG GIỮ khoá; thả A rồi đọc kết quả HAI phía. Bế tắc ⇒ một phía 500 (``40P01``) ⇒ ca đỏ.

Codex 68: "bị chặn" phải là ĐÚNG phiên B bị ĐÚNG phiên A chặn — không phải "có kết nối nào đó trong CSDL bị chặn". Mỗi yêu cầu
mang nhãn (``ContextVar`` — ``ASGITransport`` chạy ứng dụng ngay trong task gọi nên nhãn đi theo yêu cầu, kể cả task con của
middleware); ``before_cursor_execute`` ghi PID máy chủ của MỌI kết nối mà yêu cầu ấy dùng; phép đo hỏi
``pg_blocking_pids(pid_B)`` có chứa PID của A.

Kiểm ngược (bộ đột biến, không sửa tệp này): ``delete_profile`` về thứ tự cũ ⇒ ``DeadlockDetectedError``; ``upload_document`` về
thứ tự cũ ⇒ phiên tải lên KHÔNG chờ khoá hồ sơ.
"""
from __future__ import annotations

import asyncio
import contextvars
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text

import app.database as csdl
from app import models
from app.main import app as ung_dung
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    parity_config,
)
from tests.fixtures.constants import AdminURLs, AuthURLs

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
ADMISSIONS = "/api/admissions"
PDF = b"%PDF-1.4\n% gd1b hai phien\n%%EOF"

_NHAN: contextvars.ContextVar = contextvars.ContextVar("gd1b_hai_phien_nhan", default=None)


class _Diem:
    """Phiên tới điểm ⇒ báo ``toi`` rồi CHỜ ``di`` (giữ nguyên khoá). Chỉ dừng ở lần gọi ĐẦU."""

    def __init__(self):
        self.toi = asyncio.Event()
        self.di = asyncio.Event()
        self.so_lan = 0

    async def cho(self):
        self.so_lan += 1
        if self.so_lan == 1:
            self.toi.set()
            await asyncio.wait_for(self.di.wait(), 60)


def _boc(monkeypatch, chu, ten, diem):
    goc = getattr(chu, ten)

    async def boc(*a, **kw):
        kq = await goc(*a, **kw)
        await diem.cho()
        return kq

    monkeypatch.setattr(chu, ten, boc)


class _PidTheoNhan:
    """Ghi PID máy chủ PostgreSQL của mọi kết nối mà yêu cầu mang nhãn ``A`` / ``B`` dùng."""

    def __init__(self):
        self.pid = {}

    def __enter__(self):
        event.listen(csdl.engine.sync_engine, "before_cursor_execute", self._ghi)
        return self

    def __exit__(self, *a):
        event.remove(csdl.engine.sync_engine, "before_cursor_execute", self._ghi)

    def _ghi(self, conn, cursor, statement, parameters, context, executemany):
        nhan = _NHAN.get()
        if nhan:
            self.pid.setdefault(nhan, set()).add(conn.connection.driver_connection.get_server_pid())


async def _goi(nhan, ham):
    _NHAN.set(nhan)
    return await ham()


async def _bi_chan_boi(viec, ghi: _PidTheoNhan, bi="B", boi="A", giay=20.0):
    """``"chan"`` khi một kết nối của yêu cầu ``bi`` đang bị một kết nối của yêu cầu ``boi`` chặn (``pg_blocking_pids``);
    ``"xong"`` nếu ``viec`` kết thúc trước; ``"het_gio"``."""
    het = time.monotonic() + giay
    while time.monotonic() < het:
        bi_pid, boi_pid = set(ghi.pid.get(bi, ())), set(ghi.pid.get(boi, ()))
        if bi_pid and boi_pid:
            async with csdl.engine.connect() as k:
                hang = (
                    await k.execute(
                        text("SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid = ANY(:p)"),
                        {"p": list(bi_pid)},
                    )
                ).all()
            if any(set(chan) & boi_pid for _, chan in hang):
                return "chan"
        if viec.done():
            return "xong"
        await asyncio.sleep(0.1)
    return "het_gio"


async def _client(user: dict):
    c = AsyncClient(transport=ASGITransport(app=ung_dung), base_url="http://test")
    r = await c.post(AuthURLs.LOGIN, data={"username": user["username"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return c, {"Authorization": f"Bearer {r.cookies.get('access_token')}"}


async def _giay(pid: int, code: str) -> models.ProfileDocument:
    async with csdl.AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == pid, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


async def _nhan_giay(officer, pid, code):
    c, h = await _client(officer)
    try:
        r = await c.post(f"{ADMISSIONS}/{pid}/documents/{code}/paper-submitted", headers=h,
                         json={"actual_submission_format": "original"})
        assert r.status_code in (200, 201), r.text
    finally:
        await c.aclose()
    return await _giay(pid, code)


# --------------------------------------------------------------------------------------------------------------------
# Duyệt giấy (GĐ1b) ‖ xoá hồ sơ (đã đổi thứ tự hồ sơ → lead).
# --------------------------------------------------------------------------------------------------------------------
async def test_duyet_giay_song_song_xoa_ho_so_khong_be_tac_ket_qua_tuan_tu(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    from app.services import admission_service

    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "hp_xoa")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(officer_user_in_db, prof["id"], code)
    diem = _Diem()
    _boc(monkeypatch, admission_service, "_lock_profile_for_document_write", diem)

    ca, ha = await _client(manager_user_in_db)
    cb, hb = await _client(admin_user_in_db)
    try:
        with _PidTheoNhan() as ghi:
            a = asyncio.create_task(_goi("A", lambda: ca.patch(
                f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
                json={"format": "original", "expected_row_version": d.row_version},
            )))
            await asyncio.wait_for(diem.toi.wait(), 30)  # A đang GIỮ khoá hồ sơ
            b = asyncio.create_task(_goi("B", lambda: cb.delete(f"{ADMISSIONS}/{prof['id']}", headers=hb)))
            assert await _bi_chan_boi(b, ghi) == "chan", "xoá hồ sơ (B) phải CHỜ khoá hồ sơ mà phiên duyệt (A) giữ"
            diem.di.set()
            ra, rb = await asyncio.gather(a, b)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert ra.status_code == 200, ra.text
    # Tuần tự đúng: B chạy SAU A ⇒ giấy đã duyệt ⇒ K3-B chặn xoá.
    assert rb.status_code == 409, rb.text


# --------------------------------------------------------------------------------------------------------------------
# Đặt lại (GĐ1b) ‖ tải lên cùng giấy (upload đã đổi: khoá hồ sơ trước).
# --------------------------------------------------------------------------------------------------------------------
async def test_dat_lai_song_song_tai_len_cung_giay_khong_be_tac(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    from app.services import admission_service

    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "hp_tai")
    code = parity_config["upload_doc_code"]
    co, ho = await _client(officer_user_in_db)
    try:
        r = await co.post(f"{ADMISSIONS}/{prof['id']}/documents/{code}/upload", headers=ho,
                          files={"file": ("a.pdf", PDF, "application/pdf")}, data={"actual_submission_format": "photo"})
        assert r.status_code in (200, 201), r.text
    finally:
        await co.aclose()
    d = await _giay(prof["id"], code)
    diem = _Diem()
    _boc(monkeypatch, admission_service, "_lock_profile_for_document_write", diem)

    ca, ha = await _client(admin_user_in_db)
    cb, hb = await _client(officer_user_in_db)
    try:
        with _PidTheoNhan() as ghi:
            a = asyncio.create_task(_goi("A", lambda: ca.post(
                f"{ADMISSIONS}/{prof['id']}/documents/{code}/reset", headers=ha,
                json={"reason": "Tải nhầm", "expected_row_version": d.row_version},
            )))
            await asyncio.wait_for(diem.toi.wait(), 30)
            b = asyncio.create_task(_goi("B", lambda: cb.post(
                f"{ADMISSIONS}/{prof['id']}/documents/{code}/upload", headers=hb,
                files={"file": ("b.pdf", PDF, "application/pdf")}, data={"actual_submission_format": "photo"},
            )))
            assert await _bi_chan_boi(b, ghi) == "chan", "tải lên (B) phải CHỜ khoá hồ sơ mà phiên Đặt lại (A) giữ"
            diem.di.set()
            ra, rb = await asyncio.gather(a, b)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert ra.status_code == 200, ra.text
    assert rb.status_code in (200, 201), rb.text  # sau Đặt lại giấy về "missing" ⇒ tải lên hợp lệ
    assert (await _giay(prof["id"], code)).status == "uploaded"


# --------------------------------------------------------------------------------------------------------------------
# Duyệt giấy (GĐ1b) ‖ giao hồ sơ hàng loạt (bulk_assign: người đích FOR KEY SHARE → lead FOR UPDATE; không chờ hồ sơ / giấy).
#
# F18 (20-11): bản cũ giao cho CHÍNH cán bộ đang phụ trách (không đổi gì quan sát được), bỏ qua kết quả đo chặn, chỉ đòi
# ``< 500`` (``bulk_assign`` nuốt lỗi từng mục vào ``failed_ids`` ⇒ 200 với ``failed_count = 1`` vẫn xanh) và dừng phiên
# duyệt TRƯỚC khi nó khoá lead. Nay giao cho MỘT cán bộ KHÁC cùng đơn vị, đòi ``success_count == 1`` + lead đổi người phụ
# trách + giấy đã duyệt, ở HAI điểm dừng của phiên duyệt (A):
#   - ``sau_lead``  — A ĐANG GIỮ lead FOR SHARE (dừng ở ``log_document_action``, sau khi ghi giấy, chưa commit) ⇒ B PHẢI chờ
#     A (``pg_blocking_pids``); thả ⇒ lượt giao áp SAU khi duyệt commit, không mất.
#   - ``truoc_lead`` — A mới giữ HỒ SƠ, CHƯA khoá lead ⇒ B không được tạo vòng chờ với A. Kiểm ngược: ``bulk_assign`` khoá
#     lead RỒI hồ sơ (ngược thứ tự chung §4.5) ⇒ bế tắc ⇒ ca đỏ. (Khoá hồ sơ TRƯỚC lead — đúng chiều §4.5 — thì chỉ chờ,
#     không bế tắc: ca vẫn xanh, đúng.)
# --------------------------------------------------------------------------------------------------------------------
async def _can_bo_cung_don_vi(ten: str, unit_id: int) -> int:
    from app.security import get_password_hash

    async with csdl.AsyncSessionLocal() as s:
        async with s.begin():
            u = models.User(
                username=ten, email=f"{ten}@example.com", password_hash=get_password_hash("MatKhauThu!F18x9"),
                full_name=ten, role="officer", status="active", unit_id=unit_id,
            )
            s.add(u)
            await s.flush()
            return u.id


async def _nguoi_phu_trach(profile_id: int):
    async with csdl.AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.Lead.assigned_officer_id)
                .join(models.AdmissionProfile, models.AdmissionProfile.lead_id == models.Lead.id)
                .where(models.AdmissionProfile.id == profile_id)
            )
        ).scalar_one()


@pytest.mark.parametrize("diem_dung", ["sau_lead", "truoc_lead"])
async def test_duyet_giay_song_song_giao_ho_so_hang_loat_khong_be_tac(
    diem_dung, client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db,
    parity_config, seed_lead_dependencies,
):
    from app.services import admission_service, document_audit_service

    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, f"hp_giao_{diem_dung}")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(officer_user_in_db, prof["id"], code)
    can_bo_moi = await _can_bo_cung_don_vi(f"hp_giao_moi_{diem_dung}", seed_lead_dependencies["unit_id"])
    assert await _nguoi_phu_trach(prof["id"]) == officer_user_in_db["id"] != can_bo_moi
    diem = _Diem()
    if diem_dung == "sau_lead":
        _boc(monkeypatch, document_audit_service, "log_document_action", diem)
    else:
        _boc(monkeypatch, admission_service, "_lock_profile_for_document_write", diem)

    ca, ha = await _client(manager_user_in_db)
    cb, hb = await _client(admin_user_in_db)
    try:
        with _PidTheoNhan() as ghi:
            a = asyncio.create_task(_goi("A", lambda: ca.patch(
                f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
                json={"format": "original", "expected_row_version": d.row_version},
            )))
            await asyncio.wait_for(diem.toi.wait(), 30)
            b = asyncio.create_task(_goi("B", lambda: cb.post(
                f"{ADMISSIONS}/bulk/assign", headers=hb,
                json={"profile_ids": [prof["id"]], "officer_id": can_bo_moi},
            )))
            tt = await _bi_chan_boi(b, ghi)
            diem.di.set()
            ra, rb = await asyncio.gather(a, b)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    if diem_dung == "sau_lead":
        assert tt == "chan", f"giao hàng loạt (B) phải CHỜ khoá lead mà phiên duyệt (A) đang giữ ({tt})"
    assert ra.status_code == 200, ra.text
    assert rb.status_code == 200, rb.text
    assert (rb.json()["success_count"], rb.json()["failed_count"]) == (1, 0), rb.text
    assert await _nguoi_phu_trach(prof["id"]) == can_bo_moi
    assert (await _giay(prof["id"], code)).status == "verified"


# --------------------------------------------------------------------------------------------------------------------
# K4 + khoá: duyệt (giữ người thao tác FOR SHARE) ‖ xoá CHÍNH người thao tác.
# --------------------------------------------------------------------------------------------------------------------
async def test_k4_dang_duyet_thi_xoa_nguoi_thao_tac_cho_roi_409(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    from app.services import document_audit_service

    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "hp_k4a")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(officer_user_in_db, prof["id"], code)
    diem = _Diem()
    # Dừng ở log_document_action (sau khi ghi giấy, VẪN giữ mọi khoá — gồm người thao tác FOR SHARE —, chưa commit).
    _boc(monkeypatch, document_audit_service, "log_document_action", diem)

    ca, ha = await _client(manager_user_in_db)
    cb, hb = await _client(admin_user_in_db)
    try:
        with _PidTheoNhan() as ghi:
            a = asyncio.create_task(_goi("A", lambda: ca.patch(
                f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
                json={"format": "original", "expected_row_version": d.row_version},
            )))
            await asyncio.wait_for(diem.toi.wait(), 30)
            b = asyncio.create_task(_goi("B", lambda: cb.delete(
                AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb
            )))
            assert await _bi_chan_boi(b, ghi) == "chan", "xoá tài khoản (B) phải CHỜ khoá FOR SHARE của phiên đang duyệt (A)"
            diem.di.set()
            ra, rb = await asyncio.gather(a, b)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert ra.status_code == 200, ra.text
    assert rb.status_code == 409 and rb.json()["error_code"] == "USER_HAS_ACTIVITY", rb.text


async def test_k4_dang_xoa_nguoi_thao_tac_thi_duyet_bi_tu_choi(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    from app.services import user_service

    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "hp_k4b")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(officer_user_in_db, prof["id"], code)
    diem = _Diem()
    _boc(monkeypatch, user_service, "delete_user", diem)  # dừng SAU flush xoá, CHƯA commit (giữ khoá dòng user)

    ca, ha = await _client(manager_user_in_db)  # xác thực trước khi bị xoá
    cb, hb = await _client(admin_user_in_db)
    try:
        with _PidTheoNhan() as ghi:
            b = asyncio.create_task(_goi("B", lambda: cb.delete(
                AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb
            )))
            await asyncio.wait_for(diem.toi.wait(), 30)
            a = asyncio.create_task(_goi("A", lambda: ca.patch(
                f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
                json={"format": "original", "expected_row_version": d.row_version},
            )))
            # Lần này phiên DUYỆT (A) là bên bị chặn, bởi phiên XOÁ (B).
            tt = await _bi_chan_boi(a, ghi, bi="A", boi="B")
            diem.di.set()
            rb, ra = await asyncio.gather(b, a)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert tt == "chan", tt
    assert rb.status_code == 200, rb.text
    # A bị chặn rồi thấy người thao tác không còn ⇒ từ chối (409 actor_not_authorized hoặc 401 nếu xác thực lại thất bại).
    # Không bao giờ 200 / 500.
    assert ra.status_code in (401, 404, 409), (ra.status_code, ra.text)
    assert (await _giay(prof["id"], code)).status == "paper_submitted"
