# -*- coding: utf-8 -*-
"""F259 (Codex lần 15) — vòng chờ khoá giữa GHI NHẬN Quyết định và PHÊ DUYỆT HÀNG LOẠT / CÔNG BỐ NHIỀU NGUYỆN
VỌNG; phản hồi + callback phải khớp trạng thái ĐÃ COMMIT khi một bên bị PostgreSQL chọn huỷ (40P01).

Thứ tự khoá chuẩn (``quota_occupancy_service.khoa_o_chi_tieu``): mọi hồ sơ (id tăng dần) → mọi
``offering_academic_info`` (id tăng dần) → mọi ``admission_path`` (id tăng dần). Ghi nhận đi đúng thứ tự ấy;
trước lượt K, Phê duyệt hàng loạt khoá XEN KẼ hồ sơ ↔ chỉ tiêu (P1 → Q → P2) và công bố khoá chỉ tiêu theo
THỨ TỰ NGUYỆN VỌNG (Q lớn → Q nhỏ) ⇒ vòng chờ với ghi nhận.

Cách ép lịch: ĐIỂM ĐỒNG BỘ (bọc một hàm của phiên thứ nhất bằng ``monkeypatch`` — tới đó phiên DỪNG, GIỮ khoá) +
chờ PostgreSQL báo phiên thứ hai bị chặn (``pg_blocking_pids``). Chọn bên bị huỷ bằng ``SET LOCAL
deadlock_timeout`` (người dùng CSDL test là superuser): PostgreSQL chỉ kiểm vòng chờ một lần khi hết
``deadlock_timeout`` kể từ lúc phiên ấy bắt đầu chờ ⇒ phiên có trần ngắn nhất SAU khi vòng hình thành bị huỷ.

* ``test_hang_loat_va_ghi_nhan_khong_con_vong_cho[<bên bị huỷ>]`` — lịch Codex nêu: lô giữ P1 + Q, ghi nhận giữ P2
  chờ Q, lô đi tiếp chờ P2. Mã cũ: vòng chờ (bên được chọn bị huỷ). Mã mới: lô khoá TRƯỚC P1, P2, Q ⇒ ghi nhận chờ
  ngay ở P2 ⇒ không vòng; cả hai bên trần ngắn / dài đều xong, số thành công + callback = trạng thái commit.
* ``test_cong_bo_nhieu_nv_va_ghi_nhan_khong_con_vong_cho[<bên bị huỷ>]`` — NV1 ở ô id LỚN (Y), NV2 ở ô id NHỎ
  (X); ghi nhận khoá X rồi Y. Mã cũ: công bố giữ Y chờ X, ghi nhận giữ X chờ Y. Mã mới: công bố khoá TRƯỚC X, Y.
* ``test_hang_loat_bi_huy_giua_lo_chi_lui_muc_ay`` — lô thật sự bị chọn huỷ (vòng chờ với một phiên thứ ba qua
  dòng lead): SAVEPOINT từng mục ⇒ chỉ mục ấy hỏng (câu "thử lại"), mục khác commit, callback chỉ cho mục commit.
* ``test_cong_bo_bi_huy_tra_409_khong_ghi_gi`` / ``test_ghi_nhan_bi_huy_tra_409_khong_ghi_gi`` — bên bị chọn huỷ
  trả 409 rõ ràng (không 500), không ghi gì, không callback.
"""
import asyncio

import pytest
from sqlalchemy import text

import app.database as csdl
from app.database import AsyncSessionLocal
from app.repositories.council_decision_repository import CouncilDecisionRepository
from app.services import admission_choice_engine_service as eng
from app.services import admission_service as asv
from app.services import quota_occupancy_service as qos
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_hai_phien_api import (  # noqa: F401 — fixture
    _Diem,
    _ban,
    _cau_hinh_trinh_do,
    _cho_bi_chan_hoac_xong,
    _cong_bo,
    _dam_bao_sts09,
    _nop,
    _o_chi_tieu,
    _so_qd,
)
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    A,
    SACH,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration

NGAN, DAI = 200, 30000  # deadlock_timeout (ms): bên muốn bị huỷ / bên còn lại
NGAN_CHO_TRUOC = 3000  # bên bắt đầu chờ TRƯỚC khi vòng hình thành: hết trần SAU lúc vòng hình thành


async def _dat_tran(db, ms):
    await db.execute(text("SET LOCAL deadlock_timeout = '%dms'" % int(ms)))


def _boc_ghi_nhan_tran(monkeypatch, ms):
    """Phiên ghi nhận đặt ``deadlock_timeout`` ngay ở khoá đầu tiên (khoá bộ) — trước mọi lần chờ."""
    goc = CouncilDecisionRepository.khoa_bo

    async def boc(self, set_id):
        await _dat_tran(self.db, ms)
        return await goc(self, set_id)

    monkeypatch.setattr(CouncilDecisionRepository, "khoa_bo", boc)


def _boc_dung(monkeypatch, chu, ten, diem, ms):
    """Bọc ``chu.ten`` (hàm nhận ``db`` ở đối số đầu): chạy gốc, đặt trần cho phiên ấy, rồi DỪNG ở ``diem`` (lần
    đầu) — mọi khoá đã lấy giữ tới khi phiên commit."""
    goc = getattr(chu, ten)

    async def boc(*a, **kw):
        kq = await goc(*a, **kw)
        db = a[0] if a else kw["db"]
        if diem.so_lan == 0:
            await _dat_tran(db, ms)
        await diem.cho()
        return kq

    monkeypatch.setattr(chu, ten, boc)


def _theo_doi_hoa_hong(monkeypatch):
    """Callback hoa hồng của mỗi mục hàng loạt chạy SAU commit — ghi lead_id của mục mà callback THẬT SỰ chạy."""
    da_chay = []

    async def gia(db, lead_id, old, new, actor_id):
        da_chay.append(lead_id)

    monkeypatch.setattr(asv, "safe_check_commission_on_status_change", gia)
    return da_chay


async def _lead(pid):
    return await qd._q1("SELECT lead_id FROM admission_profile WHERE id = :p", p=pid)


async def _gan_nganh(pid, off):
    await qd._sql(
        "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        o=off,
        p=pid,
    )


async def _hai_em_da_nop_cung_o(hs, chi_tieu=10):
    """P1 < P2 (id), cùng ô chỉ tiêu Q (lead → ngành của Q, chỉ tiêu năm đặt sẵn), cả hai "Đã nộp"."""
    o = await _o_chi_tieu(hs, SACH[0], chi_tieu=chi_tieu)
    p1, p2 = hs[SACH[0]][1], hs[SACH[2]][1]
    assert p1 < p2
    for p in (p1, p2):
        await _nop(p)
        await _gan_nganh(p, o["off"])
    return o, p1, p2


def _duyet_hang_loat(client, ad, *pids_ver):
    return client.post(
        A + "/bulk/approve",
        json={"items": [{"profile_id": p, "version": v} for p, v in pids_ver]},
        headers=ad,
    )


async def _nguyen_vong(pid):
    return [
        tuple(r)
        for r in await qd._q(
            "SELECT id, decision, eligibility_check_result::text FROM admission_profile_choice "
            "WHERE admission_profile_id = :p ORDER BY id",
            p=pid,
        )
    ]


async def _da_duyet(*pids):
    return {p for p in pids if (await _ban(p))[0] == "approved"}


# ═══════════════════════════════ (a) Phê duyệt hàng loạt ↔ ghi nhận ════════════════════════════
@pytest.mark.parametrize("bi_huy", ["ghi_nhan", "hang_loat"])
async def test_hang_loat_va_ghi_nhan_khong_con_vong_cho(client, hs, ad, monkeypatch, bi_huy):  # noqa: F811
    await _dam_bao_sts09()
    o, p1, p2 = await _hai_em_da_nop_cung_o(hs)
    bo = await qd._bo_ok(client, ad, hs, [SACH[2]], xac_nhan_trang_thai={"submitted": 1})
    v1, v2 = (await _ban(p1))[1], (await _ban(p2))[1]
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)
    tran_gn, tran_lo = (NGAN_CHO_TRUOC, DAI) if bi_huy == "ghi_nhan" else (DAI, NGAN)
    _boc_ghi_nhan_tran(monkeypatch, tran_gn)
    diem = _Diem()
    _boc_dung(monkeypatch, asv, "_assert_quota_or_bypass", diem, tran_lo)  # dừng sau chỉ tiêu của P1
    t_lo = asyncio.create_task(_duyet_hang_loat(client, ad, (p1, v1), (p2, v2)))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    do = await _cho_bi_chan_hoac_xong(t_qd)
    diem.di.set()
    r_lo, r_qd = await asyncio.gather(t_lo, t_qd)
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ khoá của lô"
    # Không còn vòng chờ: ghi nhận KHÔNG nhận câu "thử lại" của 40P01, lô không mất mục nào.
    assert r_qd.status_code == 409 and "xac_nhan_can" in r_qd.json(), r_qd.text
    assert r_lo.status_code == 200, r_lo.text
    kq = r_lo.json()
    da_duyet = await _da_duyet(p1, p2)  # đọc SAU commit, từ kết nối khác
    assert (kq["success_count"], kq["failed_ids"]) == (2, []), (kq, da_duyet)
    assert da_duyet == {p1, p2}
    assert sorted(hoa_hong) == sorted([await _lead(p1), await _lead(p2)])
    assert await _so_qd() == 0


async def _chuyen_sang_duoc_cd(hs, nhan):
    """Đưa nguyện vọng (một NV) của em ``nhan`` sang đường xét Dược CĐ chính quy (cùng tổ hợp g1) + ngành của học
    phí theo cùng ngành (cổng dựng bộ so ngành in với học phí). Trả (id đường xét, id học vụ) của ô Dược."""
    d = hs["_danh_muc"]
    py, psg_y = d["psg"][("duoc_cd", "cq", "g1")]
    pid = hs[nhan][1]
    await qd._sql(
        "UPDATE admission_profile_choice SET admission_path_id = :y, path_subject_group_config_id = :g "
        "WHERE admission_profile_id = :p",
        y=py,
        g=psg_y,
        p=pid,
    )
    await qd._sql(
        "UPDATE fee SET resolved_major_id = :m WHERE admission_profile_id = :p", m=d["mp"]["duoc_cd"], p=pid
    )
    return py, await qd._q1("SELECT academic_info_id FROM admission_path WHERE id = :p", p=py)


@pytest.mark.parametrize("bi_huy", ["ghi_nhan", "hang_loat"])
async def test_hang_loat_hai_o_khong_tang_dan_va_ghi_nhan_khong_con_vong_cho(  # noqa: F811
    client, hs, ad, monkeypatch, bi_huy
):
    """Lô P1 < P2 nhưng ô chỉ tiêu của P1 (Y) có id LỚN hơn ô của P2 (X); ghi nhận một bộ KHÁC hồ sơ (một em ở X,
    một em ở Y) ⇒ chỉ chung DÒNG CHỈ TIÊU. Không khoá trước dòng chỉ tiêu: lô giữ Y chờ X, ghi nhận giữ X chờ Y
    (khoá trước hồ sơ thôi KHÔNG đủ). Mã mới: lô khoá X, Y trước mục đầu ⇒ ghi nhận chờ ở X ⇒ không vòng."""
    await _dam_bao_sts09()
    x = await _o_chi_tieu(hs, SACH[0], chi_tieu=10)
    _, y_ai = await _chuyen_sang_duoc_cd(hs, "loai_hinh_lien_thong")
    assert x["ai"] < y_ai
    await qd._sql("UPDATE offering_academic_info SET annual_admission_quota = 10 WHERE id = :a", a=y_ai)
    y_off = await qd._q1("SELECT offering_id FROM offering_academic_info WHERE id = :a", a=y_ai)
    p1, p2 = hs[SACH[0]][1], hs[SACH[2]][1]
    assert p1 < p2
    for p, off in ((p1, y_off), (p2, x["off"])):
        await _nop(p)
        await _gan_nganh(p, off)
    bo = await qd._bo_ok(client, ad, hs, [SACH[1], "loai_hinh_lien_thong"])
    o_bo = await qd._q(
        "SELECT academic_info_id FROM council_document_set_row WHERE set_id = :s", s=bo["id"]
    )
    assert sorted(r[0] for r in o_bo) == [x["ai"], y_ai], "phép đo không hợp lệ: bộ phải chiếm X và Y"
    v1, v2 = (await _ban(p1))[1], (await _ban(p2))[1]
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)
    tran_gn, tran_lo = (NGAN_CHO_TRUOC, DAI) if bi_huy == "ghi_nhan" else (DAI, NGAN)
    _boc_ghi_nhan_tran(monkeypatch, tran_gn)
    diem = _Diem()
    _boc_dung(monkeypatch, asv, "_assert_quota_or_bypass", diem, tran_lo)  # dừng sau ô Y của P1
    t_lo = asyncio.create_task(_duyet_hang_loat(client, ad, (p1, v1), (p2, v2)))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=2))
    do = await _cho_bi_chan_hoac_xong(t_qd)
    diem.di.set()
    r_lo, r_qd = await asyncio.gather(t_lo, t_qd)
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ khoá của lô"
    assert r_qd.status_code == 201, r_qd.text
    assert r_lo.status_code == 200, r_lo.text
    kq = r_lo.json()
    da_duyet = await _da_duyet(p1, p2)
    assert (kq["success_count"], kq["failed_ids"]) == (2, []), (kq, da_duyet)
    assert da_duyet == {p1, p2}
    assert sorted(hoa_hong) == sorted([await _lead(p1), await _lead(p2)])
    assert await _so_qd() == 1


# ═══════════════════════════════ (b) công bố nhiều nguyện vọng ↔ ghi nhận ═══════════════════════
async def _cong_bo_nv1_o_lon_nv2_o_nho(hs, monkeypatch):
    """Em công bố A = ``SACH[1]`` (hai NV): NV1 ở ô Y (Dược CĐ — id học vụ LỚN), NV2 ở ô X (Ô tô CĐ — id NHỎ). Y
    chỉ tiêu năm 0 ⇒ NV1 "chờ" (khoá Y), NV2 chỉ tiêu 10 ⇒ trúng (khoá X). Bộ ghi nhận: em ở X + em ở Y."""
    monkeypatch.setattr(eng, "_evaluate_single_choice", lambda *a, **kw: ("admitted", None, []))
    await _cau_hinh_trinh_do()
    d = hs["_danh_muc"]
    a = hs[SACH[1]][1]
    x = await _o_chi_tieu(hs, SACH[0], chi_tieu=10)
    py, _ = d["psg"][("duoc_cd", "cq", "g1")]
    y_ai = await qd._q1("SELECT academic_info_id FROM admission_path WHERE id = :p", p=py)
    assert x["ai"] < y_ai, "phép đo không hợp lệ: ô Y phải có id học vụ LỚN hơn ô X"
    await qd._sql("UPDATE offering_academic_info SET annual_admission_quota = 0 WHERE id = :a", a=y_ai)
    # Đổi thứ tự hai NV của A: NV1 = Dược (Y), NV2 = Ô tô (X) — ba bước (UNIQUE + CHECK 1..10 kiểm từng dòng).
    for dk, gia_tri in (("admission_path_id = :y", 9), ("admission_path_id <> :y", 2), ("admission_path_id = :y", 1)):
        await qd._sql(
            "UPDATE admission_profile_choice SET display_order = %d WHERE admission_profile_id = :p AND %s"
            % (gia_tri, dk),
            y=py,
            p=a,
        )
    assert [
        tuple(r)
        for r in await qd._q(
            "SELECT display_order, admission_path_id = :y FROM admission_profile_choice "
            "WHERE admission_profile_id = :p ORDER BY display_order",
            y=py,
            p=a,
        )
    ] == [(1, True), (2, False)]
    # Em của bộ ở ô Y: chuyển nguyện vọng của ``SACH[2]`` sang đường xét Dược CĐ (cùng tổ hợp g1).
    await _chuyen_sang_duoc_cd(hs, SACH[2])
    await _nop(a)
    return a, x, {"ai": y_ai, "path": py}


@pytest.mark.parametrize("bi_huy", ["ghi_nhan", "cong_bo"])
async def test_cong_bo_nhieu_nv_va_ghi_nhan_khong_con_vong_cho(client, hs, ad, monkeypatch, bi_huy):  # noqa: F811
    a, x, y = await _cong_bo_nv1_o_lon_nv2_o_nho(hs, monkeypatch)
    bo = await qd._bo_ok(client, ad, hs, [SACH[0], SACH[2]])
    o_bo = await qd._q(
        "SELECT academic_info_id FROM council_document_set_row WHERE set_id = :s ORDER BY stt", s=bo["id"]
    )
    assert sorted(r[0] for r in o_bo) == [x["ai"], y["ai"]], "phép đo không hợp lệ: bộ phải chiếm X và Y"
    tran_gn, tran_cb = (NGAN_CHO_TRUOC, DAI) if bi_huy == "ghi_nhan" else (DAI, NGAN)
    _boc_ghi_nhan_tran(monkeypatch, tran_gn)
    diem = _Diem()
    _boc_dung(monkeypatch, eng, "check_choice_admit_capacity", diem, tran_cb)  # dừng sau NV1 (ô Y)
    t_cb = asyncio.create_task(_cong_bo(client, ad, a))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=2))
    do = await _cho_bi_chan_hoac_xong(t_qd)
    diem.di.set()
    r_cb, r_qd = await asyncio.gather(t_cb, t_qd)
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ khoá của công bố"
    assert r_qd.status_code == 201, r_qd.text
    assert r_cb.status_code == 200 and r_cb.json()["final_status"] == "admitted", r_cb.text
    nv = await qd._q(
        "SELECT display_order, decision FROM admission_profile_choice WHERE admission_profile_id = :p "
        "ORDER BY display_order",
        p=a,
    )
    assert [tuple(r) for r in nv] == [(1, "waitlisted"), (2, "admitted")]
    assert (await _ban(a))[0] == "admitted" and await _so_qd() == 1


# ═══════════════════════════════ (c) lô bị chọn huỷ giữa chừng ════════════════════════════════
async def test_hang_loat_bi_huy_giua_lo_chi_lui_muc_ay(client, hs, ad, monkeypatch):  # noqa: F811
    """Phiên thứ ba T giữ dòng lead của P2 rồi CHỜ hồ sơ P1 (lô đang giữ). Lô đi tiếp tới mục P2, cập nhật lead của
    P2 ⇒ CHỜ T ⇒ vòng chờ; trần của lô ngắn ⇒ LÔ bị huỷ (40P01) ở mục P2. Đúng: chỉ mục P2 hỏng ("thử lại"), P1
    commit, callback chỉ của P1, số thành công 1. Mã cũ (không SAVEPOINT): giao dịch cả lô đã huỷ nhưng phản hồi vẫn
    đếm P1 / callback P1 chạy, hoặc 500."""
    await _dam_bao_sts09()
    o, p1, p2 = await _hai_em_da_nop_cung_o(hs)
    v1, v2 = (await _ban(p1))[1], (await _ban(p2))[1]
    l1, l2 = await _lead(p1), await _lead(p2)
    hoa_hong = _theo_doi_hoa_hong(monkeypatch)
    t_ket = await csdl.engine.connect()
    t_gd = await t_ket.begin()
    try:
        await t_ket.execute(text("SET LOCAL deadlock_timeout = '%dms'" % DAI))
        await t_ket.execute(text("UPDATE lead SET updated_at = updated_at WHERE id = :l"), {"l": l2})
        diem = _Diem()
        _boc_dung(monkeypatch, asv, "_assert_quota_or_bypass", diem, NGAN)  # lô giữ P1 (+ Q)
        t_lo = asyncio.create_task(_duyet_hang_loat(client, ad, (p1, v1), (p2, v2)))
        await asyncio.wait_for(diem.toi.wait(), 30)
        t_t = asyncio.create_task(
            t_ket.execute(
                text("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE"), {"p": p1}
            )
        )
        do = await _cho_bi_chan_hoac_xong(t_t)
        diem.di.set()
        r_lo = await asyncio.wait_for(t_lo, 60)
        await asyncio.wait_for(t_t, 60)
    finally:
        await t_gd.rollback()
        await t_ket.close()
    assert do == "chan", "phép đo không hợp lệ: phiên thứ ba không chờ hồ sơ P1 của lô"
    assert r_lo.status_code == 200, r_lo.text
    kq = r_lo.json()
    da_duyet = await _da_duyet(p1, p2)
    assert da_duyet == {p1}, (kq, da_duyet)
    assert (kq["success_count"], kq["failed_ids"]) == (1, [p2]), kq
    assert kq["errors"][str(p2)] == qos.THONG_DIEP_XUNG_DOT, kq
    assert hoa_hong == [l1]


# ═══════════════════════════════ (d) công bố bị chọn huỷ ⇒ 409 ════════════════════════════════
async def test_cong_bo_bi_huy_tra_409_khong_ghi_gi(client, hs, ad, monkeypatch):  # noqa: F811
    """T giữ lead của em A rồi CHỜ dòng học vụ X mà công bố đang giữ; công bố đi tiếp, cập nhật lead của A ⇒ CHỜ T
    ⇒ vòng chờ; trần của công bố ngắn ⇒ công bố bị huỷ ⇒ 409 "thử lại", hồ sơ / nguyện vọng không đổi."""
    monkeypatch.setattr(eng, "_evaluate_single_choice", lambda *a, **kw: ("admitted", None, []))
    await _cau_hinh_trinh_do()
    await _dam_bao_sts09()  # trúng ⇒ đồng bộ lead (cập nhật dòng lead mà T đang giữ)
    x = await _o_chi_tieu(hs, SACH[1], chi_tieu=10)  # NV1 của A = ô X
    a = hs[SACH[1]][1]
    await _nop(a)
    la = await _lead(a)
    nv_truoc = await _nguyen_vong(a)
    t_ket = await csdl.engine.connect()
    t_gd = await t_ket.begin()
    try:
        await t_ket.execute(text("SET LOCAL deadlock_timeout = '%dms'" % DAI))
        await t_ket.execute(text("UPDATE lead SET updated_at = updated_at WHERE id = :l"), {"l": la})
        diem = _Diem()
        _boc_dung(monkeypatch, eng, "check_choice_admit_capacity", diem, NGAN)
        t_cb = asyncio.create_task(_cong_bo(client, ad, a))
        await asyncio.wait_for(diem.toi.wait(), 30)
        t_t = asyncio.create_task(
            t_ket.execute(
                text("SELECT id FROM offering_academic_info WHERE id = :a FOR UPDATE"), {"a": x["ai"]}
            )
        )
        do = await _cho_bi_chan_hoac_xong(t_t)
        diem.di.set()
        r_cb = await asyncio.wait_for(t_cb, 60)
        await asyncio.wait_for(t_t, 60)
    finally:
        await t_gd.rollback()
        await t_ket.close()
    assert do == "chan", "phép đo không hợp lệ: phiên thứ ba không chờ dòng học vụ của công bố"
    assert r_cb.status_code == 409 and qos.THONG_DIEP_XUNG_DOT in r_cb.text, r_cb.text
    assert (await _ban(a))[0] == "submitted"
    assert await _nguyen_vong(a) == nv_truoc


# ═══════════════════════════════ (e) ghi nhận bị chọn huỷ ⇒ 409 ═══════════════════════════════
async def test_ghi_nhan_bi_huy_tra_409_khong_ghi_gi(client, hs, ad, monkeypatch):  # noqa: F811
    """T giữ dòng học vụ X; ghi nhận (giữ hồ sơ của bộ) CHỜ X; T CHỜ hồ sơ ấy ⇒ vòng chờ; trần ghi nhận hết sau khi
    vòng hình thành ⇒ ghi nhận bị huỷ ⇒ 409 "thử lại" (không 500), 0 văn bản, 0 dòng."""
    x = await _o_chi_tieu(hs, SACH[0], chi_tieu=10)
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    pid = hs[SACH[0]][1]
    _boc_ghi_nhan_tran(monkeypatch, NGAN_CHO_TRUOC)
    t_ket = await csdl.engine.connect()
    t_gd = await t_ket.begin()
    try:
        await t_ket.execute(text("SET LOCAL deadlock_timeout = '%dms'" % DAI))
        await t_ket.execute(
            text("SELECT id FROM offering_academic_info WHERE id = :a FOR UPDATE"), {"a": x["ai"]}
        )
        t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
        do = await _cho_bi_chan_hoac_xong(t_qd)
        t_t = asyncio.create_task(
            t_ket.execute(
                text("SELECT id FROM admission_profile WHERE id = :p FOR UPDATE"), {"p": pid}
            )
        )
        r_qd = await asyncio.wait_for(t_qd, 60)
        await asyncio.wait_for(t_t, 60)
    finally:
        await t_gd.rollback()
        await t_ket.close()
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ dòng học vụ"
    assert r_qd.status_code == 409 and qos.THONG_DIEP_XUNG_DOT in r_qd.text, r_qd.text
    assert await _so_qd() == 0
    assert await qd._q1("SELECT count(*) FROM council_decision_row") == 0
