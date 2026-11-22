"""PR-D (F15, phần máy chủ) — yêu cầu cam kết "không rõ người nhận" trả THEO TỪNG thao tác.

Trước PR-D chỉ có ``requires_ack`` gộp Duyệt / Từ chối / Đặt lại bằng OR. Giấy CHƯA duyệt không rõ người nhận: Đặt lại không
qua cổng người nhận (không cần cam kết) nhưng cờ gộp báo "cần" ⇒ hộp Đặt lại buộc tích cam kết, còn nhật ký lại ghi
``unknown_submitter_ack = false``. Từ PR-D: ``verify_requires_ack`` / ``reject_requires_ack`` / ``reset_requires_ack`` tính bằng
ĐÚNG ``document_review_rules.decide`` của cổng ghi; ``requires_ack`` cũ GIỮ NGUYÊN (giao diện hiện hành đọc nó — sửa ở PR
giao diện riêng).

Mỗi ca MỘT bất biến. Giấy bản giấy do cán bộ phụ trách nhận, rồi đánh dấu "không rõ người nhận" bằng SQL (dữ liệu cũ §4.4).
Người xem / thao tác: Admin (người duyệt, khác người nhận). Dữ liệu giả.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app import models
from app.database import AsyncSessionLocal
from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    _login,
    parity_config,
)
from tests.fixtures.gd1b import phien_ban_giay

pytestmark = pytest.mark.asyncio
ADMISSIONS = "/api/admissions"


async def _dn(client: AsyncClient, user: dict) -> dict:
    client.cookies.clear()
    return await _login(client, user["username"], user["password"])


async def _id_giay(pid: int, code: str) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument.id)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == pid, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


async def _khong_ro_nguoi_nhan(doc_id: int):
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("UPDATE profile_document SET paper_submitted_by = NULL, paper_submitted_by_unknown = true WHERE id = :d"),
                {"d": doc_id},
            )


async def _giay_khong_ro_nguoi_nhan(client, admin_h, admin, officer, cfg, hau_to, *, da_duyet: bool):
    """Hồ sơ nháp + giấy bản giấy cán bộ đã nhận (+ Admin đã duyệt nếu ``da_duyet``), rồi mất người nhận."""
    prof = await _create_profile(client, admin_h, officer, cfg, f"prd_ack_{hau_to}")
    pid, code = prof["id"], cfg["paper_doc_code"]
    h = await _dn(client, officer)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/paper-submitted", headers=h, json={"actual_submission_format": "original"}
    )
    assert r.status_code == 200, r.text
    if da_duyet:
        h = await _dn(client, admin)
        r = await client.patch(
            f"{ADMISSIONS}/{pid}/documents/{code}/verify-format", headers=h,
            json={"format": "original", "expected_row_version": await phien_ban_giay(pid, code)},
        )
        assert r.status_code == 200, r.text
    await _khong_ro_nguoi_nhan(await _id_giay(pid, code))
    return pid, code


async def _dong(client, user, pid, code) -> dict:
    h = await _dn(client, user)
    r = await client.get(f"{ADMISSIONS}/{pid}", headers=h)
    assert r.status_code == 200, r.text
    dong = [d for d in r.json()["documents_checklist"] if d["code"] == code]
    assert len(dong) == 1, r.json()["documents_checklist"]
    return dong[0]


def _co(dong: dict) -> dict:
    return {k: dong.get(k) for k in ("verify_requires_ack", "reject_requires_ack", "reset_requires_ack")}


async def _nhat_ky_dat_lai(doc_id: int) -> models.DocumentAuditLog:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.DocumentAuditLog)
                .where(models.DocumentAuditLog.profile_document_id == doc_id, models.DocumentAuditLog.action == "reset")
                .order_by(models.DocumentAuditLog.id.desc())
                .limit(1)
            )
        ).scalar_one()


# ---------------------------------------------------------------- cờ theo thao tác
async def test_giay_chua_duyet_khong_ro_nguoi_nhan_duyet_va_tu_choi_can_cam_ket_dat_lai_khong(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, code = await _giay_khong_ro_nguoi_nhan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, "chua", da_duyet=False
    )
    dong = await _dong(client, admin_user_in_db, pid, code)
    assert dong["status"] == "paper_submitted" and dong["can_verify"] and dong["can_reject"] and dong["can_reset"], dong
    assert _co(dong) == {"verify_requires_ack": True, "reject_requires_ack": True, "reset_requires_ack": False}, dong


async def test_giay_da_duyet_khong_ro_nguoi_nhan_dat_lai_van_can_cam_ket(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, code = await _giay_khong_ro_nguoi_nhan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, "da", da_duyet=True
    )
    dong = await _dong(client, admin_user_in_db, pid, code)
    assert dong["status"] == "verified" and dong["can_reset"] and not dong["can_verify"], dong
    assert _co(dong) == {"verify_requires_ack": False, "reject_requires_ack": True, "reset_requires_ack": True}, dong


async def test_truong_cu_requires_ack_giu_nguyen_nghia_gop_cho_giao_dien_hien_hanh(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """Giao diện hiện hành vẫn đọc ``requires_ack`` (gộp) — PR-D không đổi giá trị của nó."""
    pid, code = await _giay_khong_ro_nguoi_nhan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, "cu", da_duyet=False
    )
    dong = await _dong(client, admin_user_in_db, pid, code)
    assert dong["requires_ack"] is True, dong
    assert dong["requires_ack"] == any(_co(dong).values()), dong


# ---------------------------------------------------------------- nhật ký Đặt lại khớp cờ của chính thao tác Đặt lại
async def test_dat_lai_giay_chua_duyet_theo_co_dat_lai_thanh_cong_va_nhat_ky_ghi_khong_cam_ket(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """Giao diện làm theo ``reset_requires_ack`` (không cần ⇒ không gửi cam kết) ⇒ 200, nhật ký ghi đúng "không cam kết"."""
    pid, code = await _giay_khong_ro_nguoi_nhan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, "nk_chua", da_duyet=False
    )
    dong = await _dong(client, admin_user_in_db, pid, code)
    h = await _dn(client, admin_user_in_db)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/reset", headers=h,
        json={
            "expected_row_version": dong["row_version"], "reason": "Nhận nhầm giấy",
            "unknown_submitter_ack": dong["reset_requires_ack"],
        },
    )
    assert r.status_code == 200, r.text
    nk = await _nhat_ky_dat_lai(dong["document_row_id"])
    assert nk.extra_data["unknown_submitter_ack"] is dong["reset_requires_ack"] is False, (nk.extra_data, dong)


async def test_dat_lai_giay_da_duyet_khong_ro_nguoi_nhan_co_cam_ket_thi_nhat_ky_ghi_co_cam_ket(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, code = await _giay_khong_ro_nguoi_nhan(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config, "nk_da", da_duyet=True
    )
    dong = await _dong(client, admin_user_in_db, pid, code)
    h = await _dn(client, admin_user_in_db)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/reset", headers=h,
        json={
            "expected_row_version": dong["row_version"], "reason": "Đã đối chiếu sổ nhận, giấy sai người",
            "unknown_submitter_ack": dong["reset_requires_ack"],
        },
    )
    assert r.status_code == 200, r.text
    nk = await _nhat_ky_dat_lai(dong["document_row_id"])
    assert nk.extra_data["unknown_submitter_ack"] is dong["reset_requires_ack"] is True, (nk.extra_data, dong)
