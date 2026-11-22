"""PR-D (F9) — phản hồi của lệnh ghi giấy bằng ORM mang ĐÚNG ``row_version`` của CSDL.

``profile_document.row_version`` do trigger CSDL tăng ở mỗi UPDATE. Trước PR-D, sau UPDATE bằng ORM đối tượng trong phiên giữ
số CŨ ⇒ phản hồi (và checklist dựng từ ``get_all_documents`` trong cùng phiên) trả phiên bản cũ ⇒ giao diện ghi thẳng phản hồi
vào bộ đệm ⇒ bấm Đặt lại / Duyệt ngay sau đó bị 409 "đã xử lý ở thao tác khác" dù không ai đụng vào.

Ba đường ghi bằng ORM có trả hồ sơ (tải tệp, ghi nhận bản giấy, đổi loại giấy tốt nghiệp); mỗi đường ba ca, mỗi ca MỘT bất
biến:

1. ``row_version`` trong phản hồi = giá trị trong GET mới = giá trị đọc từ CSDL bằng phiên khác;
2. dùng NGAY phiên bản vừa trả cho thao tác kế ⇒ thành công;
3. phiên bản trước lệnh ghi ⇒ 409 ``VERSION_CHANGED`` (ca đối chứng: phiên bản thật sự đã đổi, ca 2 không xanh nhờ máy chủ
   bỏ qua phiên bản).

Thao tác kế: tải tệp ⇒ Đặt lại (cán bộ phụ trách); bản giấy / giấy tốt nghiệp ⇒ Admin duyệt (người nhận là cán bộ, khác Admin).
Mỗi lần đổi người thao tác: xoá cookie rồi đăng nhập lại (ứng dụng ưu tiên cookie). Dữ liệu giả.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.test_admission_doc_mutations_response_parity import (  # noqa: F401
    _create_profile,
    _login,
    parity_config,
)
from tests.api.test_pr13_graduation_proof_api import (  # noqa: F401
    GRAD_CODE,
    _create_profile as _create_grad_profile,
    graduation_config,
)
from tests.fixtures.gd1b import phien_ban_giay

pytestmark = pytest.mark.asyncio
ADMISSIONS = "/api/admissions"
PDF = b"%PDF-1.4\n% gd1b pr-d phien ban\n%%EOF"


async def _dn(client: AsyncClient, user: dict) -> dict:
    client.cookies.clear()
    return await _login(client, user["username"], user["password"])


def _rv_trong(body: dict, code: str):
    dong = [d for d in body.get("documents_checklist") or [] if d.get("code") == code]
    assert len(dong) == 1, f"checklist không có đúng một dòng {code!r}: {[d.get('code') for d in body.get('documents_checklist') or []]}"
    return dong[0]["row_version"]


# ---------------------------------------------------------------- ba lệnh ghi (trả: pid, code, rv trước lệnh, phản hồi)
async def _tai_tep(client, admin_h, officer, cfg, hau_to):
    prof = await _create_profile(client, admin_h, officer, cfg, f"prd_tai_{hau_to}")
    pid, code = prof["id"], cfg["upload_doc_code"]
    rv_truoc = await phien_ban_giay(pid, code)
    h = await _dn(client, officer)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/upload", headers=h,
        files={"file": ("u.pdf", PDF, "application/pdf")}, data={"actual_submission_format": "photo"},
    )
    assert r.status_code == 200, r.text
    return pid, code, rv_truoc, r.json()


async def _nhan_ban_giay(client, admin_h, officer, cfg, hau_to):
    prof = await _create_profile(client, admin_h, officer, cfg, f"prd_giay_{hau_to}")
    pid, code = prof["id"], cfg["paper_doc_code"]
    rv_truoc = await phien_ban_giay(pid, code)
    h = await _dn(client, officer)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/paper-submitted", headers=h, json={"actual_submission_format": "original"},
    )
    assert r.status_code == 200, r.text
    return pid, code, rv_truoc, r.json()


async def _doi_loai_giay_tot_nghiep(client, admin_h, officer, cfg, hau_to):
    prof = await _create_grad_profile(client, admin_h, officer, cfg, f"prd_tn_{hau_to}")
    pid = prof["id"]
    h = await _dn(client, officer)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/paper-submitted", headers=h,
        json={
            "actual_submission_format": "certified_copy",
            "graduation_proof_kind": "provisional_cert",
            "supplement_due_date": "2027-06-30",
        },
    )
    assert r.status_code == 200, r.text
    rv_truoc = await phien_ban_giay(pid, GRAD_CODE)
    r = await client.post(
        f"{ADMISSIONS}/{pid}/documents/{GRAD_CODE}/graduation-proof", headers=h, json={"kind": "official_diploma"},
    )
    assert r.status_code == 200, r.text
    return pid, GRAD_CODE, rv_truoc, r.json()


# ---------------------------------------------------------------- thao tác kế
async def _dat_lai(client, user, pid, code, rv):
    h = await _dn(client, user)
    return await client.post(
        f"{ADMISSIONS}/{pid}/documents/{code}/reset", headers=h,
        json={"expected_row_version": rv, "reason": "Tải nhầm tệp"},
    )


async def _duyet(client, user, pid, code, rv, fmt):
    h = await _dn(client, user)
    return await client.patch(
        f"{ADMISSIONS}/{pid}/documents/{code}/verify-format", headers=h, json={"format": fmt, "expected_row_version": rv},
    )


async def _rv_get(client, user, pid, code):
    h = await _dn(client, user)
    r = await client.get(f"{ADMISSIONS}/{pid}", headers=h)
    assert r.status_code == 200, r.text
    return _rv_trong(r.json(), code)


async def _khop_csdl_va_get(client, officer, pid, code, body):
    tra_ve = _rv_trong(body, code)
    csdl = await phien_ban_giay(pid, code)
    get_moi = await _rv_get(client, officer, pid, code)
    assert (tra_ve, get_moi) == (csdl, csdl), {"phản hồi": tra_ve, "GET mới": get_moi, "CSDL": csdl}


# ================================================================ tải tệp
async def test_tai_tep_phien_ban_trong_phan_hoi_bang_csdl_va_get_moi(
    client, admin_token_headers, officer_user_in_db, parity_config
):
    pid, code, _, body = await _tai_tep(client, admin_token_headers, officer_user_in_db, parity_config, "khop")
    await _khop_csdl_va_get(client, officer_user_in_db, pid, code, body)


async def test_tai_tep_dung_ngay_phien_ban_vua_tra_de_dat_lai_thi_thanh_cong(
    client, admin_token_headers, officer_user_in_db, parity_config
):
    pid, code, _, body = await _tai_tep(client, admin_token_headers, officer_user_in_db, parity_config, "dung")
    r = await _dat_lai(client, officer_user_in_db, pid, code, _rv_trong(body, code))
    assert r.status_code == 200, r.text


async def test_tai_tep_phien_ban_truoc_lenh_ghi_thi_409_version_changed(
    client, admin_token_headers, officer_user_in_db, parity_config
):
    pid, code, rv_truoc, _ = await _tai_tep(client, admin_token_headers, officer_user_in_db, parity_config, "cu")
    r = await _dat_lai(client, officer_user_in_db, pid, code, rv_truoc)
    assert r.status_code == 409 and r.json()["error_code"] == "VERSION_CHANGED", r.text


# ================================================================ ghi nhận bản giấy
async def test_nhan_ban_giay_phien_ban_trong_phan_hoi_bang_csdl_va_get_moi(
    client, admin_token_headers, officer_user_in_db, parity_config
):
    pid, code, _, body = await _nhan_ban_giay(client, admin_token_headers, officer_user_in_db, parity_config, "khop")
    await _khop_csdl_va_get(client, officer_user_in_db, pid, code, body)


async def test_nhan_ban_giay_dung_ngay_phien_ban_vua_tra_de_duyet_thi_thanh_cong(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, code, _, body = await _nhan_ban_giay(client, admin_token_headers, officer_user_in_db, parity_config, "dung")
    r = await _duyet(client, admin_user_in_db, pid, code, _rv_trong(body, code), "original")
    assert r.status_code == 200, r.text


async def test_nhan_ban_giay_phien_ban_truoc_lenh_ghi_thi_409_version_changed(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, parity_config
):
    pid, code, rv_truoc, _ = await _nhan_ban_giay(client, admin_token_headers, officer_user_in_db, parity_config, "cu")
    r = await _duyet(client, admin_user_in_db, pid, code, rv_truoc, "original")
    assert r.status_code == 409 and r.json()["error_code"] == "VERSION_CHANGED", r.text


# ================================================================ đổi loại giấy tốt nghiệp (giấy tạm thời ⇒ bằng chính thức)
async def test_doi_loai_giay_tot_nghiep_phien_ban_trong_phan_hoi_bang_csdl_va_get_moi(
    client, admin_token_headers, officer_user_in_db, graduation_config
):
    pid, code, _, body = await _doi_loai_giay_tot_nghiep(
        client, admin_token_headers, officer_user_in_db, graduation_config, "khop"
    )
    await _khop_csdl_va_get(client, officer_user_in_db, pid, code, body)


async def test_doi_loai_giay_tot_nghiep_dung_ngay_phien_ban_vua_tra_de_duyet_thi_thanh_cong(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, graduation_config
):
    pid, code, _, body = await _doi_loai_giay_tot_nghiep(
        client, admin_token_headers, officer_user_in_db, graduation_config, "dung"
    )
    r = await _duyet(client, admin_user_in_db, pid, code, _rv_trong(body, code), "certified_copy")
    assert r.status_code == 200, r.text


async def test_doi_loai_giay_tot_nghiep_phien_ban_truoc_lenh_ghi_thi_409_version_changed(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, graduation_config
):
    pid, code, rv_truoc, _ = await _doi_loai_giay_tot_nghiep(
        client, admin_token_headers, officer_user_in_db, graduation_config, "cu"
    )
    r = await _duyet(client, admin_user_in_db, pid, code, rv_truoc, "certified_copy")
    assert r.status_code == 409 and r.json()["error_code"] == "VERSION_CHANGED", r.text
