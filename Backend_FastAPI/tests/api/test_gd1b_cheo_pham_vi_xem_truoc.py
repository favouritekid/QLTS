"""GĐ1b PR-B — phạm vi của bản XEM TRƯỚC lô (F4 + owner Q3, phần máy chủ của Q2).

Owner Q3 (20-11): lô chéo trúng hồ sơ do CHÍNH cán bộ phụ trách ⇒ CHỈ báo số giấy bị loại (``counts.own_assigned_excluded``
= M), KHÔNG mã hồ sơ / mã giấy / họ tên / loại giấy của nhóm ấy ở bất kỳ trường nào (kể cả ``excluded``). Chỉ đếm khi DƯỚI
KHOÁ: lead vẫn do chính người ấy phụ trách, người ấy được xem hồ sơ theo phạm vi thường, lead thuộc đơn vị của quyền còn
hiệu lực. Ngoài phạm vi và mã không tồn tại ⇒ CÙNG kết quả, kể cả số đếm. ``counts.documents`` = N = số giấy của danh sách
xác nhận (``items``). Q2: ``items`` của xem trước CHÉO chỉ mang mã hồ sơ + loại giấy (không họ tên).

F4: lead chuyển đơn vị giữa câu chọn và câu nạp ⇒ BỎ IM LẶNG (không vào ``items`` / ``excluded``) — cả lô chéo lẫn lô thường
của Quản lý.

Bố trí: cán bộ chéo = ``officer_user_in_db`` (đơn vị mặc định U) được cấp quyền duyệt chéo CHÍNH đơn vị U ⇒ có hồ sơ "do mình
phụ trách" mà vẫn được xem; hồ sơ khác của U do cán bộ thứ hai phụ trách (người nhận giấy = cán bộ thứ hai).
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app.repositories import document_bulk_repository as bulk_repo
from tests.api.gd1b_cheo_tro_giup import (  # noqa: F401
    KHONG_TON_TAI,
    THAN_404,
    KhoaHo,
    bi_chan_boi_pid,
    can_bo_cheo,
    cap,
    hang,
    ho_so,
    quet_gia_tri,
    tao_nguoi,
)
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    CROSS,
    Diem,
    NHAN,
    PidTheoNhan,
    boc,
    dang_nhap,
    dn,
    dong_muc,
    lo_config,
    lo_routers,
    sql,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

KHOA_ITEMS_CHEO = {"profile_id", "document_row_id", "document_type_code", "expected_row_version", "is_mandatory"}


@pytest_asyncio.fixture
async def bo_tri(client, admin_token_headers, admin_user_in_db, officer_user_in_db, lo_config, lo_routers):
    can_bo_2 = await tao_nguoi("prb_q3_canbo2", "officer", lo_config["unit_id"])
    # Hồ sơ do CHÍNH cán bộ chéo phụ trách: chỉ nhận giấy D (loại giấy D không xuất hiện ở hồ sơ kia).
    rieng = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="q3rieng", giay_nhan="D"))[0]
    # Hồ sơ của cán bộ thứ hai: giấy A, B (người nhận = cán bộ thứ hai ⇒ cán bộ chéo duyệt được).
    khac = (await ho_so(client, admin_token_headers, can_bo_2, lo_config, tien_to="q3khac", giay_nhan="AB"))[0]
    gid = await cap(client, admin_user_in_db, officer_user_in_db["id"], lo_config["unit_id"], verify=True)
    return {"rieng": rieng, "khac": khac, "gid": gid, "can_bo_2": can_bo_2}


async def _xem_truoc(client, h, ids, gid):
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": ids, "grant_id": gid})
    assert r.status_code == 201, r.text
    return r


def _bo_thoi_gian(j):
    return {k: v for k, v in j.items() if k not in ("batch_id", "expires_at")}


async def test_q3_ho_so_minh_phu_trach_chi_tra_so_dem_khong_lo_dinh_danh_o_bat_ky_truong_nao(
    client, officer_user_in_db, bo_tri, lo_config
):
    rieng, khac, gid = bo_tri["rieng"], bo_tri["khac"], bo_tri["gid"]
    d_rieng = rieng["docs"]["D"]
    h = await dn(client, officer_user_in_db)
    # Tiền đề vị từ "được xem": cán bộ ĐỌC được hồ sơ của mình theo cổng đọc thường (3 tầng).
    assert (await client.get(f"/api/admissions/{rieng['id']}/fee-status", headers=h)).status_code != 404
    r = await _xem_truoc(client, h, [rieng["id"], khac["id"]], gid)
    j = r.json()
    # Hai con số riêng: N = số giấy trong danh sách xác nhận; M = số giấy bị loại do mình phụ trách.
    assert j["counts"]["documents"] == len(j["items"]) == 2, j
    assert j["counts"]["own_assigned_excluded"] == 1, j
    assert {it["profile_id"] for it in j["items"]} == {khac["id"]}
    # Q2 (máy chủ): mục xem trước chéo chỉ mã hồ sơ + loại giấy (+ id dòng / phiên bản để chạy) — không họ tên.
    assert all(set(it) == KHOA_ITEMS_CHEO for it in j["items"]), j["items"]
    # Quét TOÀN thân: không mã hồ sơ, mã giấy, loại giấy, họ tên của nhóm "do mình phụ trách" ở bất kỳ trường nào.
    cap_kv = quet_gia_tri(j)
    # Mọi trường mang mã (``id`` / ``*_id``) chỉ là ba loại này — mã hồ sơ, mã dòng giấy, mã lô.
    assert {k for k, _ in cap_kv if k and (k == "id" or k.endswith("_id"))} <= {"profile_id", "document_row_id", "batch_id"}
    assert rieng["id"] not in [v for k, v in cap_kv if k == "profile_id"], j
    assert d_rieng.id not in [v for k, v in cap_kv if k == "document_row_id"], j
    than = r.text
    assert lo_config["codes"]["D"] not in than and "q3rieng" not in than, than
    assert not [k for k, _ in quet_gia_tri(j) if k and "name" in k], j
    assert all(x["profile_id"] != rieng["id"] for x in j["excluded"]), j["excluded"]
    # Dòng mục lô lưu bền cũng không có hồ sơ ấy.
    assert {m["profile_id"] for m in await dong_muc(j["batch_id"])} == {khac["id"]}


async def test_q3_ngoai_pham_vi_khong_duoc_xem_va_ma_khong_ton_tai_cung_ket_qua_ke_ca_so_dem(
    client, officer_user_in_db, seed_other_unit, bo_tri, lo_config
):
    rieng, khac, gid = bo_tri["rieng"], bo_tri["khac"], bo_tri["gid"]
    h = await dn(client, officer_user_in_db)
    r_khong = _bo_thoi_gian((await _xem_truoc(client, h, [khac["id"], KHONG_TON_TAI], gid)).json())
    assert r_khong["counts"]["own_assigned_excluded"] == 0
    # (1) Cán bộ chuyển sang đơn vị khác ⇒ KHÔNG còn được xem hồ sơ "của mình" ở U (cổng đọc thường 404) ⇒ không đếm.
    await sql("UPDATE \"user\" SET unit_id = :u WHERE id = :id", u=seed_other_unit["unit_id"], id=officer_user_in_db["id"])
    h = await dn(client, officer_user_in_db)
    assert (await client.get(f"/api/admissions/{rieng['id']}/fee-status", headers=h)).status_code == 404
    r1 = _bo_thoi_gian((await _xem_truoc(client, h, [khac["id"], rieng["id"]], gid)).json())
    await sql("UPDATE \"user\" SET unit_id = :u WHERE id = :id", u=lo_config["unit_id"], id=officer_user_in_db["id"])
    # (2) Hồ sơ "của mình" ra NGOÀI đơn vị của quyền (lead chuyển đơn vị) ⇒ như mã không tồn tại.
    await sql(
        "UPDATE lead SET unit_id = :u WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        u=seed_other_unit["unit_id"], p=rieng["id"],
    )
    h = await dn(client, officer_user_in_db)
    r2 = _bo_thoi_gian((await _xem_truoc(client, h, [khac["id"], rieng["id"]], gid)).json())
    assert r1 == r_khong, (r1, r_khong)
    assert r2 == r_khong, (r2, r_khong)


async def test_q3_dem_duoi_khoa_lead_bi_giu_for_share_toi_khi_xem_truoc_commit(
    client, monkeypatch, officer_user_in_db, bo_tri
):
    """"Chỉ đếm DƯỚI KHOÁ": trong lúc xem trước còn mở giao dịch sau bước khoá lead, một lệnh đổi người phụ trách lead "của
    mình" (phiên khác) phải bị CHÍNH yêu cầu xem trước chặn (``pg_blocking_pids``)."""
    rieng, khac, gid = bo_tri["rieng"], bo_tri["khac"], bo_tri["gid"]
    lead_id = (await hang("SELECT lead_id FROM admission_profile WHERE id = :p", p=rieng["id"]))[0]["lead_id"]
    diem = Diem()
    boc(monkeypatch, bulk_repo, "lock_leads_share", diem)
    h = await dn(client, officer_user_in_db)
    with PidTheoNhan() as ghi:
        viec = asyncio.create_task(_goi_nhan("X", lambda: client.post(
            f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [rieng["id"], khac["id"]], "grant_id": gid})))
        try:
            await asyncio.wait_for(diem.toi.wait(), 30)
            pid_x = set(ghi.pid.get("X", ()))
            doi = asyncio.create_task(_goi_nhan("Y", lambda: sql(
                "UPDATE lead SET assigned_officer_id = :o WHERE id = :l", o=bo_tri["can_bo_2"]["id"], l=lead_id)))
            assert await bi_chan_boi_pid(doi, ghi, "Y", pid_x) == "chan", "đổi người phụ trách phải chờ xem trước commit"
        finally:
            diem.di.set()
        r = await asyncio.wait_for(viec, 30)
        await asyncio.wait_for(doi, 30)
    assert r.status_code == 201 and r.json()["counts"]["own_assigned_excluded"] == 1, r.text


async def _goi_nhan(nhan, ham):
    NHAN.set(nhan)
    return await ham()


async def test_f4_lo_cheo_lead_chuyen_don_vi_giua_cau_chon_va_cau_nap_thi_bo_im_lang(
    client, monkeypatch, officer_user_in_db, seed_other_unit, bo_tri
):
    khac, gid = bo_tri["khac"], bo_tri["gid"]
    h = await dn(client, officer_user_in_db)
    r_khong = _bo_thoi_gian((await _xem_truoc(client, h, [KHONG_TON_TAI], gid)).json())
    goc = bulk_repo.load_profiles_with_documents

    async def chuyen_roi_nap(db, ids):
        await sql(
            "UPDATE lead SET unit_id = :u WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
            u=seed_other_unit["unit_id"], p=khac["id"],
        )
        return await goc(db, ids)

    monkeypatch.setattr(bulk_repo, "load_profiles_with_documents", chuyen_roi_nap)
    j = (await _xem_truoc(client, h, [khac["id"]], gid)).json()
    assert j["items"] == [] and j["excluded"] == [], j
    assert _bo_thoi_gian(j) == r_khong


async def test_f4_lo_thuong_quan_ly_lead_chuyen_don_vi_giua_cau_chon_va_cau_nap_khong_vao_excluded(
    client, monkeypatch, manager_user_in_db, seed_other_unit, bo_tri
):
    khac = bo_tri["khac"]
    goc = bulk_repo.load_profiles_with_documents

    async def chuyen_roi_nap(db, ids):
        await sql(
            "UPDATE lead SET unit_id = :u WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
            u=seed_other_unit["unit_id"], p=khac["id"],
        )
        return await goc(db, ids)

    monkeypatch.setattr(bulk_repo, "load_profiles_with_documents", chuyen_roi_nap)
    h = await dn(client, manager_user_in_db)
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": [khac["id"]]})
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["items"] == [] and j["excluded"] == [], j
    assert j["counts"]["own_assigned_excluded"] == 0


async def test_quyen_cuoi_cung_het_han_trong_luc_cho_khoa_lead_thi_404_khong_tao_lo(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Codex lượt 1 PR-B, điểm chặn 2: xem trước chéo kiểm hạn quyền ở bước 3, rồi CHỜ khoá lead (phiên A giữ lead FOR
    UPDATE — phiên thứ ba xác nhận bằng ``pg_blocking_pids``). Quyền cuối cùng hết hạn trong lúc chờ ⇒ thả A ⇒ 404 cùng thân,
    KHÔNG tạo lô (đếm dòng lô từ phiên riêng)."""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="hhxt"))[0]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    lead_id = (await hang("SELECT lead_id FROM admission_profile WHERE id = :p", p=p["id"]))[0]["lead_id"]
    dem_lo = "SELECT count(*) FROM document_bulk_batch WHERE actor_user_id = :u"
    truoc = (await hang(dem_lo, u=can_bo_cheo["id"]))[0]["count"]
    cb, hb = await dang_nhap(can_bo_cheo)
    a = await KhoaHo("SELECT id FROM lead WHERE id = :l FOR UPDATE", l=lead_id).giu()
    try:
        await sql(
            "UPDATE document_cross_review_grant SET expires_at = clock_timestamp() + interval '3 seconds' WHERE id = :g",
            g=gid,
        )
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(_goi_nhan("B", lambda: cb.post(
                f"{CROSS}/bulk-verify/preview", headers=hb, json={"profile_ids": [p["id"]], "grant_id": gid})))
            assert await bi_chan_boi_pid(viec, ghi, "B", [a.pid]) == "chan", "xem trước phải chờ khoá lead (A giữ)"
            for _ in range(100):
                if (await hang("SELECT clock_timestamp() > expires_at AS het FROM document_cross_review_grant WHERE id = :g",
                               g=gid))[0]["het"]:
                    break
                await asyncio.sleep(0.1)
            assert not viec.done(), "xem trước phải còn chờ khoá lead tới lúc quyền đã hết hạn"
            await a.tha()
            r = await asyncio.wait_for(viec, 30)
    finally:
        await a.tha()
        await cb.aclose()
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    assert (await hang(dem_lo, u=can_bo_cheo["id"]))[0]["count"] == truoc


# ---------------------------------------------------------------------------------------------------- PR-B lượt 3 (Codex lượt 2)
async def test_quyen_cu_o_don_vi_a_mat_chi_con_quyen_o_don_vi_b_thi_xem_truoc_cho_a_404_khong_tao_lo(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, seed_other_unit, lo_config, lo_routers
):
    """Điểm chặn 4a (owner câu 9): xem trước bằng quyền cũ ở đơn vị A (đã thu hồi) khi người gọi CHỈ còn quyền duyệt ở đơn
    vị B ⇒ 404 cùng thân (thiếu quyền phù hợp ĐÚNG đơn vị), không phải 409; không tạo lô. (409 chỉ khi còn quyền khác hợp lệ
    ở CHÍNH đơn vị A — ca ``test_lo_cheo_xem_truoc_va_chay_ghi_via_cross_va_grant_id``.)"""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="l3qa"))[0]
    g_a = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    await cap(client, admin_user_in_db, can_bo_cheo["id"], seed_other_unit["unit_id"], verify=True)
    h = await dn(client, admin_user_in_db)
    r = await client.post(f"{CROSS}/grants/{g_a}/revoke", headers=h, json={"reason": "Đổi phân công"})
    assert r.status_code == 200, r.text
    dem_lo = "SELECT count(*) FROM document_bulk_batch WHERE actor_user_id = :u"
    truoc = (await hang(dem_lo, u=can_bo_cheo["id"]))[0]["count"]
    h = await dn(client, can_bo_cheo)
    r = await client.post(f"{CROSS}/bulk-verify/preview", headers=h, json={"profile_ids": [p["id"]], "grant_id": g_a})
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    assert (await hang(dem_lo, u=can_bo_cheo["id"]))[0]["count"] == truoc


async def test_m_theo_don_vi_doc_lai_sau_khi_cho_khoa_lead_khong_theo_don_vi_cu(
    client, officer_user_in_db, seed_other_unit, bo_tri
):
    """Điểm chặn 4b (owner câu 8): M chỉ đếm hồ sơ thuộc đơn vị người gọi CÒN được xem. Xem trước (B) chờ khoá lead "của
    mình" (phiên A giữ ``FOR UPDATE`` — phiên thứ ba xác nhận bằng ``pg_blocking_pids``); trong lúc chờ, cán bộ chuyển sang
    đơn vị khác (commit — đổi đơn vị không thu hồi quyền, owner câu 4). Thả A ⇒ đơn vị đọc LẠI sau khoá lead ⇒ hồ sơ ấy không
    còn "được xem" ⇒ M = 0, không lộ ở ``items`` / ``excluded``. Theo đơn vị đọc TRƯỚC lần chờ ⇒ M = 1."""
    rieng, khac, gid = bo_tri["rieng"], bo_tri["khac"], bo_tri["gid"]
    lead_id = (await hang("SELECT lead_id FROM admission_profile WHERE id = :p", p=rieng["id"]))[0]["lead_id"]
    cb, hb = await dang_nhap(officer_user_in_db)
    a = await KhoaHo("SELECT id FROM lead WHERE id = :l FOR UPDATE", l=lead_id).giu()
    try:
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(_goi_nhan("B", lambda: cb.post(
                f"{CROSS}/bulk-verify/preview", headers=hb, json={"profile_ids": [rieng["id"], khac["id"]], "grant_id": gid})))
            assert await bi_chan_boi_pid(viec, ghi, "B", [a.pid]) == "chan", "xem trước phải chờ khoá lead (A giữ)"
            await sql("UPDATE \"user\" SET unit_id = :u WHERE id = :id", u=seed_other_unit["unit_id"], id=officer_user_in_db["id"])
            assert not viec.done(), "xem trước phải còn chờ khoá lead tới lúc đơn vị đã đổi"
            await a.tha()
            r = await asyncio.wait_for(viec, 30)
    finally:
        await a.tha()
        await cb.aclose()
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["counts"]["own_assigned_excluded"] == 0, j
    assert rieng["id"] not in {x["profile_id"] for x in j["items"] + j["excluded"]}, j
