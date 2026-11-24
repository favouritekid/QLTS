"""GĐ1b PR-B — ma trận quyền HTTP của luồng duyệt chéo (owner Q1, 20-11) qua Casbin THẬT (ứng dụng thật, dòng Casbin seed
từ ``policy_templates.py`` — không mock enforcer).

8 API "thực hiện duyệt chéo": hàng đợi, duyệt lẻ, từ chối lẻ, xem trước lô chéo, chạy lô chéo, tra lô chéo, chốt lô chéo,
danh sách lô chéo. (``eligibility`` = cờ thanh bên cho mọi người đã đăng nhập; ``grants*`` = Admin cấp / thu hồi — ngoài Q1.)

- Vai KHÁC Cán bộ (Admin, Quản lý, Kế toán, Cộng tác viên, Người dùng) ⇒ 403, CÙNG thân 403 của Casbin, kể cả khi đích KHÔNG
  tồn tại (kiểm vai TRƯỚC khi tra hồ sơ / lô).
- Cán bộ không có quyền chéo còn hiệu lực ⇒ 404 cùng thân (so BYTE) trên cả 8 API, đích có thật hay không.
- Cán bộ đủ quyền ⇒ thao tác thành công; hồ sơ ngoài đơn vị được cấp / không tồn tại, lô không tồn tại ⇒ 404 cùng thân.
- Đúng THAO TÁC: quyền chỉ duyệt ⇒ từ chối 404; quyền chỉ từ chối ⇒ duyệt / xem trước lô 404.
"""
from __future__ import annotations

import pytest

from tests.api.gd1b_cheo_tro_giup import (  # noqa: F401
    KHONG_TON_TAI,
    LO_KHONG_TON_TAI,
    THAN_403,
    THAN_404,
    can_bo_cheo,
    cap,
    ho_so,
    tao_nguoi,
)
from tests.api.gd1b_lo_tro_giup import CROSS, dn, giay, lo_config, lo_routers, sql, xac_nhan  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _cac_api(gid, p, d, d2, ma_lo):
    """(tên, phương thức, đường, thân) — đích CÓ THẬT."""
    return [
        ("hang_doi", "GET", f"{CROSS}/queue", None),
        ("duyet", "POST", f"{CROSS}/verify",
         {"grant_id": gid, "profile_id": p, "document_row_id": d.id, "expected_row_version": d.row_version}),
        ("tu_choi", "POST", f"{CROSS}/reject",
         {"grant_id": gid, "profile_id": p, "document_row_id": d2.id, "expected_row_version": d2.row_version,
          "reason": "Bản sao mờ"}),
        ("xem_truoc", "POST", f"{CROSS}/bulk-verify/preview", {"profile_ids": [p], "grant_id": gid}),
        ("chay", "POST", f"{CROSS}/bulk-verify/{ma_lo}/execute", {"confirmation_text": "x"}),
        ("tra", "GET", f"{CROSS}/bulk-verify/{ma_lo}", None),
        ("chot", "POST", f"{CROSS}/bulk-verify/{ma_lo}/finalize", {}),
        ("danh_sach", "GET", f"{CROSS}/bulk-verify", None),
    ]


def _cac_api_khong_ton_tai(gid, d, d2):
    return [
        ("duyet", "POST", f"{CROSS}/verify",
         {"grant_id": gid, "profile_id": KHONG_TON_TAI, "document_row_id": d.id, "expected_row_version": 1}),
        ("tu_choi", "POST", f"{CROSS}/reject",
         {"grant_id": gid, "profile_id": KHONG_TON_TAI, "document_row_id": d2.id, "expected_row_version": 1,
          "reason": "x"}),
        ("chay", "POST", f"{CROSS}/bulk-verify/{LO_KHONG_TON_TAI}/execute", {"confirmation_text": "x"}),
        ("tra", "GET", f"{CROSS}/bulk-verify/{LO_KHONG_TON_TAI}", None),
        ("chot", "POST", f"{CROSS}/bulk-verify/{LO_KHONG_TON_TAI}/finalize", {}),
    ]


async def _goi(client, h, phuong_thuc, duong, than):
    if phuong_thuc == "GET":
        return await client.get(duong, headers=h)
    return await client.post(duong, headers=h, json=than)


async def _boi_canh(client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config):
    """Hồ sơ đơn vị mặc định (lead của cán bộ phụ trách) + quyền duyệt + từ chối cho cán bộ chéo + MỘT lô chéo có thật."""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="q1"))[0]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True, reject=True)
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": gid})
    assert r.status_code == 201, r.text
    return p, gid, r.json()["batch_id"]


async def test_q1_vai_khac_can_bo_403_cung_than_casbin_ke_ca_dich_khong_ton_tai(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, regular_user_in_db, officer_user_in_db,
    can_bo_cheo, lo_config, lo_routers,
):
    p, gid, ma_lo = await _boi_canh(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config
    )
    d, d2 = p["docs"]["A"], p["docs"]["B"]
    ke_toan = await tao_nguoi("prb_q1_ketoan", "accountant", lo_config["unit_id"])
    ctv = await tao_nguoi("prb_q1_ctv", "collaborator", lo_config["unit_id"])
    than_403 = set()
    for ten_vai, u in (
        ("admin", admin_user_in_db), ("manager", manager_user_in_db), ("accountant", ke_toan),
        ("collaborator", ctv), ("user", regular_user_in_db),
    ):
        h = await dn(client, u)
        for ten, pt, duong, than in _cac_api(gid, p["id"], d, d2, ma_lo) + _cac_api_khong_ton_tai(gid, d, d2):
            r = await _goi(client, h, pt, duong, than)
            assert r.status_code == 403, (ten_vai, ten, r.status_code, r.text)
            assert r.json() == THAN_403, (ten_vai, ten, r.text)
            than_403.add(r.content)
    assert len(than_403) == 1, than_403  # một thân byte duy nhất cho mọi vai, mọi API
    # Không ghi gì.
    assert (await giay(p["id"], lo_config["codes"]["A"])).status == "paper_submitted"
    assert (await giay(p["id"], lo_config["codes"]["B"])).status == "paper_submitted"


async def test_q1_can_bo_khong_co_quyen_404_cung_than_tren_ca_8_api(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p, gid, ma_lo = await _boi_canh(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config
    )
    d, d2 = p["docs"]["A"], p["docs"]["B"]
    khong_quyen = await tao_nguoi("prb_q1_khongquyen", "officer", lo_config["unit_id"])
    h = await dn(client, khong_quyen)
    cac_than = set()
    for ten, pt, duong, than in _cac_api(gid, p["id"], d, d2, ma_lo) + _cac_api_khong_ton_tai(gid, d, d2):
        r = await _goi(client, h, pt, duong, than)
        assert r.status_code == 404 and r.json() == THAN_404, (ten, r.status_code, r.text)
        cac_than.add(r.content)
    assert len(cac_than) == 1, cac_than


async def test_q1_can_bo_du_quyen_thanh_cong_ngoai_pham_vi_va_khong_ton_tai_404_cung_than(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, seed_other_unit, lo_config,
    lo_routers,
):
    # Tạo hồ sơ TRƯỚC mọi lần Admin đăng nhập lại (``cap`` / ``dn``): đăng nhập lại cùng thiết bị thu hồi phiên của
    # ``admin_token_headers``.
    p2 = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="q1b"))[0]
    # Hồ sơ NGOÀI đơn vị được cấp: lead chuyển sang đơn vị thứ hai (không có quyền ở đó).
    p_ngoai = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="q1n"))[0]
    p, gid, ma_lo = await _boi_canh(
        client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config
    )
    await sql(
        "UPDATE lead SET unit_id = :u WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        u=seed_other_unit["unit_id"], p=p_ngoai["id"],
    )
    h = await dn(client, can_bo_cheo)
    # Thành công.
    r = await client.get(f"{CROSS}/queue", headers=h)
    assert r.status_code == 200 and r.json()["total_count"] >= 1, r.text
    d = p2["docs"]["A"]
    r = await client.post(f"{CROSS}/verify", headers=h, json={
        "grant_id": gid, "profile_id": p2["id"], "document_row_id": d.id, "expected_row_version": d.row_version})
    assert r.status_code == 200 and r.json()["new_status"] == "verified", r.text
    d = p2["docs"]["B"]
    r = await client.post(f"{CROSS}/reject", headers=h, json={
        "grant_id": gid, "profile_id": p2["id"], "document_row_id": d.id, "expected_row_version": d.row_version,
        "reason": "Bản sao mờ"})
    assert r.status_code == 200 and r.json()["new_status"] == "rejected", r.text
    r = await client.post(f"{CROSS}/bulk-verify/{ma_lo}/execute", headers=h, json=await xac_nhan(ma_lo))
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    r = await client.get(f"{CROSS}/bulk-verify/{ma_lo}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    r = await client.post(f"{CROSS}/bulk-verify/{ma_lo}/finalize", headers=h, json={})
    assert r.status_code == 200 and r.json()["finalized_now"] is False, r.text
    r = await client.get(f"{CROSS}/bulk-verify", headers=h)
    assert r.status_code == 200 and [x["batch_id"] for x in r.json()["items"]] == [ma_lo], r.text
    # Ngoài phạm vi / không tồn tại ⇒ 404 CÙNG thân byte.
    cac_than = set()
    dn_ngoai = p_ngoai["docs"]["A"]
    for pt, duong, than in [
        ("POST", f"{CROSS}/verify", {"grant_id": gid, "profile_id": p_ngoai["id"], "document_row_id": dn_ngoai.id,
                                     "expected_row_version": dn_ngoai.row_version}),
        ("POST", f"{CROSS}/reject", {"grant_id": gid, "profile_id": p_ngoai["id"], "document_row_id": dn_ngoai.id,
                                     "expected_row_version": dn_ngoai.row_version, "reason": "x"}),
    ] + [(pt, duong, than) for _, pt, duong, than in _cac_api_khong_ton_tai(gid, dn_ngoai, dn_ngoai)]:
        r = await _goi(client, h, pt, duong, than)
        assert r.status_code == 404 and r.json() == THAN_404, (duong, r.text)
        cac_than.add(r.content)
    assert len(cac_than) == 1, cac_than
    assert (await giay(p_ngoai["id"], lo_config["codes"]["A"])).status == "paper_submitted"


async def test_q1_dung_thao_tac_quyen_chi_duyet_khong_tu_choi_quyen_chi_tu_choi_khong_duyet(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="q1t"))[0]
    d, d2 = p["docs"]["A"], p["docs"]["B"]
    chi_duyet = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    chi_tu_choi_nguoi = await tao_nguoi("prb_q1_chitu", "officer", None)
    chi_tu_choi = await cap(client, admin_user_in_db, chi_tu_choi_nguoi["id"], lo_config["unit_id"], reject=True)
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/reject", headers=h, json={
        "grant_id": chi_duyet, "profile_id": p["id"], "document_row_id": d2.id, "expected_row_version": d2.row_version,
        "reason": "x"})
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    h = await dn(client, chi_tu_choi_nguoi)
    for duong, than in (
        (f"{CROSS}/verify", {"grant_id": chi_tu_choi, "profile_id": p["id"], "document_row_id": d.id,
                             "expected_row_version": d.row_version}),
        (f"{CROSS}/bulk-verify/preview", {"profile_ids": [p["id"]], "grant_id": chi_tu_choi}),
    ):
        r = await client.post(duong, headers=h, json=than)
        assert r.status_code == 404 and r.json() == THAN_404, (duong, r.text)
    # Đúng thao tác ⇒ được.
    r = await client.post(f"{CROSS}/reject", headers=h, json={
        "grant_id": chi_tu_choi, "profile_id": p["id"], "document_row_id": d2.id, "expected_row_version": d2.row_version,
        "reason": "Bản sao mờ"})
    assert r.status_code == 200, r.text
    assert (await giay(p["id"], lo_config["codes"]["A"])).status == "paper_submitted"
