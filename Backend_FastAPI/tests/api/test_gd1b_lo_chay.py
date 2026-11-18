"""GĐ1b lô — CHẠY lô (đặc tả bản 3.6 §5.3–§5.5; §9 "Lô mỗi hồ sơ một giao dịch", "Mã lô", "F374", "Kiểm lại quyền ở từng
hồ sơ", "Timeout khoá", "document_row_id", "[MỚI 3.4] Quyền lô"; ma trận T8, T9, T11, T12, T16 của báo cáo agent luồng lô).

Mỗi ca kiểm MỘT bất biến. Điểm dừng: bọc hàm của dịch vụ / kho (``Diem``); hai phiên thật: mỗi người một ``AsyncClient``.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import event, select, text

import app.database as csdl
from app import models
from app.core.advisory_lock_keys import batch_lock_key
from app.database import AsyncSessionLocal
from tests.api.gd1b_lo_tro_giup import (  # noqa: F401
    BULK,
    Diem,
    PidTheoNhan,
    boc,
    cho_khoa_vang,
    dang_nhap,
    dn,
    dong_lo,
    dong_muc,
    giay,
    goi,
    khoa_vung_lo,
    lo_config,
    lo_routers,
    sql,
    tao_ho_so_cho_xet,
    xac_nhan,
)

pytestmark = pytest.mark.asyncio


async def _ho_so(client, admin_h, officer, cfg, n, giay_nhan="AB", tien_to="ch"):
    return [await tao_ho_so_cho_xet(client, admin_h, officer, cfg, f"{tien_to}{i}", giay_nhan=giay_nhan) for i in range(n)]


async def _xem_truoc(client, user, ids, **them):
    h = await dn(client, user)
    r = await client.post(f"{BULK}/preview", headers=h, json={"profile_ids": ids, "include_optional": False, **them})
    assert r.status_code == 201, r.text
    return r.json()["batch_id"]


async def _chay(client, user, batch_id):
    h = await dn(client, user)
    return await client.post(f"{BULK}/{batch_id}/execute", headers=h, json=await xac_nhan(batch_id))


async def _trang_thai_giay(doc_id: int) -> str:
    async with AsyncSessionLocal() as s:
        return (await s.execute(select(models.ProfileDocument.status).where(models.ProfileDocument.id == doc_id))).scalar_one()


def _theo_ho_so(muc):
    out = {}
    for m in muc:
        out.setdefault(m["profile_id"], set()).add((m["result"], m["reason_code"]))
    return out


# ---------------------------------------------------------------------------------------------------- đường chính
async def test_chay_lo_ghi_tung_giay_va_dong_ket_qua_ben(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["status"] == "completed" and v["counts"] == {
        "profiles": 2, "recorded": 4, "error": 0, "not_processed": 0, "pending": 0
    }
    lo = await dong_lo(ma)
    assert lo["status"] == "completed" and lo["started_at"] and lo["finished_at"] and lo["confirmation_text"]
    for p in ps:
        for k in "AB":
            d = await giay(p["id"], lo_config["codes"][k])
            assert d.status == "verified" and d.verified_by == manager_user_in_db["id"] and d.file_path is None
            assert d.verified_format == "original"
    async with AsyncSessionLocal() as s:
        nk = (
            await s.execute(
                select(models.DocumentAuditLog).where(
                    models.DocumentAuditLog.action == "verified",
                    models.DocumentAuditLog.profile_document_id == ps[0]["docs"]["A"].id,
                )
            )
        ).scalar_one()
    assert nk.extra_data["via"] == "batch" and nk.extra_data["batch_id"] == ma


async def test_chay_lai_cung_ma_lo_409_batch_exists_khong_ghi_them(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    assert (await _chay(client, manager_user_in_db, ma)).status_code == 200
    async with AsyncSessionLocal() as s:
        truoc = (await s.execute(text("SELECT count(*) FROM document_audit_log"))).scalar_one()
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 409 and r.json()["error_code"] == "BATCH_EXISTS", r.text
    async with AsyncSessionLocal() as s:
        assert (await s.execute(text("SELECT count(*) FROM document_audit_log"))).scalar_one() == truoc


async def test_ban_xem_truoc_het_han_409_preview_expired_khong_chay(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    await sql("UPDATE document_bulk_batch SET expires_at = clock_timestamp() - interval '1 second' WHERE batch_id = :b", b=ma)
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 409 and r.json()["error_code"] == "PREVIEW_EXPIRED", r.text
    assert (await dong_lo(ma))["status"] == "previewed"
    assert await _trang_thai_giay(ps[0]["docs"]["A"].id) == "paper_submitted"


async def test_hai_tab_lo_thu_hai_gap_version_changed_khong_duyet_hai_lan(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma1 = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    ma2 = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    assert (await _chay(client, manager_user_in_db, ma1)).status_code == 200
    r = await _chay(client, manager_user_in_db, ma2)
    assert r.status_code == 200, r.text
    assert {(i["result"], i["reason_code"]) for i in r.json()["items"]} == {("error", "version_changed")}
    async with AsyncSessionLocal() as s:
        n = (
            await s.execute(
                text("SELECT count(*) FROM document_audit_log WHERE action = 'verified' AND profile_document_id = :d"),
                {"d": ps[0]["docs"]["A"].id},
            )
        ).scalar_one()
    assert n == 1


async def test_chua_do_lock_timeout_thi_503_truoc_khi_giu_khoa(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    monkeypatch.setattr(svc, "BULK_VERIFY_LOCK_TIMEOUT_MS", None)
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 503 and r.json()["error_code"] == "BULK_VERIFY_NOT_CONFIGURED", r.text
    assert (await dong_lo(ma))["status"] == "previewed" and await khoa_vung_lo() == []


# ---------------------------------------------------------------------------------------------------- quyền lô (§5.3, §5.6)
async def test_admin_xem_duoc_nhung_khong_chay_lo_cua_nguoi_khac(
    client, admin_token_headers, admin_user_in_db, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    h = await dn(client, admin_user_in_db)
    r = await client.get(f"{BULK}/{ma}", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "not_started" and r.json()["can_execute"] is False, r.text
    r = await client.post(f"{BULK}/{ma}/execute", headers=h, json=await xac_nhan(ma))
    assert r.status_code == 404, r.text
    assert (await dong_lo(ma))["status"] == "previewed"


async def test_nguoi_khac_goi_lo_dang_chay_404_cung_than_khong_hoi_khoa(
    client, monkeypatch, admin_token_headers, manager_user_in_db, manager_other_unit_user_in_db, officer_user_in_db,
    lo_config, lo_routers,
):
    from app.repositories import document_bulk_repository as repo
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    diem = Diem()
    boc(monkeypatch, svc, "_commit_profile", diem)  # A dừng sau hồ sơ 1, VẪN giữ khoá lô
    ca, ha = await dang_nhap(manager_user_in_db)
    cb, hb = await dang_nhap(manager_other_unit_user_in_db)
    cau_khoa = []

    def _nghe(conn, cursor, statement, parameters, context, executemany):
        from tests.api.gd1b_lo_tro_giup import NHAN

        if NHAN.get() == "B" and ("advisory" in statement or "pg_locks" in statement):
            cau_khoa.append(statement)

    eng = [csdl.engine.sync_engine, repo.lock_engine().sync_engine]
    for e in eng:
        event.listen(e, "before_cursor_execute", _nghe)
    try:
        than_a = await xac_nhan(ma)
        a = asyncio.create_task(goi("A", lambda: ca.post(f"{BULK}/{ma}/execute", headers=ha, json=than_a)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        ma_la = uuid.uuid4()
        tra = {}
        for ten, (phuong_thuc, duoi, than) in {
            "execute": ("post", "/execute", {"confirmation_text": "x"}),
            "finalize": ("post", "/finalize", {"reason": "thử"}),
            "get": ("get", "", None),
        }.items():
            kw = {"headers": hb} | ({"json": than} if than is not None else {})
            r_that = await goi("B", lambda: getattr(cb, phuong_thuc)(f"{BULK}/{ma}{duoi}", **kw))
            r_gia = await goi("B", lambda: getattr(cb, phuong_thuc)(f"{BULK}/{ma_la}{duoi}", **kw))
            tra[ten] = (r_that.status_code, r_that.json(), r_gia.status_code, r_gia.json())
        diem.di.set()
        ra = await a
    finally:
        diem.di.set()
        for e in eng:
            event.remove(e, "before_cursor_execute", _nghe)
        await ca.aclose()
        await cb.aclose()
    for ten, (m1, b1, m2, b2) in tra.items():
        assert (m1, b1) == (404, b2) and m2 == 404, (ten, m1, b1, b2)
    assert cau_khoa == [], cau_khoa
    assert ra.status_code == 200 and ra.json()["status"] == "completed", ra.text


# ---------------------------------------------------------------------------------------------------- mỗi hồ sơ một giao dịch
async def test_bom_loi_he_thong_o_ho_so_3_ho_so_truoc_giu_ho_so_sau_chua_xu_ly(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo
    from app.services import document_transition

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 4)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    goc_ghi = repo.write_item_results
    dem = {"n": 0}

    async def ghi_loi_lan_3(*a, **kw):
        dem["n"] += 1
        if dem["n"] == 3:
            raise RuntimeError("bơm lỗi hệ thống ở hồ sơ 3")
        return await goc_ghi(*a, **kw)

    monkeypatch.setattr(repo, "write_item_results", ghi_loi_lan_3)
    goi_lai = []
    goc_tr = document_transition.transition_document

    async def tr_ghi_callback(*a, **kw):
        res = await goc_tr(*a, **kw)
        pid = kw["profile_id"]

        async def finalize(committed: bool):
            goi_lai.append((pid, committed))

        res.finalize = finalize
        return res

    monkeypatch.setattr(document_transition, "transition_document", tr_ghi_callback)
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "stopped"
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[0]["id"]] == {("recorded", None)} and kq[ps[1]["id"]] == {("recorded", None)}
    assert kq[ps[2]["id"]] == {("error", "system_error")}
    assert kq[ps[3]["id"]] == {("not_processed", None)}
    assert await _trang_thai_giay(ps[2]["docs"]["A"].id) == "paper_submitted"
    assert await _trang_thai_giay(ps[3]["docs"]["A"].id) == "paper_submitted"
    assert {pid for pid, ok in goi_lai if ok} == {ps[0]["id"], ps[1]["id"]}, goi_lai
    assert {pid for pid, ok in goi_lai if not ok} == {ps[2]["id"]}, goi_lai


async def test_commit_xong_roi_mat_ket_noi_ho_so_do_van_recorded(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """T16(b): COMMIT của hồ sơ 3 đã vào CSDL rồi phía ứng dụng mới lỗi ⇒ bước dừng đọc dòng kết quả, GIỮ ``recorded``."""
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 4)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    goc = svc._commit_profile
    dem = {"n": 0}

    async def commit_roi_loi(db):
        dem["n"] += 1
        await goc(db)
        if dem["n"] == 3:
            raise ConnectionResetError("mất kết nối SAU commit")

    monkeypatch.setattr(svc, "_commit_profile", commit_roi_loi)
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 200 and r.json()["status"] == "stopped", r.text
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[2]["id"]] == {("recorded", None)}
    assert kq[ps[3]["id"]] == {("not_processed", None)}
    assert await _trang_thai_giay(ps[2]["docs"]["A"].id) == "verified"


async def test_ho_so_bi_giu_qua_lock_timeout_ghi_profile_busy_roi_chay_tiep(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 3)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    monkeypatch.setattr(svc, "BULK_VERIFY_LOCK_TIMEOUT_MS", 300)
    async with csdl.engine.connect() as giu:
        await giu.execute(text("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE"), {"p": ps[1]["id"]})
        r = await _chay(client, manager_user_in_db, ma)
        await giu.rollback()
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[1]["id"]] == {("error", "profile_busy")}
    assert kq[ps[0]["id"]] == {("recorded", None)} and kq[ps[2]["id"]] == {("recorded", None)}
    assert await _trang_thai_giay(ps[1]["docs"]["A"].id) == "paper_submitted"


async def test_khong_ghi_duoc_ket_qua_profile_busy_thi_lo_dung(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 3)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    monkeypatch.setattr(svc, "BULK_VERIFY_LOCK_TIMEOUT_MS", 300)

    async def hong(*a, **kw):
        raise RuntimeError("không ghi được kết quả bền")

    monkeypatch.setattr(repo, "write_busy_results", hong)
    async with csdl.engine.connect() as giu:
        await giu.execute(text("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE"), {"p": ps[1]["id"]})
        r = await _chay(client, manager_user_in_db, ma)
        await giu.rollback()
    assert r.status_code == 200 and r.json()["status"] == "stopped", r.text
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[1]["id"]] == {("error", "system_error")} and kq[ps[2]["id"]] == {("not_processed", None)}


# ---------------------------------------------------------------------------------------------------- kiểm lại quyền ở TỪNG hồ sơ
@pytest.mark.parametrize("doi", ["ha_vai", "doi_don_vi", "khoa_tai_khoan"])
async def test_kiem_lai_quyen_nguoi_bam_o_tung_ho_so(
    doi, client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, seed_other_unit, lo_config,
    lo_routers,
):
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 4)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    diem = Diem(lan=2)  # dừng SAU commit hồ sơ 2
    boc(monkeypatch, svc, "_commit_profile", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        cau = {
            "ha_vai": "UPDATE \"user\" SET role = 'officer' WHERE id = :u",
            "doi_don_vi": f"UPDATE \"user\" SET unit_id = {seed_other_unit['unit_id']} WHERE id = :u",
            "khoa_tai_khoan": "UPDATE \"user\" SET status = 'inactive' WHERE id = :u",
        }[doi]
        await sql(cau, u=manager_user_in_db["id"])
        diem.di.set()
        r = await a
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 200 and r.json()["status"] == "stopped", r.text
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[0]["id"]] == {("recorded", None)} and kq[ps[1]["id"]] == {("recorded", None)}
    assert kq[ps[2]["id"]] == {("error", "actor_not_authorized")}
    assert kq[ps[3]["id"]] == {("not_processed", None)}
    for p in ps[2:]:
        for k in "AB":
            assert await _trang_thai_giay(p["docs"][k].id) == "paper_submitted"


# ---------------------------------------------------------------------------------------------------- F374 — kết nối L
async def test_chay_het_lo_khong_con_khoa_nao_trong_vung_lo(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    assert await khoa_vung_lo() == []


async def test_nha_khoa_loi_thi_huy_ket_noi_L_khoa_vang_trong_2_giay(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app.repositories import document_bulk_repository as repo

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    giu_tham_chieu = []
    goc = repo.try_lock_batch

    async def lay_khoa(*a, **kw):
        k = await goc(*a, **kw)
        giu_tham_chieu.append(k)  # giữ tham chiếu: không để thu gom rác "cứu" ca đỏ
        return k

    async def unlock_hong(lock):
        raise RuntimeError("bơm lỗi vào unlock")

    monkeypatch.setattr(repo, "try_lock_batch", lay_khoa)
    monkeypatch.setattr(repo, "unlock_batch", unlock_hong)
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    lock = giu_tham_chieu[0]
    assert await cho_khoa_vang(batch_lock_key(uuid.UUID(ma)), 2.0), "khoá lô phải vắng ≤ 2 s khi unlock lỗi"
    con = None
    for _ in range(40):
        async with csdl.engine.connect() as k:
            con = (await k.execute(text("SELECT count(*) FROM pg_stat_activity WHERE pid = :p"), {"p": lock.pid})).scalar()
        if con == 0:
            break
        await asyncio.sleep(0.05)
    assert con == 0, "kết nối L phải bị huỷ (≤ 2 s)"


async def test_huy_tac_vu_giua_ho_so_2_va_3_khoa_van_nha(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """T11: yêu cầu bị huỷ (anyio huỷ theo mức — lặp lại) khi đang giữa lô ⇒ việc nhả khoá vẫn chạy tới cùng."""
    from app.repositories import document_bulk_repository as repo
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 3)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    giu_tham_chieu = []
    goc = repo.try_lock_batch

    async def lay_khoa(*a, **kw):
        k = await goc(*a, **kw)
        giu_tham_chieu.append(k)
        return k

    monkeypatch.setattr(repo, "try_lock_batch", lay_khoa)
    diem = Diem(lan=2)
    boc(monkeypatch, svc, "_commit_profile", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        assert [x for x in await khoa_vung_lo() if x["k"] == batch_lock_key(uuid.UUID(ma))], "đang giữ khoá"
        # Huỷ LẶP LẠI (như phạm vi huỷ của anyio) cho tới khi tác vụ kết thúc.
        while not a.done():
            a.cancel()
            await asyncio.sleep(0.01)
    finally:
        diem.di.set()
        await ca.aclose()
    assert await cho_khoa_vang(batch_lock_key(uuid.UUID(ma)), 2.0), "khoá lô phải vắng ≤ 2 s sau khi huỷ"
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[0]["id"]] == {("recorded", None)} and kq[ps[1]["id"]] == {("recorded", None)}
    assert kq[ps[2]["id"]] == {(None, None)}


async def test_ket_noi_L_bi_cat_giua_lo_khong_ghi_ho_so_tiep_theo(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    """T12: L bị ``pg_terminate_backend`` khi A dừng giữa hồ sơ 1–2 ⇒ A KHÔNG ghi hồ sơ 2; tra lô ⇒
    ``interrupted_unfinalized``; chốt ⇒ ``interrupted``."""
    from app.repositories import document_bulk_repository as repo
    from app.services import document_bulk_verify_service as svc

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 3)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    giu_tham_chieu = []
    goc = repo.try_lock_batch

    async def lay_khoa(*a, **kw):
        k = await goc(*a, **kw)
        giu_tham_chieu.append(k)
        return k

    monkeypatch.setattr(repo, "try_lock_batch", lay_khoa)
    diem = Diem(lan=1)
    boc(monkeypatch, svc, "_commit_profile", diem)
    ca, ha = await dang_nhap(manager_user_in_db)
    try:
        a = asyncio.create_task(ca.post(f"{BULK}/{ma}/execute", headers=ha, json=await xac_nhan(ma)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        async with csdl.engine.connect() as k:
            assert (await k.execute(text("SELECT pg_terminate_backend(:p)"), {"p": giu_tham_chieu[0].pid})).scalar()
        assert await cho_khoa_vang(batch_lock_key(uuid.UUID(ma)), 2.0)
        diem.di.set()
        r = await a
    finally:
        diem.di.set()
        await ca.aclose()
    assert r.status_code == 200 and r.json()["status"] == "interrupted_unfinalized", r.text
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[0]["id"]] == {("recorded", None)} and kq[ps[1]["id"]] == {(None, None)}
    assert await _trang_thai_giay(ps[1]["docs"]["A"].id) == "paper_submitted"
    h = await dn(client, manager_user_in_db)
    r = await client.post(f"{BULK}/{ma}/finalize", headers=h, json={})
    assert r.status_code == 200 and r.json()["finalized_now"] is True, r.text
    assert r.json()["batch"]["status"] == "interrupted"
    kq = _theo_ho_so(await dong_muc(ma))
    assert kq[ps[1]["id"]] == {("not_processed", None)} and kq[ps[2]["id"]] == {("not_processed", None)}
    lo = await dong_lo(ma)
    assert lo["finalized_by_user_id"] == manager_user_in_db["id"] and lo["finalized_at"] is not None


# ---------------------------------------------------------------------------------------------------- socket
async def test_su_kien_bulk_verify_finished_toi_nguoi_tao_sau_commit_cuoi(
    client, monkeypatch, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers
):
    from app import socket_manager

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 1)
    ma = await _xem_truoc(client, manager_user_in_db, [ps[0]["id"]])
    phat = []

    async def emit_gia(ev, data=None, room=None, **kw):
        if ev == "bulk_verify_finished":
            phat.append((data, room, (await dong_lo(data["batch_id"]))["status"]))

    monkeypatch.setattr(socket_manager.sio, "emit", emit_gia)
    r = await _chay(client, manager_user_in_db, ma)
    assert r.status_code == 200, r.text
    assert phat == [({"batch_id": ma}, f"user_room_{manager_user_in_db['id']}", "completed")]


# ---------------------------------------------------------------------------------------------------- câu xác nhận (Codex 71 điểm 4)
@pytest.mark.parametrize("sai", ["lech_mot_giay", "chuoi_tuy_y"])
async def test_cau_xac_nhan_khong_dung_cau_chuan_cua_lo_thi_422_khong_chay_khong_luu(
    client, admin_token_headers, manager_user_in_db, officer_user_in_db, lo_config, lo_routers, sai
):
    """Máy chủ chỉ nhận ĐÚNG câu chuẩn với số mục ĐÃ LƯU của lô; câu khác (kể cả chỉ lệch số giấy) ⇒ 422
    ``CONFIRMATION_MISMATCH`` kèm số giấy, lô vẫn ``previewed``, không ghi giấy nào, không lưu câu. Câu đúng ⇒ chạy."""
    from app.services.document_bulk_verify_service import confirmation_sentence

    ps = await _ho_so(client, admin_token_headers, officer_user_in_db, lo_config, 2)
    ma = await _xem_truoc(client, manager_user_in_db, [p["id"] for p in ps])
    dung = await xac_nhan(ma)
    assert dung["confirmation_text"] == confirmation_sentence(4)  # 2 hồ sơ × 2 giấy bản giấy đã nhận
    cau = confirmation_sentence(5) if sai == "lech_mot_giay" else "Tôi xác nhận"
    h = await dn(client, manager_user_in_db)
    r = await client.post(f"{BULK}/{ma}/execute", headers=h, json={"confirmation_text": cau})
    assert r.status_code == 422 and r.json()["error_code"] == "CONFIRMATION_MISMATCH", r.text
    assert r.json()["documents"] == 4, r.text
    lo = await dong_lo(ma)
    assert (lo["status"], lo["started_at"], lo["confirmation_text"]) == ("previewed", None, None)
    assert {m["result"] for m in await dong_muc(ma)} == {None}
    for p in ps:
        for k in "AB":
            assert (await giay(p["id"], lo_config["codes"][k])).status == "paper_submitted"
    r = await client.post(f"{BULK}/{ma}/execute", headers=h, json=dung)
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    assert (await dong_lo(ma))["confirmation_text"] == dung["confirmation_text"]
