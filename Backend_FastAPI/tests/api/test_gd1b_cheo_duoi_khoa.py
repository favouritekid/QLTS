"""GĐ1b PR-B — duyệt chéo LẺ kiểm lại quyền DƯỚI KHOÁ (F2, F3) + thứ tự khoá với đổi vai / khoá tài khoản (Q4).

Hai phiên PostgreSQL thật qua HTTP (khuôn ``test_gd1b_hai_phien``): phiên A giữ khoá hồ sơ bằng một kết nối riêng; phiên B là
yêu cầu ``POST …/cross-review/verify``; phiên thứ ba đo ``pg_blocking_pids`` — KHÔNG hỏi spy. Kết quả (404 thân byte, CSDL
không đổi) đọc từ phiên CSDL riêng.

- F2: quyền hết hạn TRONG lúc B chờ khoá hồ sơ ⇒ 404 cùng thân cổng vào (owner Q1), giấy không đổi, không nhật ký.
- F2': quyền bị thu hồi SAU cổng vào, TRƯỚC khi B lấy khoá ⇒ 404 (bản cũ 409).
- F3: vai đổi / tài khoản bị khoá (SQL thô — KHÔNG kèm tự thu hồi, để chỉ còn đúng phép kiểm vai / trạng thái) sau cổng vào
  ⇒ 404.
- Thứ tự khoá: B giữ dòng quyền chờ khoá hồ sơ; Admin đổi vai qua HTTP (Q4) phải bị B chặn ở dòng quyền ⇒ thả A ⇒ B 200 (đọc
  vai cũ), đổi vai 200 + thu hồi — KHÔNG bế tắc (``40P01`` ⇒ 500).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.services import document_transition
from tests.api.gd1b_cheo_tro_giup import (  # noqa: F401
    KHONG_TON_TAI,
    THAN_404,
    KhoaHo,
    bi_chan_boi_pid,
    can_bo_cheo,
    cap,
    ho_so,
    mot,
)
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    CROSS,
    Diem,
    NHAN,
    PidTheoNhan,
    boc,
    dang_nhap,
    dn,
    giay,
    lo_config,
    lo_routers,
    sql,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _than_404_cong_vao(client, can_bo, gid, d) -> bytes:
    """Thân 404 của CỔNG VÀO (hồ sơ không tồn tại) — mốc so byte cho 404 phát hiện DƯỚI khoá."""
    h = await dn(client, can_bo)
    r = await client.post(
        f"{CROSS}/verify", headers=h,
        json={"grant_id": gid, "profile_id": KHONG_TON_TAI, "document_row_id": d.id, "expected_row_version": d.row_version},
    )
    assert r.status_code == 404 and r.json() == THAN_404, r.text
    return r.content


async def _khong_ghi(pid: int, d, code: str):
    sau = await giay(pid, code)
    assert sau.status == "paper_submitted" and sau.row_version == d.row_version, (sau.status, sau.row_version)
    n = await mot(
        "SELECT count(*) FROM document_audit_log WHERE profile_document_id = :d AND action = 'verified'", d=d.id
    )
    assert n == 0


async def test_f2_quyen_het_han_trong_luc_cho_khoa_ho_so_thi_404_khong_ghi(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="f2a"))[0]
    d = p["docs"]["A"]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    than_moc = await _than_404_cong_vao(client, can_bo_cheo, gid, d)
    cb, hb = await dang_nhap(can_bo_cheo)
    a = await KhoaHo("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE", p=p["id"]).giu()
    try:
        # Quyền còn 3 giây: B qua cổng vào khi còn hạn, rồi chờ khoá hồ sơ (A giữ) cho tới QUÁ hạn.
        await sql(
            "UPDATE document_cross_review_grant SET expires_at = clock_timestamp() + interval '3 seconds' WHERE id = :g",
            g=gid,
        )
        with PidTheoNhan() as ghi:
            viec = asyncio.create_task(
                _goi_nhan("B", lambda: cb.post(
                    f"{CROSS}/verify", headers=hb,
                    json={"grant_id": gid, "profile_id": p["id"], "document_row_id": d.id,
                          "expected_row_version": d.row_version},
                ))
            )
            assert await bi_chan_boi_pid(viec, ghi, "B", [a.pid]) == "chan", "B phải bị A chặn ở khoá hồ sơ"
            for _ in range(100):  # chờ QUÁ hạn theo đồng hồ CSDL
                if await mot("SELECT clock_timestamp() > expires_at FROM document_cross_review_grant WHERE id = :g", g=gid):
                    break
                await asyncio.sleep(0.1)
            assert await mot("SELECT clock_timestamp() > expires_at FROM document_cross_review_grant WHERE id = :g", g=gid)
            assert not viec.done(), "B phải còn chờ khoá tới lúc quyền đã hết hạn"
            await a.tha()
            r = await asyncio.wait_for(viec, 30)
    finally:
        await a.tha()
        await cb.aclose()
    assert r.status_code == 404, r.text
    assert r.content == than_moc, (r.content, than_moc)
    await _khong_ghi(p["id"], d, lo_config["codes"]["A"])


async def _goi_nhan(nhan, ham):
    NHAN.set(nhan)
    return await ham()


async def test_f2_quyen_bi_thu_hoi_sau_cong_vao_thi_404_khong_ghi(
    client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="f2b"))[0]
    d = p["docs"]["A"]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    than_moc = await _than_404_cong_vao(client, can_bo_cheo, gid, d)
    diem = Diem()
    boc(monkeypatch, document_transition, "transition_document", diem, truoc=True)  # dừng SAU cổng vào, TRƯỚC mọi khoá
    cb, hb = await dang_nhap(can_bo_cheo)
    try:
        viec = asyncio.create_task(cb.post(
            f"{CROSS}/verify", headers=hb,
            json={"grant_id": gid, "profile_id": p["id"], "document_row_id": d.id, "expected_row_version": d.row_version},
        ))
        await asyncio.wait_for(diem.toi.wait(), 30)
        h = await dn(client, admin_user_in_db)
        r_thu_hoi = await client.post(f"{CROSS}/grants/{gid}/revoke", headers=h, json={"reason": "Đủ người"})
        assert r_thu_hoi.status_code == 200, r_thu_hoi.text  # đã commit
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cb.aclose()
    assert r.status_code == 404 and r.content == than_moc, r.text
    await _khong_ghi(p["id"], d, lo_config["codes"]["A"])


@pytest.mark.parametrize("bien", ["doi_vai", "khoa"])
async def test_f3_doi_vai_hoac_khoa_tai_khoan_sau_cong_vao_thi_404_khong_ghi(
    bien, client, monkeypatch, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config,
    lo_routers,
):
    """Đổi bằng SQL thô (KHÔNG qua Q4) ⇒ dòng quyền vẫn còn hạn, chưa thu hồi: chỉ còn phép kiểm VAI (``doi_vai``) /
    TRẠNG THÁI (``khoa``) trên dòng người vừa khoá chặn được B."""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to=f"f3{bien}"))[0]
    d = p["docs"]["A"]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    than_moc = await _than_404_cong_vao(client, can_bo_cheo, gid, d)
    diem = Diem()
    boc(monkeypatch, document_transition, "transition_document", diem, truoc=True)
    cb, hb = await dang_nhap(can_bo_cheo)
    try:
        viec = asyncio.create_task(cb.post(
            f"{CROSS}/verify", headers=hb,
            json={"grant_id": gid, "profile_id": p["id"], "document_row_id": d.id, "expected_row_version": d.row_version},
        ))
        await asyncio.wait_for(diem.toi.wait(), 30)
        if bien == "doi_vai":
            await sql("UPDATE \"user\" SET role = 'accountant' WHERE id = :u", u=can_bo_cheo["id"])
        else:
            await sql("UPDATE \"user\" SET status = 'inactive' WHERE id = :u", u=can_bo_cheo["id"])
        diem.di.set()
        r = await asyncio.wait_for(viec, 30)
    finally:
        diem.di.set()
        await cb.aclose()
    assert await mot(
        "SELECT revoked_at IS NULL AND expires_at > clock_timestamp() FROM document_cross_review_grant WHERE id = :g",
        g=gid,
    ), "tiền đề: quyền phải còn hiệu lực — chỉ phép kiểm vai / trạng thái được chặn B"
    assert r.status_code == 404 and r.content == than_moc, r.text
    await _khong_ghi(p["id"], d, lo_config["codes"]["A"])


async def test_doi_vai_qua_http_xep_hang_sau_duyet_cheo_dang_giu_quyen_khong_be_tac(
    client, admin_token_headers, admin_user_in_db, officer_user_in_db, can_bo_cheo, lo_config, lo_routers
):
    """Thứ tự khoá PR-B: B (duyệt chéo) giữ người FOR KEY SHARE + dòng quyền FOR SHARE rồi chờ khoá hồ sơ (A giữ). C (Admin
    đổi vai qua HTTP ⇒ Q4: người FOR NO KEY UPDATE → dòng quyền FOR UPDATE) phải bị ĐÚNG B chặn. Thả A ⇒ B ghi với vai đọc
    được (Cán bộ), C thu hồi + đổi vai — không bên nào 500 (bế tắc)."""
    p = (await ho_so(client, admin_token_headers, officer_user_in_db, lo_config, tien_to="thu"))[0]
    d = p["docs"]["A"]
    gid = await cap(client, admin_user_in_db, can_bo_cheo["id"], lo_config["unit_id"], verify=True)
    cb, hb = await dang_nhap(can_bo_cheo)
    ca, ha = await dang_nhap(admin_user_in_db)
    a = await KhoaHo("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE", p=p["id"]).giu()
    try:
        with PidTheoNhan() as ghi:
            viec_b = asyncio.create_task(_goi_nhan("B", lambda: cb.post(
                f"{CROSS}/verify", headers=hb,
                json={"grant_id": gid, "profile_id": p["id"], "document_row_id": d.id,
                      "expected_row_version": d.row_version},
            )))
            assert await bi_chan_boi_pid(viec_b, ghi, "B", [a.pid]) == "chan"
            viec_c = asyncio.create_task(_goi_nhan("C", lambda: ca.put(
                f"/api/admin/users/{can_bo_cheo['id']}", headers=ha, data={"role": "accountant"},
            )))
            for _ in range(200):
                if ghi.pid.get("B"):
                    break
                await asyncio.sleep(0.05)
            assert await bi_chan_boi_pid(viec_c, ghi, "C", ghi.pid["B"]) == "chan", "đổi vai phải xếp hàng sau B"
            await a.tha()
            r_b = await asyncio.wait_for(viec_b, 30)
            r_c = await asyncio.wait_for(viec_c, 30)
    finally:
        await a.tha()
        await cb.aclose()
        await ca.aclose()
    assert r_b.status_code == 200 and r_b.json()["new_status"] == "verified", r_b.text
    assert r_c.status_code == 200, r_c.text
    assert (await giay(p["id"], lo_config["codes"]["A"])).verified_by == can_bo_cheo["id"]
    assert await mot("SELECT role FROM \"user\" WHERE id = :u", u=can_bo_cheo["id"]) == "accountant"
    assert await mot("SELECT revoked_by_user_id FROM document_cross_review_grant WHERE id = :g", g=gid) == admin_user_in_db["id"]
    ly_do = await mot(
        "SELECT reason FROM entity_audit_log WHERE entity_type = 'document_cross_review_grant' AND entity_id = :g"
        " AND action = 'revoked'",
        g=gid,
    )
    assert ly_do == "Tự thu hồi: tài khoản đổi vai từ Cán bộ sang Kế toán"
    assert json.loads(r_b.content)["profile_id"] == p["id"]
