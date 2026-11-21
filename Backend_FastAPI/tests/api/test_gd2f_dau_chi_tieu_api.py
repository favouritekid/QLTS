"""GĐ2-F1 — điểm chặn Codex: DẤU CHỈ TIÊU (``quota_fingerprint``) chống ghi đè chỉ tiêu ngành giữa trang bảng chỉ tiêu năm và
đường sửa học vụ CŨ (``PATCH /api/admin/academic-info/{id}`` → ``organization_service.update_academic_info`` — đổi
``annual_admission_quota`` mà không tăng ``version`` của bảng). Request THẬT (router → deps → dịch vụ → CSDL thật) + hai phiên CSDL
thật cho ca đồng thời. Không dữ liệu thật. Mỗi ca kiểm MỘT bất biến.

Tầng chủ sở hữu: ``admission_quota_table_service`` (:func:`quota_fingerprint_of` — MỘT hàm cho GET và cho kiểm;
:func:`read_quota_fingerprint` đọc dưới khoá dòng sau khoá năm, trước khi ghi). Lượt 3: mọi đường tạo / sửa / dời học vụ cũng
giữ khoá năm (``app.core.review_year_lock``) — ca hai phiên 1a–1e; PUT lấy khoá ghi một câu, không nâng khoá — ca 2. Lượt 3b:
khoá ghi ấy là ``FOR NO KEY UPDATE`` ⇒ dòng đang trỏ tới học vụ (``FOR KEY SHARE`` của khoá ngoại) không làm PUT chờ — ca 3b.
"""
from __future__ import annotations

import asyncio
import re

import pytest
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.services.admission_quota_table_service import QuotaTableConflict, quota_fingerprint_of
from tests.api.test_gd2a_bang_chi_tieu_api import (  # noqa: F401 — fixture dùng qua tên
    NAM,
    P,
    _bang,
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

pytestmark = pytest.mark.asyncio

TRANG_CU = "/api/admin/academic-info"


async def _mo(client, h):
    """Như giao diện mở trang: (phiên bản, dấu) — năm chưa có bảng ⇒ 404 mang dấu, phiên bản 0."""
    r = await client.get(f"{P}/{NAM}", headers=h)
    if r.status_code == 404:
        return 0, r.json()["quota_fingerprint"]
    assert r.status_code == 200, r.text
    return r.json()["version"], r.json()["quota_fingerprint"]


async def _sua_o_trang_cu(client, h, hoc_vu_id: int, chi_tieu: int) -> None:
    r = await client.patch(f"{TRANG_CU}/{hoc_vu_id}", headers=h, json={"annual_admission_quota": chi_tieu})
    assert r.status_code == 200, r.text


async def _tao_bang(client, h, hoc_vu) -> None:
    """Tạo bảng như giao diện: dấu lấy từ GET (404 mang dấu) — không tự tính lại trong test."""
    phien_ban, dau = await _mo(client, h)
    assert phien_ban == 0
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(0, hoc_vu), "quota_fingerprint": dau})
    assert r.status_code == 200, r.text


# ── hàm băm (không CSDL) ───────────────────────────────────────────────────────────────────────────────────────────
def test_dau_khong_phu_thuoc_thu_tu_va_la_sha256_hex():
    d = quota_fingerprint_of([(2, 5, False), (1, None, False)])
    assert d == quota_fingerprint_of([(1, None, False), (2, 5, False)])
    assert re.fullmatch(r"[0-9a-f]{64}", d)


def test_dau_phan_biet_trong_voi_0():
    assert quota_fingerprint_of([(1, None, False)]) != quota_fingerprint_of([(1, 0, False)])


def test_dau_doi_khi_nam_co_them_hoc_vu():
    assert quota_fingerprint_of([(1, 5, False)]) != quota_fingerprint_of([(1, 5, False), (2, None, False)])


def test_dau_doi_khi_hoc_vu_bi_xoa_mem():
    """Luật C: cờ xoá mềm nằm trong dấu — cùng (id, chỉ tiêu) mà khác cờ xoá ⇒ dấu khác."""
    assert quota_fingerprint_of([(1, 5, False)]) != quota_fingerprint_of([(1, 5, True)])


# ── 1–3: tuần tự qua request thật ──────────────────────────────────────────────────────────────────────────────────
async def test_trang_cu_sua_chi_tieu_sau_khi_mo_thi_put_409_giu_gia_tri_moi(client: AsyncClient, admin_token_headers, hoc_vu):
    """A mở bảng (V, dấu) → B sửa chỉ tiêu ngành ở trang cũ (V không đổi) → A lưu bản cũ ⇒ 409; giá trị của B giữ nguyên."""
    h = admin_token_headers
    await _tao_bang(client, h, hoc_vu)
    phien_ban, dau = await _mo(client, h)
    a = hoc_vu["2026"][0]
    await _sua_o_trang_cu(client, h, a, 51)
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(phien_ban, hoc_vu), "quota_fingerprint": dau})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text
    assert await _chi_tieu(a) == 51


async def test_nam_chua_co_bang_trang_cu_sua_thi_tao_bang_409_giu_gia_tri_moi(
    client: AsyncClient, admin_token_headers, hoc_vu
):
    """Khe ``version`` 0 (tăng phiên bản không đỡ được): A mở trang khi năm CHƯA có bảng (404 mang dấu) → B sửa ở trang cũ →
    A tạo bảng với dấu cũ ⇒ 409; giá trị của B giữ; không tạo bảng."""
    h = admin_token_headers
    phien_ban, dau = await _mo(client, h)
    assert phien_ban == 0
    a = hoc_vu["2026"][0]
    await _sua_o_trang_cu(client, h, a, 51)
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(0, hoc_vu), "quota_fingerprint": dau})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text
    assert await _chi_tieu(a) == 51
    assert await _bang() is None


async def test_trang_cu_sua_chi_tieu_sau_khi_mo_thi_khoa_409_bang_van_nhap(
    client: AsyncClient, admin_token_headers, hoc_vu
):
    """Khoá đóng băng đúng chỉ tiêu đã xem: B sửa ở trang cũ sau khi A mở ⇒ A khoá ⇒ 409; bảng vẫn ``draft``."""
    h = admin_token_headers
    await _tao_bang(client, h, hoc_vu)
    phien_ban, dau = await _mo(client, h)
    await _sua_o_trang_cu(client, h, hoc_vu["2026"][0], 51)
    r = await client.post(f"{P}/{NAM}/lock", headers=h, json={"version": phien_ban, "quota_fingerprint": dau})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text
    assert tuple(await _bang()) == ("draft", 1)


async def test_hoc_vu_ngoai_bang_doi_tu_trong_sang_0_cung_lam_dau_lech(client: AsyncClient, admin_token_headers, hoc_vu):
    """Trống ≠ 0 trong dấu: một học vụ của năm (không thuộc bảng) đổi chỉ tiêu từ TRỐNG sang 0 ở trang cũ ⇒ dấu lệch ⇒ 409."""
    h = admin_token_headers
    await _tao_bang(client, h, hoc_vu)
    d = hoc_vu["2026"][3]
    assert await _chi_tieu(d) is None
    phien_ban, dau = await _mo(client, h)
    await _sua_o_trang_cu(client, h, d, 0)
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(phien_ban, hoc_vu), "quota_fingerprint": dau})
    assert r.status_code == 409 and r.json()["error_code"] == "QUOTA_TABLE_STALE", r.text


# ── 4: hai phiên CSDL thật ─────────────────────────────────────────────────────────────────────────────────────────
async def test_hai_phien_trang_cu_dang_sua_thi_put_phai_cho_roi_409(admin_user_in_db, hoc_vu):
    """Phiên 1 sửa chỉ tiêu qua ĐÚNG hàm của đường PATCH cũ (``organization_service.update_academic_info``), CHƯA commit. Phiên 2
    PUT bảng với dấu cũ qua dịch vụ THẬT ⇒ phải CHỜ đúng phiên 1 (hỏi ``pg_blocking_pids`` từ phiên thứ ba); phiên 1 commit ⇒
    PUT 409 ``quota_table_stale``; giá trị phiên 1 giữ nguyên (không bị ghi đè)."""
    from app import schemas
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc
    from app.services import organization_service

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    a = hoc_vu["2026"][0]
    dau_cu = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        nguoi = await s1.get(models.User, admin_user_in_db["id"])
        await organization_service.update_academic_info(
            s1,
            academic_info_id=a,
            academic_info_in=schemas.OfferingAcademicInfoUpdate(annual_admission_quota=77),
            current_user=nguoi,
            updated_by_user_id=nguoi.id,
        )  # giữ khoá dòng học vụ, CHƯA commit
        pid2 = await _pid(s2)
        than = QuotaTablePut(**{**_than(1, hoc_vu), "quota_fingerprint": dau_cu})
        viec = asyncio.ensure_future(svc.replace_quota_table(s2, NAM, than, actor_id=admin_user_in_db["id"]))
        assert await _bi_chan_boi(pid2, pid1, viec), "PUT KHÔNG chờ lệnh sửa trang cũ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(QuotaTableConflict) as e:
            await viec
        assert e.value.reason_code == "quota_table_stale"
    finally:
        await _dong(s1, s2, viec)
    assert await _chi_tieu(a) == 77
    assert tuple(await _bang()) == ("draft", 1)


# ── 5: không chặn oan; dấu thiếu / sai định dạng ⇒ 422 ─────────────────────────────────────────────────────────────
async def test_khong_ai_sua_thi_tao_luu_khoa_voi_dau_luc_mo_deu_qua(client: AsyncClient, admin_token_headers, hoc_vu):
    h = admin_token_headers
    phien_ban, dau = await _mo(client, h)
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(phien_ban, hoc_vu), "quota_fingerprint": dau})
    assert r.status_code == 200, r.text
    phien_ban, dau = await _mo(client, h)
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(phien_ban, hoc_vu), "quota_fingerprint": dau})
    assert r.status_code == 200, r.text
    phien_ban, dau = await _mo(client, h)
    r = await client.post(f"{P}/{NAM}/lock", headers=h, json={"version": phien_ban, "quota_fingerprint": dau})
    assert r.status_code == 200 and r.json()["status"] == "locked", r.text


@pytest.mark.parametrize("dau", [None, "x" * 64, "0" * 63, "A" * 64], ids=["thieu", "khong_hex", "ngan", "chu_hoa"])
async def test_dau_thieu_hoac_sai_dinh_dang_422(client: AsyncClient, admin_token_headers, hoc_vu, dau):
    h = admin_token_headers
    them = {} if dau is None else {"quota_fingerprint": dau}
    r = await client.put(f"{P}/{NAM}", headers=h, json={**_than(0, hoc_vu), **them})
    assert r.status_code == 422, r.text
    r = await client.post(f"{P}/{NAM}/lock", headers=h, json={"version": 1, **them})
    assert r.status_code == 422, r.text
    assert await _bang() is None


# ══ GĐ2-F1 lượt 3 — điểm chặn Codex lượt 2 ═══════════════════════════════════════════════════════════════════════════
# (1) Dòng học vụ MỚI chèn sau lần đọc dấu — khoá dòng không chặn được ⇒ BẤT BIẾN: mọi lệnh ghi đổi tập (id, chỉ tiêu) của năm
#     giữ KHOÁ NĂM (``app.core.review_year_lock``) trước khi chạm dòng — tạo học vụ, sửa chỉ tiêu, dời năm, bảng chỉ tiêu.
# (2) Hai PUT khác năm cùng chạm một học vụ: trước đây cùng ``FOR SHARE`` rồi cùng nâng lên ``FOR UPDATE`` ⇒ vòng chờ ``40P01``.
async def _offering_chua_co_nam(hoc_vu) -> int:
    """Offering của học vụ năm 2025 trong fixture — CHƯA có học vụ năm 2026 ⇒ tạo được (offering, 2026)."""
    return (await _sql("SELECT offering_id FROM offering_academic_info WHERE id = :i", i=hoc_vu["2025"])).scalar_one()


async def _so_hoc_vu(offering_id: int, nam: int) -> int:
    return (
        await _sql(
            "SELECT count(*) FROM offering_academic_info WHERE offering_id = :o AND academic_year = :y", o=offering_id, y=nam
        )
    ).scalar_one()


async def _tao_hoc_vu(s, admin_user_in_db, offering_id: int):
    """Tạo học vụ năm ``NAM`` qua ĐÚNG hàm của route ``POST /api/offerings/{id}/academic-info`` (chưa commit)."""
    from app import schemas
    from app.services import organization_service

    nguoi = await s.get(models.User, admin_user_in_db["id"])
    return await organization_service.create_academic_info(
        s,
        academic_info_in=schemas.OfferingAcademicInfoCreate(
            offering_id=offering_id, academic_year=NAM, annual_admission_quota=9, is_published=False
        ),
        current_user=nguoi,
        created_by_user_id=nguoi.id,
    )


async def test_hai_phien_tao_hoc_vu_moi_dang_do_thi_put_phai_cho_roi_409(admin_user_in_db, hoc_vu):
    """1a — phiên 1 tạo học vụ mới cho năm, CHƯA commit ⇒ PUT (dấu cũ) phải CHỜ đúng phiên 1; phiên 1 commit ⇒ PUT 409; học vụ mới
    còn."""
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    dau_cu = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _tao_hoc_vu(s1, admin_user_in_db, o)  # CHƯA commit
        pid2 = await _pid(s2)
        than = QuotaTablePut(**{**_than(1, hoc_vu), "quota_fingerprint": dau_cu})
        viec = asyncio.ensure_future(svc.replace_quota_table(s2, NAM, than, actor_id=admin_user_in_db["id"]))
        assert await _bi_chan_boi(pid2, pid1, viec), "PUT KHÔNG chờ lệnh tạo học vụ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(QuotaTableConflict) as e:
            await viec
        assert e.value.reason_code == "quota_table_stale"
    finally:
        await _dong(s1, s2, viec)
    assert await _so_hoc_vu(o, NAM) == 1
    assert tuple(await _bang()) == ("draft", 1)


async def test_hai_phien_tao_hoc_vu_moi_dang_do_thi_khoa_bang_phai_cho_roi_409(admin_user_in_db, hoc_vu):
    """1b — như 1a với lệnh KHOÁ bảng: phải chờ đúng phiên tạo; sau commit ⇒ 409; bảng vẫn ``draft``."""
    from app.services import admission_quota_table_service as svc

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    dau_cu = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        await _tao_hoc_vu(s1, admin_user_in_db, o)  # CHƯA commit
        pid2 = await _pid(s2)
        viec = asyncio.ensure_future(
            svc.lock_quota_table(
                s2, NAM, expected_version=1, expected_quota_fingerprint=dau_cu, actor_id=admin_user_in_db["id"]
            )
        )
        assert await _bi_chan_boi(pid2, pid1, viec), "khoá bảng KHÔNG chờ lệnh tạo học vụ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(QuotaTableConflict) as e:
            await viec
        assert e.value.reason_code == "quota_table_stale"
    finally:
        await _dong(s1, s2, viec)
    assert await _so_hoc_vu(o, NAM) == 1
    assert tuple(await _bang()) == ("draft", 1)


async def test_hai_phien_put_dang_giu_khoa_thi_tao_hoc_vu_phai_cho(admin_user_in_db, hoc_vu):
    """1c — PUT đang giữ khoá, CHƯA commit ⇒ lệnh tạo học vụ cho năm ấy phải CHỜ đúng phiên PUT; PUT commit ⇒ tạo xong."""
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    o = await _offering_chua_co_nam(hoc_vu)
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid2 = await _pid(s2)
        than = QuotaTablePut(**{**_than(1, hoc_vu), "quota_fingerprint": await _dau()})
        await svc.replace_quota_table(s2, NAM, than, actor_id=admin_user_in_db["id"])  # giữ khoá, CHƯA commit
        pid1 = await _pid(s1)
        viec = asyncio.ensure_future(_tao_hoc_vu(s1, admin_user_in_db, o))
        assert await _bi_chan_boi(pid1, pid2, viec), "tạo học vụ KHÔNG chờ PUT đang giữ khoá — %s" % _mo_ta(viec)
        await s2.commit()
        await viec
        await s1.commit()
    finally:
        await _dong(s2, s1, viec)
    assert await _so_hoc_vu(o, NAM) == 1
    assert tuple(await _bang()) == ("draft", 2)


async def test_hai_phien_doi_hoc_vu_tu_nam_khac_vao_nam_bang_thi_put_phai_cho_roi_409(admin_user_in_db, hoc_vu):
    """1d — phiên 1 DỜI một học vụ từ năm khác VÀO năm của bảng (đường PATCH cũ), CHƯA commit ⇒ PUT (dấu cũ) chờ đúng phiên 1;
    commit ⇒ 409."""
    from app import schemas
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc
    from app.services import organization_service

    await _tao_bang_nhap(admin_user_in_db, hoc_vu)
    e_id = hoc_vu["2025"]
    dau_cu = await _dau()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        nguoi = await s1.get(models.User, admin_user_in_db["id"])
        await organization_service.update_academic_info(
            s1,
            academic_info_id=e_id,
            academic_info_in=schemas.OfferingAcademicInfoUpdate(academic_year=NAM),
            current_user=nguoi,
            updated_by_user_id=nguoi.id,
        )  # CHƯA commit
        pid2 = await _pid(s2)
        than = QuotaTablePut(**{**_than(1, hoc_vu), "quota_fingerprint": dau_cu})
        viec = asyncio.ensure_future(svc.replace_quota_table(s2, NAM, than, actor_id=admin_user_in_db["id"]))
        assert await _bi_chan_boi(pid2, pid1, viec), "PUT KHÔNG chờ lệnh dời học vụ đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(QuotaTableConflict) as e:
            await viec
        assert e.value.reason_code == "quota_table_stale"
    finally:
        await _dong(s1, s2, viec)
    assert (await _sql("SELECT academic_year FROM offering_academic_info WHERE id = :i", i=e_id)).scalar_one() == NAM
    assert tuple(await _bang()) == ("draft", 1)


async def test_hai_phien_sua_chi_tieu_hoc_vu_vua_bi_doi_nam_thi_409(admin_user_in_db, hoc_vu):
    """1e — phiên 1 DỜI học vụ ``e`` từ năm 2025 sang năm bảng, CHƯA commit (giữ khoá năm 2025 + năm bảng). Phiên 2 sửa chỉ tiêu
    ``e`` qua ĐÚNG ``update_academic_info``: đọc thấy năm 2025 ⇒ lấy khoá năm 2025 ⇒ CHỜ đúng phiên 1. Phiên 1 commit ⇒ phiên 2
    đọc lại năm DƯỚI khoá = năm bảng ≠ 2025 ⇒ 409 — không sửa chỉ tiêu một học vụ của năm mà mình KHÔNG giữ khoá; chỉ tiêu ``e``
    không đổi."""
    from app import schemas
    from app.services import organization_service
    from app.utils.exceptions import ConflictError

    e_id = hoc_vu["2025"]
    chi_tieu_truoc = (
        await _sql("SELECT annual_admission_quota FROM offering_academic_info WHERE id = :i", i=e_id)
    ).scalar_one()
    s1, s2 = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid1 = await _pid(s1)
        nguoi1 = await s1.get(models.User, admin_user_in_db["id"])
        await organization_service.update_academic_info(
            s1,
            academic_info_id=e_id,
            academic_info_in=schemas.OfferingAcademicInfoUpdate(academic_year=NAM),
            current_user=nguoi1,
            updated_by_user_id=nguoi1.id,
        )  # CHƯA commit
        pid2 = await _pid(s2)
        nguoi2 = await s2.get(models.User, admin_user_in_db["id"])
        viec = asyncio.ensure_future(
            organization_service.update_academic_info(
                s2,
                academic_info_id=e_id,
                academic_info_in=schemas.OfferingAcademicInfoUpdate(annual_admission_quota=33),
                current_user=nguoi2,
                updated_by_user_id=nguoi2.id,
            )
        )
        assert await _bi_chan_boi(pid2, pid1, viec), "sửa chỉ tiêu KHÔNG chờ lệnh dời năm đang dở — %s" % _mo_ta(viec)
        await s1.commit()
        with pytest.raises(ConflictError):
            await asyncio.wait_for(viec, 10)
    finally:
        await _dong(s1, s2, viec)
    assert tuple(
        (
            await _sql("SELECT academic_year, annual_admission_quota FROM offering_academic_info WHERE id = :i", i=e_id)
        ).one()
    ) == (NAM, chi_tieu_truoc)


async def test_hai_put_khac_nam_cung_cham_mot_hoc_vu_khong_vong_cho(admin_user_in_db, hoc_vu, monkeypatch):
    """2 — PUT A của năm khác gửi SAI một thành viên ``a`` (học vụ năm 2026) và PUT B hợp lệ của năm 2026 cùng tới điểm ngay SAU
    câu khoá dòng đầu tiên (``read_quota_fingerprint`` có khoá — điểm dừng gài bằng ``asyncio.Event``). Trước lượt 3: cả hai giữ
    ``FOR SHARE`` trên ``a`` rồi cùng nâng lên ``FOR UPDATE`` (``lock_quota_cells``) ⇒ PostgreSQL huỷ một bên ``40P01``. Nay: B CHỜ
    A (``pg_blocking_pids``) ngay ở câu khoá đầu, A 400 (thành viên sai năm), B 200, không ``40P01``. Mọi bước chờ có hạn — không
    treo."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.repositories.council_decision_repository import db_error_codes
    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc
    from app.utils.exceptions import ValidationError as LoiDuLieu

    a = hoc_vu["2026"][0]
    nam_khac = NAM - 1
    async with AsyncSessionLocal() as s:
        dau_khac = await svc.read_quota_fingerprint(s, nam_khac)
    than_a = QuotaTablePut(
        version=0, quota_fingerprint=dau_khac,
        groups=[{"code": "SAI", "name": "Sai năm", "ceiling": 5,
                 "members": [{"offering_academic_info_id": a, "annual_admission_quota": 1}]}],
    )
    than_b = QuotaTablePut(**{**_than(0, hoc_vu), "quota_fingerprint": await _dau()})

    goc = svc.read_quota_fingerprint
    den: dict = {}
    di_tiep = asyncio.Event()

    async def tram(db, academic_year, **kw):
        dau = await goc(db, academic_year, **kw)  # câu khoá dòng ĐẦU TIÊN của PUT chạy thật, rồi mới dừng
        if kw.get("lock") is not None:
            den[(await db.execute(text("SELECT pg_backend_pid()"))).scalar_one()] = True
            await asyncio.wait_for(di_tiep.wait(), 30)
        return dau

    monkeypatch.setattr(svc, "read_quota_fingerprint", tram)  # gài SAU khi đã lấy dấu của hai thân
    uid = admin_user_in_db["id"]
    sa, sb = AsyncSessionLocal(), AsyncSessionLocal()
    va = vb = None
    ket_qua: dict = {}
    b_bi_a_chan = False
    try:
        pa, pb = await _pid(sa), await _pid(sb)
        va = asyncio.ensure_future(svc.replace_quota_table(sa, nam_khac, than_a, actor_id=uid))
        for _ in range(200):
            if pa in den or va.done():
                break
            await asyncio.sleep(0.05)
        assert pa in den, "PUT sai năm không tới điểm dừng — %s" % _mo_ta(va)
        vb = asyncio.ensure_future(svc.replace_quota_table(sb, NAM, than_b, actor_id=uid))
        for _ in range(200):
            if pb in den or vb.done():
                break
            async with AsyncSessionLocal() as s3:
                chan = (await s3.execute(text("SELECT pg_blocking_pids(:p)"), {"p": pb})).scalar_one()
            if pa in (chan or []):
                b_bi_a_chan = True
                break
            await asyncio.sleep(0.05)
        di_tiep.set()
        phien = {va: ("A", sa), vb: ("B", sb)}
        con = set(phien)
        while con:
            xong, con = await asyncio.wait(con, timeout=30, return_when=asyncio.FIRST_COMPLETED)
            assert xong, "TREO: hai PUT chưa xong sau 30 s"
            for v in xong:
                ten, s = phien[v]
                ket_qua[ten] = v.exception()
                if ket_qua[ten] is None:
                    await s.commit()
                else:
                    await s.rollback()  # nhả khoá ⇒ việc kia chạy tiếp
    finally:
        di_tiep.set()
        for v in (va, vb):
            if v is not None and not v.done():
                v.cancel()
        for s in (sa, sb):
            await s.rollback()
            await s.close()
    vong_cho = [
        ten for ten, e in ket_qua.items()
        if isinstance(e, DBAPIError) and db_error_codes(e)[0] == "40P01"
    ]
    assert not vong_cho, "VÒNG CHỜ: PostgreSQL huỷ PUT %s bằng 40P01 (deadlock)" % vong_cho
    assert isinstance(ket_qua.get("A"), LoiDuLieu), ket_qua
    assert ket_qua["A"].public_payload.get("reason_code") == "quota_table_bad_member", ket_qua
    assert ket_qua.get("B") is None, ket_qua
    assert b_bi_a_chan, "PUT hợp lệ KHÔNG chờ PUT sai năm đang giữ khoá học vụ ``a``"


@pytest.mark.parametrize("vai", ["thanh_vien", "ngoai_bang"])
async def test_hai_phien_dong_tro_toi_hoc_vu_dang_mo_thi_put_khong_cho(admin_user_in_db, hoc_vu, vai):
    """3b — phiên T chèn một dòng học phí học kỳ (``offering_semester_tuition`` — khoá ngoại tới học vụ ⇒ PostgreSQL giữ
    ``FOR KEY SHARE`` trên dòng học vụ tới hết giao dịch) và GIỮ giao dịch mở. PUT bảng của năm ấy phải xong mà KHÔNG chờ T
    (``pg_blocking_pids`` hỏi từ phiên thứ ba) và xong khi T VẪN chưa kết thúc (dòng của T chưa ai thấy). ``thanh_vien``: học vụ
    ``a`` là thành viên PUT gửi lên (chỉ tiêu của nó được ghi); ``ngoai_bang``: học vụ ``d`` cùng năm, KHÔNG thuộc bảng. Khoá ghi
    của PUT là ``FOR NO KEY UPDATE`` — không xung đột với ``KEY SHARE``; ``FOR UPDATE`` (lượt 3, hay nâng khoá qua
    ``lock_quota_cells``) thì có."""
    from sqlalchemy import text

    from app.schemas.admission_quota_table import QuotaTablePut
    from app.services import admission_quota_table_service as svc

    a, _b, _c, d = hoc_vu["2026"]
    dich = a if vai == "thanh_vien" else d
    than = QuotaTablePut(**{**_than(0, hoc_vu), "quota_fingerprint": await _dau()})
    st, sp = AsyncSessionLocal(), AsyncSessionLocal()
    viec = None
    try:
        pid_t = await _pid(st)
        await st.execute(
            text(
                "INSERT INTO offering_semester_tuition (academic_info_id, semester_no, amount) VALUES (:i, 1, 1000)"
            ),
            {"i": dich},
        )  # GIỮ giao dịch mở
        pid_p = await _pid(sp)
        viec = asyncio.ensure_future(svc.replace_quota_table(sp, NAM, than, actor_id=admin_user_in_db["id"]))
        assert not await _bi_chan_boi(pid_p, pid_t, viec), (
            "PUT CHỜ giao dịch đang chèn dòng trỏ tới học vụ %s (%s) — %s" % (dich, vai, _mo_ta(viec))
        )
        await asyncio.wait_for(viec, 10)
        await sp.commit()
        assert (
            await _sql("SELECT count(*) FROM offering_semester_tuition WHERE academic_info_id = :i", i=dich)
        ).scalar_one() == 0, "T đã kết thúc trước khi PUT xong — phép đo không chứng minh được 'không chờ'"
    finally:
        await _dong(st, sp, viec)
    assert tuple(await _bang()) == ("draft", 1)
    assert await _chi_tieu(a) == 50


async def test_tao_hoc_vu_khi_khong_co_put_van_qua(admin_user_in_db, hoc_vu):
    """Ca thường: không có PUT / khoá nào đang giữ khoá năm ⇒ tạo học vụ qua ĐÚNG hàm của route ``POST
    /api/offerings/{id}/academic-info`` xong ngay (không chờ ai) và dòng đã ghi — khoá năm không đổi hành vi cũ.

    Gọi hàm dịch vụ, KHÔNG gọi HTTP: cả hai route POST học vụ trả đối tượng ORM SAU ``commit`` mà ``semester_tuitions`` chưa
    nạp ⇒ tuần tự hoá phản hồi đổ ``MissingGreenlet`` (``ResponseValidationError``) dù dòng ĐÃ ghi. Lỗi ấy CÓ TỪ TRƯỚC nhánh
    này (route / schema / model không đổi so với ``f11f8f94``; bỏ khoá năm vẫn đổ y hệt) — ghi ở gói rà §9, không vá ở đây."""
    o = await _offering_chua_co_nam(hoc_vu)
    async with AsyncSessionLocal() as s:
        await asyncio.wait_for(_tao_hoc_vu(s, admin_user_in_db, o), 10)
        await s.commit()
    assert await _so_hoc_vu(o, NAM) == 1
