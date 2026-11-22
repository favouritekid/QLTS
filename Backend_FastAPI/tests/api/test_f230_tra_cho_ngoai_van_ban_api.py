# -*- coding: utf-8 -*-
"""PR chặn F230 (Codex 22-11 A-P4) — khoá ô chỉ tiêu ở MỌI đường làm đổi số chỗ NGOÀI văn bản Hội đồng.

Thiết kế: ``logs-P5/cong-bo-ket-qua/phat-hanh-gd1/pr-f230/THIET-KE-PHA1-2026-11-22.md``; owner Q1–Q5:
``…/pr-f230/QUYET-DINH-OWNER-F230-Q1-Q5-VA-PR1-TEST-2026-11-22.md`` — CHỈ thêm khoá, luật chặn / cảnh báo của từng đường GIỮ NGUYÊN;
trả chỗ chỉ khoá; đường quên khoá ⇒ 500.

Khuôn chung các ca hai phiên (như ``test_council_decision_o_hien_tai_api``): văn bản A = điều chỉnh BỎ tên P (lead P → ô Y) —
phiên ba giữ DÒNG Quyết định của P ⇒ A dừng ở câu ghi, ĐÃ khoá ô (Y) và ĐÃ đếm số trước. Đường B (ngoài văn bản) chạm Y: phải
khoá Y ⇒ CHỜ A ⇒ kết cục tuần tự A → B: cảnh báo của A (trả về + ĐÃ LƯU) đúng số. Mã cũ: B không khoá Y ⇒ B commit giữa chừng ⇒
phép so "trước / sau" của A sai (mất cảnh báo khi B trả chỗ; sai số khi B thêm chỗ). Kết cục nghiệp vụ khẳng định TRƯỚC, phép
đo (phiên nào chờ phiên nào — ``pg_blocking_pids``) SAU.

* F1  — Rút em "Trúng tuyển" (không Quyết định) ở Y — route ``/withdraw``.
* F1b — như F1, đường dẫn thư (hồ sơ khoá TRƯỚC — bản khoá năm không chờ).
* F2  — Trả về Nháp em "Đã duyệt" ở Y — route v2 ``/admin-rollback``.
* F3  — Chốt rút sau hoàn tiền em CÒN Quyết định hiệu lực chụp ô Y (trả chỗ Phần B).
* F4  — Phê duyệt cũ: ô cổng chỉ tiêu (``applied_rules``) ≠ ô thực sự tăng (lead → Y).
* F5  — Phê duyệt đơn khi học vụ Y đang được tạo (giữ khoá năm độc quyền, chưa commit) — chờ rồi thấy chỉ tiêu.
* F6  — như F5, Phê duyệt hàng loạt ("hai lần dò đều rỗng").
* F7  — Công bố: khoá cả ô theo ngành của lead (đo bằng phiên ba ``FOR UPDATE NOWAIT``).
* F8  — Chuyển từ danh sách chờ: như F7.
* F9  — Trả về Nháp khi cấu hình cùng năm đang giữ khoá năm độc quyền ⇒ 409 "thử lại" NGAY, không chờ (bản không chờ).
* F10 — Chốt ở ``transition()``: chuyển trạng thái chiếm chỗ mà chưa khoá ⇒ ``ServiceError`` (500), trạng thái không đổi.
* F11 — Kiểm kê mã (đọc nguồn): đủ các đường, đúng thứ tự khoá, một lần khoá ô.
* F12 — Phê duyệt (ô cổng CAO, ô lead THẤP) ‖ Phê duyệt hàng loạt [thấp, cao]: MỘT lần khoá ô ⇒ không vòng chờ.
"""
import asyncio
import inspect
import re

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

import app.database as csdl
from app import models
from app.core.advisory_lock_keys import REVIEW_YEAR_NS
from app.database import AsyncSessionLocal
from app.services import admission_choice_engine_service as engine
from app.services import admission_service as asv
from app.services import admission_state_service as state_service
from app.services import payment_service as ps
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import ServiceError
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_bulk_ngu_canh_chi_tieu_api import _dong_nam, _ho_so_cu, _nganh_khac, _thu_khoa
from tests.api.test_council_decision_hai_phien_api import (
    _ban,
    _boc,
    _cho_bi_chan_hoac_xong,
    _dam_bao_sts09,
    _Diem,
    _nop,
)
from tests.api.test_council_decision_khoa_cheo_api import _chuyen_sang_duoc_cd, _duyet_hang_loat, _gan_nganh
from tests.api.test_council_decision_khoa_goc_chuoi_api import PhienBa, chan_cua, cho_bi_chan_boi
from tests.api.test_council_decision_o_hien_tai_api import (
    Q,
    _bo_nganh_lead,
    _bo_none,
    _canh_bao_da_luu,
    _canh_bao_y,
    _dat_o_y,
    _dem_nganh,
    _dong_hieu_luc,
    _o_y,
)
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    A,
    SACH,
    V2,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

#: Em thứ hai (B chạm ô Y) — "Đã duyệt" trong seed, nguyện vọng in ở ô X (Ô tô CĐ chính quy).
E = SACH[1]


# ═══════════════════════════════ công cụ ═════════════════════════════════════════════════════════
class PhienCauHinh:
    """Phiên CSDL riêng giả lập lệnh cấu hình đang dở (tạo / dời năm học vụ — ``organization_service``): giữ khoá năm ĐỘC
    QUYỀN (``REVIEW_YEAR_NS``) và một thay đổi học vụ CHƯA commit."""

    async def __aenter__(self):
        self.ket_noi = await csdl.engine.connect()
        self.giao_dich = await self.ket_noi.begin()
        self.pid = (await self.ket_noi.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        return self

    async def khoa_nam(self, *nam):
        for n in sorted(nam):
            await self.ket_noi.execute(text("SELECT pg_advisory_xact_lock(:ns, :k)"), {"ns": REVIEW_YEAR_NS, "k": n})

    async def dua_hoc_vu_ve(self, ai_id, *, nam, chi_tieu):
        """"Học vụ xuất hiện": dời dòng ``ai_id`` về năm ``nam`` + đặt chỉ tiêu (như PATCH dời năm — khoá năm cũ + mới)."""
        await self.ket_noi.execute(
            text("UPDATE offering_academic_info SET academic_year = :n, annual_admission_quota = :q WHERE id = :a"),
            {"n": nam, "q": chi_tieu, "a": ai_id},
        )

    async def commit(self):
        await self.giao_dich.commit()

    async def tha(self):
        if self.giao_dich.is_active:
            await self.giao_dich.rollback()

    async def __aexit__(self, *exc):
        await self.tha()
        await self.ket_noi.close()


async def _hai_phien(client, ad, hs, r1, lam_b):  # noqa: F811
    """A (điều chỉnh bỏ tên P) dừng ở câu ghi dòng; rồi chạy ``lam_b``. Trả (phản hồi A, kết quả B, pid A, chặn của B)."""
    dong_p = await _dong_hieu_luc(hs[SACH[0]][1])
    async with PhienBa() as ba:
        await ba.khoa("council_decision_row", [dong_p])
        t_a = asyncio.create_task(qd._dieu_chinh(client, ad, r1["id"], "801", bo_dong=[dong_p]))
        pid_a = await cho_bi_chan_boi(ba.pid, t_a)
        assert pid_a is not None, "phép đo không hợp lệ: A không tới câu ghi dòng"
        t_b = asyncio.create_task(lam_b())
        pid_b = await cho_bi_chan_boi(pid_a, t_b)
        chan_b = await chan_cua(pid_b)
        await ba.tha()
        r_a, r_b = await asyncio.gather(t_a, t_b)
    return r_a, r_b, pid_a, chan_b


async def _x_cua(nhan_hs, hs):  # noqa: F811
    """(id học vụ, id loại hình) của nguyện vọng in (đầu tiên) của em ``nhan_hs``."""
    r = await qd._q(
        "SELECT ap.academic_info_id, oai.offering_id FROM admission_profile_choice c "
        "JOIN admission_path ap ON ap.id = c.admission_path_id "
        "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id "
        "WHERE c.admission_profile_id = :p ORDER BY c.display_order, c.id LIMIT 1",
        p=hs[nhan_hs][1],
    )
    return tuple(r[0])


async def _dat_o_cong(pid, ai_id):
    """Ảnh chụp luật trỏ học vụ ``ai_id`` ⇒ cổng chỉ tiêu Phê duyệt cũ khoá / so ô ấy (``_resolve_quota_context``)."""
    await qd._sql(
        "UPDATE admission_profile SET applied_rules = jsonb_set(COALESCE(applied_rules, '{}'::jsonb), '{academic_info_id}', "
        "to_jsonb(CAST(:a AS integer))) WHERE id = :p",
        a=ai_id,
        p=pid,
    )


def _phe_duyet(client, ad, pid, ver):  # noqa: F811
    return client.post(A + "/%d/approve" % pid, json={"version": ver}, headers=ad)


# ═══════════════════════════════ F1 / F1b / F2 / F3 — đường TRẢ chỗ ═══════════════════════════════
async def _chuan_bi_tra_cho_phan_a(client, ad, hs, trang_thai_e):  # noqa: F811
    """R1 (P, chụp X) + ô Y chỉ tiêu 1 đang 2 / 1: em đơn vị khác ("Đã duyệt") + em E (``trang_thai_e``) — cả hai Phần A theo
    lead → Y. Trả (R1, ô Y)."""
    _, r1 = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    y = await _dat_o_y(hs, 1, SACH[0], "don_vi_khac", E)
    await qd._sql("UPDATE admission_profile SET status = :s WHERE id = :p", s=trang_thai_e, p=hs[E][1])
    assert (await _dem_nganh(y))[0] == 2, "tiền điều kiện: ô Y 2 / 1"
    return r1, y


def _kiem_a_tra_cho(r_a, y, cong_bo=0):
    """A (bỏ tên P về Y) chạy TRƯỚC B trả chỗ: "2 → 3 … vượt 2", đã lưu."""
    assert r_a.status_code == 201, r_a.text
    cb = r_a.json()["canh_bao_vuot_chi_tieu"]
    assert cb == [_canh_bao_y(y, 1, 2, 3, cong_bo, 3)], (
        "A làm Y 2 → 3 / 1 phải cảnh báo (B trả chỗ TRƯỚC hoặc SAU cả lần so của A, không giữa chừng): %r" % cb
    )
    return cb


async def test_f1_rut_em_trung_tuyen_cho_van_ban_o_y_khong_mat_canh_bao(client, hs, ad):  # noqa: F811
    r1, y = await _chuan_bi_tra_cho_phan_a(client, ad, hs, "admitted")
    e = hs[E][1]
    ver = (await _ban(e))[1]
    r_a, r_b, pid_a, chan_b = await _hai_phien(
        client,
        ad,
        hs,
        r1,
        lambda: client.post(A + "/%d/withdraw" % e, json={"reason": "GIA rut ho so thu F230", "version": ver}, headers=ad),
    )
    cb = _kiem_a_tra_cho(r_a, y)
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)
    assert r_b.status_code == 200, r_b.text
    assert (await _ban(e))[0] == "withdrawn"
    assert (await _dem_nganh(y))[0] == 2, "ô Y cuối: 2 / 1 (em đơn vị khác + P)"
    assert chan_b == [pid_a], "phép đo: lệnh rút phải chờ ĐÚNG phiên A ở ô Y — %r" % (chan_b,)


async def _rut_qua_duong_dan_thu(pid):
    """Như ``magic_link_service._handle_withdraw``: hồ sơ ĐÃ khoá (``get_token_for_confirm``) rồi mới gọi rút."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            p = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == pid)
                    .options(selectinload(models.AdmissionProfile.lead))
                    .with_for_update()
                )
            ).scalar_one()
            await asv.withdraw_profile(
                s,
                pid,
                None,
                {"reason": "Ung vien tu rut ho so qua magic-link GIA", "version": p.version},
                profile_locked_by_caller=True,
            )
    return "xong"


async def test_f1b_rut_qua_duong_dan_thu_cho_van_ban_o_y(client, hs, ad):  # noqa: F811
    r1, y = await _chuan_bi_tra_cho_phan_a(client, ad, hs, "admitted")
    e = hs[E][1]
    r_a, r_b, pid_a, chan_b = await _hai_phien(client, ad, hs, r1, lambda: _rut_qua_duong_dan_thu(e))
    cb = _kiem_a_tra_cho(r_a, y)
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)
    assert r_b == "xong"
    assert (await _ban(e))[0] == "withdrawn"
    assert (await _dem_nganh(y))[0] == 2
    assert chan_b == [pid_a], "phép đo: rút qua đường dẫn thư phải chờ ĐÚNG phiên A ở ô Y — %r" % (chan_b,)


async def test_f2_tra_ve_nhap_em_da_duyet_cho_van_ban_o_y(client, hs, ad):  # noqa: F811
    r1, y = await _chuan_bi_tra_cho_phan_a(client, ad, hs, "approved")
    e = hs[E][1]
    r_a, r_b, pid_a, chan_b = await _hai_phien(
        client,
        ad,
        hs,
        r1,
        lambda: client.post(
            V2 + "/%d/admin-rollback" % e, json={"reason": "GIA tra ve nhap de thu F230"}, headers=ad
        ),
    )
    cb = _kiem_a_tra_cho(r_a, y)
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)
    assert r_b.status_code == 200, r_b.text
    assert (await _ban(e))[0] == "draft"
    assert (await _dem_nganh(y))[0] == 2
    assert chan_b == [pid_a], "phép đo: trả về Nháp phải chờ ĐÚNG phiên A ở ô Y — %r" % (chan_b,)


async def _chot_rut_sau_hoan(pid):
    """Đúng chuỗi khoá của ``payment_service.process_approved_refund``: khoá năm → khoá hồ sơ → ``_finalize_withdrawn``."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            nam = await qos.lock_years_of_profiles(s, [pid])
            p = (
                await s.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == pid)
                    .options(selectinload(models.AdmissionProfile.lead))
                    .with_for_update()
                )
            ).scalar_one()
            await asv._finalize_withdrawn(
                s, p, None, from_status="withdrawal_pending", reason="GIA chot rut sau hoan tien F230", locked_years=nam
            )
    return "xong"


async def test_f3_chot_rut_sau_hoan_tra_cho_phan_b_cho_van_ban_o_y(client, hs, ad):  # noqa: F811
    # Q giữ chỗ ở Y bằng dòng Quyết định CHỤP Y (Phần B) và đang "Chờ hoàn tiền"; lead Q không trỏ ngành ⇒ chốt rút trả chỗ CHỈ ở
    # phần B của Y. Y: em đơn vị khác (Phần A) + Q (Phần B) = 2 / 1.
    q = hs[Q][1]
    await _chuyen_sang_duoc_cd(hs, Q)
    await qd._qd_cua_bo(client, ad, hs, [Q], "502")
    await _bo_nganh_lead(q)
    await qd._sql("UPDATE admission_profile SET status = 'withdrawal_pending' WHERE id = :p", p=q)
    _, r1 = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    y = await _dat_o_y(hs, 1, SACH[0], "don_vi_khac")
    assert (await _dem_nganh(y))[0] == 2, "tiền điều kiện: ô Y 2 / 1"
    r_a, r_b, pid_a, chan_b = await _hai_phien(client, ad, hs, r1, lambda: _chot_rut_sau_hoan(q))
    cb = _kiem_a_tra_cho(r_a, y, cong_bo=1)
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)
    assert r_b == "xong"
    assert (await _ban(q))[0] == "withdrawn"
    assert (await _dem_nganh(y))[0] == 2, "ô Y cuối: 2 / 1 (Q đã trả chỗ Phần B)"
    assert chan_b == [pid_a], "phép đo: chốt rút phải chờ ĐÚNG phiên A ở ô Y (ô chụp Phần B) — %r" % (chan_b,)


# ═══════════════════════════════ F4 — Phê duyệt cũ khoá ô thực sự tăng ═════════════════════════════
async def test_f4_phe_duyet_o_cong_khac_o_tang_van_cho_van_ban_o_y(client, hs, ad):  # noqa: F811
    # E "Đã nộp", lead → Y, ảnh chụp luật trỏ học vụ W (≠ X, ≠ Y; chỉ tiêu 10) ⇒ cổng chỉ tiêu so W, nhưng em SẼ được đếm ở Y.
    # Y chỉ tiêu 1, đang 1 / 1 (em đơn vị khác). Đúng: Phê duyệt khoá cả Y ⇒ CHỜ A ⇒ A "1 → 2 … vượt 1". Mã cũ (chỉ khoá W): Phê
    # duyệt commit giữa chừng ⇒ A đếm sau = 3 ⇒ "1 → 3" (gán cả chỗ của Phê duyệt cho A).
    await _dam_bao_sts09()
    _, r1 = await qd._qd_cua_bo(client, ad, hs, [SACH[0]], "501")
    y = await _dat_o_y(hs, 1, SACH[0], "don_vi_khac", E)
    x_ai, _ = await _x_cua(SACH[0], hs)
    w = await qd._q1(
        "SELECT id FROM offering_academic_info WHERE academic_year = 2026 AND id <> ALL(CAST(:k AS integer[])) "
        "ORDER BY id LIMIT 1",
        k=[x_ai, y["ai"]],
    )
    assert w is not None, "seed thiếu học vụ thứ ba năm 2026"
    await qd._sql("UPDATE offering_academic_info SET annual_admission_quota = 10 WHERE id = :a", a=w)
    e = hs[E][1]
    await _nop(e)
    await _dat_o_cong(e, w)
    assert await _dem_nganh(y) == (1, 0, 1), "tiền điều kiện: ô Y 1 / 1"
    ver = (await _ban(e))[1]
    r_a, r_b, pid_a, chan_b = await _hai_phien(client, ad, hs, r1, lambda: _phe_duyet(client, ad, e, ver))
    assert r_a.status_code == 201, r_a.text
    cb = r_a.json()["canh_bao_vuot_chi_tieu"]
    assert cb == [_canh_bao_y(y, 1, 1, 2, 0, 2)], "A làm Y 1 → 2: số trước / sau phải là của RIÊNG A — %r" % cb
    assert await _canh_bao_da_luu(r_a.json()["id"], "ghi_nhan_dieu_chinh") == _bo_none(cb)
    assert r_b.status_code == 200, r_b.text  # luật cổng chỉ tiêu GIỮ NGUYÊN (owner Q1): so ô W, còn chỗ
    assert (await _dem_nganh(y))[0] == 3
    assert chan_b == [pid_a], "phép đo: Phê duyệt phải chờ ĐÚNG phiên A ở ô Y — %r" % (chan_b,)


# ═══════════════════════════════ F5 / F6 — học vụ xuất hiện sau lần dò rỗng ═══════════════════════════
async def _chuan_bi_hoc_vu_vang(hs):  # noqa: F811
    """Ngành 2 (khác ngành của Y) KHÔNG có học vụ năm 2026 (dòng z dời sang 2030); E "Đã nộp", hồ sơ cũ (không
    ``academic_info_id``), lead → ngành 2; em đơn vị khác ("Đã duyệt") lead → ngành 2 ⇒ 1 chỗ khi học vụ có lại. Trả (ngành 2,
    z, năm gốc, chỉ tiêu gốc)."""
    await _dam_bao_sts09()
    y = await _o_y(hs)
    off2, z = await _nganh_khac(y["off"])
    nam_z, ct_z = (await qd._q("SELECT academic_year, annual_admission_quota FROM offering_academic_info WHERE id = :a", a=z))[0]
    await qd._sql("UPDATE offering_academic_info SET academic_year = 2030 WHERE id = :a", a=z)
    assert await _dong_nam(off2, 2026) == 0, "tiền điều kiện: ngành 2 còn học vụ năm 2026"
    e = hs[E][1]
    await _nop(e)
    await _ho_so_cu(e)
    for nhan in (E, "don_vi_khac"):
        await _gan_nganh(hs[nhan][1], off2)
    return off2, z, nam_z, ct_z


async def _tra_lai(z, nam_z, ct_z):
    await qd._sql(
        "UPDATE offering_academic_info SET academic_year = :n, annual_admission_quota = :q WHERE id = :a", n=nam_z, q=ct_z, a=z
    )


async def _cho_phien_cau_hinh(lam, z):
    """Phiên cấu hình giữ khoá năm 2026 + 2030 (độc quyền) và đưa học vụ z về 2026 chỉ tiêu 1 — CHƯA commit; chạy ``lam``;
    commit. Trả (kết quả, pid bị chặn, chặn của nó, pid phiên cấu hình)."""
    async with PhienCauHinh() as c:
        await c.khoa_nam(2026, 2030)
        await c.dua_hoc_vu_ve(z, nam=2026, chi_tieu=1)
        t = asyncio.create_task(lam())
        pid_t = await cho_bi_chan_boi(c.pid, t)
        chan_t = await chan_cua(pid_t)
        await c.commit()
        r = await t
    return r, pid_t, chan_t, c.pid


async def test_f5_phe_duyet_cho_hoc_vu_dang_tao_roi_bi_chan_vuot_chi_tieu(client, hs, ad):  # noqa: F811
    off2, z, nam_z, ct_z = await _chuan_bi_hoc_vu_vang(hs)
    e = hs[E][1]
    ver = (await _ban(e))[1]
    try:
        r, pid_t, chan_t, pid_c = await _cho_phien_cau_hinh(lambda: _phe_duyet(client, ad, e, ver), z)
        assert r.status_code == 400 and "Vượt chỉ tiêu" in r.text, (
            "học vụ (chỉ tiêu 1, đã 1 chỗ) commit trước khi Phê duyệt đếm ⇒ phải chặn — %s" % r.text
        )
        assert (await _ban(e))[0] == "submitted"
        async with AsyncSessionLocal() as db:
            assert await qos.count_by_offering_year(db, offering_id=off2, academic_year=2026) == 1
        assert pid_t is not None and chan_t == [pid_c], "phép đo: Phê duyệt phải CHỜ khoá năm của phiên cấu hình — %r" % (chan_t,)
    finally:
        await _tra_lai(z, nam_z, ct_z)


async def test_f6_phe_duyet_hang_loat_cho_hoc_vu_dang_tao_roi_bi_chan(client, hs, ad):  # noqa: F811
    off2, z, nam_z, ct_z = await _chuan_bi_hoc_vu_vang(hs)
    e = hs[E][1]
    ver = (await _ban(e))[1]
    try:
        r, pid_t, chan_t, pid_c = await _cho_phien_cau_hinh(lambda: _duyet_hang_loat(client, ad, (e, ver)), z)
        assert r.status_code == 200, r.text
        kq = r.json()
        assert (kq["success_count"], kq["failed_ids"]) == (0, [e]), kq
        assert "Vượt chỉ tiêu" in kq["errors"][str(e)], kq
        assert (await _ban(e))[0] == "submitted"
        async with AsyncSessionLocal() as db:
            assert await qos.count_by_offering_year(db, offering_id=off2, academic_year=2026) == 1
        assert pid_t is not None and chan_t == [pid_c], "phép đo: lô phải CHỜ khoá năm của phiên cấu hình — %r" % (chan_t,)
    finally:
        await _tra_lai(z, nam_z, ct_z)


# ═══════════════════════════════ F7 / F8 — công bố / chuyển chờ khoá ô theo lead ═════════════════════════
async def _do_khoa_trong_luc_dung(monkeypatch, chay, *muc):
    """Chạy ``chay`` (phiên riêng) tới khi lần gọi ĐẦU ``qos.lock_quota_cells`` xong thì DỪNG (giữ khoá); đo từng dòng ``muc``
    bằng phiên ba ``FOR UPDATE NOWAIT``; thả; LÙI phiên ``chay`` (không ghi gì). Trả {nhãn: "bi_giu" | "trong"}."""
    diem = _Diem()
    _boc(monkeypatch, qos, "lock_quota_cells", diem)
    t = asyncio.create_task(chay())
    await asyncio.wait_for(diem.toi.wait(), 30)
    do = {nhan: await _thu_khoa(bang, id_) for bang, id_, nhan in muc}
    diem.di.set()
    try:
        await t
    except Exception:  # noqa: BLE001 — kết cục xét chỗ không thuộc phép đo này; phiên đã lùi
        pass
    monkeypatch.undo()
    return do


async def test_f7_cong_bo_khoa_ca_o_nganh_theo_lead(client, hs, ad, monkeypatch):  # noqa: F811
    g = hs[SACH[2]][1]
    y = await _dat_o_y(hs, 1, SACH[2])
    x_ai, _ = await _x_cua(SACH[2], hs)
    duong_g = await qd._q1(
        "SELECT admission_path_id FROM admission_profile_choice WHERE admission_profile_id = :p ORDER BY display_order LIMIT 1",
        p=g,
    )
    assert x_ai != y["ai"], "phép đo không hợp lệ: ô nguyện vọng phải KHÁC ô theo lead"
    await qd._sql("UPDATE admission_profile SET status = 'reviewing' WHERE id = :p", p=g)

    async def cong_bo():
        async with AsyncSessionLocal() as s:
            try:
                profile = (
                    await s.execute(
                        select(models.AdmissionProfile)
                        .where(models.AdmissionProfile.id == g)
                        .options(*engine.t6_profile_load_options())
                        .with_for_update()
                    )
                ).scalar_one()
                await engine.evaluate_cascade(s, profile)
            finally:
                await s.rollback()

    do = await _do_khoa_trong_luc_dung(
        monkeypatch, cong_bo, ("offering_academic_info", y["ai"], "y"), ("admission_path", duong_g, "duong_nv")
    )
    assert do == {"y": "bi_giu", "duong_nv": "bi_giu"}, (
        "công bố phải khoá cả ô theo ngành của lead (cách đếm Phê duyệt cũ) — %r (duong_nv: đối chứng dương)" % do
    )


async def test_f8_chuyen_tu_danh_sach_cho_khoa_ca_o_nganh_theo_lead(client, hs, ad, monkeypatch):  # noqa: F811
    g = hs[SACH[2]][1]
    y = await _dat_o_y(hs, 1, SACH[2])
    x_ai, _ = await _x_cua(SACH[2], hs)
    assert x_ai != y["ai"], "phép đo không hợp lệ: ô nguyện vọng phải KHÁC ô theo lead"
    nv = await qd._q1(
        "SELECT id FROM admission_profile_choice WHERE admission_profile_id = :p ORDER BY display_order LIMIT 1", p=g
    )
    duong_g = await qd._q1("SELECT admission_path_id FROM admission_profile_choice WHERE id = :c", c=nv)
    await qd._sql("UPDATE admission_profile SET status = 'waitlisted' WHERE id = :p", p=g)
    await qd._sql("UPDATE admission_profile_choice SET decision = 'waitlisted' WHERE id = :c", c=nv)

    async def chuyen():
        async with AsyncSessionLocal() as s:
            try:
                profile = (
                    await s.execute(
                        select(models.AdmissionProfile)
                        .where(models.AdmissionProfile.id == g)
                        .options(selectinload(models.AdmissionProfile.lead))
                        .with_for_update()
                    )
                ).scalar_one()
                choice = (
                    await s.execute(
                        select(models.AdmissionProfileChoice)
                        .where(models.AdmissionProfileChoice.id == nv)
                        .options(
                            selectinload(models.AdmissionProfileChoice.admission_path).selectinload(
                                models.AdmissionPath.academic_info
                            )
                        )
                    )
                ).scalar_one()
                await engine.promote_waitlisted_choice(s, choice=choice, profile=profile, actor=None)
            finally:
                await s.rollback()

    do = await _do_khoa_trong_luc_dung(
        monkeypatch, chuyen, ("offering_academic_info", y["ai"], "y"), ("admission_path", duong_g, "duong_nv")
    )
    assert do == {"y": "bi_giu", "duong_nv": "bi_giu"}, (
        "chuyển chờ phải khoá cả ô theo ngành của lead — %r (duong_nv: đối chứng dương)" % do
    )


# ═══════════════════════════════ F9 — bản khoá năm KHÔNG CHỜ ═════════════════════════════════════
async def test_f9_tra_ve_nhap_khi_cau_hinh_giu_khoa_nam_tra_409_khong_cho(client, hs, ad):  # noqa: F811
    # Hồ sơ bị khoá ở ``deps.py`` TRƯỚC service ⇒ chờ khoá năm lúc ấy sẽ khép vòng với người lấy khoá năm độc quyền rồi mới
    # khoá hồ sơ (GĐ2-C §7.2). Đúng: thử không chờ ⇒ 409 "thử lại" NGAY (owner Q3), hồ sơ giữ nguyên. Mã sai (bản có chờ): chờ.
    e = hs[E][1]
    async with PhienCauHinh() as c:
        await c.khoa_nam(2026)
        t = asyncio.create_task(
            client.post(V2 + "/%d/admin-rollback" % e, json={"reason": "GIA tra ve nhap de thu F230"}, headers=ad)
        )
        pid_t = await cho_bi_chan_boi(c.pid, t, giay=10)
        xong_truoc = t.done()
        await c.tha()
        r = await t
    assert r.status_code == 409 and qos.CONFLICT_MESSAGE in r.text, r.text
    assert (await _ban(e))[0] == "approved"
    assert xong_truoc and pid_t is None, "phép đo: trả về Nháp KHÔNG được chờ khoá năm khi đang giữ hồ sơ — chặn bởi %r" % pid_t


# ═══════════════════════════════ F10 — chốt ở transition() ════════════════════════════════════════
async def test_f10_chot_transition_chua_khoa_o_thi_500_va_khong_doi_trang_thai(hs):  # noqa: F811
    pid = hs[E][1]
    await _nop(pid)
    async with AsyncSessionLocal() as db:
        p = await db.get(models.AdmissionProfile, pid)
        with pytest.raises(ServiceError) as loi:
            await state_service.transition(db, p, "approved", skip_dispatch=True)
        assert loi.value.detail == qos.OCCUPANCY_TRANSITION_UNLOCKED_MESSAGE
        assert loi.value.status_code == 500
        await db.rollback()
    assert (await _ban(pid))[0] == "submitted"
    # đối chứng: khoá năm + đủ ô (đúng thứ tự đường thật) ⇒ qua
    async with AsyncSessionLocal() as db:
        nam = await qos.lock_years_of_profiles(db, [pid])
        p = await db.get(models.AdmissionProfile, pid)
        await qos.lock_quota_for_profiles(db, locked_years=nam, profile_ids=[pid])
        await state_service.transition(db, p, "approved", skip_dispatch=True)
        assert p.status == "approved"
        await db.rollback()


# ═══════════════════════════════ F11 — kiểm kê mã ════════════════════════════════════════════════
_KHOA_NAM_CO_CHO = re.compile(r"(?<!try_)lock_years_of_profiles\(")
#: Câu khoá DÒNG HỒ SƠ (``select(models.AdmissionProfile)`` … ``.with_for_update(``) — đường hoàn tiền khoá dòng tiền trước đó, được.
_KHOA_HO_SO = re.compile(r"select\(models\.AdmissionProfile\)[^;]{0,400}?\.with_for_update\(", re.S)


def test_f11_kiem_ke_moi_duong_doi_so_cho_khoa_nam_truoc_khoa_o_mot_lan():
    """Đọc nguồn: (1) đường tự khoá hồ sơ lấy khoá năm CÓ CHỜ đúng một lần TRƯỚC câu khoá hồ sơ đầu tiên; (2) đường nhận hồ sơ
    đã khoá ở ``deps.py`` CHỈ dùng bản KHÔNG CHỜ; (3) mỗi đường khoá ô đúng MỘT lần qua ``lock_quota_for_profiles`` (không gọi
    thẳng ``lock_quota_cells``); (4) ``_finalize_withdrawn`` đòi ``locked_years`` và mọi nơi gọi truyền nó; (5) ``transition()``
    gọi chốt."""
    tu_khoa = {
        "approve_profile": asv.approve_profile,
        "withdraw_profile": asv.withdraw_profile,
        "_lock_before_batch_approval": asv._lock_before_batch_approval,
        "process_approved_refund": ps.RefundService.process_approved_refund,
    }
    for ten, ham in tu_khoa.items():
        nguon = inspect.getsource(ham)
        assert len(_KHOA_NAM_CO_CHO.findall(nguon)) == 1, ten
        assert _KHOA_HO_SO.search(nguon) is not None, ten
        assert _KHOA_NAM_CO_CHO.search(nguon).start() < _KHOA_HO_SO.search(nguon).start(), ten
    khoa_o = {
        "approve_profile": asv.approve_profile,
        "_lock_before_batch_approval": asv._lock_before_batch_approval,
        "_finalize_withdrawn": asv._finalize_withdrawn,
        "evaluate_cascade": engine.evaluate_cascade,
        "promote_waitlisted_choice": engine.promote_waitlisted_choice,
        "admin_rollback_profile": engine.admin_rollback_profile,
    }
    for ten, ham in khoa_o.items():
        nguon = inspect.getsource(ham)
        assert nguon.count("lock_quota_for_profiles(") == 1, ten
        assert "lock_quota_cells(" not in nguon, ten
    for ten in ("evaluate_cascade", "promote_waitlisted_choice", "admin_rollback_profile"):
        nguon = inspect.getsource(khoa_o[ten])
        assert "try_lock_years_of_profiles(" in nguon and not _KHOA_NAM_CO_CHO.search(nguon), ten
        assert nguon.index("try_lock_years_of_profiles(") < nguon.index("lock_quota_for_profiles("), ten
    tham_so = inspect.signature(asv._finalize_withdrawn).parameters["locked_years"]
    assert tham_so.default is inspect.Parameter.empty and tham_so.kind is inspect.Parameter.KEYWORD_ONLY
    for ham in (asv.withdraw_profile, ps.RefundService.process_approved_refund):
        nguon = inspect.getsource(ham)
        assert nguon.count("_finalize_withdrawn(") == nguon.count("locked_years=quota_years"), ham.__name__
    assert "check_quota_locked_for_transition(" in inspect.getsource(state_service.transition)


# ═══════════════════════════════ F12 — Phê duyệt: MỘT lần khoá ô ═════════════════════════════════
async def test_f12_phe_duyet_o_cong_cao_o_lead_thap_va_hang_loat_khong_vong_cho(client, hs, ad, monkeypatch):  # noqa: F811
    # E: ô cổng (``applied_rules``) = Y (CAO), lead → X (THẤP). Lô (a1 → X, a2 → Y) khoá trước [X, Y]. Phê duyệt khoá hợp [X, Y]
    # MỘT câu ⇒ lô chờ, không vòng. Biến thể khoá hai lần (ô cổng CAO rồi ô Phần A THẤP) ⇒ Phê duyệt giữ Y chờ X, lô giữ X chờ Y
    # ⇒ 40P01. Điểm đồng bộ: lần gọi ĐẦU ``lock_quota_cells`` (của Phê duyệt) xong thì DỪNG.
    await _dam_bao_sts09()
    x_ai, x_off = await _x_cua("don_vi_khac", hs)
    y = await _o_y(hs)
    assert x_ai < y["ai"], "phép đo không hợp lệ: ô lead phải có id THẤP hơn ô cổng"
    await qd._sql(
        "UPDATE offering_academic_info SET annual_admission_quota = 10 WHERE id = ANY(CAST(:a AS integer[]))",
        a=[x_ai, y["ai"]],
    )
    e, a1, a2 = hs[E][1], hs[SACH[2]][1], hs["don_vi_khac"][1]
    for p, off in ((e, x_off), (a1, x_off), (a2, y["off"])):
        await _nop(p)
        await _gan_nganh(p, off)
    await _dat_o_cong(e, y["ai"])
    ve, v1, v2 = (await _ban(e))[1], (await _ban(a1))[1], (await _ban(a2))[1]
    diem = _Diem()
    _boc(monkeypatch, qos, "lock_quota_cells", diem)
    t_pd = asyncio.create_task(_phe_duyet(client, ad, e, ve))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_lo = asyncio.create_task(_duyet_hang_loat(client, ad, (a1, v1), (a2, v2)))
    do = await _cho_bi_chan_hoac_xong(t_lo)
    diem.di.set()
    r_pd, r_lo = await asyncio.gather(t_pd, t_lo)
    assert qos.CONFLICT_MESSAGE not in r_pd.text and qos.CONFLICT_MESSAGE not in r_lo.text, (r_pd.text, r_lo.text)
    assert r_pd.status_code == 200, r_pd.text
    assert r_lo.status_code == 200 and (r_lo.json()["success_count"], r_lo.json()["failed_ids"]) == (2, []), r_lo.text
    assert do == "chan", "phép đo không hợp lệ: lô không chờ khoá ô của Phê duyệt"
