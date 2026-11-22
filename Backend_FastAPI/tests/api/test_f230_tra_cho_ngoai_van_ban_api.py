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
* F14a / F14b — owner 22-11 (``…/pr-f230/QUYET-DINH-OWNER-F230-RUT-QUA-THU-2026-11-22.md``): ứng viên tự rút qua liên kết trong
  thư khi cấu hình cùng năm đang giữ khoá năm ⇒ 409 NGAY câu owner; hồ sơ, liên kết giữ nguyên, 0 thông báo; nhả khoá ⇒ CHÍNH
  liên kết ấy rút được ĐÚNG MỘT lần, lần thứ ba bị từ chối theo luật liên kết đã dùng.
"""
import ast
import asyncio
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

import app.database as csdl
from app import models
from app.core.advisory_lock_keys import REVIEW_YEAR_NS
from app.config import settings
from app.database import AsyncSessionLocal
from app.services import admission_choice_engine_service as engine
from app.services import admission_service as asv
from app.services import admission_state_service as state_service
from app.services import magic_link_service as mls
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


async def _o_moi_nguyen_vong(pid):
    """[(id học vụ, id đường xét, id nguyện vọng)] của MỌI nguyện vọng của em (thứ tự hiển thị)."""
    return [
        tuple(r)
        for r in await qd._q(
            "SELECT ap.academic_info_id, c.admission_path_id, c.id FROM admission_profile_choice c "
            "JOIN admission_path ap ON ap.id = c.admission_path_id WHERE c.admission_profile_id = :p "
            "ORDER BY c.display_order, c.id",
            p=pid,
        )
    ]


async def _them_nguyen_vong_hai(hs, pid):
    """Thêm nguyện vọng THỨ HAI (Kế toán TC chính quy — ô KHÁC X, Y) cho em ``pid`` ⇒ phép "khoá ô của MỌI nguyện vọng" có
    hai nguyện vọng ở hai ô khác nhau (em seed ``loai_hinh_chinh_quy`` chỉ có một)."""
    py, psg = hs["_danh_muc"]["psg"][("kt_tc", "cq", "g1")]
    await qd._sql(
        "INSERT INTO admission_profile_choice (admission_profile_id, admission_path_id, path_subject_group_config_id, "
        "display_order) VALUES (:p, :y, :g, 2)",
        p=pid,
        y=py,
        g=psg,
    )


async def _hoc_vu_ngoai(*loai_tru):
    """Một học vụ năm 2026 NGOÀI mọi ô của phép đo — đối chứng ÂM (phải ra "trong")."""
    ai = await qd._q1(
        "SELECT id FROM offering_academic_info WHERE academic_year = 2026 AND id <> ALL(CAST(:k AS integer[])) "
        "ORDER BY id LIMIT 1",
        k=sorted(set(loai_tru)),
    )
    assert ai is not None, "seed thiếu học vụ năm 2026 ngoài tập đo"
    return ai


async def test_f7_cong_bo_khoa_ca_o_nganh_theo_lead(client, hs, ad, monkeypatch):  # noqa: F811
    g = hs[SACH[2]][1]
    y = await _dat_o_y(hs, 1, SACH[2])
    await _them_nguyen_vong_hai(hs, g)
    nv = await _o_moi_nguyen_vong(g)
    assert len({ai for ai, _, _ in nv}) == len(nv) == 2, "phép đo không hợp lệ: hai nguyện vọng ở hai ô khác nhau — %r" % nv
    assert all(ai != y["ai"] for ai, _, _ in nv), "phép đo không hợp lệ: ô của MỌI nguyện vọng phải KHÁC ô theo lead"
    ngoai = await _hoc_vu_ngoai(y["ai"], *[ai for ai, _, _ in nv])
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

    muc = [("offering_academic_info", y["ai"], "y"), ("offering_academic_info", ngoai, "ngoai")]
    for i, (ai, duong, _) in enumerate(nv):
        muc += [("offering_academic_info", ai, "hoc_vu_nv%d" % i), ("admission_path", duong, "duong_nv%d" % i)]
    do = await _do_khoa_trong_luc_dung(monkeypatch, cong_bo, *muc)
    mong = {nhan: ("trong" if nhan == "ngoai" else "bi_giu") for _, _, nhan in muc}
    assert do == mong, (
        "công bố phải khoá ô theo ngành của lead (cách đếm Phê duyệt cũ) + ô của MỌI nguyện vọng; dòng ngoài tập KHÔNG bị giữ "
        "(đối chứng âm) — %r" % do
    )


async def test_f8_chuyen_tu_danh_sach_cho_khoa_ca_o_nganh_theo_lead(client, hs, ad, monkeypatch):  # noqa: F811
    # Chuyển nguyện vọng THỨ HAI (không phải nguyện vọng đầu) ⇒ khoá phải theo nguyện vọng được chuyển, không theo thứ tự.
    g = hs[SACH[2]][1]
    y = await _dat_o_y(hs, 1, SACH[2])
    await _them_nguyen_vong_hai(hs, g)
    nv = await _o_moi_nguyen_vong(g)
    assert len({ai for ai, _, _ in nv}) == len(nv) == 2, "phép đo không hợp lệ: hai nguyện vọng ở hai ô khác nhau — %r" % nv
    assert all(ai != y["ai"] for ai, _, _ in nv), "phép đo không hợp lệ: ô của MỌI nguyện vọng phải KHÁC ô theo lead"
    ai_cho, duong_cho, id_cho = nv[1]
    ngoai = await _hoc_vu_ngoai(y["ai"], *[ai for ai, _, _ in nv])
    await qd._sql("UPDATE admission_profile SET status = 'waitlisted' WHERE id = :p", p=g)
    await qd._sql("UPDATE admission_profile_choice SET decision = 'waitlisted' WHERE id = :c", c=id_cho)

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
                        .where(models.AdmissionProfileChoice.id == id_cho)
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
        monkeypatch,
        chuyen,
        ("offering_academic_info", y["ai"], "y"),
        ("offering_academic_info", ai_cho, "hoc_vu_nv"),
        ("admission_path", duong_cho, "duong_nv"),
        ("offering_academic_info", ngoai, "ngoai"),
    )
    assert do == {"y": "bi_giu", "hoc_vu_nv": "bi_giu", "duong_nv": "bi_giu", "ngoai": "trong"}, (
        "chuyển chờ phải khoá ô theo ngành của lead + ô của nguyện vọng được chuyển; dòng ngoài tập KHÔNG bị giữ — %r" % do
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
async def _chuyen_chua_khoa(pid, toi, khoa=None):
    """Phiên riêng: (tuỳ chọn ``khoa(db)`` — khoá một phần), rồi ``transition()`` sang ``toi``. Trả lỗi bắt được (hoặc None); luôn
    LÙI phiên (không ghi gì)."""
    async with AsyncSessionLocal() as db:
        try:
            if khoa is not None:
                await khoa(db)
            p = await db.get(models.AdmissionProfile, pid)
            await state_service.transition(db, p, toi, skip_dispatch=True)
            return None
        except ServiceError as loi:
            return loi
        finally:
            await db.rollback()


def _kiem_loi_chot(loi):
    assert loi is not None, "chốt phải TỪ CHỐI chuyển trạng thái (giao dịch chưa khoá đủ)"
    assert loi.detail == qos.OCCUPANCY_TRANSITION_UNLOCKED_MESSAGE and loi.status_code == 500, loi


async def test_f10_chot_transition_chua_khoa_o_thi_500_va_khong_doi_trang_thai(hs):  # noqa: F811
    pid = hs[E][1]
    await _nop(pid)
    _kiem_loi_chot(await _chuyen_chua_khoa(pid, "approved"))
    assert (await _ban(pid))[0] == "submitted"

    # đối chứng: khoá năm + đủ ô (đúng thứ tự đường thật) ⇒ qua
    async def khoa_du(db):
        nam = await qos.lock_years_of_profiles(db, [pid])
        await qos.lock_quota_for_profiles(db, locked_years=nam, profile_ids=[pid])

    assert await _chuyen_chua_khoa(pid, "approved", khoa_du) is None


async def test_f10a_canh_ra_trung_tuyen_sang_da_rut_chua_khoa_bi_chan(hs):  # noqa: F811
    # Chiều RA khỏi trạng thái chiếm chỗ (trả chỗ) cũng phải bị chốt — không chỉ chiều vào.
    pid = hs[E][1]
    await qd._sql("UPDATE admission_profile SET status = 'admitted' WHERE id = :p", p=pid)
    _kiem_loi_chot(await _chuyen_chua_khoa(pid, "withdrawn"))
    assert (await _ban(pid))[0] == "admitted"


async def test_f10b_cho_hoan_sang_da_rut_con_quyet_dinh_chua_khoa_bi_chan(client, hs, ad):  # noqa: F811
    # ``withdrawal_pending → withdrawn`` KHÔNG vượt ranh giới chiếm chỗ — chỉ nhánh "trả chỗ Phần B" (em còn dòng Quyết định
    # hiệu lực) bắt được nó.
    q = hs[Q][1]
    await _chuyen_sang_duoc_cd(hs, Q)
    await qd._qd_cua_bo(client, ad, hs, [Q], "502")
    await qd._sql("UPDATE admission_profile SET status = 'withdrawal_pending' WHERE id = :p", p=q)
    assert await _dong_hieu_luc(q) is not None, "phép đo không hợp lệ: em phải còn dòng Quyết định hiệu lực"
    _kiem_loi_chot(await _chuyen_chua_khoa(q, "withdrawn"))
    assert (await _ban(q))[0] == "withdrawal_pending"


async def test_f10c_co_o_ma_thieu_khoa_nam_bi_chan(hs):  # noqa: F811
    pid = hs[E][1]
    await _nop(pid)
    await _dat_o_y(hs, 1, E)  # lead → Y ⇒ em có ô Phần A

    async def chi_khoa_o(db):
        ai, path = await qos.profile_quota_cells(db, [pid])
        assert ai, "phép đo không hợp lệ: em phải có ô học vụ"
        await qos.lock_quota_cells(db, ai, path)  # đủ ô, KHÔNG khoá năm

    _kiem_loi_chot(await _chuyen_chua_khoa(pid, "approved", chi_khoa_o))
    assert (await _ban(pid))[0] == "submitted"


async def test_f10d_co_nam_va_hoc_vu_ma_thieu_duong_xet_bi_chan(hs):  # noqa: F811
    pid = hs[E][1]
    await _nop(pid)
    await _dat_o_y(hs, 1, E)
    nv = await _o_moi_nguyen_vong(pid)
    await qd._sql("UPDATE admission_profile_choice SET decision = 'admitted' WHERE id = :c", c=nv[0][2])  # ⇒ ô đường xét Phần A

    async def thieu_duong_xet(db):
        await qos.lock_years_of_profiles(db, [pid])
        ai, path = await qos.profile_quota_cells(db, [pid])
        assert ai and path, "phép đo không hợp lệ: em phải có cả ô học vụ lẫn ô đường xét"
        await qos.lock_quota_cells(db, ai, [])  # năm + học vụ, THIẾU đường xét

    _kiem_loi_chot(await _chuyen_chua_khoa(pid, "approved", thieu_duong_xet))
    assert (await _ban(pid))[0] == "submitted"


class _GianLog:
    """Bọc một logger: ghi lại mọi lần gọi ``ham`` (rồi vẫn chuyển cho logger gốc)."""

    def __init__(self, goc_log, ghi, ham):
        self._goc, self._ghi, self._ham = goc_log, ghi, ham

    def __getattr__(self, ten):
        ham_goc = getattr(self._goc, ten)
        if ten != self._ham:
            return ham_goc

        def boc(su_kien, **kw):
            self._ghi.append((su_kien, kw))
            return ham_goc(su_kien, **kw)

        return boc


async def test_f10e_lo_hai_ho_so_mot_em_thieu_khoa_chi_em_ay_loi_em_kia_duoc_duyet(client, hs, ad, monkeypatch):  # noqa: F811
    # Owner 22-11 (Q5 ở Phê duyệt LÔ): chốt từ chối ⇒ lỗi của RIÊNG hồ sơ ấy ("Unexpected error (ref: …)"), ngăn của nó bị huỷ,
    # hồ sơ giữ nguyên; có log của chốt + log của lô (cùng mã ref); lô vẫn 200, em kia được duyệt. Cố ý để em 2 thiếu khoá: bọc
    # ``lock_quota_for_profiles`` của lô bỏ em 2 (sổ khoá vẫn trung thực — chỉ ghi những gì đã khoá).
    # Dựng như F12: em 1 lead → X, em 2 lead → Y; ô cổng của em 2 = X (chỉ tiêu 10) ⇒ ô Y chỉ đến từ ô của RIÊNG em 2.
    await _dam_bao_sts09()
    e1, e2 = hs[SACH[2]][1], hs["don_vi_khac"][1]
    x_ai, x_off = await _x_cua("don_vi_khac", hs)
    y = await _o_y(hs)
    assert x_ai != y["ai"], "phép đo không hợp lệ: ô X phải khác ô Y"
    await qd._sql("UPDATE offering_academic_info SET annual_admission_quota = 10 WHERE id = :a", a=x_ai)
    for pid_, off in ((e1, x_off), (e2, y["off"])):
        await _nop(pid_)
        await _gan_nganh(pid_, off)
    await _dat_o_cong(e2, x_ai)
    v1, v2 = (await _ban(e1))[1], (await _ban(e2))[1]
    goc = qos.lock_quota_for_profiles

    async def bo_em_2(db, *, profile_ids, **kw):
        return await goc(db, profile_ids=[x for x in profile_ids if x != e2], **kw)

    log_chot, log_lo = [], []
    monkeypatch.setattr(qos, "lock_quota_for_profiles", bo_em_2)
    monkeypatch.setattr(qos, "log", _GianLog(qos.log, log_chot, "error"))
    monkeypatch.setattr(asv, "log", _GianLog(asv.log, log_lo, "exception"))
    r = await _duyet_hang_loat(client, ad, (e1, v1), (e2, v2))
    monkeypatch.undo()
    assert r.status_code == 200, r.text
    kq = r.json()
    assert (kq["success_count"], kq["failed_ids"]) == (1, [e2]), kq
    loi_e2 = kq["errors"][str(e2)]
    assert loi_e2.startswith("Unexpected error (ref: "), kq
    assert ((await _ban(e1))[0], (await _ban(e2))[0]) == ("approved", "submitted")
    chot = [kw for su_kien, kw in log_chot if su_kien == "quota_chuyen_trang_thai_chua_khoa_o" and kw.get("profile_id") == e2]
    assert chot and y["ai"] in chot[0]["missing"]["ai"], "phải có log của chốt nêu em 2 thiếu khoá ô Y — %r" % log_chot
    lo = [kw for su_kien, kw in log_lo if su_kien == "bulk_action_unexpected_error" and kw.get("profile_id") == e2]
    assert lo and lo[0]["error_type"] == "ServiceError" and lo[0]["correlation_id"] in loi_e2, (
        "phải có log của lô kèm đúng mã ref — %r" % log_lo
    )


# ═══════════════════════════════ F11 — kiểm kê mã (AST) ══════════════════════════════════════════
_THU_MUC_APP = Path(asv.__file__).resolve().parents[1]
#: Đích làm đổi số chỗ: trạng thái chiếm chỗ, ``draft`` (trả về Nháp), ``withdrawn`` (rút / trả chỗ Phần B). Đích là BIẾN (hoặc
#: tham chiếu tới hàm chuyển trạng thái mà không gọi ngay) ⇒ coi như đổi số (``_BIEN``).
_DICH_DOI_SO = frozenset(qos.OCCUPYING_STATUSES) | {"draft", qos.RELEASED_STATUSES}
_BIEN = "<biến>"
#: Module chủ sở hữu trạng thái; miễn trừ ĐÚNG một phạm vi — chính hàm ``transition`` (không cả tệp).
_MODULE_TRANG_THAI = "admission_state_service"
_CHU_SO_HUU = "services/admission_state_service.py:transition"
_KHOA_NAM_CO_CHO = frozenset({"lock_years_of_profiles"})
_KHOA_NAM = frozenset({"lock_years_of_profiles", "try_lock_years_of_profiles"})
#: Bảng kiểm kê: MỌI phạm vi có lời gọi / tham chiếu hàm chuyển trạng thái tới đích đổi số → (cách khoá, {đích: số lần}).
#: * ``tu_khoa``: khoá năm CÓ CHỜ chặn MỌI đường tới câu khoá hồ sơ; câu khoá hồ sơ chặn mọi đường tới khoá ô; một lần
#:   ``lock_quota_for_profiles`` chặn mọi đường tới lời gọi;
#: * ``qua_lo``: ``_lock_before_batch_approval`` chặn mọi đường tới lời gọi (hàm ấy theo ``tu_khoa``);
#: * ``qua_finalize``: ``locked_years`` bắt buộc, một lần ``lock_quota_for_profiles`` chặn mọi đường tới lời gọi (nơi gọi:
#:   ``_NOI_GOI_FINALIZE``);
#: * ``khong_cho``: hồ sơ đã khoá ở ``deps.py`` ⇒ CHỈ bản khoá năm KHÔNG CHỜ, chặn mọi đường tới một lần ``lock_quota_for_profiles``;
#: * ``khong_doi_so``: cạnh trong tập chiếm chỗ (từ trạng thái đã chiếm chỗ) hoặc đích bị khoá trạng thái Quyết định chặn — không
#:   đổi số; chỉ được đúng các đích kê ở đây.
#: "Chặn mọi đường" = theo LUỒNG CHẠY (``_bi_chan``), không theo số dòng: câu khoá trong nhánh ``if`` / vòng lặp / ``lambda`` không
#: chặn được lời gọi nằm ngoài nhánh.
_KIEM_KE = {
    "services/admission_service.py:approve_profile": ("tu_khoa", {"approved": 1}),
    "services/admission_service.py:bulk_approve": ("qua_lo", {"approved": 1}),
    "services/admission_service.py:_finalize_withdrawn": ("qua_finalize", {"withdrawn": 1}),
    "services/admission_choice_engine_service.py:evaluate_cascade": ("khong_cho", {_BIEN: 1}),
    "services/admission_choice_engine_service.py:promote_waitlisted_choice": ("khong_cho", {"admitted": 1}),
    "services/admission_choice_engine_service.py:admin_rollback_profile": ("khong_cho", {"draft": 1}),
    "services/admission_service.py:_perform_enrollment_core": ("khong_doi_so", {"enrolled": 1}),  # confirmed / overridden → enrolled
    "services/admission_service.py:override_profile": ("khong_doi_so", {"overridden": 1}),  # approved → overridden
    "services/admission_service.py:verify_and_confirm": ("khong_doi_so", {"confirmed": 1}),  # approved / admitted → confirmed
    "services/admission_service.py:cancel_withdrawal": ("khong_doi_so", {"draft": 1}),  # withdrawal_pending → draft (QĐ: chặn)
}
#: Nơi gọi ``_finalize_withdrawn`` (rút route / thư, chốt rút sau hoàn tiền): khoá năm (có chờ; đường thư: không chờ) chặn mọi
#: đường tới câu khoá hồ sơ và tới lời gọi; truyền ``locked_years``.
_NOI_GOI_FINALIZE = {
    "services/admission_service.py:withdraw_profile",
    "services/payment_service.py:RefundService.process_approved_refund",
}


def _ten_goi(call):
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _bi_danh(cay, rel):
    """(tên trỏ tới HÀM ``admission_state_service.transition``, tên trỏ tới MODULE ấy) trong một tệp — đọc từ MỌI câu import
    (kể cả import lười trong thân hàm), không viết cứng tên: ``from …admission_state_service import transition [as x]`` ⇒ hàm;
    ``from … import admission_state_service [as m]`` / ``import …admission_state_service as m`` ⇒ module. Chính module chủ sở hữu:
    thêm tên hàm ``transition``."""
    ham = {"transition"} if Path(rel).stem == _MODULE_TRANG_THAI else set()
    mod = set()
    for n in ast.walk(cay):
        if isinstance(n, ast.ImportFrom):
            if (n.module or "").split(".")[-1] == _MODULE_TRANG_THAI:
                ham |= {a.asname or a.name for a in n.names if a.name == "transition"}
            mod |= {a.asname or a.name for a in n.names if a.name == _MODULE_TRANG_THAI}
        elif isinstance(n, ast.Import):
            mod |= {a.asname for a in n.names if a.asname and a.name.split(".")[-1] == _MODULE_TRANG_THAI}
    return ham, mod


def _la_getattr_chuyen(nut):
    return (
        isinstance(nut, ast.Call)
        and isinstance(nut.func, ast.Name)
        and nut.func.id == "getattr"
        and len(nut.args) >= 2
        and isinstance(nut.args[1], ast.Constant)
        and nut.args[1].value == "transition"
    )


def _la_ham_chuyen(nut, bi_danh, *, goi):
    """``nut`` trỏ tới hàm chuyển trạng thái: tên bí danh hàm (khi được GỌI: thêm tên trần ``transition`` ở mọi tệp — rộng hơn
    cần, chủ ý); ``.transition`` — khi được GỌI: mọi đối tượng, khi chỉ tham chiếu: đối tượng là bí danh module (``.transition``
    của enum ở chỗ khác không phải hàm này); ``getattr(…, "transition")``."""
    ham, mod = bi_danh
    if isinstance(nut, ast.Name):
        return isinstance(nut.ctx, ast.Load) and (nut.id in ham or (goi and nut.id == "transition"))
    if isinstance(nut, ast.Attribute):
        return (
            isinstance(nut.ctx, ast.Load)
            and nut.attr == "transition"
            and (goi or (isinstance(nut.value, ast.Name) and nut.value.id in mod))
        )
    return _la_getattr_chuyen(nut)


def _quet_app():
    """{khoá phạm vi: (nút, [mọi nút thuộc phạm vi], bí danh của tệp)} cho mọi tệp ``app/**.py``. Phạm vi = mỗi hàm ("tệp:Lớp.hàm"),
    thân mỗi lớp ("tệp:Lớp.<lớp>"), thân module ("tệp:<module>"). Hàm / lớp lồng là phạm vi riêng; thân ``lambda`` THUỘC phạm vi
    bao nó (được quét)."""
    ra = {}
    for tep in sorted(_THU_MUC_APP.rglob("*.py")):
        cay = ast.parse(tep.read_text(encoding="utf-8"))
        rel = tep.relative_to(_THU_MUC_APP).as_posix()
        bi_danh = _bi_danh(cay, rel)

        def thu(nut, khoa, tien_to):
            cac, ngan = [], list(ast.iter_child_nodes(nut))
            while ngan:
                x = ngan.pop()
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    thu(x, "%s:%s%s" % (rel, tien_to, x.name), tien_to + x.name + ".")
                    continue
                if isinstance(x, ast.ClassDef):
                    thu(x, "%s:%s%s.<lop>" % (rel, tien_to, x.name), tien_to + x.name + ".")
                    continue
                cac.append(x)
                ngan.extend(ast.iter_child_nodes(x))
            ra[khoa] = (nut, cac, bi_danh)

        thu(cay, "%s:<module>" % rel, "")
    return ra


def _dich(call):
    for kw in call.keywords:
        if kw.arg == "new_status":
            return kw.value.value if isinstance(kw.value, ast.Constant) else _BIEN
    if len(call.args) >= 3:
        a = call.args[2]
        return a.value if isinstance(a, ast.Constant) else _BIEN
    return _BIEN


def _chuyen_trong(cac, bi_danh):
    """[(nút, đích)] mọi lời gọi hàm chuyển trạng thái trong ``cac`` + mọi tham chiếu KHÔNG gọi ngay (gán, truyền đi, ``getattr``
    tách rời — đích ``_BIEN``)."""
    goi = [c for c in cac if isinstance(c, ast.Call) and _la_ham_chuyen(c.func, bi_danh, goi=True)]
    la_func = {id(c.func) for c in goi}
    tham_chieu = [x for x in cac if id(x) not in la_func and _la_ham_chuyen(x, bi_danh, goi=False)]
    # ``getattr(m, "transition")`` là ``func`` của lời gọi ngoài ⇒ đã tính ở ``goi``; ``m`` trong ``m.transition`` không phải hàm.
    return [(c, _dich(c)) for c in goi] + [(x, _BIEN) for x in tham_chieu]


def _goi(cac, ten):
    return [c for c in cac if isinstance(c, ast.Call) and _ten_goi(c) == ten]


def _la_khoa_ho_so(call):
    return _ten_goi(call) == "with_for_update" and any(
        isinstance(x, ast.Call)
        and _ten_goi(x) == "select"
        and x.args
        and isinstance(x.args[0], ast.Attribute)
        and x.args[0].attr == "AdmissionProfile"
        for x in ast.walk(call)
    )


# ── luồng chạy: "câu khoá CHẮC CHẮN đã chạy trên MỌI đường tới nút đích" ─────────────────────────
def _goi_chac_chan(bt, la_khoa):
    """Biểu thức ``bt`` CHẮC CHẮN chạy một lời gọi thoả ``la_khoa`` — không tính nhánh ``x if c else y``, vế sau của ``and`` /
    ``or``, thân comprehension, ``lambda`` / hàm lồng (chạy sau hoặc không chạy)."""
    if isinstance(bt, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    if isinstance(bt, ast.Call) and la_khoa(bt):
        return True
    if isinstance(bt, ast.IfExp):
        return _goi_chac_chan(bt.test, la_khoa)
    if isinstance(bt, ast.BoolOp):
        return _goi_chac_chan(bt.values[0], la_khoa)
    if isinstance(bt, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        return _goi_chac_chan(bt.generators[0].iter, la_khoa)
    return any(_goi_chac_chan(x, la_khoa) for x in ast.iter_child_nodes(bt))


def _ket_thuc(ds):
    return bool(ds) and isinstance(ds[-1], (ast.Raise, ast.Return))


def _ds_chac_chan(ds, la_khoa):
    """Đi hết danh sách câu ``ds`` thì CHẮC CHẮN đã gọi ``la_khoa``; danh sách luôn kết thúc bằng ``raise`` / ``return`` (không tới
    câu sau) coi như đạt."""
    return any(_cau_chac_chan(c, la_khoa) for c in ds) or _ket_thuc(ds)


def _cau_chac_chan(cau, la_khoa):
    if isinstance(cau, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return False
    if isinstance(cau, ast.If):
        return _goi_chac_chan(cau.test, la_khoa) or (
            _ds_chac_chan(cau.body, la_khoa) and _ds_chac_chan(cau.orelse, la_khoa)
        )
    if isinstance(cau, (ast.With, ast.AsyncWith)):
        return any(_goi_chac_chan(i.context_expr, la_khoa) for i in cau.items) or _ds_chac_chan(cau.body, la_khoa)
    if isinstance(cau, (ast.Try, getattr(ast, "TryStar", ast.Try))):
        # thân try chắc chắn chạy hết khi MỌI except đều ném tiếp / trả về (không đi tiếp xuống câu sau)
        return (_ds_chac_chan(cau.body, la_khoa) and all(_ket_thuc(h.body) for h in cau.handlers)) or _ds_chac_chan(
            cau.finalbody, la_khoa
        )
    if isinstance(cau, (ast.For, ast.AsyncFor)):
        return _goi_chac_chan(cau.iter, la_khoa)
    if isinstance(cau, ast.While):
        return _goi_chac_chan(cau.test, la_khoa)
    if isinstance(cau, ast.Match):
        return _goi_chac_chan(cau.subject, la_khoa)
    return _goi_chac_chan(cau, la_khoa)


def _chua(nut, dich):
    return any(x is dich for x in ast.walk(nut))


def _duong(ds, dich):
    """[(danh sách câu, chỉ số, nhánh)] từ ``ds`` xuống câu trong cùng chứa ``dich`` (nhánh = tên thân con chứa nó, None nếu
    ``dich`` nằm ở phần biểu thức của chính câu)."""
    for i, cau in enumerate(ds):
        if not _chua(cau, dich):
            continue
        for ten in ("body", "orelse", "finalbody"):
            con = getattr(cau, ten, None)
            if isinstance(con, list) and any(isinstance(c, ast.stmt) and _chua(c, dich) for c in con):
                return [(ds, i, ten)] + _duong(con, dich)
        for h in getattr(cau, "handlers", None) or []:
            if _chua(h, dich):
                return [(ds, i, "handlers")] + _duong(h.body, dich)
        for ca in getattr(cau, "cases", None) or []:
            if _chua(ca, dich):
                return [(ds, i, "cases")] + _duong(ca.body, dich)
        return [(ds, i, None)]
    return []


def _bi_chan(ham, dich, la_khoa):
    """MỌI đường chạy từ đầu ``ham`` tới nút ``dich`` đều đã qua một lời gọi ``la_khoa`` (theo luồng, không theo số dòng)."""
    duong = _duong(ham.body, dich)
    assert duong, "phép đo hỏng: không tìm thấy nút đích trong thân hàm"
    for ds, i, nhanh in duong:
        if any(_cau_chac_chan(c, la_khoa) for c in ds[:i]):
            return True
        cau = ds[i]
        if nhanh is None:
            continue
        dau = []
        if isinstance(cau, (ast.If, ast.While)):
            dau = [cau.test]
        elif isinstance(cau, (ast.For, ast.AsyncFor)):
            dau = [cau.iter]
        elif isinstance(cau, (ast.With, ast.AsyncWith)):
            dau = [it.context_expr for it in cau.items]
        elif isinstance(cau, ast.Match):
            dau = [cau.subject]
        if any(_goi_chac_chan(x, la_khoa) for x in dau):
            return True
        if isinstance(cau, ast.Try) and nhanh == "orelse" and _ds_chac_chan(cau.body, la_khoa):
            return True
    return False


def _ten_la(*ten):
    return lambda c: _ten_goi(c) in ten


def _kiem_khoa_nam_truoc_ho_so(khoa, ham, cac, la_nam, cam_ban_thu):
    co_cho = _goi(cac, "lock_years_of_profiles")
    ho_so = [c for c in cac if isinstance(c, ast.Call) and _la_khoa_ho_so(c)]
    assert len(co_cho) == 1 and ho_so, (khoa, "đúng MỘT lần khoá năm CÓ CHỜ + có câu khoá hồ sơ", len(co_cho), len(ho_so))
    for c in ho_so:
        assert _bi_chan(ham, c, la_nam), (khoa, "khoá năm phải chặn MỌI đường tới câu khoá hồ sơ", c.lineno)
    if cam_ban_thu:
        assert not _goi(cac, "try_lock_years_of_profiles"), (khoa, "đường tự khoá hồ sơ không dùng bản không chờ")
    return ho_so


def test_f11_kiem_ke_ast_moi_duong_doi_so_cho_deu_khoa_dung_thu_tu():
    """Quét AST MỌI ``app/**.py`` (hàm, thân lớp, thân module; kể cả thân ``lambda``): (1) mọi lời gọi / tham chiếu hàm chuyển
    trạng thái (bí danh lấy từ câu import của ``admission_state_service``, ``.transition``, ``getattr(…, "transition")``) tới đích
    đổi số (chiếm chỗ, ``draft``, ``withdrawn``, biến) phải nằm trong ``_KIEM_KE`` đúng đích, đúng số lần — và ngược lại; miễn trừ
    ĐÚNG ``admission_state_service.py:transition``; (2) cách khoá từng phạm vi đúng mục kê, thứ tự THEO LUỒNG CHẠY (không gọi
    thẳng ``lock_quota_cells``; ``khong_cho`` không dùng bản có chờ); (3) mọi lời gọi ``_finalize_withdrawn`` truyền
    ``locked_years``, nơi gọi khoá năm chặn mọi đường tới câu khoá hồ sơ và tới lời gọi; (4) chốt ở ``transition()`` chặn mọi
    đường tới câu đặt ``.status``."""
    pham_vi = _quet_app()
    thay = {}
    for khoa, (_, cac, bi_danh) in pham_vi.items():
        if khoa == _CHU_SO_HUU:
            continue
        dich = [d for _, d in _chuyen_trong(cac, bi_danh) if d == _BIEN or d in _DICH_DOI_SO]
        if dich:
            thay[khoa] = {d: dich.count(d) for d in set(dich)}
    assert thay == {k: v[1] for k, v in _KIEM_KE.items()}, (
        "lời gọi / tham chiếu chuyển trạng thái đổi số chỗ NGOÀI bảng kiểm kê (hoặc bảng kê thừa / lệch đích) — %r" % thay
    )
    for khoa, (cach, _) in _KIEM_KE.items():
        ham, cac, bi_danh = pham_vi[khoa]
        chuyen = [n for n, d in _chuyen_trong(cac, bi_danh) if d == _BIEN or d in _DICH_DOI_SO]
        if cach == "khong_doi_so":
            continue
        assert not _goi(cac, "lock_quota_cells"), (khoa, "không gọi thẳng lock_quota_cells")
        if cach == "qua_lo":
            assert len(_goi(cac, "_lock_before_batch_approval")) == 1, khoa
            for n in chuyen:
                assert _bi_chan(ham, n, _ten_la("_lock_before_batch_approval")), (khoa, "khoá lô phải chặn mọi đường", n.lineno)
            ham_lo, cac_lo, _ = pham_vi["services/admission_service.py:_lock_before_batch_approval"]
            ho_so = _kiem_khoa_nam_truoc_ho_so("_lock_before_batch_approval", ham_lo, cac_lo, _ten_la(*_KHOA_NAM_CO_CHO), True)
            khoa_o_lo = _goi(cac_lo, "lock_quota_for_profiles")
            assert len(khoa_o_lo) == 1 and not _goi(cac_lo, "lock_quota_cells"), "_lock_before_batch_approval"
            assert ho_so and _bi_chan(ham_lo, khoa_o_lo[0], _la_khoa_ho_so), (
                "_lock_before_batch_approval",
                "khoá hồ sơ phải chặn mọi đường tới khoá ô",
            )
            continue
        khoa_o = _goi(cac, "lock_quota_for_profiles")
        assert len(khoa_o) == 1, (khoa, "đúng MỘT lần lock_quota_for_profiles", len(khoa_o))
        for n in chuyen:
            assert _bi_chan(ham, n, _ten_la("lock_quota_for_profiles")), (
                khoa,
                "lock_quota_for_profiles phải chặn MỌI đường tới lời gọi chuyển trạng thái",
                n.lineno,
            )
        if cach == "tu_khoa":
            _kiem_khoa_nam_truoc_ho_so(khoa, ham, cac, _ten_la(*_KHOA_NAM_CO_CHO), True)
            assert _bi_chan(ham, khoa_o[0], _la_khoa_ho_so), (khoa, "khoá hồ sơ phải chặn mọi đường tới khoá ô")
        elif cach == "khong_cho":
            assert not _goi(cac, "lock_years_of_profiles"), (khoa, "đường nhận hồ sơ đã khoá KHÔNG được dùng bản có chờ")
            assert len(_goi(cac, "try_lock_years_of_profiles")) == 1, (khoa, "đúng MỘT lần khoá năm không chờ")
            assert _bi_chan(ham, khoa_o[0], _ten_la("try_lock_years_of_profiles")), (
                khoa,
                "bản không chờ phải chặn mọi đường tới khoá ô",
            )
        elif cach == "qua_finalize":
            ten_tham_so = [a.arg for a in ham.args.kwonlyargs]
            assert "locked_years" in ten_tham_so, "_finalize_withdrawn phải có tham số chỉ-từ-khoá locked_years"
            assert ham.args.kw_defaults[ten_tham_so.index("locked_years")] is None, "locked_years phải BẮT BUỘC (không mặc định)"
    noi_goi = {}
    for khoa, (ham, cac, _) in pham_vi.items():
        for c in _goi(cac, "_finalize_withdrawn"):
            assert any(kw.arg == "locked_years" for kw in c.keywords), (khoa, c.lineno, "thiếu locked_years")
            noi_goi.setdefault(khoa, []).append(c)
    assert set(noi_goi) == _NOI_GOI_FINALIZE, sorted(noi_goi)
    for khoa, goi_finalize in noi_goi.items():
        ham, cac, _ = pham_vi[khoa]
        _kiem_khoa_nam_truoc_ho_so(khoa, ham, cac, _ten_la(*_KHOA_NAM), False)
        for c in goi_finalize:
            assert _bi_chan(ham, c, _ten_la(*_KHOA_NAM)), (khoa, "khoá năm phải chặn mọi đường tới _finalize_withdrawn", c.lineno)
    ham_ts, cac_ts, _ = pham_vi[_CHU_SO_HUU]
    dat_trang_thai = [
        x
        for x in cac_ts
        if isinstance(x, (ast.Assign, ast.AugAssign, ast.AnnAssign))
        and any(isinstance(t, ast.Attribute) and t.attr == "status" for t in getattr(x, "targets", [getattr(x, "target", None)]))
    ]
    assert dat_trang_thai, "phép đo hỏng: transition() không còn câu đặt .status"
    for x in dat_trang_thai:
        assert _bi_chan(ham_ts, x, _ten_la("check_quota_locked_for_transition")), (
            "chốt ở transition() phải chặn MỌI đường tới câu đặt .status",
            x.lineno,
        )


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


# ═══════════════════════════════ F14 — rút qua liên kết trong thư khi khoá năm bận (owner 22-11) ═════════
#: Trần thời gian của lần 409 "ngay" (một request bình thường dưới 2 s; chờ khoá năm thì treo tới khi phiên cấu hình nhả).
TRAN_409_GIAY = 5.0


async def _lien_ket_rut(hs):  # noqa: F811
    """Liên kết rút còn hạn cho em E ("Trúng tuyển", không Quyết định — rút thẳng về "Đã rút"). Trả (giá trị, 4 số CCCD, id)."""
    pid = hs[E][1]
    await qd._sql("UPDATE admission_profile SET status = 'admitted' WHERE id = :p", p=pid)
    gia_tri = secrets.token_urlsafe(32)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            tk_ = models.AdmissionConfirmationToken(
                profile_id=pid,
                action_type="withdraw",
                token=gia_tri,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(tk_)
            await s.flush()
            id_ = tk_.id
    return gia_tri, hs[E][0][-settings.ADMISSION_CONFIRM_CCCD_DIGITS:], id_


def _rut_qua_thu(client, gia_tri, so_cccd):  # noqa: F811
    return client.post("/api/v2/admissions/magic-link/withdraw/%s" % gia_tri, json={"cccd": so_cccd})


async def _trang_thai_lien_ket(id_):
    r = await qd._q(
        "SELECT confirmed_at, attempt_count, locked_at, lock_until, expires_at, lock_count "
        "FROM admission_confirmation_token WHERE id = :i",
        i=id_,
    )
    return tuple(r[0])


async def _so_thong_bao():
    """Tổng dòng thông báo (hàng đợi + thông báo + lần gửi) — đọc từ kết nối mới."""
    return tuple(
        [await qd._q1("SELECT count(*) FROM %s" % bang) for bang in ("notification_outbox", "notification", "notification_delivery")]
    )


async def _so_lan_rut(pid):
    return await qd._q1(
        "SELECT count(*) FROM admission_profile_status_history WHERE profile_id = :p AND to_status = 'withdrawn'", p=pid
    )


async def _rut_khi_khoa_nam_ban(client, gia_tri, so_cccd):  # noqa: F811
    """Phiên cấu hình giữ khoá năm 2026 ĐỘC QUYỀN; gửi yêu cầu rút qua thư. Trả (phản hồi, giây, pid bị chặn bởi phiên cấu hình,
    xong trước khi nhả)."""
    async with PhienCauHinh() as c:
        await c.khoa_nam(2026)
        bd = time.monotonic()
        t = asyncio.create_task(_rut_qua_thu(client, gia_tri, so_cccd))
        pid_t = await cho_bi_chan_boi(c.pid, t, giay=TRAN_409_GIAY)
        xong_truoc = t.done()
        giay = time.monotonic() - bd
        await c.tha()
        r = await t
    return r, giay, pid_t, xong_truoc


async def test_f14a_rut_qua_thu_khi_cau_hinh_giu_khoa_nam_tra_409_ngay_khong_tieu_thu_lien_ket(client, hs):  # noqa: F811
    gia_tri, so_cccd, id_ = await _lien_ket_rut(hs)
    pid = hs[E][1]
    lien_ket_truoc, thong_bao_truoc = await _trang_thai_lien_ket(id_), await _so_thong_bao()
    r, giay, pid_t, xong_truoc = await _rut_khi_khoa_nam_ban(client, gia_tri, so_cccd)
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == mls.WITHDRAW_CONFIG_BUSY_MESSAGE, r.text  # câu owner nguyên văn
    # kiểm từ phiên mới
    assert (await _ban(pid))[0] == "admitted", "hồ sơ phải giữ nguyên trạng thái"
    assert await _trang_thai_lien_ket(id_) == lien_ket_truoc, "liên kết phải giữ nguyên (chưa dùng, không trừ lượt, không đổi hạn)"
    assert await _so_thong_bao() == thong_bao_truoc, "lần 409 KHÔNG được gửi / xếp hàng thông báo"
    assert await _so_lan_rut(pid) == 0, "lần 409 KHÔNG ghi nhận rút"
    # phép đo: trả NGAY, không chờ phiên cấu hình
    assert xong_truoc and pid_t is None and giay < TRAN_409_GIAY, (
        "phép đo: rút qua thư KHÔNG được chờ khoá năm — xong trước khi nhả: %s, %.2f s, bị chặn bởi: %r" % (xong_truoc, giay, pid_t)
    )


async def test_f14b_nha_khoa_thi_chinh_lien_ket_rut_dung_mot_lan_lan_ba_bi_tu_choi(client, hs):  # noqa: F811
    gia_tri, so_cccd, id_ = await _lien_ket_rut(hs)
    pid = hs[E][1]
    r1, _, _, _ = await _rut_khi_khoa_nam_ban(client, gia_tri, so_cccd)
    assert r1.status_code == 409, r1.text
    assert (await _trang_thai_lien_ket(id_))[0] is None, "lần 409 không được đánh dấu liên kết đã dùng"
    r2 = await _rut_qua_thu(client, gia_tri, so_cccd)  # khoá đã nhả — CHÍNH liên kết ấy, còn hạn
    assert r2.status_code == 200, r2.text
    assert (await _ban(pid))[0] == "withdrawn"
    assert (await _trang_thai_lien_ket(id_))[0] is not None, "lần thành công đánh dấu liên kết đã dùng"
    assert await _so_lan_rut(pid) == 1, "rút thành công ĐÚNG MỘT lần"
    r3 = await _rut_qua_thu(client, gia_tri, so_cccd)
    assert r3.status_code == 400 and "already been used" in r3.text, r3.text  # luật hiện hành của liên kết đã dùng
    assert await _so_lan_rut(pid) == 1
