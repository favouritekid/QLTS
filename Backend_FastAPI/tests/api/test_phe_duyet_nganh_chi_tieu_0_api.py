# -*- coding: utf-8 -*-
"""N4 — ngành chỉ tiêu năm 0 ĐÓNG TUYỆT ĐỐI với nút "Phê duyệt" cũ (đơn + lô), kể cả Admin xin vượt.

Nguồn luật: ``logs-P5/cong-bo-ket-qua/gd2/QUYET-DINH-OWNER-H1-VA-N4-2026-11-20.md`` (owner 20-11, THẮNG hai bản phân tích N4)
+ vị trí chốt theo ``PHAN-TICH-N4-BO-SUNG-CODEX-2026-11-20.md`` (ngay sau nhánh chỉ tiêu trống, TRƯỚC khi cần
``lead.offering_id``). Tầng chủ sở hữu: ``admission_service._assert_quota_or_bypass`` (mọi lối Phê duyệt cũ đi qua);
vị từ "ngành đóng" MỘT nguồn: ``quota_occupancy_service.is_offering_closed``.

Mọi ca đi qua REQUEST THẬT (route đơn ``/approve``, route lô ``/bulk/approve``, ``/finalize``); kết cục đo bằng SQL ở KẾT
NỐI KHÁC (``qd._q`` / ``_ban`` / ``_da_dung`` mở phiên mới) — vết từ chối phải còn sau khi giao dịch Phê duyệt lùi. Mỗi ca
MỘT bất biến; ca đối chứng chỉ khác đúng điều kiện được canh.

* N4-2 — Admin xin vượt ở ngành 0 bị chặn (đơn, lô); câu hướng dẫn theo bảng chỉ tiêu năm (đã khoá / chưa khoá).
* N4-3 — hồ sơ ĐÃ được tính chỗ nhờ Quyết định hiệu lực vẫn bị chặn khi bấm Phê duyệt.
* Codex — hồ sơ có ``applied_rules.academic_info_id`` trỏ ngành 0 nhưng ``lead.offering_id`` đã mất vẫn bị chặn.
* N4-6 — Quản lý xin vượt ở ngành 0 ⇒ 400 (không còn 403); ngành chỉ tiêu dương vẫn 403; lô giữ HTTP 200 + lý do từng hồ sơ.
* N4-7 — Admin xin vượt bị chặn ⇒ ĐÚNG MỘT vết ``quota_bypass_denied_closed``; Phê duyệt thường ⇒ 0 vết xin vượt; ghi /
  commit vết hỏng ⇒ lỗi kỹ thuật (đơn 503, lô: mục báo lỗi kỹ thuật), hồ sơ giữ nguyên, không vết dở (Codex 22-11 lượt 2).
* N4-1 — ``/finalize`` giữ luật cũ: em đã chiếm chỗ hoàn tất nhập học, số chỗ đã dùng giữ nguyên; cơ chế Admin xin vượt cũ
  còn; cùng ngành ấy, hồ sơ MỚI xin Phê duyệt vẫn bị chặn.
* Đối chứng "trống ≠ 0" và "N4 không lan sang chỉ tiêu dương".

N4-4 (ghi nhận Quyết định vào ngành 0 chỉ cảnh báo) KHÔNG đổi mã — canh bởi
``test_council_decision_canh_bao_chi_tieu_api.py::test_n9_vuot_chi_tieu_nganh_va_duong_xet_van_ghi_kem_canh_bao`` (Tier 5g).
"""
import pytest

from app import models
from app.database import AsyncSessionLocal
from app.services import quota_occupancy_service as qos
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_bulk_ngu_canh_chi_tieu_api import _nganh_khac
from tests.api.test_council_decision_hai_phien_api import (
    _da_dung,
    _dam_bao_sts09,
    _nop,
    _o_chi_tieu,
)
from tests.api.test_council_decision_khoa_cheo_api import _gan_nganh
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    A,
    SACH,
    _ban,
    _co_qd,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

NAM = 2026
#: Lý do xin vượt hợp lệ (≥ 20 ký tự — lược đồ chặn lý do ngắn bằng 422 trước khi tới dịch vụ).
LY_DO_XIN_VUOT = "GIA Hiệu trưởng cho nhận thêm một em vào ngành đã đóng"
CAU_DONG = "Ngành đã đóng tuyển (chỉ tiêu 0)"


def _cau_mong_doi(bang_da_khoa):
    """Câu báo NGUYÊN VĂN (owner 20-11: N4-6 lý do; N4-2 hướng dẫn theo bảng chỉ tiêu năm). Viết tay ở đây — KHÔNG lấy
    hằng của dịch vụ — để test khoá chữ đã chốt."""
    if bang_da_khoa:
        huong_dan = (
            "Bảng chỉ tiêu năm %d đã khoá: muốn nhận thêm, Admin mở khoá bảng có ghi lý do, đặt chỉ tiêu ngành > 0, "
            "rồi khoá lại." % NAM
        )
    else:
        huong_dan = (
            "Bảng chỉ tiêu năm %d chưa khoá: muốn nhận thêm, Admin đặt lại chỉ tiêu ngành > 0 rồi khoá bảng." % NAM
        )
    return CAU_DONG + " — chặn Phê duyệt, kể cả khi Admin ghi lý do xin vượt chỉ tiêu. " + huong_dan


# ── công cụ ─────────────────────────────────────────────────────────────────────────────────────────────────────
async def _chi_tieu(o):
    return await qd._q1("SELECT annual_admission_quota FROM offering_academic_info WHERE id = :a", a=o["ai"])


async def _ho_so_nganh(hs, chi_tieu, nhan=SACH[0]):
    """Hồ sơ ``nhan`` "Đã nộp", lead → ngành của ô K (NV1 của ``SACH[0]``), chỉ tiêu năm của K = ``chi_tieu`` (None = trống).
    ``applied_rules`` của dữ liệu giả rỗng ⇒ ngữ cảnh chỉ tiêu dò theo ``lead.offering_id`` + năm. Trả (id hồ sơ, ô K)."""
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=chi_tieu)
    pid = hs[nhan][1]
    await _nop(pid)
    await _gan_nganh(pid, o["off"])
    assert await _chi_tieu(o) == chi_tieu, "tiền điều kiện: chỉ tiêu ô K chưa đặt được"
    assert (await _ban(pid))[0] == "submitted"
    return pid, o


async def _chiem_cho(pid, o, trang_thai="approved"):
    """Hồ sơ ``pid`` CHIẾM một chỗ ở ô K (trạng thái chiếm chỗ, lead → ngành của K) — dữ liệu giả, SQL."""
    await qd._sql("UPDATE admission_profile SET status = :s WHERE id = :p", s=trang_thai, p=pid)
    await _gan_nganh(pid, o["off"])


def _duyet(client, h, pid, ver, xin_vuot=False):
    body = {"version": ver}
    if xin_vuot:
        body.update(bypass_quota=True, bypass_reason=LY_DO_XIN_VUOT)
    return client.post(A + "/%d/approve" % pid, json=body, headers=h)


def _duyet_lo(client, h, *muc):
    """``muc`` = (id hồ sơ, version, xin_vuot) — mỗi mục mang cặp xin vượt RIÊNG (``BulkApproveItem``)."""
    items = []
    for pid, ver, xin_vuot in muc:
        item = {"profile_id": pid, "version": ver}
        if xin_vuot:
            item.update(bypass_quota=True, bypass_reason=LY_DO_XIN_VUOT)
        items.append(item)
    return client.post(A + "/bulk/approve", json={"items": items}, headers=h)


async def _vet_xin_vuot(pid):
    """Mọi vết liên quan xin vượt chỉ tiêu của hồ sơ (thành công lẫn bị từ chối), đọc ở KẾT NỐI KHÁC: [(action, người)]."""
    return [
        tuple(r)
        for r in await qd._q(
            "SELECT action, actor_user_id FROM entity_audit_log WHERE entity_type = 'AdmissionProfile' "
            "AND entity_id = :p AND action LIKE 'quota_bypass%' ORDER BY id",
            p=pid,
        )
    ]


async def _id_nguoi(ten):
    return await qd._q1('SELECT id FROM "user" WHERE username = :u', u="gia_e2_" + ten)


async def _dam_bao_sts11():
    """Trạng thái tư vấn đích của "Đã nhập học" (``sync_lead_from_admission``: enrolled → sts11) — seed Hội đồng không có;
    id + giai đoạn chép từ ``conftest.seed_lead_dependencies``."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            if await s.get(models.PipelineStage, "stg06") is None:
                s.add(models.PipelineStage(id="stg06", name="Da nhap hoc", order=1006, is_final_stage=True))
                await s.flush()
            if await s.get(models.ConsultationStatus, "sts11") is None:
                s.add(
                    models.ConsultationStatus(id="sts11", name="Da nhap hoc", color_code="#006600", stage_id="stg06")
                )


# ═══════════════════════════════ N4-2 — Admin xin vượt ở ngành 0 bị chặn ═══════════════════════════════════════
async def test_n4_2_admin_xin_vuot_nganh_0_bi_chan_don(client, hs, ad):  # noqa: F811
    await _dam_bao_sts09()  # thiếu chốt ⇒ Phê duyệt đi tới 200 thật (không dừng ở đồng bộ lead)
    pid, _ = await _ho_so_nganh(hs, 0)
    r = await _duyet(client, ad, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    assert (await _ban(pid))[0] == "submitted"


async def test_n4_2_admin_xin_vuot_nganh_0_bi_chan_lo(client, hs, ad):  # noqa: F811
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, 0)
    r = await _duyet_lo(client, ad, (pid, (await _ban(pid))[1], True))
    assert r.status_code == 200, r.text
    kq = r.json()
    assert (kq["success_count"], kq["failed_ids"]) == (0, [pid]), kq
    assert kq["errors"][str(pid)].startswith(CAU_DONG), kq
    assert (await _ban(pid))[0] == "submitted"


@pytest.mark.parametrize("bang", ["da_khoa", "nhap", "chua_co"])
async def test_n4_2_cau_bao_theo_bang_chi_tieu_nam(client, hs, ad, bang):  # noqa: F811
    # Đã khoá ⇒ hướng dẫn mở khoá có lý do, đặt > 0, khoá lại. Nháp / năm chưa có bảng ⇒ đặt lại chỉ tiêu, khoá bảng (KHÔNG
    # bảo mở một bảng chưa khoá). Chỉ tiêu đặt TRƯỚC khi khoá bảng (trigger luật B chặn sửa chỉ tiêu năm đã khoá).
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, 0)
    if bang == "da_khoa":
        await qd._sql(
            "INSERT INTO admission_quota_table (academic_year, status, locked_by_user_id, locked_at) "
            "VALUES (:n, 'locked', :u, now())",
            n=NAM,
            u=await _id_nguoi("admin"),
        )
    elif bang == "nhap":
        await qd._sql("INSERT INTO admission_quota_table (academic_year, status) VALUES (:n, 'draft')", n=NAM)
    trang_thai_bang = await qd._q("SELECT status FROM admission_quota_table WHERE academic_year = :n", n=NAM)
    assert [r[0] for r in trang_thai_bang] == {"da_khoa": ["locked"], "nhap": ["draft"], "chua_co": []}[bang]
    r = await _duyet(client, ad, pid, (await _ban(pid))[1])
    assert r.status_code == 400 and r.json()["detail"] == _cau_mong_doi(bang == "da_khoa"), r.text


# ═══════════════════════════════ N4-3 — đã được tính chỗ vẫn bị chặn ═══════════════════════════════════════════
async def test_n4_3_ho_so_da_tinh_cho_nho_quyet_dinh_van_bi_chan(client, hs, ad):  # noqa: F811
    # Em có Quyết định hiệu lực (Phần B) — được đếm là đã chiếm chỗ; là người DUY NHẤT của ô K. Luật cũ: không cộng thêm
    # chỗ ⇒ 0 + 0 ≤ 0 ⇒ CHO QUA. Owner N4-3: Phê duyệt vào ngành 0 VẪN chặn, kể cả hồ sơ đã được tính chỗ.
    await _dam_bao_sts09()
    pid = await _co_qd(client, ad, hs, SACH[0], trang_thai="submitted")
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=0)
    await _gan_nganh(pid, o["off"])
    async with AsyncSessionLocal() as db:
        assert await qos.has_effective_row(db, pid), "tiền điều kiện: em phải có Quyết định hiệu lực"
    assert await _da_dung(o) == 1, "tiền điều kiện: em là người duy nhất chiếm chỗ ô K"
    r = await _duyet(client, ad, pid, (await _ban(pid))[1])
    assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    assert (await _ban(pid))[0] == "submitted" and await _da_dung(o) == 1


# ═══════════════════════════════ Codex — mất lead.offering_id vẫn bị chặn ═══════════════════════════════════════
@pytest.mark.parametrize("duong, xin_vuot", [("don", False), ("lo", False), ("don", True)])
async def test_n4_codex_mat_nganh_o_lead_van_bi_chan(client, hs, ad, duong, xin_vuot):  # noqa: F811
    # Ảnh chụp luật trỏ thẳng học vụ chỉ tiêu 0; ``lead.offering_id`` = NULL ⇒ phép đếm của luật cũ "bỏ qua" (return sớm).
    # Chốt đặt sau phép đếm sẽ lọt; chốt đúng chỗ (ngay sau nhánh chỉ tiêu trống) chặn mọi lối.
    await _dam_bao_sts09()
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=0)
    pid = hs[SACH[0]][1]
    await _nop(pid)
    await qd._sql(
        "UPDATE admission_profile SET applied_rules = jsonb_build_object('academic_info_id', CAST(:a AS integer)) "
        "WHERE id = :p",
        a=o["ai"],
        p=pid,
    )
    await qd._sql(
        "UPDATE lead SET offering_id = NULL WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)", p=pid
    )
    assert await qd._q1(
        "SELECT l.offering_id IS NULL AND (p.applied_rules ->> 'academic_info_id')::int = :a "
        "FROM admission_profile p JOIN lead l ON l.id = p.lead_id WHERE p.id = :p",
        a=o["ai"],
        p=pid,
    ), "tiền điều kiện: ảnh chụp trỏ ô K, lead mất ngành"
    ver = (await _ban(pid))[1]
    if duong == "don":
        r = await _duyet(client, ad, pid, ver, xin_vuot=xin_vuot)
        assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    else:
        r = await _duyet_lo(client, ad, (pid, ver, xin_vuot))
        assert r.status_code == 200, r.text
        assert r.json()["failed_ids"] == [pid] and r.json()["errors"][str(pid)].startswith(CAU_DONG), r.text
    assert (await _ban(pid))[0] == "submitted"


# ═══════════════════════════════ N4-6 — mã lỗi theo đúng ca ngành 0 ═══════════════════════════════════════════
async def test_n4_6_quan_ly_xin_vuot_nganh_0_tra_400(client, hs, ad, tk):  # noqa: F811
    # Trước N4: Quản lý xin vượt ⇒ 403 "Chỉ Admin được phép ghi đè…". Owner N4-6: ngành 0 ⇒ 400, lý do ngành đóng.
    await _dam_bao_sts09()
    ql = await tk("ql_u1")
    pid, _ = await _ho_so_nganh(hs, 0)
    r = await _duyet(client, ql, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    assert (await _ban(pid))[0] == "submitted"


async def test_n4_6_quan_ly_xin_vuot_nganh_duong_van_403(client, hs, ad, tk):  # noqa: F811
    # Đối chứng: ngành chỉ tiêu 1 đã đầy (em khác chiếm chỗ) ⇒ Quản lý xin vượt VẪN 403 như cũ (N4 không lan sang > 0).
    await _dam_bao_sts09()
    ql = await tk("ql_u1")
    pid, o = await _ho_so_nganh(hs, 1)
    await _chiem_cho(hs[SACH[2]][1], o)
    assert await _da_dung(o) == 1, "tiền điều kiện: ô K đã đầy"
    r = await _duyet(client, ql, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 403, r.text
    assert (await _ban(pid))[0] == "submitted"


async def test_n4_6_lo_tra_200_ly_do_tung_ho_so(client, hs, ad):  # noqa: F811
    # Lô hai mục: p ở ngành 0, q ở ngành khác còn chỗ ⇒ HTTP 200 (hợp đồng lô), p bị chặn với ĐÚNG câu ngành đóng, q vẫn duyệt.
    await _dam_bao_sts09()
    p, o = await _ho_so_nganh(hs, 0)
    q = hs[SACH[2]][1]
    off2, ai2 = await _nganh_khac(o["off"])
    await qd._sql("UPDATE offering_academic_info SET annual_admission_quota = 5 WHERE id = :a", a=ai2)
    await _nop(q)
    await _gan_nganh(q, off2)
    r = await _duyet_lo(client, ad, (p, (await _ban(p))[1], False), (q, (await _ban(q))[1], False))
    assert r.status_code == 200, r.text
    kq = r.json()
    assert (kq["success_count"], kq["failed_ids"]) == (1, [p]), kq
    assert kq["errors"][str(p)] == _cau_mong_doi(False), kq
    assert ((await _ban(p))[0], (await _ban(q))[0]) == ("submitted", "approved")


# ═══════════════════════════════ N4-7 — vết lần xin vượt bị chặn ═══════════════════════════════════════════════
async def test_n4_7_admin_xin_vuot_bi_chan_ghi_dung_mot_vet(client, hs, ad):  # noqa: F811
    # Giao dịch Phê duyệt LÙI (400) — vết phải ở phiên riêng; đọc ở kết nối khác thấy ĐÚNG MỘT vết, đúng mã, đúng người.
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, 0)
    r = await _duyet(client, ad, pid, (await _ban(pid))[1], xin_vuot=True)
    # Codex 22-11 lượt 2 (A-P3 c): lỗi NGHIỆP VỤ đúng mã — không phải lỗi kỹ thuật cùng mã HTTP.
    assert r.status_code == 400 and r.json()["error_code"] == "BUSINESS_RULE_VIOLATION", r.text
    assert await _vet_xin_vuot(pid) == [("quota_bypass_denied_closed", await _id_nguoi("admin"))]
    assert (await _ban(pid))[0] == "submitted"


def _hong_vet(monkeypatch, kieu):
    """Làm HỎNG phiên ghi vết ``quota_bypass_denied_closed`` (chỉ vết ấy): ``kieu`` = "ghi" ⇒ lệnh ghi ném lỗi; "commit" ⇒
    ghi xong nhưng commit của PHIÊN VẾT ném lỗi (dòng đã thêm vào phiên mà không commit được). Chỉ trong test."""
    from app.services import audit_service

    goc = audit_service.log_audit

    async def boc(db, *a, **kw):
        if kw.get("action") != "quota_bypass_denied_closed":
            return await goc(db, *a, **kw)
        if kieu == "ghi":
            raise RuntimeError("GIA lỗi ghi vết (test)")
        kq = await goc(db, *a, **kw)

        async def commit_hong():
            raise RuntimeError("GIA lỗi commit vết (test)")

        db.commit = commit_hong
        return kq

    monkeypatch.setattr(audit_service, "log_audit", boc)


@pytest.mark.parametrize("loi", ["ghi", "commit"])
@pytest.mark.parametrize("duong", ["don", "lo"])
async def test_n4_7_loi_ghi_vet_bat_buoc_thi_bao_loi_ky_thuat_ho_so_giu_nguyen(  # noqa: F811
    client, hs, ad, monkeypatch, duong, loi
):
    # Codex 22-11 lượt 2 (A-P2 / A-P3 a): vết N4-7 BẮT BUỘC ⇒ ghi / commit vết hỏng thì KHÔNG trả lỗi nghiệp vụ "ngành đóng"
    # như thể vết đã có. Đơn: lỗi kỹ thuật (503 ``SERVICE_UNAVAILABLE``); lô: HTTP 200 theo hợp đồng lô, mục ấy báo lỗi kỹ thuật
    # (câu chung có sẵn của lô). Cả hai: hồ sơ giữ nguyên, không có vết dở (đọc từ phiên mới).
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, 0)
    ver = (await _ban(pid))[1]
    _hong_vet(monkeypatch, loi)
    if duong == "don":
        r = await _duyet(client, ad, pid, ver, xin_vuot=True)
        assert r.status_code == 503 and r.json()["error_code"] == "SERVICE_UNAVAILABLE", r.text
    else:
        r = await _duyet_lo(client, ad, (pid, ver, True))
        assert r.status_code == 200, r.text
        kq = r.json()
        assert kq["failed_ids"] == [pid] and kq["errors"][str(pid)].startswith("Unexpected error (ref:"), kq
    monkeypatch.undo()
    assert (await _ban(pid))[0] == "submitted"
    assert await _vet_xin_vuot(pid) == []


async def test_n4_7_phe_duyet_thuong_khong_ghi_vet_xin_vuot(client, hs, ad):  # noqa: F811
    # Bấm Phê duyệt THÔNG THƯỜNG (không xin vượt) ở ngành 0: vẫn báo ngành đóng nhưng KHÔNG ghi nhầm thành một lần xin vượt.
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, 0)
    r = await _duyet(client, ad, pid, (await _ban(pid))[1])
    assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    assert await _vet_xin_vuot(pid) == []


async def test_n4_7_lo_moi_muc_xin_vuot_mot_vet(client, hs, ad):  # noqa: F811
    # Lô, cùng ngành 0: p xin vượt ⇒ một vết; q không xin vượt ⇒ không vết. Cặp xin vượt lấy theo TỪNG mục.
    await _dam_bao_sts09()
    p, o = await _ho_so_nganh(hs, 0)
    q = hs[SACH[2]][1]
    await _nop(q)
    await _gan_nganh(q, o["off"])
    r = await _duyet_lo(client, ad, (p, (await _ban(p))[1], True), (q, (await _ban(q))[1], False))
    assert r.status_code == 200 and sorted(r.json()["failed_ids"]) == sorted([p, q]), r.text
    admin = await _id_nguoi("admin")
    assert (await _vet_xin_vuot(p), await _vet_xin_vuot(q)) == ([("quota_bypass_denied_closed", admin)], [])


async def test_n4_7_quan_ly_xin_vuot_nganh_0_ghi_mot_vet(client, hs, ad, tk):  # noqa: F811
    # Giữ hợp đồng sẵn có "mọi lần xin vượt bị từ chối đều để lại vết" (trước N4 ca này ghi ``quota_bypass_denied_role``):
    # nay ngành đóng chặn TRƯỚC kiểm vai ⇒ một vết ``quota_bypass_denied_closed``. [Chờ owner xác nhận — câu hỏi Q2 pha 1.]
    await _dam_bao_sts09()
    ql = await tk("ql_u1")
    pid, _ = await _ho_so_nganh(hs, 0)
    r = await _duyet(client, ql, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 400, r.text
    assert await _vet_xin_vuot(pid) == [("quota_bypass_denied_closed", await _id_nguoi("ql_u1"))]


# ═══════════════════════════════ N4-1 — /finalize giữ luật cũ ═══════════════════════════════════════════════════
async def test_n4_1_hoan_tat_nhap_hoc_em_duy_nhat_giu_luat_cu(client, hs, ad):  # noqa: F811
    # Em đã được nhận (chiếm chỗ) rồi ngành mới đóng: hoàn tất nhập học theo luật cũ, số chỗ đã dùng 1 → 1 (owner N4-1, N4-3).
    await _dam_bao_sts11()
    pid, o = await _ho_so_nganh(hs, 0)
    await _chiem_cho(pid, o, trang_thai="confirmed")
    assert await _da_dung(o) == 1, "tiền điều kiện: em là người duy nhất chiếm chỗ ô K"
    r = await client.post(A + "/%d/finalize" % pid, json={"version": (await _ban(pid))[1]}, headers=ad)
    assert r.status_code == 200, r.text
    assert ((await _ban(pid))[0], await _da_dung(o)) == ("enrolled", 1)


async def test_n4_1_hoan_tat_nhap_hoc_admin_xin_vuot_theo_co_che_cu(client, hs, ad):  # noqa: F811
    # Ngành 0 có HAI em chiếm chỗ ⇒ hoàn tất cho một em là "vượt" theo luật cũ; Admin ghi lý do xin vượt VẪN qua (cơ chế hiện
    # hành giữ cho /finalize — owner N4-1), có vết ``quota_bypassed``; số chỗ đã dùng 2 → 2.
    await _dam_bao_sts11()
    pid, o = await _ho_so_nganh(hs, 0)
    await _chiem_cho(pid, o, trang_thai="confirmed")
    await _chiem_cho(hs[SACH[2]][1], o)
    assert await _da_dung(o) == 2, "tiền điều kiện: hai em chiếm chỗ ô K"
    r = await client.post(
        A + "/%d/finalize" % pid,
        json={"version": (await _ban(pid))[1], "bypass_quota": True, "bypass_reason": LY_DO_XIN_VUOT},
        headers=ad,
    )
    assert r.status_code == 200, r.text
    assert ((await _ban(pid))[0], await _da_dung(o)) == ("enrolled", 2)
    assert await _vet_xin_vuot(pid) == [("quota_bypassed", await _id_nguoi("admin"))]


async def test_n4_1_cung_nganh_da_dong_ho_so_moi_xin_vuot_bi_chan(client, hs, ad):  # noqa: F811
    # Cùng ngành đã đóng có một em đã chiếm chỗ: hồ sơ MỚI, Admin xin vượt ⇒ bị chặn (owner N4-1 "test thêm"). Ca này khác
    # N4-2 đơn ở chỗ ngành CÓ người dùng chỗ (chốt không được phụ thuộc "chưa ai dùng").
    await _dam_bao_sts09()
    pid, o = await _ho_so_nganh(hs, 0)
    await _chiem_cho(hs[SACH[2]][1], o, trang_thai="confirmed")
    assert await _da_dung(o) == 1, "tiền điều kiện: ô K đã có một em chiếm chỗ"
    r = await _duyet(client, ad, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    assert (await _ban(pid))[0] == "submitted" and await _da_dung(o) == 1


# ═══════════════════════════════ đối chứng / ca biên ═════════════════════════════════════════════════════════════
async def test_n4_chi_tieu_trong_van_khong_gioi_han(client, hs, ad):  # noqa: F811
    # Trống ≠ 0: chỉ tiêu NULL ⇒ nút cũ vẫn hiểu là không giới hạn (owner giữ) — Phê duyệt thường qua.
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, None)
    r = await _duyet(client, ad, pid, (await _ban(pid))[1])
    assert r.status_code == 200, r.text
    assert (await _ban(pid))[0] == "approved"


async def test_n4_doi_chung_admin_xin_vuot_nganh_duong_van_qua(client, hs, ad):  # noqa: F811
    # N4 không lan sang chỉ tiêu dương: ngành 1 đã đầy, Admin ghi lý do xin vượt ⇒ vẫn duyệt được, có vết ``quota_bypassed``.
    await _dam_bao_sts09()
    pid, o = await _ho_so_nganh(hs, 1)
    await _chiem_cho(hs[SACH[2]][1], o)
    assert await _da_dung(o) == 1, "tiền điều kiện: ô K đã đầy"
    r = await _duyet(client, ad, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 200, r.text
    assert (await _ban(pid))[0] == "approved"
    assert await _vet_xin_vuot(pid) == [("quota_bypassed", await _id_nguoi("admin"))]


async def test_n4_chi_tieu_am_coi_nhu_dong(client, hs, ad):  # noqa: F811
    # Chỉ tiêu âm chỉ có qua SQL tay (cột không có CHECK ≥ 0). Coi như ngành đóng: Admin xin vượt vẫn bị chặn.
    # [Chờ owner xác nhận — câu hỏi Q3 pha 1.]
    await _dam_bao_sts09()
    pid, _ = await _ho_so_nganh(hs, -1)
    r = await _duyet(client, ad, pid, (await _ban(pid))[1], xin_vuot=True)
    assert r.status_code == 400 and r.json()["detail"].startswith(CAU_DONG), r.text
    assert (await _ban(pid))[0] == "submitted"
