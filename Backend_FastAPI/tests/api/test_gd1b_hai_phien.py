"""GĐ1b V1 — hai phiên PostgreSQL thật trên mã lõi (đặc tả bản 3.6 §4.5, §9 "Thứ tự khoá", "K4 + khoá", "ghi giấy phải khoá
hồ sơ trước", §16 V1).

Mỗi người thao tác một ``AsyncClient`` riêng (ứng dụng ưu tiên cookie — dùng chung client sẽ lẫn danh tính). Điểm dừng: bọc
hàm của lõi để phiên A dừng khi ĐANG GIỮ khoá; đo phiên B bị chặn bằng ``pg_blocking_pids`` từ một kết nối khác; thả A rồi đọc
kết quả HAI phía. Bế tắc ⇒ một phía 500 (PostgreSQL ``40P01``) ⇒ ca đỏ.

Kiểm ngược (chạy bằng bộ đột biến, không sửa tệp này): trả ``delete_profile`` / ``upload_document`` về thứ tự cũ ⇒ phép đo thấy
bế tắc.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

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


async def _cho_bi_chan(viec, giay=20.0):
    het = time.monotonic() + giay
    while time.monotonic() < het:
        async with csdl.engine.connect() as k:
            n = (
                await k.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND cardinality(pg_blocking_pids(pid)) > 0"
                    )
                )
            ).scalar_one()
        if n:
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
        a = asyncio.create_task(ca.patch(
            f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
            json={"format": "original", "expected_row_version": d.row_version},
        ))
        await asyncio.wait_for(diem.toi.wait(), 30)  # A đang GIỮ khoá hồ sơ
        b = asyncio.create_task(cb.delete(f"{ADMISSIONS}/{prof['id']}", headers=hb))
        assert await _cho_bi_chan(b) == "chan", "xoá hồ sơ phải CHỜ khoá hồ sơ của phiên duyệt"
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
        a = asyncio.create_task(ca.post(
            f"{ADMISSIONS}/{prof['id']}/documents/{code}/reset", headers=ha,
            json={"reason": "Tải nhầm", "expected_row_version": d.row_version},
        ))
        await asyncio.wait_for(diem.toi.wait(), 30)
        b = asyncio.create_task(cb.post(
            f"{ADMISSIONS}/{prof['id']}/documents/{code}/upload", headers=hb,
            files={"file": ("b.pdf", PDF, "application/pdf")}, data={"actual_submission_format": "photo"},
        ))
        assert await _cho_bi_chan(b) == "chan", "tải lên phải CHỜ khoá hồ sơ (khoá hồ sơ trước khi ghi giấy)"
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
# Duyệt giấy (GĐ1b) ‖ giao hồ sơ hàng loạt (bulk_assign giữ lead FOR UPDATE, không chờ hồ sơ / giấy).
# --------------------------------------------------------------------------------------------------------------------
async def test_duyet_giay_song_song_giao_ho_so_hang_loat_khong_be_tac(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    from app.services import admission_service

    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "hp_giao")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(officer_user_in_db, prof["id"], code)
    diem = _Diem()
    _boc(monkeypatch, admission_service, "_lock_profile_for_document_write", diem)

    ca, ha = await _client(manager_user_in_db)
    cb, hb = await _client(admin_user_in_db)
    try:
        a = asyncio.create_task(ca.patch(
            f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
            json={"format": "original", "expected_row_version": d.row_version},
        ))
        await asyncio.wait_for(diem.toi.wait(), 30)
        b = asyncio.create_task(cb.post(
            f"{ADMISSIONS}/bulk/assign", headers=hb,
            json={"profile_ids": [prof["id"]], "officer_id": officer_user_in_db["id"]},
        ))
        await _cho_bi_chan(b, giay=5.0)  # có thể không chặn: bulk_assign chỉ giữ lead
        diem.di.set()
        ra, rb = await asyncio.gather(a, b)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert ra.status_code == 200, ra.text
    assert rb.status_code < 500, rb.text


# --------------------------------------------------------------------------------------------------------------------
# K4 + khoá: duyệt (giữ người thao tác FOR SHARE) ‖ xoá CHÍNH người thao tác.
# --------------------------------------------------------------------------------------------------------------------
async def test_k4_dang_duyet_thi_xoa_nguoi_thao_tac_cho_roi_409(
    client, monkeypatch, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "hp_k4a")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(officer_user_in_db, prof["id"], code)
    diem = _Diem()

    # Dừng ở log_document_action của dịch vụ nhật ký (sau khi ghi giấy, VẪN giữ mọi khoá, chưa commit).
    from app.services import document_audit_service

    _boc(monkeypatch, document_audit_service, "log_document_action", diem)

    ca, ha = await _client(manager_user_in_db)
    cb, hb = await _client(admin_user_in_db)
    try:
        a = asyncio.create_task(ca.patch(
            f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
            json={"format": "original", "expected_row_version": d.row_version},
        ))
        await asyncio.wait_for(diem.toi.wait(), 30)  # A đã ghi giấy, GIỮ mọi khoá (gồm người thao tác FOR SHARE)
        b = asyncio.create_task(cb.delete(AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb))
        assert await _cho_bi_chan(b) == "chan", "xoá tài khoản phải CHỜ khoá FOR SHARE của phiên đang duyệt"
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
        b = asyncio.create_task(cb.delete(AdminURLs.USER_DETAIL(manager_user_in_db["id"]), headers=hb))
        await asyncio.wait_for(diem.toi.wait(), 30)
        a = asyncio.create_task(ca.patch(
            f"{ADMISSIONS}/{prof['id']}/documents/{code}/verify-format", headers=ha,
            json={"format": "original", "expected_row_version": d.row_version},
        ))
        tt = await _cho_bi_chan(a)
        diem.di.set()
        rb, ra = await asyncio.gather(b, a)
    finally:
        diem.di.set()
        await ca.aclose()
        await cb.aclose()
    assert rb.status_code == 200, rb.text
    # A tới sau: hoặc bị chặn ở khoá người thao tác rồi thấy dòng đã xoá (409 actor_not_authorized), hoặc bị từ chối ngay ở
    # xác thực (401) nếu yêu cầu tới sau commit. Không bao giờ 200 / 500.
    assert ra.status_code in (401, 404, 409), (tt, ra.status_code, ra.text)
    assert (await _giay(prof["id"], code)).status == "paper_submitted"
