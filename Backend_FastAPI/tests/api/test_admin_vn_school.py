"""API smoke for admin vn_school CRUD + KV assignment router (PR-B).

End-to-end qua app + real DB: lifecycle school + KV, dup-409, overlap-400,
DELETE=deactivate giữ KV (GET /kv vẫn trả), provinces, require_admin (403).
Mỗi test dùng moet_school_code RIÊNG (API commit thật).
"""
import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio]

BASE = "/api/v2/admin/vn-school"


def _school(code: str, **kw) -> dict:
    return {
        "moet_school_code": code,
        "moet_province_code": kw.get("prov", "048"),
        "name": kw.get("name", f"Trường {code}"),
        "province": kw.get("province", "Tỉnh Lâm Đồng"),
        "level": kw.get("level", "THPT"),
    }


async def test_school_lifecycle_and_kv(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    # CREATE
    r = await client.post(f"{BASE}/schools", json=_school("APISCH_A"), headers=h)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["is_active"] is True
    assert r.json()["current_kv"] is None

    # LIST (lọc mã tỉnh MOET — tránh phụ thuộc extension unaccent của q-search).
    r = await client.get(
        f"{BASE}/schools",
        params={"moet_province_code": "048"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1

    # ADD KV
    r = await client.post(
        f"{BASE}/schools/{sid}/kv",
        json={"kv_code": "KV1", "effective_from_year": 2025, "source": "manual_admin"},
        headers=h,
    )
    assert r.status_code == 201, r.text

    # LIST KV
    r = await client.get(f"{BASE}/schools/{sid}/kv", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 1
    aid = r.json()[0]["id"]

    # current_kv giờ = KV1 (qua GET schools)
    r = await client.get(
        f"{BASE}/schools", params={"moet_province_code": "048"}, headers=h
    )
    assert r.json()["items"][0]["current_kv"] == "KV1"

    # UPDATE KV
    r = await client.patch(
        f"{BASE}/kv/{aid}", json={"kv_code": "KV2-NT"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["kv_code"] == "KV2-NT"

    # DELETE school = deactivate; KV assignment VẪN còn.
    r = await client.delete(f"{BASE}/schools/{sid}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
    r = await client.get(f"{BASE}/schools/{sid}/kv", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1  # KV không bị xoá


async def test_create_duplicate_409(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    r1 = await client.post(
        f"{BASE}/schools", json=_school("APISCH_DUP"), headers=h
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        f"{BASE}/schools", json=_school("APISCH_DUP"), headers=h
    )
    assert r2.status_code == 409, r2.text


async def test_kv_overlap_400(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    r = await client.post(f"{BASE}/schools", json=_school("APISCH_OV"), headers=h)
    sid = r.json()["id"]
    r1 = await client.post(
        f"{BASE}/schools/{sid}/kv",
        json={"kv_code": "KV1", "effective_from_year": 2020, "effective_to_year": 2025},
        headers=h,
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        f"{BASE}/schools/{sid}/kv",
        json={"kv_code": "KV2", "effective_from_year": 2024},
        headers=h,
    )
    assert r2.status_code == 400, r2.text  # overlap → BusinessRuleViolation


async def test_create_invalid_level_422(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    r = await client.post(
        f"{BASE}/schools",
        json=_school("APISCH_BAD", level="KHONG_HOP_LE"),
        headers=admin_token_headers,
    )
    assert r.status_code == 422, r.text


async def test_provinces_endpoint(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    h = admin_token_headers
    await client.post(
        f"{BASE}/schools",
        json=_school("APISCH_P", prov="042", province="Tỉnh Gia Lai"),
        headers=h,
    )
    r = await client.get(f"{BASE}/provinces", headers=h)
    assert r.status_code == 200, r.text
    codes = {p["moet_province_code"] for p in r.json()}
    assert "042" in codes


async def test_non_admin_forbidden(
    client: AsyncClient, officer_token_headers: dict, setup_test_database
) -> None:
    client.cookies.clear()
    r = await client.post(
        f"{BASE}/schools", json=_school("APISCH_OFF"), headers=officer_token_headers
    )
    assert r.status_code == 403, r.text
