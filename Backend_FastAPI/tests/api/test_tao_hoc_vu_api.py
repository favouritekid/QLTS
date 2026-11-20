# -*- coding: utf-8 -*-
"""Tạo học vụ (``offering_academic_info``) qua ĐÚNG route HTTP — phản hồi thành công VÀ tải lại thấy học vụ vừa tạo.

Lỗi được khoá (có từ 11-04-2026, khi thêm quan hệ ``semester_tuitions``): dịch vụ tạo trả bản ghi CHƯA nạp
``semester_tuitions``; router commit rồi mới dựng phản hồi ⇒ schema đọc quan hệ lazy ngoài greenlet ⇒ ``MissingGreenlet``
⇒ 500, trong khi dòng ĐÃ được ghi. Người dùng thấy báo lỗi, bấm lại ⇒ "đã tồn tại".

Hai route cùng gọi ``organization_service.create_academic_info`` và đều được giao diện dùng:
``POST /api/offerings/{id}/academic-info`` (``frontend/src/lib/api/program-data.ts``) và
``POST /api/admin/offerings/{id}/academic-info`` (``frontend/src/lib/api/endpoints.ts``). Gọi thẳng hàm dịch vụ KHÔNG bắt
được lỗi này (nó nằm ở chỗ nối router ↔ tuần tự hoá phản hồi) ⇒ test phải đi qua HTTP.
"""
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app import models
from app.database import AsyncSessionLocal

# Năm TƯƠNG LAI so với ngày chạy test: dịch vụ cấm sửa học phí của năm QUÁ KHỨ ⇒ năm ghim cứng sẽ đỏ khi lịch sang năm sau.
NAM = datetime.now(timezone.utc).year + 1

#: Hai route TẠO học vụ (giao diện dùng cả hai) và hai route SỬA học vụ (``program-data.ts`` dùng route thường,
#: ``endpoints.ts`` dùng route admin) — cùng gọi ``organization_service.create_academic_info`` / ``update_academic_info``.
ROUTE_TAO = ["/api/offerings/%d/academic-info", "/api/admin/offerings/%d/academic-info"]
ROUTE_SUA = ["/api/academic-info/%d", "/api/admin/academic-info/%d"]


async def _tao_loai_hinh(client: AsyncClient, ad: Dict[str, str]) -> int:
    """Đơn vị → ngành → loại hình đào tạo, qua route admin thật (như ``test_admin_organization``)."""
    duoi = uuid.uuid4().hex[:6]
    r = await client.post(
        "/api/admin/organization-units", json={"name": "Khoa thử tạo học vụ %s" % duoi, "type": "Khoa"}, headers=ad
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/admin/programs",
        json={
            "name": "Ngành thử tạo học vụ %s" % duoi,
            "degree_level": "Cao đẳng",
            "code": "6%06d" % (int(duoi, 16) % 1_000_000),
            "unit_id": r.json()["id"],
        },
        headers=ad,
    )
    assert r.status_code == 201, r.text
    ma_nganh = r.json()["id"]
    r = await client.post(
        "/api/admin/programs/%d/offerings" % ma_nganh,
        json={"offering_type": "Chính quy", "program_id": ma_nganh, "duration_semesters": 6},
        headers=ad,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _dem_dong(offering_id: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(func.count()).select_from(models.OfferingAcademicInfo).where(
                    models.OfferingAcademicInfo.offering_id == offering_id
                )
            )
        ).scalar_one()


def _than_tao(offering_id: int) -> dict:
    return {
        "offering_id": offering_id,
        "academic_year": NAM,
        "annual_admission_quota": 40,
        "tuition_fee_per_year": "12000000",
        "is_published": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "duong_dan, ma_mong_doi",
    [
        ("/api/offerings/%d/academic-info", 200),
        ("/api/admin/offerings/%d/academic-info", 201),
    ],
    ids=["route_thuong", "route_admin"],
)
async def test_tao_hoc_vu_phan_hoi_thanh_cong_va_tai_lai_thay_hoc_vu(
    client: AsyncClient, admin_token_headers: Dict[str, str], duong_dan: str, ma_mong_doi: int
):
    oid = await _tao_loai_hinh(client, admin_token_headers)

    r = await client.post(duong_dan % oid, json=_than_tao(oid), headers=admin_token_headers)

    # 1. Phản hồi thành công, mang đúng bản ghi (kể cả danh sách học phí theo học kỳ — rỗng với học vụ mới).
    assert r.status_code == ma_mong_doi, r.text
    moi = r.json()
    assert moi["offering_id"] == oid
    assert moi["academic_year"] == NAM
    assert moi["annual_admission_quota"] == 40
    assert moi["semester_tuitions"] == []
    assert isinstance(moi["id"], int)

    # 2. Tải lại danh sách học vụ của loại hình (đúng route giao diện dùng) ⇒ thấy học vụ vừa tạo, đúng một lần.
    r = await client.get("/api/offerings/%d/academic-info" % oid, headers=admin_token_headers)
    assert r.status_code == 200, r.text
    ds = r.json()
    assert [(x["id"], x["academic_year"]) for x in ds] == [(moi["id"], NAM)]

    # 3. CSDL: đúng một dòng.
    assert await _dem_dong(oid) == 1


@pytest.mark.asyncio
async def test_tao_lai_cung_nam_bao_da_ton_tai_khong_tao_dong_thu_hai(
    client: AsyncClient, admin_token_headers: Dict[str, str]
):
    """Kịch bản người dùng bấm lại: lần đầu thành công, lần hai báo trùng (409), không sinh dòng thứ hai."""
    oid = await _tao_loai_hinh(client, admin_token_headers)
    duong_dan = "/api/offerings/%d/academic-info" % oid

    r1 = await client.post(duong_dan, json=_than_tao(oid), headers=admin_token_headers)
    assert r1.status_code == 200, r1.text

    r2 = await client.post(duong_dan, json=_than_tao(oid), headers=admin_token_headers)
    assert r2.status_code == 409, r2.text

    assert await _dem_dong(oid) == 1


# ═══════════════ Chỉ tiêu TRỐNG ≠ 0 (owner chốt 20-11) ═══════════════════════════════════════════════════════════════
# Hợp đồng API: null / vắng = chưa đặt chỉ tiêu (máy chủ không giới hạn); 0 = CHỦ ĐỘNG đóng ngành (chặn mọi lần Phê duyệt —
# ``admission_service`` ADM-026). Tạo để trống ⇒ lưu null; sửa học phí (không gửi chỉ tiêu) ⇒ chỉ tiêu GIỮ nguyên; gửi null ⇒
# đặt về trống. Lỗi giao diện đi kèm (form Cấu hình Tuyển sinh tự đổi trống thành 0) khoá ở ``AcademicInfoPanel.test.tsx``.


async def _chi_tieu_trong_csdl(academic_info_id: int) -> Optional[int]:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.OfferingAcademicInfo.annual_admission_quota).where(
                    models.OfferingAcademicInfo.id == academic_info_id
                )
            )
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.parametrize("cach", ["gui_null", "khong_gui"])
@pytest.mark.parametrize("duong_dan", ROUTE_TAO, ids=["route_thuong", "route_admin"])
async def test_tao_hoc_vu_chi_tieu_trong_luu_null_khong_thanh_0(
    client: AsyncClient, admin_token_headers: Dict[str, str], duong_dan: str, cach: str
):
    oid = await _tao_loai_hinh(client, admin_token_headers)
    than = _than_tao(oid)
    if cach == "gui_null":
        than["annual_admission_quota"] = None
    else:
        del than["annual_admission_quota"]

    r = await client.post(duong_dan % oid, json=than, headers=admin_token_headers)

    assert r.status_code in (200, 201), r.text
    assert r.json()["annual_admission_quota"] is None
    assert await _chi_tieu_trong_csdl(r.json()["id"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("duong_dan", ROUTE_TAO, ids=["route_thuong", "route_admin"])
async def test_tao_hoc_vu_chi_tieu_0_luu_dung_0(
    client: AsyncClient, admin_token_headers: Dict[str, str], duong_dan: str
):
    oid = await _tao_loai_hinh(client, admin_token_headers)
    than = _than_tao(oid)
    than["annual_admission_quota"] = 0

    r = await client.post(duong_dan % oid, json=than, headers=admin_token_headers)

    assert r.status_code in (200, 201), r.text
    assert r.json()["annual_admission_quota"] == 0
    assert await _chi_tieu_trong_csdl(r.json()["id"]) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ban_dau, than_sua, mong_doi",
    [
        (None, {"tuition_fee_per_year": "13000000"}, None),
        (0, {"tuition_fee_per_year": "13000000"}, 0),
        (40, {"annual_admission_quota": None}, None),
        (None, {"annual_admission_quota": 0}, 0),
    ],
    ids=["trong_sua_hoc_phi_van_trong", "0_sua_hoc_phi_van_0", "40_dat_ve_trong", "trong_dat_0"],
)
@pytest.mark.parametrize("duong_dan", ROUTE_SUA, ids=["route_thuong", "route_admin"])
async def test_sua_hoc_vu_trong_khac_0(
    client: AsyncClient,
    admin_token_headers: Dict[str, str],
    duong_dan: str,
    ban_dau: Optional[int],
    than_sua: dict,
    mong_doi: Optional[int],
):
    oid = await _tao_loai_hinh(client, admin_token_headers)
    than = _than_tao(oid)
    than["annual_admission_quota"] = ban_dau
    r = await client.post("/api/offerings/%d/academic-info" % oid, json=than, headers=admin_token_headers)
    assert r.status_code == 200, r.text
    ai = r.json()["id"]
    assert await _chi_tieu_trong_csdl(ai) == ban_dau

    r = await client.patch(duong_dan % ai, json=than_sua, headers=admin_token_headers)

    assert r.status_code == 200, r.text
    assert r.json()["annual_admission_quota"] == mong_doi
    assert await _chi_tieu_trong_csdl(ai) == mong_doi
