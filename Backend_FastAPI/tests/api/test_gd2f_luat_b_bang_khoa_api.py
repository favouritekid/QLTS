"""GĐ2-F1 — luật B (owner chốt 19-11): khoá bảng chỉ tiêu năm ĐÓNG BĂNG chỉ tiêu nhưng vẫn cho cấu hình học phí sớm.

R1 tạo học vụ cho năm đã khoá: chỉ tiêu TRỐNG (NULL) ⇒ cho; có chỉ tiêu (kể cả 0 — trống ≠ 0) ⇒ chặn.
R2 nhập / đổi chỉ tiêu học vụ của năm đã khoá ⇒ chặn (GĐ2-A, ca ở ``test_gd2a_bang_chi_tieu_api.py``).
R3 chuyển năm học vụ có chỉ tiêu VÀO / RA năm đã khoá ⇒ chặn, kể cả khi con số không đổi; chỉ tiêu trống ⇒ cho.
R4 học vụ là thành viên nhóm của bảng chỉ tiêu ⇒ không đổi năm: 409 "gỡ khỏi nhóm trước" (bảng nháp lẫn bảng khoá).

Tầng chủ sở hữu R1–R3: trigger CSDL (``admission_quota_ddl.STATEMENTS_F1``) — các ca "SQL tay" đi thẳng CSDL chứng minh trigger
tự chặn. Dịch vụ kiểm trước (SAU khoá năm) cùng hình dạng phản hồi — ca hình dạng so thân 409 của hai tầng. Route POST học vụ
đang hỏng ở bước tuần tự hoá phản hồi THÀNH CÔNG (lỗi có từ trước, ngoài phạm vi) ⇒ ca tạo HỢP LỆ gọi hàm dịch vụ; ca tạo bị
CHẶN dùng route thật (lỗi ném trước bước ấy). Mỗi ca kiểm MỘT bất biến; không dữ liệu thật.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.models.admission_quota_ddl import MESSAGE_QUOTA_TABLE_LOCKED, SQLSTATE_QUOTA_TABLE_LOCKED
from tests.api.test_gd2a_bang_chi_tieu_api import (  # noqa: F401 — fixture dùng qua tên
    NAM,
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
from tests.api.test_gd2f_dau_chi_tieu_api import _offering_chua_co_nam, _so_hoc_vu

pytestmark = pytest.mark.asyncio

KHOA_409 = {"detail": MESSAGE_QUOTA_TABLE_LOCKED, "error_code": "QUOTA_TABLE_LOCKED"}
SUA = "/api/admin/academic-info"


async def _khoa(admin_user_in_db, hoc_vu) -> None:
    """Bảng 2026: nháp v1 (a = 50, b = 60 nhóm N1; c = 40 nhóm N2; d ngoài bảng) rồi KHOÁ (v2) qua đúng dịch vụ."""
    from app.services import admission_quota_table_service as svc

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    dau = await _dau()
    async with AsyncSessionLocal() as s:
        await svc.lock_quota_table(s, NAM, expected_version=1, expected_quota_fingerprint=dau, actor_id=admin_user_in_db["id"])
        await s.commit()
    assert tuple(await _bang()) == ("locked", 2)


async def _dong_hoc_vu(ai: int):
    return tuple(
        (await _sql("SELECT academic_year, annual_admission_quota FROM offering_academic_info WHERE id = :i", i=ai)).one()
    )


async def _dat_chi_tieu(ai: int, chi_tieu) -> None:
    """Đặt chỉ tiêu bằng SQL — chỉ gọi khi năm của dòng CHƯA khoá (dựng dữ liệu, trước ``_khoa``)."""
    await _sql("UPDATE offering_academic_info SET annual_admission_quota = :q WHERE id = :i", q=chi_tieu, i=ai)


async def _tao(admin_user_in_db, offering_id: int, chi_tieu, s=None):
    """Tạo học vụ năm ``NAM`` qua ĐÚNG hàm của route POST (``organization_service.create_academic_info``)."""
    from app import schemas
    from app.services import organization_service

    async def _chay(phien):
        nguoi = await phien.get(models.User, admin_user_in_db["id"])
        return await organization_service.create_academic_info(
            phien,
            academic_info_in=schemas.OfferingAcademicInfoCreate(
                offering_id=offering_id, academic_year=NAM, annual_admission_quota=chi_tieu, is_published=False
            ),
            current_user=nguoi,
            created_by_user_id=nguoi.id,
        )

    if s is not None:
        return await _chay(s)
    async with AsyncSessionLocal() as phien:
        await asyncio.wait_for(_chay(phien), 10)
        await phien.commit()


def _bi_tu_choi_vi_khoa(e: BaseException) -> bool:
    """Bị từ chối vì bảng năm đã khoá — ở lớp kiểm trước (dịch vụ) HAY ở trigger (SQLSTATE riêng): cùng một luật."""
    from app.repositories.council_decision_repository import db_error_codes
    from app.services.admission_quota_table_service import QuotaTableLockedWrite

    return isinstance(e, QuotaTableLockedWrite) or db_error_codes(e)[0] == SQLSTATE_QUOTA_TABLE_LOCKED


# ══ R1 — tạo học vụ cho năm đã khoá ══════════════════════════════════════════════════════════════════════════════════
async def test_r1_nam_khoa_tao_hoc_vu_chi_tieu_trong_thi_duoc(admin_user_in_db, hoc_vu):
    """Chỉ tiêu TRỐNG ⇒ cho (cấu hình học phí sớm cho năm đã khoá bảng)."""
    await _khoa(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    await _tao(admin_user_in_db, o, None)
    assert await _so_hoc_vu(o, NAM) == 1


@pytest.mark.parametrize("chi_tieu", [0, 50], ids=["so_0_khong_phai_trong", "co_chi_tieu"])
async def test_r1_nam_khoa_tao_hoc_vu_co_chi_tieu_bi_chan_409(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, chi_tieu
):
    """Có chỉ tiêu (kể cả 0) ⇒ route POST thật trả 409 cùng hình dạng lỗi trigger; không tạo dòng."""
    await _khoa(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    r = await client.post(
        f"/api/offerings/{o}/academic-info",
        headers=admin_token_headers,
        json={"offering_id": o, "academic_year": NAM, "annual_admission_quota": chi_tieu, "is_published": False},
    )
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _so_hoc_vu(o, NAM) == 0


# ══ R3 — chuyển năm học vụ có chỉ tiêu vào / ra năm đã khoá ══════════════════════════════════════════════════════════
async def test_r3_doi_hoc_vu_co_chi_tieu_vao_nam_khoa_409(client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu):
    e = hoc_vu["2025"]
    await _dat_chi_tieu(e, 7)
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.patch(f"{SUA}/{e}", headers=admin_token_headers, json={"academic_year": NAM})
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _dong_hoc_vu(e) == (NAM - 1, 7)


async def test_r3_doi_hoc_vu_co_chi_tieu_ra_khoi_nam_khoa_409(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    """Học vụ ``d`` NGOÀI bảng nhưng có chỉ tiêu, con số KHÔNG đổi — chỉ đổi năm ⇒ vẫn chặn."""
    d = hoc_vu["2026"][3]
    await _dat_chi_tieu(d, 5)
    await _khoa(admin_user_in_db, hoc_vu)
    r = await client.patch(f"{SUA}/{d}", headers=admin_token_headers, json={"academic_year": NAM - 1})
    assert (r.status_code, r.json()) == (409, KHOA_409), r.text
    assert await _dong_hoc_vu(d) == (NAM, 5)


@pytest.mark.parametrize("huong", ["vao", "ra"])
async def test_r3_doi_hoc_vu_chi_tieu_trong_qua_nam_khoa_thi_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, huong
):
    """Chỉ tiêu TRỐNG ⇒ chuyển vào / ra năm đã khoá được."""
    await _khoa(admin_user_in_db, hoc_vu)
    ai, dich = (hoc_vu["2025"], NAM) if huong == "vao" else (hoc_vu["2026"][3], NAM - 1)
    r = await client.patch(f"{SUA}/{ai}", headers=admin_token_headers, json={"academic_year": dich})
    assert r.status_code == 200, r.text
    assert await _dong_hoc_vu(ai) == (dich, None)


# ══ R4 — thành viên nhóm không đổi năm ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("trang_thai", ["nhap", "khoa"])
async def test_r4_thanh_vien_nhom_doi_nam_409_ro_rang(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, trang_thai
):
    """``a`` là thành viên nhóm N1 ⇒ 409 câu "gỡ khỏi nhóm trước" (không phải lỗi khoá ngoại). Bảng khoá: R4 báo TRƯỚC R3
    (việc người dùng phải làm trước tiên)."""
    if trang_thai == "nhap":
        await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    else:
        await _khoa(admin_user_in_db, hoc_vu)
    a = hoc_vu["2026"][0]
    r = await client.patch(f"{SUA}/{a}", headers=admin_token_headers, json={"academic_year": NAM - 1})
    assert r.status_code == 409, r.text
    assert r.json() == {
        "detail": "Học vụ đang nằm trong nhóm của bảng chỉ tiêu năm %d — gỡ khỏi nhóm trước." % NAM,
        "error_code": "ACADEMIC_INFO_IN_QUOTA_GROUP",
    }, r.text
    assert await _dong_hoc_vu(a) == (NAM, 50)


# ══ Đối chứng — năm CHƯA khoá (bảng nháp): mọi thao tác trên đều được ══════════════════════════════════════════════════
@pytest.mark.parametrize("thao_tac", ["tao_co_chi_tieu", "doi_vao_co_chi_tieu", "doi_ra_co_chi_tieu", "sua_chi_tieu"])
async def test_doi_chung_nam_chua_khoa_thi_duoc(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu, thao_tac
):
    e, d = hoc_vu["2025"], hoc_vu["2026"][3]
    await _dat_chi_tieu(e, 7)
    await _dat_chi_tieu(d, 5)
    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    if thao_tac == "tao_co_chi_tieu":
        o = await _offering_chua_co_nam(hoc_vu)
        await _tao(admin_user_in_db, o, 50)
        assert await _so_hoc_vu(o, NAM) == 1
        return
    ai, than, sau = {
        "doi_vao_co_chi_tieu": (e, {"academic_year": NAM}, (NAM, 7)),
        "doi_ra_co_chi_tieu": (d, {"academic_year": NAM - 1}, (NAM - 1, 5)),
        "sua_chi_tieu": (d, {"annual_admission_quota": 8}, (NAM, 8)),
    }[thao_tac]
    r = await client.patch(f"{SUA}/{ai}", headers=admin_token_headers, json=than)
    assert r.status_code == 200, r.text
    assert await _dong_hoc_vu(ai) == sau


# ══ SQL tay — trigger tự chặn, không qua dịch vụ ═════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "ca, sqlstate",
    [
        ("chen_co_chi_tieu", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("chen_chi_tieu_0", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("chen_chi_tieu_trong", None),
        ("doi_nam_vao_co_chi_tieu", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("doi_nam_ra_co_chi_tieu", SQLSTATE_QUOTA_TABLE_LOCKED),
        ("doi_nam_chi_tieu_trong", None),
    ],
)
async def test_sql_tay_trigger_tu_chan_theo_luat_b(admin_user_in_db, hoc_vu, ca, sqlstate):
    from app.repositories.council_decision_repository import db_error_codes

    e, d = hoc_vu["2025"], hoc_vu["2026"][3]
    if ca in ("doi_nam_vao_co_chi_tieu", "doi_nam_ra_co_chi_tieu"):
        await _dat_chi_tieu(e if ca == "doi_nam_vao_co_chi_tieu" else d, 7)
    await _khoa(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    chen = (
        "INSERT INTO offering_academic_info (offering_id, academic_year, is_published, is_deleted, annual_admission_quota) "
        "VALUES (:o, :y, false, false, :q)"
    )
    cau, ts = {
        "chen_co_chi_tieu": (chen, {"o": o, "y": NAM, "q": 50}),
        "chen_chi_tieu_0": (chen, {"o": o, "y": NAM, "q": 0}),
        "chen_chi_tieu_trong": (chen, {"o": o, "y": NAM, "q": None}),
        "doi_nam_vao_co_chi_tieu": ("UPDATE offering_academic_info SET academic_year = :y WHERE id = :i", {"y": NAM, "i": e}),
        "doi_nam_ra_co_chi_tieu": ("UPDATE offering_academic_info SET academic_year = :y WHERE id = :i", {"y": NAM - 1, "i": d}),
        "doi_nam_chi_tieu_trong": ("UPDATE offering_academic_info SET academic_year = :y WHERE id = :i", {"y": NAM - 1, "i": d}),
    }[ca]
    try:
        await _sql(cau, **ts)
        that = None
    except Exception as loi:  # noqa: BLE001 — đọc SQLSTATE bằng thuộc tính
        that = db_error_codes(loi)[0]
        if that is None:
            raise
    assert that == sqlstate


# ══ Hình dạng phản hồi — lớp kiểm trước ở dịch vụ == trigger qua handler ═════════════════════════════════════════════
async def test_lop_kiem_truoc_va_trigger_tra_cung_than_409(
    client: AsyncClient, admin_token_headers, admin_user_in_db, hoc_vu
):
    """Đổi chỉ tiêu học vụ năm khoá (R2 — dịch vụ KHÔNG kiểm trước ⇒ trigger ``QLC01`` → ``database_error_handler``) và tạo học
    vụ có chỉ tiêu (R1 — dịch vụ chặn trước) trả CÙNG mã + thân."""
    await _khoa(admin_user_in_db, hoc_vu)
    a = hoc_vu["2026"][0]
    o = await _offering_chua_co_nam(hoc_vu)
    r_trigger = await client.patch(f"{SUA}/{a}", headers=admin_token_headers, json={"annual_admission_quota": 51})
    r_dich_vu = await client.post(
        f"/api/offerings/{o}/academic-info",
        headers=admin_token_headers,
        json={"offering_id": o, "academic_year": NAM, "annual_admission_quota": 9, "is_published": False},
    )
    assert (r_trigger.status_code, r_trigger.json()) == (r_dich_vu.status_code, r_dich_vu.json()) == (409, KHOA_409)


# ══ Hai phiên — khoá bảng đang dở ↔ tạo học vụ có chỉ tiêu ═══════════════════════════════════════════════════════════
async def test_hai_phien_khoa_bang_dang_do_thi_tao_hoc_vu_co_chi_tieu_cho_roi_bi_tu_choi(admin_user_in_db, hoc_vu):
    """Phiên 1 khoá bảng, CHƯA commit ⇒ lệnh tạo học vụ có chỉ tiêu CHỜ đúng phiên 1 (khoá năm); phiên 1 commit ⇒ bị từ chối
    vì bảng đã khoá; không có dòng mới."""
    from app.services import admission_quota_table_service as svc

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    dau = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await svc.lock_quota_table(s1, NAM, expected_version=1, expected_quota_fingerprint=dau, actor_id=admin_user_in_db["id"])
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(_tao(admin_user_in_db, o, 9, s=s2))
        assert await _bi_chan_boi(pid2, pid1, viec), "tạo học vụ KHÔNG chờ lệnh khoá bảng đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(Exception) as loi:
            await asyncio.wait_for(viec, 10)
        assert _bi_tu_choi_vi_khoa(loi.value), repr(loi.value)
    finally:
        await _dong(s1, s2, viec)
    assert tuple(await _bang()) == ("locked", 2)
    assert await _so_hoc_vu(o, NAM) == 0


async def test_hai_phien_tao_hoc_vu_co_chi_tieu_dang_do_thi_khoa_bang_cho_roi_409(admin_user_in_db, hoc_vu):
    """Phiên 1 tạo học vụ CÓ chỉ tiêu, CHƯA commit ⇒ lệnh khoá bảng (dấu lúc mở) CHỜ đúng phiên 1; phiên 1 commit ⇒ khoá 409
    (tập học vụ của năm đã đổi); bảng vẫn nháp, học vụ mới còn."""
    from app.services import admission_quota_table_service as svc
    from app.services.admission_quota_table_service import QuotaTableConflict

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    dau = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _tao(admin_user_in_db, o, 9, s=s1)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(
            svc.lock_quota_table(s2, NAM, expected_version=1, expected_quota_fingerprint=dau, actor_id=admin_user_in_db["id"])
        )
        assert await _bi_chan_boi(pid2, pid1, viec), "khoá bảng KHÔNG chờ lệnh tạo học vụ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(QuotaTableConflict) as loi:
            await asyncio.wait_for(viec, 10)
        assert loi.value.reason_code == "quota_table_stale"
    finally:
        await _dong(s1, s2, viec)
    assert tuple(await _bang()) == ("draft", 1)
    assert await _so_hoc_vu(o, NAM) == 1
