"""GĐ2-F1 — điểm chặn Codex: DẤU CHỈ TIÊU (``quota_fingerprint``) chống ghi đè chỉ tiêu ngành giữa trang bảng chỉ tiêu năm và
đường sửa học vụ CŨ (``PATCH /api/admin/academic-info/{id}`` → ``organization_service.update_academic_info`` — đổi
``annual_admission_quota`` mà không tăng ``version`` của bảng). Request THẬT (router → deps → dịch vụ → CSDL thật) + hai phiên CSDL
thật cho ca đồng thời. Không dữ liệu thật. Mỗi ca kiểm MỘT bất biến.

Tầng chủ sở hữu: ``admission_quota_table_service`` (:func:`quota_fingerprint_of` — MỘT hàm cho GET và cho kiểm;
:func:`read_quota_fingerprint` đọc ``FOR SHARE`` sau khoá năm, trước khi ghi).
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
    _gui,
    _mo_ta,
    _pid,
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
    r = await client.put(f"{P}/{NAM}", headers=h, json=await _gui(0, hoc_vu))
    assert r.status_code == 200, r.text


# ── hàm băm (không CSDL) ───────────────────────────────────────────────────────────────────────────────────────────
def test_dau_khong_phu_thuoc_thu_tu_va_la_sha256_hex():
    d = quota_fingerprint_of([(2, 5), (1, None)])
    assert d == quota_fingerprint_of([(1, None), (2, 5)])
    assert re.fullmatch(r"[0-9a-f]{64}", d)


def test_dau_phan_biet_trong_voi_0():
    assert quota_fingerprint_of([(1, None)]) != quota_fingerprint_of([(1, 0)])


def test_dau_doi_khi_nam_co_them_hoc_vu():
    assert quota_fingerprint_of([(1, 5)]) != quota_fingerprint_of([(1, 5), (2, None)])


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
