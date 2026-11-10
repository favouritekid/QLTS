# -*- coding: utf-8 -*-
"""F230 chặng 2b — HAI PHIÊN có ĐIỂM ĐỒNG BỘ (ép CẢ HAI thứ tự, không phó mặc lịch của event loop), qua REQUEST
THẬT; kết cục đo bằng SQL (CLAUDE.md §10). Codex lần 14 câu 2 (b) + câu 5; đặc tả 8.5 + bổ sung lượt J.

Điểm đồng bộ: bọc một hàm của phiên thứ nhất (``monkeypatch``) — tới đó phiên DỪNG, GIỮ mọi khoá đã lấy; phiên thứ
hai chạy tới khi PostgreSQL báo nó bị chặn (``pg_blocking_pids``) hoặc nó xong trước; rồi mới cho phiên thứ nhất
đi tiếp. Mỗi ca ghi rõ thứ tự khoá mong đợi.

* (i)  ghi nhận ↔ từ chối hồ sơ lẻ — hai thứ tự;
* (ii) gọi THẲNG ``admission_state_service.transition`` tới đích bị khoá, KHÔNG khoá hồ sơ trước, trong lúc ghi nhận
       giữ khoá hồ sơ — chỉ khoá CỦA CHỐT (``kiem_chuyen_trang_thai``) giữ bất biến (đột biến ``c7-m08`` ⇒ ĐỎ);
* (iii) công bố theo nguyện vọng ĐI TỚI nhánh thành công (seed thêm cấu hình trình độ) + hai phiên ghi nhận ↔ công bố;
* chỗ CUỐI CÙNG: Phê duyệt cũ / công bố ↔ ghi nhận — ghi nhận khoá dòng chỉ tiêu SAU hồ sơ ⇒ lần đếm của bên kia
  thấy dòng mới (không vượt); thứ tự ngược ⇒ ghi nhận vẫn ghi (owner N9: không chặn theo chỉ tiêu);
* số chỗ theo thao tác THẬT: ghi nhận → huỷ hiệu lực → khôi phục;
* dòng bộ dựng qua cổng LUÔN đủ khoá đếm (đường duy nhất tạo dòng bộ).
"""
import asyncio
import time

import pytest
from sqlalchemy import text

import app.database as csdl
from app import models
from app.database import AsyncSessionLocal
from app.repositories.council_decision_repository import CouncilDecisionRepository
from app.services import admission_service as asv
from app.services import admission_state_service as state_service
from app.services import council_decision_service as qd_vb
from app.services import council_decision_status_service as tt_qd
from app.services import quota_occupancy_service as qos
from app.utils.exceptions import QuyetDinhKhoaHoSo
from tests.api import test_council_decisions_api as qd
from tests.api.test_council_decision_profile_gates_api import (  # noqa: F401 — fixture
    A,
    SACH,
    V2,
    _ban,
    _la_chan,
    ad,
    hs,
    tk,
)

pytestmark = pytest.mark.integration


# ═══════════════════════════════ điểm đồng bộ ══════════════════════════════════════════════
class _Diem:
    """Phiên tới điểm ⇒ báo ``toi`` rồi CHỜ ``di`` (giữ nguyên khoá). Chỉ dừng ở lần gọi ĐẦU."""

    def __init__(self):
        self.toi = asyncio.Event()
        self.di = asyncio.Event()
        self.so_lan = 0

    async def cho(self):
        self.so_lan += 1
        if self.so_lan == 1:
            self.toi.set()
            await asyncio.wait_for(self.di.wait(), 60)


def _boc(monkeypatch, chu, ten, diem):
    """Bọc ``chu.ten``: chạy hàm gốc RỒI dừng ở điểm (khoá hàm gốc lấy được giữ tới khi phiên commit)."""
    goc = getattr(chu, ten)

    async def boc(*a, **kw):
        kq = await goc(*a, **kw)
        await diem.cho()
        return kq

    monkeypatch.setattr(chu, ten, boc)


async def _cho_bi_chan_hoac_xong(*viec, giay=30.0):
    """``"chan"`` khi một phiên CSDL đang bị phiên khác chặn; ``"xong"`` nếu việc đã kết thúc trước (không chờ
    khoá nào); ``"het_gio"``."""
    het = time.monotonic() + giay
    while time.monotonic() < het:
        async with csdl.engine.connect() as k:
            n = (
                await k.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND cardinality(pg_blocking_pids(pid)) > 0"
                    )
                )
            ).scalar_one()
        if n:
            return "chan"
        if any(v.done() for v in viec):
            return "xong"
        await asyncio.sleep(0.1)
    return "het_gio"


async def _so_qd():
    return await qd._q1("SELECT count(*) FROM council_decision WHERE trang_thai = 'hieu_luc'")


async def _nop(pid):
    await qd._sql("UPDATE admission_profile SET status = 'submitted' WHERE id = :p", p=pid)


async def _bo_da_nop(client, ad, hs, nhan):  # noqa: F811
    await _nop(hs[nhan][1])
    return await qd._bo_ok(client, ad, hs, [nhan], xac_nhan_trang_thai={"submitted": 1})


def _tu_choi(client, ad, pid, ver):  # noqa: F811
    return client.post(
        A + "/%d/reject" % pid, json={"reason": "GIA tu choi thu", "version": ver}, headers=ad
    )


# ═══════════════════════════════ (i) ghi nhận ↔ từ chối lẻ ══════════════════════════════════
async def test_hai_phien_ghi_nhan_giu_khoa_truoc_tu_choi_sau(client, hs, ad, monkeypatch):  # noqa: F811
    # Thứ tự khoá: ghi nhận bộ → hồ sơ (GIỮ) ; từ chối hồ sơ (CHỜ) → sau commit đọc thấy QĐ ⇒ chốt chặn.
    nhan = SACH[0]
    pid = hs[nhan][1]
    bo = await _bo_da_nop(client, ad, hs, nhan)
    ver = (await _ban(pid))[1]
    diem = _Diem()
    _boc(monkeypatch, CouncilDecisionRepository, "khoa_ho_so", diem)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_tc = asyncio.create_task(_tu_choi(client, ad, pid, ver))
    do = await _cho_bi_chan_hoac_xong(t_tc)
    diem.di.set()
    r_qd, r_tc = await asyncio.gather(t_qd, t_tc)
    assert do == "chan", "phép đo không hợp lệ: từ chối không chờ khoá hồ sơ của ghi nhận"
    assert r_qd.status_code == 201, r_qd.text
    assert _la_chan(r_tc), r_tc.text
    assert (await _ban(pid))[0] == "submitted" and await _so_qd() == 1


async def test_hai_phien_tu_choi_giu_khoa_truoc_ghi_nhan_sau(client, hs, ad, monkeypatch):  # noqa: F811
    # Thứ tự khoá: từ chối hồ sơ (GIỮ, đã qua chốt) ; ghi nhận bộ → hồ sơ (CHỜ) → thấy trạng thái mới ⇒ đòi Admin
    # xác nhận (C3), không ghi.
    nhan = SACH[0]
    pid = hs[nhan][1]
    bo = await _bo_da_nop(client, ad, hs, nhan)
    ver = (await _ban(pid))[1]
    diem = _Diem()
    _boc(monkeypatch, tt_qd, "kiem_chuyen_trang_thai", diem)
    t_tc = asyncio.create_task(_tu_choi(client, ad, pid, ver))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    do = await _cho_bi_chan_hoac_xong(t_qd)
    diem.di.set()
    r_tc, r_qd = await asyncio.gather(t_tc, t_qd)
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ khoá hồ sơ của từ chối"
    assert r_tc.status_code == 200, r_tc.text
    assert r_qd.status_code == 409 and "xac_nhan_can" in r_qd.json(), r_qd.text
    assert (await _ban(pid))[0] == "rejected" and await _so_qd() == 0


# ═══════════════════════════════ (ii) chốt gọi thẳng, không khoá trước ═══════════════════════
async def test_hai_phien_chot_transition_goi_thang_khong_khoa_truoc_va_ghi_nhan(  # noqa: F811
    client, hs, ad, monkeypatch
):
    # Nơi gọi KHÔNG khoá hồ sơ (khác mọi nơi gọi hôm nay) ⇒ chỉ ``FOR UPDATE`` của CHỐT tuần tự hoá với ghi nhận:
    # chốt chờ khoá hồ sơ của ghi nhận → đọc SAU commit → thấy QĐ ⇒ chặn. Bỏ khoá của chốt (``c7-m08``) ⇒ chốt đọc
    # trước commit, cho qua, lệnh UPDATE chờ rồi ghi đè ⇒ "QĐ đã ghi VÀ hồ sơ đã bị từ chối".
    nhan = SACH[0]
    pid = hs[nhan][1]
    bo = await _bo_da_nop(client, ad, hs, nhan)
    diem = _Diem()
    _boc(monkeypatch, CouncilDecisionRepository, "khoa_ho_so", diem)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    await asyncio.wait_for(diem.toi.wait(), 30)

    async def _chuyen():
        async with AsyncSessionLocal() as db:
            p = await db.get(models.AdmissionProfile, pid)  # KHÔNG FOR UPDATE
            try:
                await state_service.transition(db, p, "rejected", skip_dispatch=True)
                await db.flush()
                await db.commit()
                return "da_chuyen"
            except QuyetDinhKhoaHoSo:
                await db.rollback()
                return "bi_chan"

    t_ch = asyncio.create_task(_chuyen())
    do = await _cho_bi_chan_hoac_xong(t_ch)
    diem.di.set()
    r_qd, kq = await asyncio.gather(t_qd, t_ch)
    assert r_qd.status_code == 201, r_qd.text
    assert kq == "bi_chan" and (await _ban(pid))[0] == "submitted", (kq, await _ban(pid))
    assert do == "chan", "phép đo không hợp lệ: chốt không chờ khoá hồ sơ của ghi nhận"


# ═══════════════════════════════ (iii) công bố theo nguyện vọng THÀNH CÔNG ═════════════════════
async def _cau_hinh_trinh_do():
    """Ngành giả ĐỦ cấu hình trình độ (owner Q20(a)) để công bố đi tới nhánh THÀNH CÔNG — seed Hội đồng không gán
    ``degree_level_id`` nên công bố luôn dừng 503 ``CHOICE_TARGET_LEVEL_NOT_CONFIGURED``."""
    async with csdl.engine.begin() as c:
        for ma, ten, td in (
            ("cao_dang", "Cao đẳng giả HP", "Cao đẳng"),
            ("trung_cap", "Trung cấp giả HP", "Trung cấp"),
        ):
            dl = (
                await c.execute(text("SELECT id FROM config_degree_level WHERE code = :m"), {"m": ma})
            ).scalar()
            if dl is None:
                dl = (
                    await c.execute(
                        text(
                            "INSERT INTO config_degree_level (code, name, display_order, is_active) "
                            "VALUES (:m, :t, 1, true) RETURNING id"
                        ),
                        {"m": ma, "t": ten},
                    )
                ).scalar_one()
            await c.execute(
                text("UPDATE major_program SET degree_level_id = :d WHERE degree_level = :t"),
                {"d": dl, "t": td},
            )


def _cong_bo(client, ad, pid):  # noqa: F811
    return client.post(V2 + "/%d/publish-result" % pid, headers=ad)


async def test_cong_bo_theo_nguyen_vong_thanh_cong_khi_du_cau_hinh(client, hs, ad):  # noqa: F811
    # Ca nền cho (iii): nhánh THÀNH CÔNG chạy được (không còn 503) — hồ sơ đổi trạng thái theo kết quả xét.
    await _cau_hinh_trinh_do()
    pid = hs[SACH[1]][1]
    await _nop(pid)
    r = await _cong_bo(client, ad, pid)
    assert r.status_code == 200, r.text
    assert (await _ban(pid))[0] != "submitted", await _ban(pid)


async def test_hai_phien_ghi_nhan_giu_khoa_truoc_cong_bo_sau(client, hs, ad, monkeypatch):  # noqa: F811
    # Thứ tự khoá: ghi nhận bộ → hồ sơ (GIỮ) ; công bố hồ sơ (CHỜ — ``kiem_xet_moi`` FOR UPDATE) → thấy QĐ ⇒ 409.
    await _cau_hinh_trinh_do()
    nhan = SACH[1]
    pid = hs[nhan][1]
    bo = await _bo_da_nop(client, ad, hs, nhan)
    diem = _Diem()
    _boc(monkeypatch, CouncilDecisionRepository, "khoa_ho_so", diem)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_cb = asyncio.create_task(_cong_bo(client, ad, pid))
    do = await _cho_bi_chan_hoac_xong(t_cb)
    diem.di.set()
    r_qd, r_cb = await asyncio.gather(t_qd, t_cb)
    assert do == "chan", "phép đo không hợp lệ: công bố không chờ khoá hồ sơ của ghi nhận"
    assert r_qd.status_code == 201, r_qd.text
    assert _la_chan(r_cb) and r_cb.json()["tinh_trang_qd"] == tt_qd.HL, r_cb.text
    assert (await _ban(pid))[0] == "submitted" and await _so_qd() == 1


async def test_hai_phien_cong_bo_thanh_cong_truoc_ghi_nhan_sau(client, hs, ad, monkeypatch):  # noqa: F811
    # Thứ tự khoá: công bố hồ sơ (GIỮ, đã qua cổng) → học vụ → đường xét ; ghi nhận bộ → hồ sơ (CHỜ) → thấy trạng
    # thái mới ⇒ đòi Admin xác nhận (C3), không ghi. Nhánh công bố THÀNH CÔNG (200), không phải 503.
    await _cau_hinh_trinh_do()
    nhan = SACH[1]
    pid = hs[nhan][1]
    bo = await _bo_da_nop(client, ad, hs, nhan)
    diem = _Diem()
    _boc(monkeypatch, tt_qd, "kiem_xet_moi", diem)
    t_cb = asyncio.create_task(_cong_bo(client, ad, pid))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    do = await _cho_bi_chan_hoac_xong(t_qd)
    diem.di.set()
    r_cb, r_qd = await asyncio.gather(t_cb, t_qd)
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ khoá hồ sơ của công bố"
    assert r_cb.status_code == 200, r_cb.text
    assert r_qd.status_code == 409 and "xac_nhan_can" in r_qd.json(), r_qd.text
    assert (await _ban(pid))[0] != "submitted" and await _so_qd() == 0


# ═══════════════════════════════ chỗ CUỐI CÙNG ═════════════════════════════════════════════
async def _o_chi_tieu(hs, nhan_qd, *, chi_tieu=1):
    """Ô chỉ tiêu của dòng bộ sẽ ghi nhận (khoá CHỤP của NV in của ``nhan_qd``): đặt chỉ tiêu năm. Trả khoá."""
    pid = hs[nhan_qd][1]
    k = (
        await qd._q(
            "SELECT ap.academic_info_id, oai.offering_id, ap.id FROM admission_profile_choice c "
            "JOIN admission_path ap ON ap.id = c.admission_path_id "
            "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id "
            "WHERE c.admission_profile_id = :p ORDER BY c.display_order, c.id LIMIT 1",
            p=pid,
        )
    )[0]
    await qd._sql(
        "UPDATE offering_academic_info SET annual_admission_quota = :n WHERE id = :a", n=chi_tieu, a=k[0]
    )
    return {"ai": k[0], "off": k[1], "path": k[2]}


async def _dam_bao_sts09():
    """Trạng thái tư vấn đích của "Đã duyệt" (``sync_lead_from_admission``) — seed Hội đồng không có; id + giai đoạn
    chép từ ``conftest.seed_lead_dependencies`` (giai đoạn ``stg04`` do fixture ``hs`` của module cổng dựng)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            if await s.get(models.ConsultationStatus, "sts09") is None:
                s.add(
                    models.ConsultationStatus(
                        id="sts09", name="Du dieu kien nhap hoc", color_code="#00CC00", stage_id="stg04"
                    )
                )


async def _da_dung(o):
    async with AsyncSessionLocal() as db:
        return await qos.dem_theo_nganh_nam(db, offering_id=o["off"], academic_year=2026)


async def test_cho_cuoi_phe_duyet_cu_trong_luc_ghi_nhan_chua_commit_khong_vuot(  # noqa: F811
    client, hs, ad, monkeypatch
):
    # Chỉ tiêu 1. Ghi nhận em B (khoá chụp ô X) DỪNG sau khi đã chèn dòng (chưa commit) — giữ hồ sơ B + dòng chỉ tiêu
    # X. Phê duyệt cũ em A (lead ô X): khoá hồ sơ A → CHỜ dòng chỉ tiêu X → sau commit đếm thấy B ⇒ "vượt chỉ tiêu",
    # A không được duyệt. Thiếu khoá dòng chỉ tiêu ở ghi nhận ⇒ A đếm 0 trước commit, được duyệt ⇒ 2 / 1.
    o = await _o_chi_tieu(hs, SACH[0])
    a = hs[SACH[1]][1]
    await _nop(a)
    await qd._sql(
        "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        o=o["off"],
        p=a,
    )
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    assert await _da_dung(o) == 0
    diem = _Diem()
    _boc(monkeypatch, CouncilDecisionRepository, "chen_dong_tu_bo", diem)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    await asyncio.wait_for(diem.toi.wait(), 30)
    ver = (await _ban(a))[1]
    t_ap = asyncio.create_task(
        client.post(A + "/%d/approve" % a, json={"version": ver}, headers=ad)
    )
    do = await _cho_bi_chan_hoac_xong(t_ap)
    diem.di.set()
    r_qd, r_ap = await asyncio.gather(t_qd, t_ap)
    assert r_qd.status_code == 201, r_qd.text
    assert r_ap.status_code == 400 and "Vượt chỉ tiêu" in str(r_ap.json()), r_ap.text
    assert (await _ban(a))[0] == "submitted" and await _da_dung(o) == 1
    assert do == "chan", "phép đo không hợp lệ: Phê duyệt cũ không chờ dòng chỉ tiêu của ghi nhận"


async def test_cho_cuoi_phe_duyet_cu_truoc_ghi_nhan_sau_van_ghi_n9(client, hs, ad, monkeypatch):  # noqa: F811
    # Thứ tự ngược: Phê duyệt cũ em A giữ hồ sơ A + dòng chỉ tiêu X (đã đếm 0 < 1) ; ghi nhận em B CHỜ dòng chỉ tiêu
    # X → sau khi A commit vẫn GHI (owner N9: ghi nhận không chặn theo chỉ tiêu — giấy đã ký) ⇒ 2 / 1, do văn bản
    # đã ký, không do Phê duyệt cũ. Không deadlock.
    await _dam_bao_sts09()
    o = await _o_chi_tieu(hs, SACH[0])
    a = hs[SACH[1]][1]
    await _nop(a)
    await qd._sql(
        "UPDATE lead SET offering_id = :o WHERE id = (SELECT lead_id FROM admission_profile WHERE id = :p)",
        o=o["off"],
        p=a,
    )
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    diem = _Diem()
    _boc(monkeypatch, asv, "_assert_quota_or_bypass", diem)
    ver = (await _ban(a))[1]
    t_ap = asyncio.create_task(
        client.post(A + "/%d/approve" % a, json={"version": ver}, headers=ad)
    )
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    do = await _cho_bi_chan_hoac_xong(t_qd)
    diem.di.set()
    r_ap, r_qd = await asyncio.gather(t_ap, t_qd)
    assert do == "chan", "phép đo không hợp lệ: ghi nhận không chờ dòng chỉ tiêu của Phê duyệt cũ"
    assert r_ap.status_code == 200, r_ap.text
    assert r_qd.status_code == 201, r_qd.text
    assert (await _ban(a))[0] == "approved" and await _da_dung(o) == 2


async def test_cho_cuoi_cong_bo_trong_luc_ghi_nhan_chua_commit_khong_vuot(  # noqa: F811
    client, hs, ad, monkeypatch
):
    # Chỉ tiêu năm 1 ở ô X (NV1 của em A = đường xét của NV in của em B). Ghi nhận B DỪNG sau khi chèn dòng (giữ
    # dòng chỉ tiêu X). Công bố A: khoá hồ sơ A → CHỜ dòng chỉ tiêu X (mức năm) → sau commit đếm thấy B ⇒ NV1 KHÔNG
    # trúng. Thiếu khoá ở ghi nhận ⇒ NV1 trúng ⇒ 2 / 1. Điểm của MỌI nguyện vọng ép "đạt" (khuôn
    # ``test_choice_engine_quota_concurrent``) — chỉ cổng chỉ tiêu quyết; seed thật chấm trượt cả hai NV.
    from app.services import admission_choice_engine_service as eng

    monkeypatch.setattr(eng, "_evaluate_single_choice", lambda *a, **kw: ("admitted", None, []))
    await _cau_hinh_trinh_do()
    o = await _o_chi_tieu(hs, SACH[0])
    a = hs[SACH[1]][1]
    await _nop(a)
    nv1 = await qd._q1(
        "SELECT c.id FROM admission_profile_choice c WHERE c.admission_profile_id = :p "
        "ORDER BY c.display_order, c.id LIMIT 1",
        p=a,
    )
    assert await qd._q1(
        "SELECT admission_path_id FROM admission_profile_choice WHERE id = :c", c=nv1
    ) == o["path"]
    bo = await qd._bo_ok(client, ad, hs, [SACH[0]])
    diem = _Diem()
    _boc(monkeypatch, CouncilDecisionRepository, "chen_dong_tu_bo", diem)
    t_qd = asyncio.create_task(qd._ghi(client, ad, bo["id"], so="501", so_hs=1))
    await asyncio.wait_for(diem.toi.wait(), 30)
    t_cb = asyncio.create_task(_cong_bo(client, ad, a))
    do = await _cho_bi_chan_hoac_xong(t_cb)
    diem.di.set()
    r_qd, r_cb = await asyncio.gather(t_qd, t_cb)
    assert r_qd.status_code == 201, r_qd.text
    assert r_cb.status_code == 200, r_cb.text
    assert await qd._q1("SELECT decision FROM admission_profile_choice WHERE id = :c", c=nv1) != "admitted"
    async with AsyncSessionLocal() as db:
        assert await qos.dem_theo_thong_tin_hoc_vu(db, academic_info_id=o["ai"]) == 1
    assert do == "chan", "phép đo không hợp lệ: công bố không chờ dòng chỉ tiêu của ghi nhận"


# ═══════════════════════════════ số chỗ theo thao tác THẬT ═══════════════════════════════════
async def test_dem_cho_theo_thao_tac_that_ghi_nhan_huy_hieu_luc_khoi_phuc(client, hs, ad):  # noqa: F811
    nhan = SACH[0]
    bo = await qd._bo_ok(client, ad, hs, [nhan])
    k = (
        await qd._q(
            "SELECT admission_path_id, academic_info_id, offering_id, academic_year "
            "FROM council_document_set_row WHERE set_id = :s",
            s=bo["id"],
        )
    )[0]

    async def dem():
        async with AsyncSessionLocal() as db:
            return (
                await qos.dem_theo_duong_xet(db, admission_path_id=k[0]),
                await qos.dem_theo_thong_tin_hoc_vu(db, academic_info_id=k[1]),
                await qos.dem_theo_nganh_nam(db, offering_id=k[2], academic_year=k[3]),
                (await qos.dem_da_trung_tuyen_theo_duong_xet(db, [k[0]]))[k[0]],
            )

    truoc = await dem()
    x = await qd._ghi_ok(client, ad, bo["id"], so="501", so_hs=1)
    assert await dem() == tuple(n + 1 for n in truoc)
    r = await qd._huy_hieu_luc(client, ad, x["id"], "701")
    assert r.status_code == 201, r.text
    assert await dem() == truoc
    h = r.json()["id"]
    r = await qd._huy_ghi_nhan(client, ad, h, "701")
    assert r.status_code == 200, r.text
    assert await dem() == tuple(n + 1 for n in truoc)


# ═══════════════════════════════ dòng bộ qua cổng luôn đủ khoá đếm ═════════════════════════════
async def test_dong_bo_dung_qua_cong_luon_du_khoa_dem_va_dung_chuoi(client, hs, ad):  # noqa: F811
    # Đường DUY NHẤT tạo dòng bộ là dựng bộ qua cổng; cổng chặn dòng không có nguyện vọng in, nguyện vọng in đòi đủ
    # chuỗi đường xét → học vụ → ngành ⇒ ba khoá đếm luôn có và khớp chuỗi (câu hỏi "thiếu khoá" chỉ còn ca sửa
    # tay CSDL — báo cáo lượt J).
    bo = await qd._bo_ok(client, ad, hs, SACH)
    hang = await qd._q(
        "SELECT r.stt, r.admission_path_id IS NOT NULL AND r.academic_info_id IS NOT NULL "
        "AND r.offering_id IS NOT NULL, EXISTS (SELECT 1 FROM admission_path ap "
        "JOIN offering_academic_info oai ON oai.id = ap.academic_info_id WHERE ap.id = r.admission_path_id "
        "AND ap.academic_info_id = r.academic_info_id AND oai.offering_id = r.offering_id "
        "AND oai.academic_year = r.academic_year) FROM council_document_set_row r WHERE r.set_id = :s "
        "ORDER BY r.stt",
        s=bo["id"],
    )
    assert [tuple(h) for h in hang] == [(i, True, True) for i in range(1, len(SACH) + 1)]


def test_thu_tu_khoa_ghi_nhan_ho_so_truoc_dong_chi_tieu():
    """Kiểm kê thứ tự khoá trong MÃ (đọc nguồn): ở ba thao tác làm tăng Phần B, ``khoa_chi_tieu_cua_dong_bo`` đứng
    SAU ``khoa_ho_so`` (thứ tự chung hồ sơ → học vụ → đường xét)."""
    import inspect

    for ham in (qd_vb.ghi_nhan_quyet_dinh, qd_vb.ghi_nhan_dieu_chinh, qd_vb.huy_ghi_nhan):
        nguon = inspect.getsource(ham)
        assert nguon.count("khoa_chi_tieu_cua_dong_bo(") == 1, ham.__name__
        assert nguon.index("repo.khoa_ho_so(") < nguon.index("khoa_chi_tieu_cua_dong_bo("), ham.__name__
