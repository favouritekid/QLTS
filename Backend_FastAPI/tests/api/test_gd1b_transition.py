"""GĐ1b S4 — ``transition_document`` qua các nút lẻ (đặc tả bản 3.6 §4, §4.2, §4.6b, §4.7, §9).

Mỗi ca kiểm MỘT bất biến. Fixture: chuỗi tự đủ của ``test_admission_doc_mutations_response_parity`` (một giấy tải tệp + một
giấy bản giấy). Mỗi lần đổi người thao tác: xoá cookie rồi đăng nhập lại (ứng dụng ưu tiên cookie hơn header).
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

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

pytestmark = pytest.mark.asyncio
ADMISSIONS = "/api/admissions"
PDF = b"%PDF-1.4\n% gd1b\n%%EOF"


async def _dn(client: AsyncClient, user: dict) -> dict:
    client.cookies.clear()
    return await _login(client, user["username"], user["password"])


async def _giay(pid: int, code: str) -> models.ProfileDocument:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.ProfileDocument)
                .join(models.ConfigDocumentType, models.ConfigDocumentType.id == models.ProfileDocument.document_type_id)
                .where(models.ProfileDocument.profile_id == pid, models.ConfigDocumentType.code == code)
            )
        ).scalar_one()


async def _nhat_ky(doc_id: int):
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.DocumentAuditLog)
                .where(models.DocumentAuditLog.profile_document_id == doc_id)
                .order_by(models.DocumentAuditLog.id)
            )
        ).scalars().all()


async def _nhan_giay(client, user, pid, code):
    h = await _dn(client, user)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/paper-submitted", headers=h, json={"actual_submission_format": "original"}
    )
    assert r.status_code in (200, 201), r.text
    return await _giay(pid, code)


async def _tai(client, user, pid, code, noi_dung=PDF):
    h = await _dn(client, user)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/upload", headers=h,
        files={"file": ("u.pdf", noi_dung, "application/pdf")}, data={"actual_submission_format": "photo"},
    )
    assert r.status_code in (200, 201), r.text
    return await _giay(pid, code)


async def _duyet(client, user, pid, code, rv, **them):
    h = await _dn(client, user)
    return await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{code}/verify-format", headers=h,
        json={"format": "original", "expected_row_version": rv, **them},
    )


async def _dat_lai(client, user, pid, code, rv, **them):
    h = await _dn(client, user)
    return await client.post(f"{ADMISSIONS}/{pid}/documents/{code}/reset", headers=h, json={"expected_row_version": rv, **them})


# ---------------------------------------------------------------- luật người nhận (§4.2)
async def test_nguoi_nhan_khong_tu_duyet_giay_minh_nhan_nguoi_khac_duyet_duoc(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "nn_tu_duyet")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, manager_user_in_db, prof["id"], code)
    r = await _duyet(client, manager_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 409 and r.json()["error_code"] == "OWN_SUBMISSION", r.text
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 200, r.text
    assert (await _giay(prof["id"], code)).status == "verified"


async def test_khong_ro_nguoi_nhan_can_cam_ket_kem_ly_do(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "nn_khong_ro")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, officer_user_in_db, prof["id"], code)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(
                text("UPDATE profile_document SET paper_submitted_by = NULL, paper_submitted_by_unknown = true WHERE id = :d"),
                {"d": d.id},
            )
    d = await _giay(prof["id"], code)
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 409 and r.json()["error_code"] == "UNKNOWN_SUBMITTER", r.text
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version, unknown_submitter_ack=True)
    assert r.status_code == 409, "cam kết mà thiếu lý do vẫn chặn"
    r = await _duyet(
        client, admin_user_in_db, prof["id"], code, d.row_version, unknown_submitter_ack=True, reason="Đã đối chiếu sổ nhận"
    )
    assert r.status_code == 200, r.text
    nk = (await _nhat_ky(d.id))[-1]
    assert nk.action == "verified" and nk.extra_data["unknown_submitter_ack"] is True and nk.reason


async def test_cam_ket_khong_mo_duong_khi_nguoi_nhan_da_biet_la_minh(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "nn_ack_minh")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, manager_user_in_db, prof["id"], code)
    r = await _duyet(
        client, manager_user_in_db, prof["id"], code, d.row_version, unknown_submitter_ack=True, reason="cố lách"
    )
    assert r.status_code == 409 and r.json()["error_code"] == "OWN_SUBMISSION", r.text


# ---------------------------------------------------------------- phiên bản dòng (§4.5)
async def test_phien_ban_dong_cu_thi_409_khong_ghi(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "rv_cu")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, officer_user_in_db, prof["id"], code)
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version - 1 if d.row_version > 1 else d.row_version + 7)
    assert r.status_code == 409 and r.json()["error_code"] == "VERSION_CHANGED", r.text
    assert (await _giay(prof["id"], code)).status == "paper_submitted"


async def test_giay_da_xu_ly_o_thao_tac_khac_gui_ban_cu_thi_version_changed_khong_phai_not_pending(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """§5.9 / §9 "hai tab": tab 1 đã duyệt; tab 2 gửi đúng phiên bản nó đã xem ⇒ VERSION_CHANGED (làm mới), không ghi."""
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "rv_hai_tab")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, officer_user_in_db, prof["id"], code)
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 200, r.text
    so_dong = len(await _nhat_ky(d.id))
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 409 and r.json()["error_code"] == "VERSION_CHANGED", r.text
    assert len(await _nhat_ky(d.id)) == so_dong


# ---------------------------------------------------------------- bằng chứng (§4.6b)
async def test_duyet_giay_co_tep_ghi_bang_chung_dung_sha256(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "bc_sha")
    code = parity_config["upload_doc_code"]
    noi_dung = PDF + os.urandom(8)
    d = await _tai(client, officer_user_in_db, prof["id"], code, noi_dung)
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        ev = (
            await s.execute(select(models.DocumentEvidenceFile).where(models.DocumentEvidenceFile.profile_document_id == d.id))
        ).scalar_one()
    assert ev.sha256 == hashlib.sha256(noi_dung).hexdigest() and ev.file_path == d.file_path and not ev.file_missing


async def test_duyet_giay_ma_tep_khong_con_tren_o_thi_khong_duyet_khong_bang_chung(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "bc_mat")
    code = parity_config["upload_doc_code"]
    d = await _tai(client, officer_user_in_db, prof["id"], code)
    os.remove(d.file_path)
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 409 and r.json()["error_code"] == "FILE_MISSING_ON_DISK", r.text
    assert (await _giay(prof["id"], code)).status == "uploaded"
    async with AsyncSessionLocal() as s:
        assert (
            await s.execute(select(models.DocumentEvidenceFile).where(models.DocumentEvidenceFile.profile_document_id == d.id))
        ).first() is None


# ---------------------------------------------------------------- Đặt lại (§4.2, §9)
async def test_dat_lai_giay_da_duyet_nguoi_nhan_bi_chan_khong_ly_do_422_co_ly_do_giu_tep(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "dl_da_duyet")
    code = parity_config["upload_doc_code"]
    d = await _tai(client, manager_user_in_db, prof["id"], code)  # Quản lý là NGƯỜI TẢI
    r = await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 200, r.text
    d = await _giay(prof["id"], code)
    tep = d.file_path
    r = await _dat_lai(client, manager_user_in_db, prof["id"], code, d.row_version, reason="nhầm")
    assert r.status_code == 409 and r.json()["error_code"] == "OWN_SUBMISSION", r.text
    r = await _dat_lai(client, admin_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 422, r.text
    r = await _dat_lai(client, admin_user_in_db, prof["id"], code, d.row_version, reason="Nộp nhầm giấy khác")
    assert r.status_code == 200, r.text
    assert (await _giay(prof["id"], code)).status == "missing"
    assert os.path.exists(tep), "tệp đã duyệt (bằng chứng) phải còn trên đĩa"
    nk = (await _nhat_ky(d.id))[-1]
    assert nk.action == "reset" and nk.old_status == "verified" and nk.reason
    assert nk.extra_data["before"]["file_sha256"] == hashlib.sha256(open(tep, "rb").read()).hexdigest()
    assert nk.extra_data["before"]["verified_by"] == admin_user_in_db["id"]


async def test_da_duyet_tu_choi_roi_dat_lai_tep_con(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    """F365: Đã duyệt → Từ chối → Đặt lại ⇒ tệp còn (bằng chứng của lần duyệt)."""
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "f365")
    code = parity_config["upload_doc_code"]
    d = await _tai(client, officer_user_in_db, prof["id"], code)
    assert (await _duyet(client, admin_user_in_db, prof["id"], code, d.row_version)).status_code == 200
    d = await _giay(prof["id"], code)
    h = await _dn(client, admin_user_in_db)
    r = await client.post(
        f"{ADMISSIONS}/{prof['id']}/documents/{code}/reject", headers=h,
        json={"reason": "Ảnh mờ", "expected_row_version": d.row_version},
    )
    assert r.status_code == 200, r.text
    d = await _giay(prof["id"], code)
    tep = d.file_path
    r = await _dat_lai(client, admin_user_in_db, prof["id"], code, d.row_version, reason="Thu lại bản rõ")
    assert r.status_code == 200, r.text
    assert os.path.exists(tep)


# ---------------------------------------------------------------- X1 giấy ngoài cấu hình (§4.2)
async def _giay_ngoai_cau_hinh(pid: int, uploader_id: int) -> tuple[int, str]:
    ts = f"{int(datetime.now().timestamp() * 1000)}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            dt = models.ConfigDocumentType(code=f"x1_{ts}", name=f"X1_{ts}", display_order=99)
            s.add(dt)
            await s.flush()
            pd = models.ProfileDocument(
                profile_id=pid, document_type_id=dt.id, category="path", status="paper_submitted",
                paper_submitted_by=uploader_id, paper_submitted_at=datetime.now(timezone.utc),
                actual_submission_format="original",
            )
            s.add(pd)
            await s.flush()
            return pd.id, dt.code


async def test_x1_quan_ly_dat_lai_giay_ngoai_cau_hinh_can_bo_khong_duyet_khong(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "x1")
    doc_id, code = await _giay_ngoai_cau_hinh(prof["id"], officer_user_in_db["id"])
    d = await _giay(prof["id"], code)
    r = await _duyet(client, manager_user_in_db, prof["id"], code, d.row_version)
    assert r.status_code == 409 and r.json()["error_code"] == "OUTSIDE_CONFIG", r.text
    r = await _dat_lai(client, officer_user_in_db, prof["id"], code, d.row_version, reason="dọn")
    assert r.status_code == 404, r.text
    r = await _dat_lai(client, manager_user_in_db, prof["id"], code, d.row_version, reason="Giấy cũ của đường xét trước")
    assert r.status_code == 200, r.text
    nk = (await _nhat_ky(doc_id))[-1]
    assert nk.action == "reset" and nk.extra_data["via"] == "extra_cleanup"


# ---------------------------------------------------------------- cờ máy chủ + định danh (§4.7)
async def test_co_may_chu_va_dinh_danh_dong_cho_moi_giay(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "co")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, manager_user_in_db, prof["id"], code)
    h = await _dn(client, manager_user_in_db)
    r = await client.get(f"{ADMISSIONS}/{prof['id']}", headers=h)
    assert r.status_code == 200, r.text
    ds = {x["code"]: x for x in r.json()["documents_checklist"]}
    for x in ds.values():
        assert isinstance(x["document_row_id"], int) and isinstance(x["row_version"], int), x
    giay = ds[code]
    assert giay["document_id"] is None, "document_id giữ nghĩa 'id để tải tệp' — giấy bản giấy không có"
    assert (giay["document_row_id"], giay["row_version"]) == (d.id, d.row_version)
    assert giay["can_verify"] is False and giay["verify_block_reason"] == "own_submission"
    assert giay["can_view_history"] is True


# ---------------------------------------------------------------- lịch sử K2 (§4.7)
async def test_lich_su_quan_ly_dung_don_vi_xem_duoc_sai_don_vi_va_can_bo_404(
    client, admin_token_headers, manager_user_in_db, manager_other_unit_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "lich_su")
    code = parity_config["paper_doc_code"]
    d = await _nhan_giay(client, officer_user_in_db, prof["id"], code)
    url = f"{ADMISSIONS}/{prof['id']}/documents/{d.id}/history"
    r = await client.get(url, headers=await _dn(client, manager_user_in_db))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["document_row_id"] == d.id and [e["action"] for e in body["entries"]] == ["paper_submitted"]
    assert "file_path" not in str(body), "phản hồi hẹp — không đường dẫn tệp"
    r = await client.get(url, headers=await _dn(client, manager_other_unit_user_in_db))
    assert r.status_code == 404, r.text
    r = await client.get(url, headers=await _dn(client, officer_user_in_db))
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------- Codex 68: Đặt lại không xoá tệp ngoài thư mục hồ sơ
async def test_dat_lai_khong_xoa_tep_ngoai_thu_muc_ho_so_khi_duong_dan_csdl_sai(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    prof = await _create_profile(client, admin_token_headers, officer_user_in_db, parity_config, "dl_ngoai")
    code = parity_config["upload_doc_code"]
    d = await _tai(client, officer_user_in_db, prof["id"], code)
    nan_nhan = f"uploads/admissions/{prof['id'] + 100000}/nan-nhan.pdf"
    os.makedirs(os.path.dirname(nan_nhan), exist_ok=True)
    with open(nan_nhan, "wb") as f:
        f.write(PDF)
    try:
        async with AsyncSessionLocal() as s:
            async with s.begin():
                await s.execute(text("UPDATE profile_document SET file_path = :p WHERE id = :d"), {"p": nan_nhan, "d": d.id})
        d = await _giay(prof["id"], code)
        r = await _dat_lai(client, officer_user_in_db, prof["id"], code, d.row_version, reason="Tải nhầm")
        assert r.status_code == 200, r.text
        assert (await _giay(prof["id"], code)).status == "missing"
        assert os.path.exists(nan_nhan), "tệp ngoài thư mục hồ sơ KHÔNG được xoá"
    finally:
        if os.path.exists(nan_nhan):
            os.remove(nan_nhan)
            os.rmdir(os.path.dirname(nan_nhan))
