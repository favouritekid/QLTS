"""GĐ2-F1 — luật C (owner chốt 19-11): khi bảng chỉ tiêu năm đã khoá, ma trận chỉ tiêu và tập ngành có hiệu lực phải đứng yên ⇒
KHÔNG xoá mềm / khôi phục học vụ CÓ chỉ tiêu (khác NULL — kể cả 0); học vụ chỉ tiêu trống vẫn xoá / khôi phục được; muốn làm thì
Admin mở khoá (lý do, lưu vết) rồi khoá lại. Áp cho MỌI đường: xoá / khôi phục một học vụ, dây chuyền xoá loại hình đào tạo.

Tầng chủ sở hữu: trigger CSDL (theo dõi ``is_deleted``) — ca "SQL tay" đi thẳng CSDL. Dịch vụ lấy khoá năm TRƯỚC khi chạm dòng
rồi kiểm trước, cùng thân 409. Xoá / khôi phục đi qua ĐÚNG route HTTP (đo wiring); dữ liệu nền dựng bằng SQL / dịch vụ (route
POST tạo học vụ còn lỗi có từ trước — ngoài phạm vi). Ca hai phiên dừng lệnh xoá / khôi phục NGAY SAU khoá năm (trước khi ghi
dòng) để đo đúng khoá năm, không lẫn với khoá dòng. Mỗi ca kiểm MỘT bất biến; không dữ liệu thật.

Lưu ý thời gian: dịch vụ cấm xoá học vụ của năm QUÁ KHỨ (luật có từ trước) ⇒ các ca xoá dùng năm ``NAM`` (2026).
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.models.admission_quota_ddl import SQLSTATE_QUOTA_TABLE_LOCKED
from tests.api.test_gd2a_bang_chi_tieu_api import (  # noqa: F401 — fixture dùng qua tên
    NAM,
    P,
    _bang,
    _bi_chan_boi,
    _dau,
    _dong,
    _mo_ta,
    _pid,
    _sql,
    _tao_bang_nhap,
    hoc_vu,
)
from tests.api.test_gd2f_luat_b_bang_khoa_api import KHOA_409, _bi_tu_choi_vi_khoa, _dat_chi_tieu, _khoa

pytestmark = pytest.mark.asyncio

XOA = "/api/admin/academic-info/%d"
XOA_CU = "/api/academic-info/%d"
KHOI_PHUC = "/api/admin/academic-info/%d/restore"
XOA_OFFERING = "/api/admin/offerings/%d"


async def _da_xoa(ai: int) -> bool:
    return (await _sql("SELECT is_deleted FROM offering_academic_info WHERE id = :i", i=ai)).scalar_one()


async def _dat_xoa(ai: int, x: bool) -> None:
    """Đặt cờ xoá mềm bằng SQL — chỉ gọi khi năm của dòng CHƯA khoá (dựng dữ liệu, trước ``_khoa``)."""
    await _sql("UPDATE offering_academic_info SET is_deleted = :x WHERE id = :i", x=x, i=ai)


async def _offering_hai_nam(hoc_vu, chi_tieu_2026) -> tuple:
    """Loại hình của học vụ ``e`` (năm 2025, chỉ tiêu trống) + thêm học vụ 2026 chỉ tiêu ``chi_tieu_2026`` (SQL, trước khi khoá)."""
    e = hoc_vu["2025"]
    o = (await _sql("SELECT offering_id FROM offering_academic_info WHERE id = :i", i=e)).scalar_one()
    moi = (
        await _sql(
            "INSERT INTO offering_academic_info (offering_id, academic_year, is_published, is_deleted, annual_admission_quota) "
            "VALUES (:o, :y, false, false, :q) RETURNING id",
            o=o, y=NAM, q=chi_tieu_2026,
        )
    ).scalar_one()
    return o, e, moi


async def _offering_con_hoat_dong(o: int) -> bool:
    return (await _sql("SELECT is_active FROM program_offering WHERE id = :o", o=o)).scalar_one()


# ══ Một học vụ — năm đã khoá ══════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("chi_tieu, bi_chan", [(50, True), (0, True), (None, False)], ids=["co_chi_tieu", "so_0", "trong"])
async def test_c_nam_khoa_xoa_hoc_vu(client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, chi_tieu, bi_chan):
    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, chi_tieu)
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(XOA % d, headers=admin_token_headers)
    if bi_chan:
        assert (r.status_code, r.json()) == (409, KHOA_409), r.text
        assert await _da_xoa(d) is False
    else:
        assert r.status_code == 204, r.text
        assert await _da_xoa(d) is True


@pytest.mark.parametrize("chi_tieu, bi_chan", [(50, True), (0, True), (None, False)], ids=["co_chi_tieu", "so_0", "trong"])
async def test_c_nam_khoa_khoi_phuc_hoc_vu(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, chi_tieu, bi_chan
):
    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, chi_tieu)
    await _dat_xoa(d, True)
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.post(KHOI_PHUC % d, headers=admin_token_headers)
    if bi_chan:
        assert (r.status_code, r.json()) == (409, KHOA_409), r.text
        assert await _da_xoa(d) is True
    else:
        assert r.status_code == 200, r.text
        assert await _da_xoa(d) is False


async def test_c_nam_khoa_xoa_qua_route_cu_cung_bi_chan(client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu):
    """Route xoá thứ hai (``DELETE /api/academic-info/{id}``) đi CÙNG hàm dịch vụ ⇒ cùng 409."""
    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 50)
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(XOA_CU % d, headers=admin_token_headers)
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _da_xoa(d) is False


@pytest.mark.parametrize("thao_tac", ["xoa", "khoi_phuc"])
async def test_c_nam_chua_khoa_xoa_khoi_phuc_hoc_vu_co_chi_tieu_thi_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, thao_tac
):
    """Đối chứng: bảng năm còn NHÁP ⇒ xoá / khôi phục học vụ có chỉ tiêu đều được."""
    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 50)
    if thao_tac == "khoi_phuc":
        await _dat_xoa(d, True)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    if thao_tac == "xoa":
        r = await client.delete(XOA % d, headers=admin_token_headers)
        assert r.status_code == 204, r.text
        assert await _da_xoa(d) is True
    else:
        r = await client.post(KHOI_PHUC % d, headers=admin_token_headers)
        assert r.status_code == 200, r.text
        assert await _da_xoa(d) is False


# ══ Dây chuyền xoá loại hình đào tạo ═════════════════════════════════════════════════════════════════════════════════
async def test_c_day_chuyen_xoa_offering_co_hoc_vu_chi_tieu_nam_khoa_409_khong_doi_gi(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    """Loại hình có học vụ 2025 (chỉ tiêu trống) + học vụ 2026 chỉ tiêu 50; bảng 2026 khoá ⇒ xoá loại hình 409, KHÔNG dòng nào đổi
    (kể cả học vụ năm khác) và loại hình vẫn hoạt động."""
    o, e, moi = await _offering_hai_nam(hoc_vu, 50)
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.delete(XOA_OFFERING % o, headers=admin_token_headers)
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert (await _da_xoa(e), await _da_xoa(moi), await _offering_con_hoat_dong(o)) == (False, False, True)


async def test_c_day_chuyen_xoa_offering_nam_chua_khoa_thi_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    """Đối chứng: bảng 2026 còn nháp ⇒ xoá loại hình được, mọi học vụ của nó xoá mềm."""
    o, e, moi = await _offering_hai_nam(hoc_vu, 50)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    r = await client.delete(XOA_OFFERING % o, headers=admin_token_headers)
    assert r.status_code == 204, r.text
    assert (await _da_xoa(e), await _da_xoa(moi), await _offering_con_hoat_dong(o)) == (True, True, False)


# ══ SQL tay — trigger tự chặn ════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "ca, sqlstate",
    [
        ("xoa_co_chi_tieu", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("xoa_chi_tieu_0", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("xoa_chi_tieu_trong", None),
        ("khoi_phuc_co_chi_tieu", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("khoi_phuc_chi_tieu_0", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("day_chuyen_offering", SQLSTATE_QUOTA_TABLE_LOCKED),
    ],
)
async def test_c_sql_tay_trigger_tu_chan(admin_user_in_db, hoc_vu, ca, sqlstate):
    from app.repositories.council_decision_repository import db_error_codes

    #: ca → (chỉ tiêu của d, d đã xoá mềm sẵn?, cờ xoá mềm đích)
    dung = {
        "xoa_co_chi_tieu": (50, False, True),
        "xoa_chi_tieu_0": (0, False, True),
        "xoa_chi_tieu_trong": (None, False, True),
        "khoi_phuc_co_chi_tieu": (50, True, False),
        "khoi_phuc_chi_tieu_0": (0, True, False),
    }
    d = hoc_vu["2026"][3]
    o = e = None
    if ca == "day_chuyen_offering":
        o, e, _moi = await _offering_hai_nam(hoc_vu, 50)
    else:
        chi_tieu, xoa_san, _ = dung[ca]
        await _dat_chi_tieu(d, chi_tieu)
        if xoa_san:
            await _dat_xoa(d, True)
    await _khoa(admin_user_in_db, hoc_vu)
    if ca == "day_chuyen_offering":
        cau, ts = "UPDATE offering_academic_info SET is_deleted = true WHERE offering_id = :o", {"o": o}
    else:
        cau, ts = "UPDATE offering_academic_info SET is_deleted = :x WHERE id = :i", {"x": dung[ca][2], "i": d}
    try:
        await _sql(cau, **ts)
        that = None
    except Exception as loi:  # noqa: BLE001 — đọc SQLSTATE bằng thuộc tính
        that = db_error_codes(loi)[0]
        if that is None:
            raise
    assert that == sqlstate
    if ca == "day_chuyen_offering":
        assert await _da_xoa(e) is False  # câu UPDATE hỏng ⇒ dòng năm khác cũng không đổi


# ══ Dấu chỉ tiêu mang cờ xoá mềm ═════════════════════════════════════════════════════════════════════════════════════
async def test_c_xoa_mem_nam_chua_khoa_lam_dau_doi_khoa_bang_dau_cu_409(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    """Bảng nháp; Admin mở bảng (dấu D0); xoá mềm học vụ ``d`` (chỉ tiêu trống — luật C cho phép) ⇒ dấu GET đổi; khoá bảng với D0
    ⇒ 409 ``quota_table_stale`` (khoá không chạy trên tập ngành có hiệu lực cũ)."""
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    g0 = await client.get(f"{P}/{NAM}", headers=admin_token_headers)
    assert g0.status_code == 200, g0.text
    d0 = g0.json()["quota_fingerprint"]
    d = hoc_vu["2026"][3]
    assert (await client.delete(XOA % d, headers=admin_token_headers)).status_code == 204
    assert (await client.get(f"{P}/{NAM}", headers=admin_token_headers)).json()["quota_fingerprint"] != d0
    r = await client.post(f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": 1, "quota_fingerprint": d0})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text
    assert tuple(await _bang()) == ("draft", 1)


# ══ Mở khoá (lý do, vết) ⇒ xoá ⇒ khoá lại ════════════════════════════════════════════════════════════════════════════
async def test_c_mo_khoa_co_ly_do_roi_xoa_roi_khoa_lai_duoc_va_co_vet(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 5)
    await _khoa(admin_user_in_db, hoc_vu)  # v2 locked
    ly_do = "Điều chỉnh tập ngành — thử luật C"
    r = await client.post(f"{P}/{NAM}/unlock", headers=admin_token_headers, json={"version": 2, "reason": ly_do})
    assert r.status_code == 200, r.text
    assert (await client.delete(XOA % d, headers=admin_token_headers)).status_code == 204
    g = (await client.get(f"{P}/{NAM}", headers=admin_token_headers)).json()
    r = await client.post(
        f"{P}/{NAM}/lock", headers=admin_token_headers, json={"version": g["version"], "quota_fingerprint": g["quota_fingerprint"]}
    )
    assert r.status_code == 200, r.text
    assert await _da_xoa(d) is True and (await _bang())[0] == "locked"
    vet = (
        await _sql(
            "SELECT action, reason FROM entity_audit_log WHERE entity_type = 'admission_quota_table' AND entity_id = :y "
            "AND action = 'unlocked'",
            y=NAM,
        )
    ).all()
    assert [tuple(v) for v in vet] == [("unlocked", ly_do)]


# ══ Hai phiên — khoá năm của đường xoá / khôi phục ════════════════════════════════════════════════════════════════════
def _gai_diem_dung(monkeypatch):
    """Dừng lệnh xoá / khôi phục NGAY SAU khoá năm, TRƯỚC khi ghi dòng: bọc lớp kiểm trước của dịch vụ (gọi sau khoá năm)."""
    from app.services import admission_quota_table_service as svc

    goc = svc.check_academic_info_delete_flag_allowed
    den, di_tiep = asyncio.Event(), asyncio.Event()

    async def tram(*a, **kw):
        den.set()
        await asyncio.wait_for(di_tiep.wait(), 30)
        return await goc(*a, **kw)

    monkeypatch.setattr(svc, "check_academic_info_delete_flag_allowed", tram)
    return den, di_tiep


async def _nguoi(s, admin_user_in_db):
    return await s.get(models.User, admin_user_in_db["id"])


@pytest.mark.parametrize("thao_tac", ["xoa", "khoi_phuc"])
async def test_c_hai_phien_xoa_khoi_phuc_dang_do_thi_khoa_bang_cho_roi_409(admin_user_in_db, hoc_vu, monkeypatch, thao_tac):
    """Phiên 1 xoá / khôi phục học vụ ``d`` (chỉ tiêu 5, bảng nháp) và DỪNG ngay sau khoá năm (chưa ghi dòng) ⇒ lệnh khoá bảng
    (dấu lúc mở) CHỜ đúng phiên 1 — khoá năm, không phải khoá dòng; phiên 1 ghi + commit ⇒ khoá bảng 409 (cờ xoá mềm đổi dấu)."""
    from app.services import admission_quota_table_service as svc
    from app.services import organization_service
    from app.services.admission_quota_table_service import QuotaTableConflict

    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 5)
    if thao_tac == "khoi_phuc":
        await _dat_xoa(d, True)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    dau = await _dau()
    den, di_tiep = _gai_diem_dung(monkeypatch)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec1 = viec2 = None
    try:
        pid1 = await _pid(s1)
        nguoi = await _nguoi(s1, admin_user_in_db)
        ham = organization_service.delete_academic_info if thao_tac == "xoa" else organization_service.restore_academic_info
        viec1 = asyncio.ensure_future(ham(s1, academic_info_id=d, current_user=nguoi))
        await asyncio.wait_for(den.wait(), 10)
        pid2 = await _pid(s2)
        viec2 = asyncio.ensure_future(
            svc.lock_quota_table(s2, NAM, expected_version=1, expected_quota_fingerprint=dau, actor_id=admin_user_in_db["id"])
        )
        assert await _bi_chan_boi(pid2, pid1, viec2), "khoá bảng KHÔNG chờ lệnh %s đang dở — %s" % (thao_tac, _mo_ta(viec2))
        di_tiep.set()
        await asyncio.wait_for(viec1, 10)
        await s1.commit()
        with pytest.raises(QuotaTableConflict) as loi:
            await asyncio.wait_for(viec2, 10)
        assert loi.value.reason_code == "quota_table_stale"
    finally:
        di_tiep.set()
        if viec1 is not None and not viec1.done():
            try:
                await asyncio.wait_for(viec1, 10)
            except (Exception, asyncio.CancelledError):
                pass
        await _dong(s1, s2, viec2)
    assert tuple(await _bang()) == ("draft", 1)
    assert await _da_xoa(d) is (thao_tac == "xoa")


async def test_c_hai_phien_khoa_bang_dang_do_thi_xoa_cho_roi_bi_chan(admin_user_in_db, hoc_vu):
    """Phiên 1 khoá bảng, CHƯA commit ⇒ xoá học vụ có chỉ tiêu CHỜ đúng phiên 1; phiên 1 commit ⇒ xoá bị từ chối vì bảng đã khoá;
    dòng không đổi."""
    from app.services import admission_quota_table_service as svc
    from app.services import organization_service

    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 5)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    dau = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await svc.lock_quota_table(s1, NAM, expected_version=1, expected_quota_fingerprint=dau, actor_id=admin_user_in_db["id"])
        pid2 = await _pid(s2)
        nguoi = await _nguoi(s2, admin_user_in_db)
        viec = asyncio.ensure_future(organization_service.delete_academic_info(s2, academic_info_id=d, current_user=nguoi))
        assert await _bi_chan_boi(pid2, pid1, viec), "xoá KHÔNG chờ lệnh khoá bảng đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(Exception) as loi:
            await asyncio.wait_for(viec, 10)
        assert _bi_tu_choi_vi_khoa(loi.value), repr(loi.value)
    finally:
        await _dong(s1, s2, viec)
    assert tuple(await _bang()) == ("locked", 2)
    assert await _da_xoa(d) is False
