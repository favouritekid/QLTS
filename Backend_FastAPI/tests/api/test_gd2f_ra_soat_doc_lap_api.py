"""GĐ2-F1 — Codex lượt 3, đợt rà ĐỘC LẬP (owner chốt 20-11: sửa gộp một đợt).

1. GET bảng chỉ tiêu (kể cả thân 404 năm chưa có bảng) trả ``academic_infos`` — học vụ của năm đọc CÙNG lần với dấu chỉ tiêu
   (``read_quota_snapshot``): trình soạn lấy danh sách chọn + giá trị điền sẵn từ đây (điểm chặn giao diện).
2. "Xoá ngành" = xoá TỪNG loại hình của ngành như ``delete_program_offering`` (owner chốt 20-11), kể cả loại hình đang "Ngừng":
   một giao dịch, trọn-hoặc-không, luật C (học vụ có chỉ tiêu — kể cả 0 — ở năm đã khoá ⇒ 409, không đổi gì); MỘT helper với xoá
   loại hình. Hai phiên: tạo học vụ đang dở ⇒ xoá ngành chờ rồi xoá luôn; thứ tự ngược ⇒ tạo 409.
3. Khôi phục học vụ ↔ xoá loại hình, hai phiên, CẢ HAI thứ tự — kiểm TRẠNG THÁI CUỐI (loại hình tắt, 0 học vụ hiệu lực).
4. Dây chuyền xoá khoá dòng học vụ bằng MỘT câu ``FOR NO KEY UPDATE ORDER BY id`` ⇒ không vòng chờ ``40P01`` với
   ``lock_quota_cells`` (ghi nhận / Phê duyệt hàng loạt: ``FOR UPDATE`` id tăng dần, không lấy khoá năm).
5. Ghi qua đối tượng ORM nạp TRƯỚC khoá năm: nạp lại sau khoá — không thì gán trùng ảnh cũ ⇒ không ghi gì mà vẫn báo thành công.
6. PATCH gửi tường minh ``"academic_year": null`` ⇒ 422.
7. Xoá loại hình: học vụ vừa bị dời năm ở nơi khác (năm ngoài tập đã khoá) ⇒ 409 tải lại.
8. (Codex lượt 4, owner chốt 20-11) Ngành "Ngừng" / đã xoá ⇒ không tạo, không bật lại loại hình (409 ``MAJOR_PROGRAM_INACTIVE``);
   tạo / bật lại loại hình và xoá ngành xếp hàng qua khoá dòng ngành — hai phiên, cả hai thứ tự, kiểm trạng thái cuối.

Ca hai phiên đo "chờ" bằng ``pg_blocking_pids`` từ phiên thứ ba; mọi bước chờ có hạn. Dữ liệu nền dựng bằng SQL / dịch vụ (route
POST tạo học vụ còn lỗi có từ trước ở lần tạo thành công — ngoài phạm vi). Không dữ liệu thật.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from tests.api.test_gd2a_bang_chi_tieu_api import (  # noqa: F401 — fixture dùng qua tên
    NAM,
    P,
    _bi_chan_boi,
    _chi_tieu,
    _dau,
    _dong,
    _mo_ta,
    _pid,
    _sql,
    _tao_bang_nhap,
    _than,
    hoc_vu,
)
from tests.api.test_gd2f_dau_chi_tieu_api import _so_hoc_vu
from tests.api.test_gd2f_luat_b_bang_khoa_api import KHOA_409, _dat_chi_tieu, _khoa, _tao
from tests.api.test_gd2f_luat_c_xoa_khoi_phuc_api import dong_ho_trong_nam  # noqa: F401 — fixture dùng qua tên
from tests.api.test_gd2f_thanh_vien_xoa_va_loai_hinh_api import (
    _da_xoa,
    _loai_hinh_hoat_dong,
    _offering_cua,
    _so_hoc_vu_con_hieu_luc,
    _xoa_loai_hinh,
)

pytestmark = pytest.mark.asyncio

NGANH = "/api/admin/programs/%d"


# ══ 1 — GET bảng: học vụ của năm CÙNG ảnh với dấu ════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("co_bang", [True, False], ids=["co_bang_200", "chua_co_bang_404"])
async def test_get_bang_tra_hoc_vu_cua_nam_cung_anh_voi_dau(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, co_bang
):
    """Danh sách = ĐÚNG mọi dòng của năm trong CSDL (kể cả đã xoá mềm, chỉ tiêu 0 / trống) và dấu trả kèm = hàm băm
    (``quota_fingerprint_of``) của CHÍNH danh sách ấy — 200 và thân 404."""
    from app.services.admission_quota_table_service import quota_fingerprint_of

    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 0)
    if co_bang:
        await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    await _sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=d)
    r = await client.get(f"{P}/{NAM}", headers=admin_token_headers)
    assert r.status_code == (200 if co_bang else 404), r.text
    j = r.json()
    bo = [(x["offering_academic_info_id"], x["annual_admission_quota"], x["is_deleted"]) for x in j["academic_infos"]]
    dong = (
        await _sql(
            "SELECT id, annual_admission_quota, is_deleted FROM offering_academic_info WHERE academic_year = :y", y=NAM
        )
    ).all()
    assert sorted(bo) == sorted(tuple(x) for x in dong)
    assert (d, 0, True) in bo
    assert j["quota_fingerprint"] == quota_fingerprint_of(bo)


# ══ 2 — Xoá ngành = xoá từng loại hình ═══════════════════════════════════════════════════════════════════════════════
async def _nganh_rieng(unit_id: int, dong) -> tuple:
    """Một ngành RIÊNG (ngoài ngành của ``hoc_vu``): mỗi phần tử ``dong`` = (năm, chỉ tiêu, loại hình đang hoạt động) ⇒ một loại
    hình + một học vụ. Dựng TRƯỚC khi khoá bảng. Trả (id ngành, [id loại hình], [id học vụ])."""
    ts = int(datetime.now().timestamp() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Dữ liệu nền (``seed_lead_dependencies``) chèn ngành với id TƯỜNG MINH, không đẩy sequence ⇒ tự chọn id kế tiếp.
            nid = (await s.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM major_program"))).scalar_one()
            mp = models.MajorProgram(
                id=nid, name=f"Ngành thử xoá {ts}", code=f"G2FX{ts}", degree_level="Cao đẳng", unit_id=unit_id,
                is_active=True,
            )
            s.add(mp)
            await s.flush()
            loai_hinh, hoc_vu_ids = [], []
            for i, (nam, chi_tieu, hoat_dong) in enumerate(dong):
                ot = models.ConfigOfferingType(code=f"g2fx_{ts}_{i}", name=f"G2FX {ts} {i}", display_order=i + 1)
                s.add(ot)
                await s.flush()
                po = models.ProgramOffering(
                    offering_type=f"G2FX_{ts}_{i}", program_id=mp.id, offering_type_id=ot.id,
                    is_active=hoat_dong, duration_semesters=6,
                )
                s.add(po)
                await s.flush()
                ai = models.OfferingAcademicInfo(
                    offering_id=po.id, academic_year=nam, is_published=True, annual_admission_quota=chi_tieu
                )
                s.add(ai)
                await s.flush()
                loai_hinh.append(po.id)
                hoc_vu_ids.append(ai.id)
            nganh_id = mp.id
    return nganh_id, loai_hinh, hoc_vu_ids


async def _trang_thai(nganh_id: int, loai_hinh, hoc_vu_ids) -> tuple:
    """(ngành hoạt động, [loại hình hoạt động], [học vụ đã xoá mềm])."""
    nganh = (await _sql("SELECT is_active FROM major_program WHERE id = :i", i=nganh_id)).scalar_one()
    return nganh, [await _loai_hinh_hoat_dong(o) for o in loai_hinh], [await _da_xoa(h) for h in hoc_vu_ids]


async def _xoa_nganh(s, admin_user_in_db, nganh_id):
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.delete_major_program(s, nganh_id, current_user=nguoi)


@pytest.mark.parametrize("chi_tieu", [50, 0], ids=["co_chi_tieu", "so_0"])
async def test_xoa_nganh_co_hoc_vu_co_chi_tieu_o_nam_da_khoa_409_khong_doi_gi(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, seed_lead_dependencies, chi_tieu
):
    """(a) Ngành có học vụ chỉ tiêu ``chi_tieu`` (50 / 0 — khác NULL) ở năm đã khoá ⇒ 409 như trigger; ngành, MỌI loại hình, MỌI
    học vụ giữ nguyên."""
    nganh, lh, hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True), (NAM, chi_tieu, True)])
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(NGANH % nganh, headers=admin_token_headers)
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _trang_thai(nganh, lh, hv) == (True, [True, True], [False, False])


async def test_xoa_nganh_chi_co_hoc_vu_chi_tieu_trong_o_nam_da_khoa_thi_xoa_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, seed_lead_dependencies
):
    """(b) Ở năm đã khoá ngành chỉ có học vụ chỉ tiêu TRỐNG (năm chưa khoá có chỉ tiêu cũng được) ⇒ 204; ngành, mọi loại hình tắt,
    mọi học vụ xoá mềm."""
    nganh, lh, hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM, None, True), (NAM - 1, 30, True)])
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(NGANH % nganh, headers=admin_token_headers)
    assert r.status_code == 204, r.text
    assert await _trang_thai(nganh, lh, hv) == (False, [False, False], [True, True])


async def test_xoa_nganh_nhieu_loai_hinh_mot_bi_chan_thi_khong_doi_gi(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, seed_lead_dependencies
):
    """(c) Bốn loại hình, chỉ MỘT (ở giữa theo id) có học vụ chỉ tiêu ở năm đã khoá ⇒ 409; KHÔNG loại hình / học vụ nào đổi."""
    nganh, lh, hv = await _nganh_rieng(
        seed_lead_dependencies["unit_id"],
        [(NAM, None, True), (NAM - 1, 20, True), (NAM, 40, True), (NAM, None, True)],
    )
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(NGANH % nganh, headers=admin_token_headers)
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _trang_thai(nganh, lh, hv) == (True, [True] * 4, [False] * 4)


async def test_xoa_nganh_loai_hinh_dang_ngung_co_chi_tieu_o_nam_da_khoa_van_409(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, seed_lead_dependencies
):
    """Owner chốt 20-11: xoá ngành tính CẢ loại hình đang "Ngừng" (học vụ của nó vẫn hiệu lực) ⇒ học vụ có chỉ tiêu dưới loại hình
    ngừng ở năm đã khoá vẫn chặn 409."""
    nganh, lh, hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True), (NAM, 50, False)])
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(NGANH % nganh, headers=admin_token_headers)
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _trang_thai(nganh, lh, hv) == (True, [True, False], [False, False])


@pytest.mark.parametrize("hoat_dong", [True, False], ids=["loai_hinh_hoat_dong", "loai_hinh_dang_ngung"])
async def test_xoa_nganh_nam_chua_khoa_ma_tran_chi_tieu_khong_con_tinh_hoc_vu_cua_nganh(
    client: AsyncClient, admin_token_headers, seed_lead_dependencies, hoat_dong
):
    """(d) Năm chưa khoá: xoá ngành ⇒ ma trận chỉ tiêu (``QuotaMatrixService.get_matrix``) KHÔNG còn tính học vụ của ngành — kể
    cả học vụ dưới loại hình đang "Ngừng". Trước đây chỉ tắt loại hình, học vụ vẫn hiệu lực ⇒ ma trận vẫn cộng."""
    from app.services.quota_matrix_service import QuotaMatrixService

    nganh, _lh, hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM, 20, hoat_dong), (NAM, 30, True)])

    async def _hang() -> set:
        async with AsyncSessionLocal() as s:
            return {r.academic_info_id for r in (await QuotaMatrixService(s).get_matrix(NAM)).rows}

    assert set(hv) <= await _hang()  # đối chứng: trước khi xoá, ma trận có tính
    r = await client.delete(NGANH % nganh, headers=admin_token_headers)
    assert r.status_code == 204, r.text
    assert not (set(hv) & await _hang())


async def test_hai_phien_tao_hoc_vu_dang_do_thi_xoa_nganh_cho_roi_xoa_ca_hoc_vu_moi(admin_user_in_db, seed_lead_dependencies):
    """Phiên 1 tạo học vụ năm MỚI dưới một loại hình của ngành, CHƯA commit ⇒ xoá ngành CHỜ đúng phiên 1 (khoá dòng loại hình);
    phiên 1 commit ⇒ xoá ngành thấy học vụ mới, xoá luôn ⇒ không còn học vụ hiệu lực nào dưới ngành đã xoá."""
    nganh, lh, hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True), (NAM - 1, None, True)])
    o = lh[1]
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _tao(admin_user_in_db, o, None, s=s1)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_nganh(s2, admin_user_in_db, nganh))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá ngành KHÔNG chờ lệnh tạo học vụ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert await _so_hoc_vu(o, NAM) == 1
    assert (await _so_hoc_vu_con_hieu_luc(o), await _trang_thai(nganh, lh, hv)) == (0, (False, [False, False], [True, True]))


async def test_hai_phien_xoa_nganh_dang_do_thi_tao_hoc_vu_cho_roi_409(admin_user_in_db, seed_lead_dependencies):
    """Thứ tự ngược: phiên 1 xoá ngành, CHƯA commit ⇒ tạo học vụ dưới loại hình của ngành CHỜ phiên 1; commit ⇒ tạo 409 (loại
    hình đã tắt), 0 dòng mới."""
    from app.services.organization_service import ProgramOfferingInactive

    nganh, lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True)])
    o = lh[0]
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _xoa_nganh(s1, admin_user_in_db, nganh)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_tao(admin_user_in_db, o, None, s=s2))
        assert await _bi_chan_boi(pid2, pid1, viec), "tạo học vụ KHÔNG chờ lệnh xoá ngành đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(ProgramOfferingInactive):
            await asyncio.wait_for(viec, 10)
    finally:
        await _dong(s1, s2, viec)
    assert await _so_hoc_vu(o, NAM) == 0


# ══ 3 — Khôi phục ↔ xoá loại hình, hai phiên, trạng thái cuối ════════════════════════════════════════════════════════
async def _khoi_phuc(s, admin_user_in_db, ai):
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.restore_academic_info(s, ai, current_user=nguoi)


async def _xoa_hoc_vu(s, admin_user_in_db, ai):
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.delete_academic_info(s, ai, current_user=nguoi)


async def test_hai_phien_xoa_loai_hinh_dang_do_thi_khoi_phuc_cho_roi_409_trang_thai_cuoi(admin_user_in_db, hoc_vu):
    """Phiên 1 xoá loại hình ``o`` (của ``e`` đã xoá mềm), CHƯA commit ⇒ khôi phục ``e`` chờ phiên 1; commit ⇒ khôi phục 409
    ``ProgramOfferingInactive``. TRẠNG THÁI CUỐI: loại hình tắt, 0 học vụ hiệu lực dưới nó."""
    from app.services.organization_service import ProgramOfferingInactive

    e = hoc_vu["2025"]
    o = await _offering_cua(e)
    await _sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=e)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    loi = None
    try:
        pid1 = await _pid(s1)
        await _xoa_loai_hinh(s1, admin_user_in_db, o)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_khoi_phuc(s2, admin_user_in_db, e))
        assert await _bi_chan_boi(pid2, pid1, viec), "khôi phục KHÔNG chờ lệnh xoá loại hình đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        try:
            await asyncio.wait_for(viec, 10)
        except ProgramOfferingInactive as x:
            loi = x
        await s2.commit()  # khôi phục lọt qua (nếu có) được commit ⇒ trạng thái cuối lộ ra
    finally:
        await _dong(s1, s2, viec)
    assert (await _loai_hinh_hoat_dong(o), await _so_hoc_vu_con_hieu_luc(o)) == (False, 0)
    assert isinstance(loi, ProgramOfferingInactive)


async def test_hai_phien_khoi_phuc_dang_do_thi_xoa_loai_hinh_cho_roi_xoa_ca_hoc_vu_vua_khoi_phuc(admin_user_in_db, hoc_vu):
    """Thứ tự ngược: phiên 1 khôi phục ``e``, CHƯA commit ⇒ xoá loại hình ``o`` chờ phiên 1; commit ⇒ xoá thấy ``e`` đã hiệu lực,
    xoá luôn. TRẠNG THÁI CUỐI: loại hình tắt, 0 học vụ hiệu lực."""
    e = hoc_vu["2025"]
    o = await _offering_cua(e)
    await _sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=e)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _khoi_phuc(s1, admin_user_in_db, e)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_loai_hinh(s2, admin_user_in_db, o))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá loại hình KHÔNG chờ lệnh khôi phục đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert (await _loai_hinh_hoat_dong(o), await _so_hoc_vu_con_hieu_luc(o)) == (False, 0)


# ══ 4 — Dây chuyền khoá dòng học vụ theo id: không vòng chờ với Phê duyệt hàng loạt ══════════════════════════════════
async def _ctid(ai: int) -> tuple:
    trang, dong = (
        await _sql("SELECT ctid::text FROM offering_academic_info WHERE id = :i", i=ai)
    ).scalar_one().strip("()").split(",")
    return int(trang), int(dong)


async def test_day_chuyen_xoa_loai_hinh_khoa_dong_hoc_vu_theo_id_khong_vong_cho_voi_lock_quota_cells(
    admin_user_in_db, hoc_vu
):
    """Loại hình ``o`` có hai học vụ ``e`` < ``x`` (id) mà ``e`` nằm SAU ``x`` về vị trí vật lý (ctid) — một câu UPDATE theo
    ``offering_id`` (quét tuần tự hay chỉ mục: khoá trùng thì theo ctid) chạm ``x`` TRƯỚC ``e``. Phiên A làm như
    ``lock_quota_cells`` (``FOR UPDATE`` id tăng dần): giữ ``e``; phiên B xoá loại hình ⇒ chờ A ở ``e``; A xin tiếp ``x``. Dây chuyền
    khoá dòng bằng MỘT câu ``ORDER BY id`` ⇒ B chưa giữ ``x`` ⇒ A lấy ngay, không ``40P01``; B xong sau A. (A lấy hai dòng ở hai
    câu để dựng ĐÚNG xen kẽ mà một câu ``WHERE id IN (e, x) ORDER BY id FOR UPDATE`` gặp khi có tranh chấp.)"""
    from sqlalchemy.exc import DBAPIError

    from app.repositories.council_decision_repository import db_error_codes
    from app.services.quota_occupancy_service import lock_quota_cells

    e = hoc_vu["2025"]
    o = await _offering_cua(e)
    x = (
        await _sql(
            "INSERT INTO offering_academic_info (offering_id, academic_year, is_published, is_deleted, annual_admission_quota) "
            "VALUES (:o, :y, false, false, NULL) RETURNING id",
            o=o, y=NAM - 2,
        )
    ).scalar_one()
    assert e < x
    for _ in range(20):  # tiền điều kiện vật lý: dời phiên bản dòng e ra SAU x
        if await _ctid(e) > await _ctid(x):
            break
        await _sql("UPDATE offering_academic_info SET updated_at = now() WHERE id = :i", i=e)
    assert await _ctid(e) > await _ctid(x), "không dựng được tiền điều kiện: e phải nằm sau x về vị trí vật lý"

    sa, sb = AsyncSessionLocal(), AsyncSessionLocal()
    viec = viec_a = None
    try:
        pid_a = await _pid(sa)
        await lock_quota_cells(sa, [e], [])
        pid_b = await _pid(sb)
        viec = asyncio.ensure_future(_xoa_loai_hinh(sb, admin_user_in_db, o))
        assert await _bi_chan_boi(pid_b, pid_a, viec), "xoá loại hình KHÔNG chờ dòng e đang bị khoá — %s" % _mo_ta(viec)
        viec_a = asyncio.ensure_future(lock_quota_cells(sa, [x], []))
        try:
            await asyncio.wait_for(viec_a, 10)
        except DBAPIError as loi:
            pytest.fail("phiên A (lock_quota_cells) bị huỷ %s — vòng chờ với dây chuyền xoá" % (db_error_codes(loi),))
        await sa.commit()
        try:
            await asyncio.wait_for(viec, 10)
        except DBAPIError as loi:
            pytest.fail("phiên B (xoá loại hình) bị huỷ %s — vòng chờ với lock_quota_cells" % (db_error_codes(loi),))
        await sb.commit()
    finally:
        if viec_a is not None and not viec_a.done():
            try:
                await asyncio.wait_for(viec_a, 10)
            except (Exception, asyncio.CancelledError):
                pass
        await _dong(sa, sb, viec)
    assert (await _loai_hinh_hoat_dong(o), await _so_hoc_vu_con_hieu_luc(o)) == (False, 0)


# ══ 5 — Nạp lại đối tượng ORM sau khoá năm ═══════════════════════════════════════════════════════════════════════════
async def test_hai_phien_put_bang_dang_ghi_60_thi_patch_50_cho_roi_ghi_dung_50(admin_user_in_db, hoc_vu):
    """PUT bảng đang giữ khoá năm, ghi ``a`` = 60, CHƯA commit; PATCH ``a`` = 50 nạp ``a`` (= 50, ảnh cũ) rồi chờ khoá năm; PUT
    commit ⇒ PATCH phải GHI 50 (CSDL = 50). Không nạp lại: gán 50 = ảnh nạp ⇒ SQLAlchemy bỏ cột ⇒ CSDL giữ 60 mà PATCH vẫn 200."""
    from app import schemas
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc
    from app.services import organization_service

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    a = hoc_vu["2026"][0]
    assert await _chi_tieu(a) == 50
    nhom = _than(1, hoc_vu)["groups"]
    nhom[0]["members"][0]["annual_admission_quota"] = 60
    than = QuotaTablePut(version=1, quota_fingerprint=await _dau(), groups=nhom)
    s2, s1 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid2 = await _pid(s2)
        await svc.replace_quota_table(s2, NAM, than, actor_id=admin_user_in_db["id"])  # a = 60, giữ khoá năm, CHƯA commit
        pid1 = await _pid(s1)
        nguoi = await s1.get(models.User, admin_user_in_db["id"])
        viec = asyncio.ensure_future(
            organization_service.update_academic_info(
                s1,
                academic_info_id=a,
                academic_info_in=schemas.OfferingAcademicInfoUpdate(annual_admission_quota=50),
                current_user=nguoi,
                updated_by_user_id=nguoi.id,
            )
        )
        assert await _bi_chan_boi(pid1, pid2, viec), "PATCH KHÔNG chờ PUT đang giữ khoá năm — %s" % _mo_ta(viec)
        await s2.commit()
        await asyncio.wait_for(viec, 10)
        await s1.commit()
    finally:
        await _dong(s2, s1, viec)
    assert await _chi_tieu(a) == 50


async def test_hai_phien_khoi_phuc_dang_do_thi_xoa_hoc_vu_cho_roi_xoa_that(admin_user_in_db, hoc_vu, dong_ho_trong_nam):
    """Học vụ ``d`` đang xoá mềm. Phiên 1 khôi phục ``d``, CHƯA commit; phiên 2 xoá ``d`` nạp ``d`` (đã xoá — ảnh cũ) rồi chờ khoá
    năm; phiên 1 commit ⇒ phiên 2 phải GHI cờ xoá (cuối cùng ``d`` đã xoá). Không nạp lại: gán ``True`` = ảnh nạp ⇒ không ghi cờ."""
    d = hoc_vu["2026"][3]
    await _sql("UPDATE offering_academic_info SET is_deleted = true WHERE id = :i", i=d)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _khoi_phuc(s1, admin_user_in_db, d)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_hoc_vu(s2, admin_user_in_db, d))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá học vụ KHÔNG chờ lệnh khôi phục đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert await _da_xoa(d) is True


async def test_hai_phien_xoa_hoc_vu_dang_do_thi_khoi_phuc_cho_roi_khoi_phuc_that(admin_user_in_db, hoc_vu, dong_ho_trong_nam):
    """Phiên 1 xoá ``d``, CHƯA commit; phiên 2 khôi phục ``d`` nạp ``d`` (chưa xoá — ảnh cũ) rồi chờ khoá năm; phiên 1 commit ⇒
    phiên 2 phải GHI cờ khôi phục (cuối cùng ``d`` hiệu lực). Không nạp lại: gán ``False`` = ảnh nạp ⇒ không ghi cờ, vẫn 200."""
    d = hoc_vu["2026"][3]
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _xoa_hoc_vu(s1, admin_user_in_db, d)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_khoi_phuc(s2, admin_user_in_db, d))
        assert await _bi_chan_boi(pid2, pid1, viec), "khôi phục KHÔNG chờ lệnh xoá đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert await _da_xoa(d) is False


# ══ 6 — PATCH "academic_year": null ══════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("duong", ["/api/admin/academic-info/%d", "/api/academic-info/%d"], ids=["trang_admin", "trang_cu"])
async def test_patch_nam_hoc_null_tuong_minh_422(client: AsyncClient, admin_token_headers, hoc_vu, duong):
    d = hoc_vu["2026"][3]
    r = await client.patch(duong % d, headers=admin_token_headers, json={"academic_year": None})
    assert r.status_code == 422, r.text
    assert (await _sql("SELECT academic_year FROM offering_academic_info WHERE id = :i", i=d)).scalar_one() == NAM


# ══ 7 — Xoá loại hình: học vụ vừa đổi năm ở nơi khác ⇒ 409 ═══════════════════════════════════════════════════════════
async def test_hai_phien_doi_nam_hoc_vu_dang_do_thi_xoa_loai_hinh_cho_roi_409_tai_lai(admin_user_in_db, hoc_vu):
    """Phiên 1 dời ``e`` từ năm ``NAM - 1`` sang ``NAM - 2`` (PATCH), CHƯA commit; phiên 2 xoá loại hình ``o`` đọc tập năm {NAM-1}
    rồi chờ khoá năm ấy; phiên 1 commit ⇒ đọc lại dưới khoá thấy năm NGOÀI tập đã khoá ⇒ 409 tải lại, không xoá gì."""
    from app import schemas
    from app.services import organization_service
    from app.utils.exceptions import ConflictError

    e = hoc_vu["2025"]
    o = await _offering_cua(e)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        nguoi = await s1.get(models.User, admin_user_in_db["id"])
        await organization_service.update_academic_info(
            s1,
            academic_info_id=e,
            academic_info_in=schemas.OfferingAcademicInfoUpdate(academic_year=NAM - 2),
            current_user=nguoi,
            updated_by_user_id=nguoi.id,
        )  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_loai_hinh(s2, admin_user_in_db, o))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá loại hình KHÔNG chờ lệnh dời năm đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(ConflictError) as loi:
            await asyncio.wait_for(viec, 10)
        assert "vừa đổi năm" in str(loi.value.detail)
    finally:
        await _dong(s1, s2, viec)
    dong = (await _sql("SELECT academic_year, is_deleted FROM offering_academic_info WHERE id = :i", i=e)).one()
    assert (tuple(dong), await _loai_hinh_hoat_dong(o)) == ((NAM - 2, False), True)


# ══ 8 — Codex lượt 4: ngành Ngừng / đã xoá ⇒ không tạo, không bật lại loại hình; tạo / bật lại / xoá ngành xếp hàng ════
# Owner chốt 20-11 (cùng khuôn luật loại hình → học vụ): ``major_program.is_active = false`` ("Ngừng" và "Xoá ngành" chung cờ) ⇒
# tạo loại hình mới / bật lại loại hình (ngừng → hoạt động) 409 ``MAJOR_PROGRAM_INACTIVE``. Ba lệnh lấy khoá DÒNG ngành
# ``FOR NO KEY UPDATE`` đầu tiên; xoá ngành lấy nó TRƯỚC khi liệt kê loại hình ⇒ không loại hình nào chen vào sau bước liệt kê.
LOAI_HINH_NGANH = "/api/admin/programs/%d/offerings"
SUA_LOAI_HINH = "/api/admin/offerings/%d"
NGANH_NGUNG_409 = {
    "detail": "Ngành đang ngừng / đã xoá — bật lại ngành trước khi tạo / bật lại loại hình đào tạo.",
    "error_code": "MAJOR_PROGRAM_INACTIVE",
}


async def _dem_loai_hinh(nganh_id: int) -> tuple:
    """(số loại hình của ngành, số loại hình đang hoạt động)."""
    return tuple(
        (
            await _sql(
                "SELECT count(*), count(*) FILTER (WHERE is_active) FROM program_offering WHERE program_id = :n", n=nganh_id
            )
        ).one()
    )


def _ten_loai_hinh_moi() -> str:
    return "G2FN_%d" % int(datetime.now().timestamp() * 1_000_000)


async def _tao_loai_hinh(s, admin_user_in_db, nganh_id):
    from app import schemas
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.create_program_offering(
        s,
        schemas.ProgramOfferingCreate(offering_type=_ten_loai_hinh_moi(), program_id=nganh_id, duration_semesters=6),
        current_user=nguoi,
    )


async def _bat_lai_loai_hinh(s, admin_user_in_db, offering_id):
    from app import schemas
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.update_program_offering(
        s, offering_id, schemas.ProgramOfferingUpdate(is_active=True), current_user=nguoi
    )


async def _tat_nganh(client: AsyncClient, admin_token_headers, nganh_id: int, cach: str) -> None:
    """"Ngừng ngành" (PUT ``is_active = false`` — KHÔNG dây chuyền) hoặc "Xoá ngành" (DELETE — dây chuyền)."""
    if cach == "ngung":
        r = await client.put(NGANH % nganh_id, headers=admin_token_headers, json={"is_active": False})
        assert r.status_code == 200, r.text
    else:
        r = await client.delete(NGANH % nganh_id, headers=admin_token_headers)
        assert r.status_code == 204, r.text
    assert (await _sql("SELECT is_active FROM major_program WHERE id = :i", i=nganh_id)).scalar_one() is False


async def test_hai_phien_tao_loai_hinh_dang_do_thi_xoa_nganh_cho_roi_xoa_ca_loai_hinh_moi(
    admin_user_in_db, seed_lead_dependencies
):
    """Phiên 1 tạo loại hình mới cho ngành, CHƯA commit ⇒ xoá ngành CHỜ đúng phiên 1 (khoá dòng ngành — chèn loại hình chỉ lấy
    ``FOR KEY SHARE`` trên ngành, không chặn được ai); phiên 1 commit ⇒ xoá ngành liệt kê SAU khi có khoá, thấy loại hình mới, tắt
    luôn ⇒ ngành đã xoá, 0 loại hình hoạt động (2 loại hình: cũ + mới)."""
    nganh, _lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True)])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _tao_loai_hinh(s1, admin_user_in_db, nganh)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_nganh(s2, admin_user_in_db, nganh))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá ngành KHÔNG chờ lệnh tạo loại hình đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    nganh_hd = (await _sql("SELECT is_active FROM major_program WHERE id = :i", i=nganh)).scalar_one()
    assert (nganh_hd, await _dem_loai_hinh(nganh)) == (False, (2, 0))


async def test_hai_phien_xoa_nganh_dang_do_thi_tao_loai_hinh_cho_roi_409(admin_user_in_db, seed_lead_dependencies):
    """Thứ tự ngược: phiên 1 xoá ngành, CHƯA commit ⇒ tạo loại hình CHỜ phiên 1; commit ⇒ tạo đọc ``is_active`` DƯỚI khoá ⇒ 409
    ``MajorProgramInactive``; không dòng loại hình mới, 0 loại hình hoạt động."""
    from app.services.organization_service import MajorProgramInactive

    nganh, _lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True)])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _xoa_nganh(s1, admin_user_in_db, nganh)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_tao_loai_hinh(s2, admin_user_in_db, nganh))
        assert await _bi_chan_boi(pid2, pid1, viec), "tạo loại hình KHÔNG chờ lệnh xoá ngành đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(MajorProgramInactive):
            await asyncio.wait_for(viec, 10)
    finally:
        await _dong(s1, s2, viec)
    assert await _dem_loai_hinh(nganh) == (1, 0)


async def test_hai_phien_xoa_nganh_dang_do_thi_bat_lai_loai_hinh_cho_roi_409(admin_user_in_db, seed_lead_dependencies):
    """Phiên 1 xoá ngành, CHƯA commit; phiên 2 gửi ``is_active = true`` cho loại hình ĐANG hoạt động (ảnh nạp: hoạt động ⇒ tưởng
    "giữ nguyên") rồi chờ khoá ngành; phiên 1 commit ⇒ nạp lại dưới khoá thấy loại hình đã bị tắt ⇒ đây là BẬT LẠI ⇒ 409.
    Không khoá ngành hoặc không nạp lại ⇒ loại hình hoạt động lại dưới ngành đã xoá."""
    from app.services.organization_service import MajorProgramInactive

    nganh, lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True)])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    loi = None
    try:
        pid1 = await _pid(s1)
        await _xoa_nganh(s1, admin_user_in_db, nganh)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_bat_lai_loai_hinh(s2, admin_user_in_db, lh[0]))
        assert await _bi_chan_boi(pid2, pid1, viec), "bật lại loại hình KHÔNG chờ lệnh xoá ngành đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        try:
            await asyncio.wait_for(viec, 10)
        except MajorProgramInactive as x:
            loi = x
        await s2.commit()  # bật lại lọt qua (nếu có) được commit ⇒ trạng thái cuối lộ ra
    finally:
        await _dong(s1, s2, viec)
    assert await _dem_loai_hinh(nganh) == (1, 0)
    assert isinstance(loi, MajorProgramInactive)


async def test_hai_phien_bat_lai_loai_hinh_dang_do_thi_xoa_nganh_cho_roi_tat_ca(admin_user_in_db, seed_lead_dependencies):
    """Thứ tự ngược: phiên 1 bật lại loại hình đang ngừng (ngành hoạt động), CHƯA commit ⇒ xoá ngành chờ phiên 1; commit ⇒ xoá ngành
    tắt luôn loại hình vừa bật ⇒ 0 loại hình hoạt động dưới ngành đã xoá."""
    nganh, lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, False)])
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _bat_lai_loai_hinh(s1, admin_user_in_db, lh[0])  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_xoa_nganh(s2, admin_user_in_db, nganh))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá ngành KHÔNG chờ lệnh bật lại loại hình đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        await asyncio.wait_for(viec, 10)
        await s2.commit()
    finally:
        await _dong(s1, s2, viec)
    assert await _dem_loai_hinh(nganh) == (1, 0)


@pytest.mark.parametrize("cach", ["ngung", "da_xoa"])
async def test_tao_loai_hinh_duoi_nganh_ngung_hoac_da_xoa_409(
    client: AsyncClient, admin_token_headers, seed_lead_dependencies, cach
):
    """Route THẬT ``POST /api/admin/programs/{id}/offerings``: ngành "Ngừng" (PUT) hoặc đã xoá (DELETE) ⇒ 409, không dòng mới."""
    nganh, _lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, True)])
    await _tat_nganh(client, admin_token_headers, nganh, cach)
    truoc = await _dem_loai_hinh(nganh)
    r = await client.post(
        LOAI_HINH_NGANH % nganh,
        headers=admin_token_headers,
        json={"offering_type": _ten_loai_hinh_moi(), "program_id": nganh, "duration_semesters": 6},
    )
    assert (r.status_code, r.json()) == (409, NGANH_NGUNG_409), r.text
    assert await _dem_loai_hinh(nganh) == truoc


@pytest.mark.parametrize("cach", ["ngung", "da_xoa"])
async def test_bat_lai_loai_hinh_duoi_nganh_ngung_hoac_da_xoa_409_van_tat(
    client: AsyncClient, admin_token_headers, seed_lead_dependencies, cach
):
    """Route THẬT ``PUT /api/admin/offerings/{id}``: loại hình đang ngừng, ngành "Ngừng" hoặc đã xoá ⇒ gửi ``is_active = true``
    ⇒ 409, loại hình vẫn tắt."""
    nganh, lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, False)])
    await _tat_nganh(client, admin_token_headers, nganh, cach)
    r = await client.put(SUA_LOAI_HINH % lh[0], headers=admin_token_headers, json={"is_active": True})
    assert (r.status_code, r.json()) == (409, NGANH_NGUNG_409), r.text
    assert await _loai_hinh_hoat_dong(lh[0]) is False


@pytest.mark.parametrize(
    "nganh_ngung, loai_hinh_hoat_dong",
    [(True, True), (False, False)],
    ids=["nganh_ngung_loai_hinh_dang_hoat_dong_sua_truong_khac", "nganh_hoat_dong_bat_lai_loai_hinh"],
)
async def test_sua_loai_hinh_khong_phai_bat_lai_duoi_nganh_ngung_van_duoc(
    client: AsyncClient, admin_token_headers, seed_lead_dependencies, nganh_ngung, loai_hinh_hoat_dong
):
    """Không chặn quá tay: form sửa loại hình LUÔN gửi ``is_active``. (1) Ngành "Ngừng" (không dây chuyền) + loại hình đang hoạt
    động: lưu ``is_active = true`` kèm trường khác ⇒ 200 (không phải bật lại). (2) Ngành hoạt động: bật lại loại hình ⇒ 200."""
    nganh, lh, _hv = await _nganh_rieng(seed_lead_dependencies["unit_id"], [(NAM - 1, None, loai_hinh_hoat_dong)])
    if nganh_ngung:
        await _tat_nganh(client, admin_token_headers, nganh, "ngung")
        assert await _loai_hinh_hoat_dong(lh[0]) is True  # đối chứng: "Ngừng ngành" không tắt loại hình
    r = await client.put(
        SUA_LOAI_HINH % lh[0], headers=admin_token_headers, json={"is_active": True, "duration_semesters": 8}
    )
    assert r.status_code == 200, r.text
    dong = (await _sql("SELECT is_active, duration_semesters FROM program_offering WHERE id = :i", i=lh[0])).one()
    assert tuple(dong) == (True, 8)
