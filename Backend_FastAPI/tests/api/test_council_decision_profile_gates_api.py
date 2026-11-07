# -*- coding: utf-8 -*-
"""Lượt I (F230) — CỔNG trên luồng hồ sơ khi em có tên trong Quyết định ĐÃ KÝ (HL), đang chờ Admin quyết (CQ)
hoặc mang dấu AppSheet (DA — owner 07-11 E1), qua REQUEST THẬT; trạng thái / yêu cầu hoàn / token đo bằng SQL.
Đặc tả mục 2.4 + 5.5 + 8.1. Mỗi ca một bất biến; đối chứng cùng ca chỉ khác điều kiện được canh.

Tầng chủ sở hữu: ``admission_state_service.transition`` (``kiem_chuyen_trang_thai``); kiểm sớm trong từng hàm
và cờ giao diện là lớp phụ. Kiểm kê: mọi chỗ gọi ``transition`` với đích bị khoá đều có ca ở đây.
"""
import ast
import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

import app.database as csdl
from app.database import AsyncSessionLocal
from app import models
from app.services import admission_state_service as state_service
from app.utils.exceptions import QuyetDinhKhoaHoSo
from tests.api import test_council_decisions_api as qd
from tests.fixtures.hoi_dong_seed import seed_hoi_dong

pytestmark = pytest.mark.integration

A = "/api/admissions"
V2 = "/api/v2/admissions"
SACH = qd.SACH


async def _dam_bao_trang_thai_tu_van():
    """Trạng thái tư vấn mà ``sync_lead_from_admission`` cần khi hồ sơ ĐƯỢC chuyển (ca đối chứng, hai phiên) —
    seed Hội đồng không có. Id + giai đoạn chép từ ``conftest.seed_lead_dependencies``; ``sts08`` (đích của
    ``withdrawn`` trong ``ADMISSION_TO_LEAD_STATUS_MAP``) đặt ở giai đoạn "Không đi học"."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for sid, ten, thu_tu in (
                ("stg02", "Dang tu van", 1002),
                ("stg03", "Da nop ho so", 1003),
                ("stg04", "Ket qua ho so", 1004),
                ("stg07", "Khong di hoc", 1007),
            ):
                if await s.get(models.PipelineStage, sid) is None:
                    s.add(
                        models.PipelineStage(
                            id=sid, name=ten, order=thu_tu, is_final_stage=(sid == "stg07")
                        )
                    )
            await s.flush()
            for sid, ten, stg in (
                ("sts06", "Dong y tu van", "stg02"),
                ("sts07", "Da nop ho so", "stg03"),
                ("sts08", "Tu choi tu van", "stg07"),
                ("sts16", "Ho so khong dat", "stg04"),
            ):
                if await s.get(models.ConsultationStatus, sid) is None:
                    s.add(
                        models.ConsultationStatus(
                            id=sid, name=ten, color_code="#888888", stage_id=stg
                        )
                    )


@pytest_asyncio.fixture
async def hs(setup_test_database):
    async with csdl.engine.begin() as conn:
        du_lieu = await seed_hoi_dong(conn)
    await _dam_bao_trang_thai_tu_van()
    return du_lieu


@pytest_asyncio.fixture
async def tk(client, hs):
    return qd.api._TaiKhoan(client, hs)


@pytest_asyncio.fixture
async def ad(client, tk):
    h = await tk("admin")
    await qd.api._tai_ba_mau_api(client, h)
    return h


async def _co_qd(client, ad, hs, nhan, so="501", trang_thai="submitted"):
    """Ghi nhận Quyết định cho MỘT hồ sơ sạch rồi đặt trạng thái hồ sơ (dữ liệu giả, SQL)."""
    await qd._qd_cua_bo(client, ad, hs, [nhan], so)
    pid = hs[nhan][1]
    await qd._sql("UPDATE admission_profile SET status = :s WHERE id = :p", s=trang_thai, p=pid)
    return pid


async def _dau(hs, nhan, trang_thai="submitted"):
    pid = hs[nhan][1]
    await qd._sql(
        "UPDATE admission_profile SET status = :s, revision_reason = :d WHERE id = :p",
        s=trang_thai,
        d=qd.DAU,
        p=pid,
    )
    return pid


async def _ban(pid):
    return (
        await qd._q("SELECT status, version FROM admission_profile WHERE id = :p", p=pid)
    )[0]


async def _so_yeu_cau_hoan():
    return await qd._q1("SELECT count(*) FROM refund_request")


#: Cụm có trong MỌI thông điệp của ``council_decision_status_service`` (không có trong thông điệp deadlock /
#: xung đột chung) — route cũ (``/api/admissions``) đổi lỗi miền thành HTTPException nên mất ``public_payload``.
CUM_CHAN = "Quyết định đã ký"


def _la_chan(r):
    """409 do CỔNG Quyết định: route V2 giữ payload (``thao_tac``); route cũ chỉ còn ``detail``."""
    if r.status_code != 409:
        return False
    j = r.json()
    if "thao_tac" in j:
        return j.get("error_code") in (None, "COUNCIL_DECISION_LOCKS_PROFILE")
    return CUM_CHAN in str(j.get("detail", ""))


# ═══════════════════════════════ → rejected ═════════════════════════════════════════════════
@pytest.mark.parametrize("dau", ["qd", "appsheet"])
async def test_tu_choi_le_bi_chan(client, hs, ad, dau):
    pid = await (_co_qd(client, ad, hs, SACH[0]) if dau == "qd" else _dau(hs, SACH[0]))
    st, ver = await _ban(pid)
    r = await client.post(
        A + "/%d/reject" % pid, json={"reason": "GIA tu choi thu", "version": ver}, headers=ad
    )
    assert _la_chan(r), r.text
    assert (await _ban(pid))[0] == st


async def test_tu_choi_le_doi_chung_khong_qd_thi_duoc(client, hs, ad):
    pid = hs[SACH[0]][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    st, ver = await _ban(pid)
    r = await client.post(
        A + "/%d/reject" % pid, json={"reason": "GIA tu choi thu", "version": ver}, headers=ad
    )
    assert r.status_code == 200, r.text
    assert (await _ban(pid))[0] == "rejected"


async def test_tu_choi_hang_loat_bo_qua_em_co_qd(client, hs, ad):
    p1 = await _co_qd(client, ad, hs, SACH[0])
    p2 = hs[SACH[1]][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=p2)
    items = [{"profile_id": p, "version": (await _ban(p))[1]} for p in (p1, p2)]
    r = await client.post(
        A + "/bulk/reject", json={"items": items, "reason": "GIA tu choi hang loat"}, headers=ad
    )
    assert r.status_code == 200, r.text
    assert r.json()["failed_ids"] == [p1], r.text
    assert (await _ban(p1))[0] == "submitted" and (await _ban(p2))[0] == "rejected"


async def test_tu_choi_danh_sach_cho_bi_chan(client, hs, ad):
    pid = await _co_qd(client, ad, hs, SACH[1], trang_thai="waitlisted")
    cid = await qd._q1(
        "SELECT min(id) FROM admission_profile_choice WHERE admission_profile_id = :p", p=pid
    )
    await qd._sql("UPDATE admission_profile_choice SET decision = 'waitlisted' WHERE id = :c", c=cid)
    r = await client.post(
        V2 + "/%d/waitlist-reject" % pid,
        json={"choice_id": cid, "reason": "GIA tu choi danh sach cho"},
        headers=ad,
    )
    assert r.status_code == 409, r.text
    assert (await _ban(pid))[0] == "waitlisted"


# ═══════════════════════════════ rút ═══════════════════════════════════════════════════════
@pytest.mark.parametrize("dau", ["qd", "appsheet"])
async def test_rut_qua_can_bo_bi_chan_khong_tu_lap_yeu_cau_hoan(client, hs, ad, dau):
    pid = await (_co_qd(client, ad, hs, SACH[0]) if dau == "qd" else _dau(hs, SACH[0]))
    st, ver = await _ban(pid)
    truoc = await _so_yeu_cau_hoan()
    r = await client.post(
        A + "/%d/withdraw" % pid, json={"reason": "GIA em xin rut", "version": ver}, headers=ad
    )
    assert _la_chan(r), r.text
    assert (await _ban(pid))[0] == st and await _so_yeu_cau_hoan() == truoc


async def test_link_rut_tao_truoc_qd_bam_sau_van_bi_chan(client, hs, ad):
    # G8: link tạo khi "Đã nộp" (chưa có QĐ) → ghi nhận QĐ → bấm link qua route công khai thật ⇒ chặn;
    # trạng thái, yêu cầu hoàn, token KHÔNG đổi (đo CSDL).
    nhan = SACH[0]
    pid = hs[nhan][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    r = await client.post(A + "/%d/send-magic-link" % pid, json={"action": "withdraw"}, headers=ad)
    assert r.status_code in (200, 201), r.text
    token = await qd._q1(
        "SELECT token FROM admission_confirmation_token WHERE profile_id = :p AND "
        "action_type = 'withdraw'",
        p=pid,
    )
    bo = await qd._bo_ok(client, ad, hs, [nhan], xac_nhan_trang_thai={"submitted": 1})
    await qd._ghi_ok(client, ad, bo["id"], so="501", so_hs=1)
    truoc = await _so_yeu_cau_hoan()
    client.cookies.clear()
    r = await client.post(
        V2 + "/magic-link/withdraw/%s" % token, json={"cccd": hs[nhan][0][-4:]}
    )
    assert r.status_code == 409, r.text
    assert (await _ban(pid))[0] == "submitted" and await _so_yeu_cau_hoan() == truoc
    assert (
        await qd._q1(
            "SELECT confirmed_at FROM admission_confirmation_token WHERE token = :t", t=token
        )
        is None
    )


async def test_tao_link_rut_bi_chan_va_co_tat(client, hs, ad):
    pid = await _co_qd(client, ad, hs, SACH[0])
    r = await client.post(A + "/%d/send-magic-link" % pid, json={"action": "withdraw"}, headers=ad)
    assert _la_chan(r), r.text
    r = await client.get(A + "/%d" % pid, headers=ad)
    assert r.status_code == 200, r.text
    q = r.json()["permissions"]
    assert q["send_withdraw_link"] is False and q["reject"] is False
    assert q["admin_rollback"] is False and q["publish_result"] is False


async def test_danh_sach_an_tu_choi_em_co_qd_doi_chung_cung_trang(client, hs, ad):
    # Nối đường ĐỌC DANH SÁCH (``get_profiles`` lean — đọc gộp cả trang): cùng một trang, em có QĐ mất
    # "reject", em không QĐ cùng trạng thái vẫn có.
    pid = await _co_qd(client, ad, hs, SACH[0])
    p2 = hs[SACH[1]][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=p2)
    r = await client.get(A + "?page=1&page_size=100&status=submitted", headers=ad)
    assert r.status_code == 200, r.text
    hang = {x["id"]: x["available_actions"] for x in r.json()["profiles"]}
    assert "reject" not in hang[pid] and "reject" in hang[p2], hang


async def test_co_doi_chung_khong_qd_thi_bat(client, hs, ad):
    pid = hs[SACH[0]][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    q = (await client.get(A + "/%d" % pid, headers=ad)).json()["permissions"]
    assert q["send_withdraw_link"] is True and q["reject"] is True and q["admin_rollback"] is True


async def test_chot_rut_khi_hoan_xong_van_cho_em_co_qd(client, hs, ad):
    # Cạnh MIỄN: withdrawal_pending → withdrawn (chốt rút khi hoàn xong — C3). Đối chứng cùng ca:
    # submitted → withdrawn bị chặn.
    pid = await _co_qd(client, ad, hs, SACH[0], trang_thai="withdrawal_pending")
    async with AsyncSessionLocal() as db:
        p = await db.get(models.AdmissionProfile, pid)
        await state_service.transition(db, p, "withdrawn", skip_dispatch=True)
        assert p.status == "withdrawn"
        await db.rollback()
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    async with AsyncSessionLocal() as db:
        p = await db.get(models.AdmissionProfile, pid)
        with pytest.raises(QuyetDinhKhoaHoSo):
            await state_service.transition(db, p, "withdrawn", skip_dispatch=True)
        await db.rollback()


# ═══════════════════════════════ → draft ═══════════════════════════════════════════════════
@pytest.mark.parametrize("dau", ["qd", "appsheet"])
async def test_huy_quy_trinh_rut_bi_chan(client, hs, ad, dau):
    pid = await (
        _co_qd(client, ad, hs, SACH[0], trang_thai="withdrawal_pending")
        if dau == "qd"
        else _dau(hs, SACH[0], trang_thai="withdrawal_pending")
    )
    r = await client.post(
        A + "/%d/cancel-withdrawal" % pid, json={"reason": "GIA huy quy trinh rut"}, headers=ad
    )
    assert _la_chan(r), r.text
    assert (await _ban(pid))[0] == "withdrawal_pending"


@pytest.mark.parametrize("dau", ["qd", "appsheet"])
async def test_admin_tra_ve_nhap_bi_chan(client, hs, ad, dau):
    pid = await (_co_qd(client, ad, hs, SACH[0]) if dau == "qd" else _dau(hs, SACH[0]))
    r = await client.post(
        V2 + "/%d/admin-rollback" % pid, json={"reason": "GIA tra ve nhap thu"}, headers=ad
    )
    assert _la_chan(r), r.text
    assert (await _ban(pid))[0] == "submitted"


async def test_xoa_ho_so_nhap_co_ten_trong_van_ban_bi_chan(client, hs, ad):
    pid = await _co_qd(client, ad, hs, SACH[0], trang_thai="draft")
    r = await client.delete(A + "/%d" % pid, headers=ad)
    assert r.status_code == 409, r.text
    assert await qd._q1("SELECT count(*) FROM admission_profile WHERE id = :p", p=pid) == 1


# ═══════════════════════════════ công bố theo nguyện vọng (N11, C7, E1) ══════════════════════
async def test_cong_bo_theo_nguyen_vong_bi_chan_em_co_qd(client, hs, ad):
    pid = await _co_qd(client, ad, hs, SACH[1])
    r = await client.post(V2 + "/%d/publish-result" % pid, headers=ad)
    assert _la_chan(r), r.text
    assert (await _ban(pid))[0] == "submitted"


async def test_cong_bo_theo_nguyen_vong_bi_chan_em_cho_admin_quyet(client, hs, ad):
    # F244-3: QĐ bị huỷ hiệu lực ⇒ em vào nhóm chờ ⇒ công bố theo NV vẫn chặn.
    _, x = await qd._qd_cua_bo(client, ad, hs, [SACH[1]], "501")
    assert (await qd._huy_hieu_luc(client, ad, x["id"], "701")).status_code == 201
    pid = hs[SACH[1]][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    r = await client.post(V2 + "/%d/publish-result" % pid, headers=ad)
    assert _la_chan(r) and r.json()["tinh_trang_qd"] == "cho_admin_quyet", r.text


@pytest.mark.parametrize("dau", ["qd", "appsheet"])
async def test_dua_len_tu_danh_sach_cho_bi_chan(client, hs, ad, dau):
    # E1: ``promote_waitlisted_choice`` (danh sách chờ → trúng tuyển) là một lần xét ⇒ như công bố.
    pid = await (
        _co_qd(client, ad, hs, SACH[1], trang_thai="waitlisted")
        if dau == "qd"
        else _dau(hs, SACH[1], trang_thai="waitlisted")
    )
    cid = await qd._q1(
        "SELECT min(id) FROM admission_profile_choice WHERE admission_profile_id = :p", p=pid
    )
    await qd._sql("UPDATE admission_profile_choice SET decision = 'waitlisted' WHERE id = :c", c=cid)
    r = await client.post(
        V2 + "/%d/waitlist-promote" % pid,
        json={"choice_id": cid, "reason": "GIA dua len"},
        headers=ad,
    )
    assert _la_chan(r), r.text
    assert (await _ban(pid))[0] == "waitlisted"
    assert await qd._q1(
        "SELECT decision FROM admission_profile_choice WHERE id = :c", c=cid
    ) == "waitlisted"


async def test_cong_bo_theo_nguyen_vong_bi_chan_dau_appsheet(client, hs, ad):
    pid = await _dau(hs, SACH[1])
    r = await client.post(V2 + "/%d/publish-result" % pid, headers=ad)
    assert _la_chan(r) and r.json()["dau_appsheet"] is True, r.text


# ═══════════════════════════════ hai phiên — ghi nhận ↔ rút (G12) ═══════════════════════════
async def test_hai_phien_ghi_nhan_va_rut_chi_mot_ket_cuc(client, hs, ad):
    nhan = SACH[0]
    pid = hs[nhan][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    bo = await qd._bo_ok(client, ad, hs, [nhan], xac_nhan_trang_thai={"submitted": 1})
    ver = (await _ban(pid))[1]
    r_qd, r_rut = await asyncio.gather(
        qd._ghi(client, ad, bo["id"], so="501", so_hs=1),
        client.post(
            A + "/%d/withdraw" % pid, json={"reason": "GIA em xin rut", "version": ver}, headers=ad
        ),
    )
    assert r_qd.status_code < 500 and r_rut.status_code < 500, (r_qd.text, r_rut.text)
    co_qd = await qd._q1("SELECT count(*) FROM council_decision")
    st = (await _ban(pid))[0]
    if r_qd.status_code == 201:  # ghi nhận trước ⇒ rút bị CỔNG chặn, hồ sơ giữ "Đã nộp"
        assert _la_chan(r_rut) and st == "submitted" and co_qd == 1, r_rut.text
    else:  # rút trước ⇒ ghi nhận thấy trạng thái mới, đòi Admin xác nhận (C3) — không ghi; KHÔNG deadlock
        assert r_rut.status_code == 200 and r_qd.status_code == 409 and co_qd == 0, r_qd.text
        assert "xac_nhan_can" in r_qd.json(), r_qd.text
        assert st in ("withdrawn", "withdrawal_pending")


async def test_hai_phien_ghi_nhan_va_cong_bo_khong_bao_gio_ca_hai(client, hs, ad):
    # G12 / đặc tả 8.5: công bố theo nguyện vọng khoá hồ sơ (``kiem_xet_moi`` FOR UPDATE) rồi mới đọc tình trạng;
    # ghi nhận khoá bộ → hồ sơ. Bất biến: KHÔNG có kết cục "Quyết định đã ghi VÀ hồ sơ đã bị công bố đổi trạng
    # thái"; không 5xx; 409 của ghi nhận (nếu có) là đòi xác nhận, không phải deadlock.
    nhan = SACH[1]
    pid = hs[nhan][1]
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)
    bo = await qd._bo_ok(client, ad, hs, [nhan], xac_nhan_trang_thai={"submitted": 1})
    r_qd, r_cb = await asyncio.gather(
        qd._ghi(client, ad, bo["id"], so="501", so_hs=1),
        client.post(V2 + "/%d/publish-result" % pid, headers=ad),
    )
    # Seed Hội đồng không cấu hình trình độ cho bộ máy nguyện vọng ⇒ công bố đi QUA cổng rồi dừng fail-closed ở
    # T6 (503 ``CHOICE_TARGET_LEVEL_NOT_CONFIGURED``, giao dịch lùi) — 5xx DUY NHẤT được nhận ở đây; deadlock /
    # lỗi khác vẫn đỏ. Nhánh "công bố đổi trạng thái trước" cùng cơ chế với ca rút ở trên (khoá hồ sơ + đếm lại).
    assert r_qd.status_code < 500, r_qd.text
    assert r_cb.status_code < 500 or (
        r_cb.status_code == 503
        and r_cb.json().get("error_code") == "CHOICE_TARGET_LEVEL_NOT_CONFIGURED"
    ), r_cb.text
    co_qd = await qd._q1("SELECT count(*) FROM council_decision")
    st = (await _ban(pid))[0]
    assert not (co_qd == 1 and st != "submitted"), (st, r_qd.text, r_cb.text)
    if r_qd.status_code == 201:
        assert r_cb.status_code >= 400, r_cb.text
    else:
        assert r_qd.status_code == 409 and "xac_nhan_can" in r_qd.json(), r_qd.text
        assert co_qd == 0


async def test_hai_phien_huy_hieu_luc_va_rut(client, hs, ad):
    # G12: văn bản huỷ khoá văn bản → hồ sơ; rút khoá hồ sơ ở cổng. Văn bản huỷ LUÔN ghi được; rút chỉ qua
    # khi đọc thấy Quyết định đã hết hiệu lực (em vào nhóm chờ — CQ không khoá trạng thái, owner C7).
    pid = await _co_qd(client, ad, hs, SACH[0])
    x_id = await qd._q1(
        "SELECT decision_id FROM council_decision_row WHERE profile_id = :p", p=pid
    )
    ver = (await _ban(pid))[1]
    r_huy, r_rut = await asyncio.gather(
        qd._huy_hieu_luc(client, ad, x_id, "701"),
        client.post(
            A + "/%d/withdraw" % pid, json={"reason": "GIA em xin rut", "version": ver}, headers=ad
        ),
    )
    assert r_huy.status_code == 201, r_huy.text
    assert r_rut.status_code < 500, r_rut.text
    assert await qd._q1(
        "SELECT count(*) FROM council_decision_hold WHERE profile_id = :p AND trang_thai = 'cho_quyet'",
        p=pid,
    ) == 1
    st = (await _ban(pid))[0]
    if r_rut.status_code == 200:
        assert st in ("withdrawn", "withdrawal_pending")
    else:
        assert _la_chan(r_rut) and st == "submitted", r_rut.text


# ═══════════════════════════════ kiểm kê chỗ gọi transition với đích bị khoá ═════════════════
DICH = {"draft", "rejected", "withdrawal_pending", "withdrawn"}
#: (tệp, hàm bao) → ca đo qua request thật ở module này.
DA_CO_CA = {
    ("admission_service.py", "reject_profile"): "test_tu_choi_le_bi_chan",
    ("admission_service.py", "bulk_reject"): "test_tu_choi_hang_loat_bo_qua_em_co_qd",
    ("admission_service.py", "withdraw_profile"): "test_rut_qua_can_bo_bi_chan_khong_tu_lap_yeu_cau_hoan",
    ("admission_service.py", "_finalize_withdrawn"): "test_chot_rut_khi_hoan_xong_van_cho_em_co_qd",
    ("admission_service.py", "cancel_withdrawal"): "test_huy_quy_trinh_rut_bi_chan",
    ("admission_choice_engine_service.py", "reject_waitlisted_choice"): "test_tu_choi_danh_sach_cho_bi_chan",
    ("admission_choice_engine_service.py", "admin_rollback_profile"): "test_admin_tra_ve_nhap_bi_chan",
}


def test_moi_cho_goi_transition_den_dich_bi_khoa_deu_co_ca():
    goc = Path(__file__).resolve().parents[2] / "app"
    thay = set()
    for tep in goc.rglob("*.py"):
        cay = ast.parse(tep.read_text(encoding="utf-8"))
        for ham in ast.walk(cay):
            if not isinstance(ham, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for n in ast.walk(ham):
                if (
                    isinstance(n, ast.Call)
                    and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
                    in ("transition", "state_transition")
                    and len(n.args) >= 3
                    and isinstance(n.args[2], ast.Constant)
                    and n.args[2].value in DICH
                ):
                    thay.add((tep.name, ham.name))
    assert len(thay) >= 7, "phép đo rỗng"
    assert thay == set(DA_CO_CA), (sorted(thay - set(DA_CO_CA)), sorted(set(DA_CO_CA) - thay))
    ten = set(globals())
    assert all(v in ten for v in DA_CO_CA.values())
