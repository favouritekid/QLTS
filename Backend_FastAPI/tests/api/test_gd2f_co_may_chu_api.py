"""GĐ2-F1 — cờ máy chủ cho giao diện: KHOÁ "cờ = cổng ghi" qua REQUEST THẬT (router → deps → dịch vụ → CSDL thật).

Ba nhóm cờ thêm ở GĐ2-F1 (giao diện chỉ hiện nút theo cờ — thin client):
  * ``priority_evidence_documents[*].requires_ack`` / ``review_block_reason`` — cùng hàm
    ``document_review_rules.decide_priority_evidence`` với cổng duyệt / từ chối (``priority_override_service``);
  * ``priority_evidence_documents[*].can_mark_paper_submitted`` — cùng hàm
    ``document_review_rules.priority_evidence_paper_recordable`` với cổng route ghi nhận bản giấy;
  * ``available_actions`` của bảng chỉ tiêu năm — cùng hàm ``admission_quota_table_service.quota_table_actions`` với cổng
    sửa / khoá / mở khoá.
Mỗi ca: đọc cờ bằng GET của đúng người xem ⇒ so với giá trị mong đợi của kịch bản ⇒ gọi cổng ghi THẬT và đòi kết quả khớp
cờ. Không dữ liệu thật.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.api.test_gd2_minh_chung_uu_tien_api import (  # noqa: F401 — fixture dùng qua tên
    CAM_KET,
    MA,
    V1,
    _duyet,
    _ghi_nhan_giay,
    _ho_so,
    _khong_cookie,
    _sql,
    _tai_len,
    _tu_choi,
    ba_vai,
    don_tep,
    parity_config,
)
from tests.api.test_gd2a_bang_chi_tieu_api import NAM, P, _than, hoc_vu  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _muc(client, headers, pid, ma=MA):
    """Dòng ``priority_evidence_documents`` của mã ``ma`` khi ``headers`` là người xem."""
    _khong_cookie(client)
    r = await client.get(f"{V1}/{pid}", headers=headers)
    assert r.status_code == 200, r.text
    muc = [x for x in r.json()["priority_evidence_documents"] if x["sub_code"] == ma]
    assert len(muc) == 1, r.json()["priority_evidence_documents"]
    return muc[0]


# --------------------------------------------------------------------------------------------------------------------
# requires_ack / review_block_reason ⇔ cổng duyệt / từ chối (người xem = Quản lý trong đơn vị)
# --------------------------------------------------------------------------------------------------------------------
async def _dung_kich_ban_duyet(client, ba_vai, pid, kich_ban):
    if kich_ban == "can_bo_tai_tep":
        assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    elif kich_ban == "quan_ly_tu_tai_tep":
        assert (await _tai_len(client, ba_vai["quan_ly"], pid)).status_code == 200
    elif kich_ban == "tep_khong_ro_nguoi_tai":
        assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
        await _sql(
            "UPDATE profile_document SET uploaded_by = NULL WHERE profile_id = :p AND category = 'priority_evidence'",
            p=pid,
        )
    elif kich_ban == "chua_co_dong":
        pass
    elif kich_ban == "quan_ly_tu_nhan_giay":
        assert (await _ghi_nhan_giay(client, ba_vai["quan_ly"], pid)).status_code == 200
    elif kich_ban == "can_bo_nhan_giay":
        assert (await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)).status_code == 200
    else:  # pragma: no cover
        raise AssertionError(kich_ban)


#: (kịch bản, requires_ack mong đợi, review_block_reason mong đợi) — người xem = Quản lý trong đơn vị.
_KICH_BAN_DUYET = [
    ("can_bo_tai_tep", False, None),
    ("quan_ly_tu_tai_tep", False, "own_submission"),
    ("tep_khong_ro_nguoi_tai", True, None),
    ("chua_co_dong", True, None),
    ("quan_ly_tu_nhan_giay", False, "own_submission"),
    ("can_bo_nhan_giay", False, None),
]


@pytest.mark.parametrize("kich_ban,can_cam_ket,ly_do_chan", _KICH_BAN_DUYET, ids=[k[0] for k in _KICH_BAN_DUYET])
async def test_co_cam_ket_va_ly_do_chan_khop_cong_duyet(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep,
    kich_ban, can_cam_ket, ly_do_chan,
):
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, f"f1_duyet_{kich_ban}")
    don_tep.append(pid)
    await _dung_kich_ban_duyet(client, ba_vai, pid, kich_ban)
    muc = await _muc(client, ba_vai["quan_ly"], pid)
    assert (muc["requires_ack"], muc["review_block_reason"]) == (can_cam_ket, ly_do_chan), (kich_ban, muc)

    # Cổng ghi THẬT phải nói đúng điều cờ nói.
    if muc["review_block_reason"] is not None:
        ma_loi = muc["review_block_reason"].upper()
        # Cam kết KHÔNG mở đường khi bị chặn. Từ chối: lý do của cam kết = ``reject_reason`` (thân không có ``reason``).
        for goi, cam_ket in ((_duyet, CAM_KET), (_tu_choi, {"unknown_submitter_ack": True})):
            r = await goi(client, ba_vai["quan_ly"], pid, **cam_ket)
            assert r.status_code == 409 and r.json().get("error_code") == ma_loi, (kich_ban, goi.__name__, r.text)
    elif muc["requires_ack"]:
        r = await _duyet(client, ba_vai["quan_ly"], pid)
        assert r.status_code == 409 and r.json().get("error_code") == "UNKNOWN_SUBMITTER", (kich_ban, r.text)
        r = await _duyet(client, ba_vai["quan_ly"], pid, **CAM_KET)
        assert r.status_code == 200, (kich_ban, r.text)
    else:
        r = await _duyet(client, ba_vai["quan_ly"], pid)
        assert r.status_code == 200, (kich_ban, r.text)


async def test_co_theo_nguoi_xem_admin_khac_quan_ly_tu_tai(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Cờ tính cho NGƯỜI XEM: Quản lý tự tải ⇒ với Quản lý bị chặn, với Admin thì không — Admin duyệt được."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "f1_nguoi_xem")
    don_tep.append(pid)
    assert (await _tai_len(client, ba_vai["quan_ly"], pid)).status_code == 200
    assert (await _muc(client, ba_vai["quan_ly"], pid))["review_block_reason"] == "own_submission"
    muc_admin = await _muc(client, ba_vai["admin"], pid)
    assert (muc_admin["requires_ack"], muc_admin["review_block_reason"]) == (False, None), muc_admin
    r = await _duyet(client, ba_vai["admin"], pid)
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------------------------------------------------
# can_mark_paper_submitted ⇔ cổng route ghi nhận bản giấy
# --------------------------------------------------------------------------------------------------------------------
MA_NGOAI_DANH_MUC = "98"

#: (vai người bấm, kịch bản, cờ mong đợi)
_KICH_BAN_GIAY = [
    ("can_bo", "chua_co_dong", True),
    ("quan_ly", "chua_co_dong", True),
    ("admin", "chua_co_dong", True),
    ("can_bo", "da_ghi_nhan_giay", False),
    ("can_bo", "da_co_tep", False),
    ("can_bo", "trang_thai_khong_cho_sua_giay", False),
    ("can_bo", "ma_ngoai_danh_muc", False),
]


@pytest.mark.parametrize(
    "vai,kich_ban,co_mong_doi", _KICH_BAN_GIAY, ids=[f"{v}-{k}" for v, k, _ in _KICH_BAN_GIAY]
)
async def test_co_ghi_nhan_ban_giay_khop_cong_ghi(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep,
    vai, kich_ban, co_mong_doi,
):
    trang_thai = "approved" if kich_ban == "trang_thai_khong_cho_sua_giay" else "submitted"
    pid = await _ho_so(
        client, admin_token_headers, officer_user_in_db, parity_config, f"f1_giay_{vai}_{kich_ban}", trang_thai=trang_thai
    )
    don_tep.append(pid)
    ma = MA
    if kich_ban == "da_ghi_nhan_giay":
        assert (await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)).status_code == 200
    elif kich_ban == "da_co_tep":
        assert (await _tai_len(client, ba_vai["can_bo"], pid)).status_code == 200
    elif kich_ban == "ma_ngoai_danh_muc":
        ma = MA_NGOAI_DANH_MUC
        assert (
            await _sql(
                "SELECT count(*) FROM priority_object_config WHERE academic_year = 2026 AND sub_code = :m", m=ma
            )
        ).scalar_one() == 0
        await _sql(
            "UPDATE admission_profile SET priority_object_codes = CAST(:c AS jsonb) WHERE id = :p",
            c='["%s"]' % ma, p=pid,
        )

    muc = await _muc(client, ba_vai[vai], pid, ma=ma)
    assert muc["can_mark_paper_submitted"] is co_mong_doi, (vai, kich_ban, muc)

    _khong_cookie(client)
    r = await client.post(f"/api/v2/admissions/{pid}/priority-evidence/{ma}/paper-submitted", headers=ba_vai[vai])
    assert (r.status_code == 200) is muc["can_mark_paper_submitted"], (vai, kich_ban, r.status_code, r.text)


async def test_dong_ban_giay_hien_trang_thai_paper_submitted(
    client: AsyncClient, admin_token_headers, officer_user_in_db, parity_config, ba_vai, don_tep
):
    """Dòng minh chứng KHÔNG tệp (đã ghi nhận bản giấy) hiện ``paper_submitted`` — không còn ``uploaded``."""
    pid = await _ho_so(client, admin_token_headers, officer_user_in_db, parity_config, "f1_trang_thai_giay")
    don_tep.append(pid)
    assert (await _muc(client, ba_vai["can_bo"], pid))["status"] == "missing"
    assert (await _ghi_nhan_giay(client, ba_vai["can_bo"], pid)).status_code == 200
    muc = await _muc(client, ba_vai["can_bo"], pid)
    assert (muc["status"], muc["document_file_path"]) == ("paper_submitted", None), muc
    assert muc["document_id"] is not None, muc


# --------------------------------------------------------------------------------------------------------------------
# available_actions của bảng chỉ tiêu ⇔ cổng sửa / khoá / mở khoá
# --------------------------------------------------------------------------------------------------------------------
async def test_available_actions_bang_chi_tieu_khop_cong(client: AsyncClient, admin_token_headers, hoc_vu):
    h = admin_token_headers
    r = await client.put(f"{P}/{NAM}", headers=h, json=_than(0, hoc_vu))
    assert r.status_code == 200, r.text
    assert r.json()["available_actions"] == ["edit", "lock"], r.text
    r = await client.get(f"{P}/{NAM}", headers=h)
    assert r.json()["available_actions"] == ["edit", "lock"], r.text
    # Bảng nháp: KHÔNG có "unlock" ⇒ cổng mở khoá từ chối.
    r = await client.post(f"{P}/{NAM}/unlock", headers=h, json={"version": 1, "reason": "thử cổng"})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_NOT_LOCKED", r.text
    # Có "lock" ⇒ khoá được.
    r = await client.post(f"{P}/{NAM}/lock", headers=h, json={"version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["available_actions"] == ["unlock"], r.text
    # Bảng khoá: KHÔNG có "edit" / "lock" ⇒ cổng sửa và cổng khoá từ chối.
    r = await client.put(f"{P}/{NAM}", headers=h, json=_than(2, hoc_vu))
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_LOCKED", r.text
    r = await client.post(f"{P}/{NAM}/lock", headers=h, json={"version": 2})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_ALREADY_LOCKED", r.text
    # Có "unlock" ⇒ mở khoá được; về lại edit + lock.
    r = await client.post(f"{P}/{NAM}/unlock", headers=h, json={"version": 2, "reason": "Điều chỉnh chỉ tiêu thử"})
    assert r.status_code == 200, r.text
    assert r.json()["available_actions"] == ["edit", "lock"], r.text
