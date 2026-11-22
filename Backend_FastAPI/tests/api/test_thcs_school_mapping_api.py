# -*- coding: utf-8 -*-
"""Công cụ ghép tên trường THCS (owner 22-11) — NỐI DÂY qua app thật (CLAUDE.md chung §10): danh sách nhóm, tạo
trường mới từ nhóm, ghép / huỷ ghép, áp ghép (chạy thử mặc định · cờ tắt ⇒ 409 · cờ bật ⇒ ghi), cần gạt đóng băng
tuyển sinh chặn lượt áp ghép, chỉ Admin.

Logic chi tiết: ``tests/unit/test_thcs_school_mapping_service.py``.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal
from tests.fixtures.hoi_dong_seed import LUC, chen, ma_gia

pytestmark = [pytest.mark.asyncio]

NHOM = "/api/v2/admin/vn-school/thcs-mapping"
AP = "/api/v2/admissions/thcs-school-mapping/apply"
XA = "/api/v2/admin/vn-locality/communes"


async def _ho_so_thcs(ten: str, so: int, status: str = "submitted") -> int:
    async with AsyncSessionLocal() as s:
        unit = await chen(s, "organization_unit", name=f"Đơn vị thử {so}", type="department")
        lead = await chen(
            s, "lead", full_name="Lead giả", phone="0000000000", source="gia", status="new",
            assignment_status="pending", lead_score=0, location_proximity=0, occupation_relevance=0,
            academic_performance=0, created_at=LUC, updated_at=LUC, version=1, consultation_count=0,
            cached_urgency_score=0, is_hot_lead=False, is_overdue=False, unit_id=unit,
        )
        pid = await chen(
            s, "admission_profile", lead_id=lead, academic_year=2026, citizen_id=ma_gia(72000 + so),
            applied_rules={}, created_at=LUC, updated_at=LUC, status=status, uses_choice_engine=False,
            academic_history=[{"school_id": None, "school_name": ten, "level": None, "year_from": 2018,
                               "year_to": 2021, "grade_to": 9, "gpa": None, "graduation_type": "THCS"}],
        )
        await s.commit()
    return pid


async def _lich_su(pid: int):
    async with AsyncSessionLocal() as s:
        return (await s.execute(
            text("SELECT academic_history FROM admission_profile WHERE id = :p"), {"p": pid}
        )).scalar_one()


async def test_luong_admin_nhom_tao_truong_chay_thu_va_khoa_ap_that(
    client: AsyncClient, admin_token_headers: dict, setup_test_database, monkeypatch
) -> None:
    h = admin_token_headers
    monkeypatch.setattr(settings, "THCS_MAPPING_APPLY_ENABLED", False)
    r = await client.post(XA, json={"commune_code": "99301", "province": "Tỉnh Thử", "district": "",
                                    "ward": "Xã Thử", "area_code": "KV1"}, headers=h)
    assert r.status_code == 201, r.text
    pid = await _ho_so_thcs("Trường THCS Lê Lợi", 1)

    r = await client.get(f"{NHOM}/groups", headers=h)
    assert r.status_code == 200, r.text
    nhom = {g["normalized_name"]: g for g in r.json()["items"]}
    assert nhom["lê lợi"]["profile_count"] == 1 and nhom["lê lợi"]["mapping"] is None

    r = await client.post(
        f"{NHOM}/groups/create-school",
        json={"normalized_name": "lê lợi",
              "school": {"moet_province_code": "048", "name": "THCS Lê Lợi", "province": "Tỉnh Thử",
                         "level": "THCS", "commune_code": "99301"}},
        headers=h,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["school"]["id"]
    assert r.json()["school"]["is_internal_code"] is True
    assert r.json()["mapping"]["school_id"] == sid

    # Mặc định là chạy thử: không gửi gì ⇒ không ghi.
    r = await client.post(AP, json={}, headers=h)
    assert r.status_code == 200, r.text
    kq = r.json()
    assert (kq["dry_run"], kq["applied"], kq["apply_enabled"]) == (True, False, False)
    assert (kq["rows_to_change"], kq["profiles_to_change"]) == (1, 1)
    assert (await _lich_su(pid))[0]["school_id"] is None

    # Chạy thật khi cờ tắt ⇒ 409 rõ ràng, không ghi gì.
    r = await client.post(AP, json={"dry_run": False, "expected_rows_to_change": 1,
                                    "expected_profiles_to_change": 1}, headers=h)
    assert r.status_code == 409, r.text
    assert r.json().get("reason") == "apply_disabled"
    assert (await _lich_su(pid))[0]["school_id"] is None

    # Cờ bật ⇒ ghi đúng dòng.
    monkeypatch.setattr(settings, "THCS_MAPPING_APPLY_ENABLED", True)
    r = await client.post(AP, json={"dry_run": False, "expected_rows_to_change": 1,
                                    "expected_profiles_to_change": 1}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True
    dong = (await _lich_su(pid))[0]
    assert (dong["school_id"], dong["level"]) == (sid, "THCS")

    # Huỷ ghép: dòng ghép biến mất, school_id đã áp KHÔNG bị gỡ.
    r = await client.post(f"{NHOM}/groups/unmap", json={"normalized_name": "lê lợi"}, headers=h)
    assert r.status_code == 200, r.text
    assert (await _lich_su(pid))[0]["school_id"] == sid


async def test_ghep_voi_truong_thpt_400_ten_chua_chuan_hoa_400(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    r = await client.post(
        "/api/v2/admin/vn-school/schools",
        json={"moet_school_code": "040901", "moet_province_code": "048", "name": "THPT Y", "province": "P",
              "level": "THPT"},
        headers=h,
    )
    sid = r.json()["id"]
    r = await client.post(f"{NHOM}/groups/map", json={"normalized_name": "lê lợi", "school_id": sid}, headers=h)
    assert r.status_code == 400, r.text
    r = await client.post(f"{NHOM}/groups/map", json={"normalized_name": "Trường THCS Lê Lợi", "school_id": sid},
                          headers=h)
    assert r.status_code == 400, r.text


async def test_dong_bang_tuyen_sinh_chan_ap_ghep(
    client: AsyncClient, admin_token_headers: dict, setup_test_database, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "ADMISSION_FROZEN", True)
    r = await client.post(AP, json={}, headers=admin_token_headers)
    assert r.status_code == 503, r.text
    # Danh sách nhóm (đọc) vẫn mở; ghép là danh mục ⇒ không bị đóng băng.
    r = await client.get(f"{NHOM}/groups", headers=admin_token_headers)
    assert r.status_code == 200, r.text


async def test_moi_duong_chi_admin(
    client: AsyncClient, officer_token_headers: dict, setup_test_database
) -> None:
    client.cookies.clear()
    h = officer_token_headers
    for method, path, body in (
        ("get", f"{NHOM}/groups", None),
        ("post", f"{NHOM}/groups/map", {"normalized_name": "a", "school_id": 1}),
        ("post", f"{NHOM}/groups/unmap", {"normalized_name": "a"}),
        ("post", f"{NHOM}/groups/create-school",
         {"normalized_name": "a", "school": {"moet_province_code": "048", "name": "X", "province": "P",
                                             "level": "THCS"}}),
        ("post", AP, {}),
    ):
        r = await getattr(client, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (path, r.status_code, r.text)
