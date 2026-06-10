"""API smoke for admin commune KV CRUD router (PR-A).

End-to-end qua FastAPI app + real test DB: lifecycle admin (create →
list → replace-area temporal → retire), gate dup/404, PATCH không đổi
area_code, và require_admin (officer → 403).

Mỗi test dùng commune_code RIÊNG (API commit thật, không rollback per-test)
→ tránh đụng partial-active guard giữa các test trong cùng run.
"""
import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio]

BASE = "/api/v2/admin/vn-locality/communes"


def _payload(code: str, area: str = "KV3", **kw) -> dict:
    return {
        "commune_code": code,
        "province": kw.get("province", "Tỉnh Lâm Đồng"),
        "ward": kw.get("ward", f"Xã {code}"),
        "area_code": area,
    }


async def test_commune_lifecycle_create_replace_retire(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    code = "APISMK_LIFE"
    # CREATE
    r = await client.post(BASE, json=_payload(code, "KV3"), headers=admin_token_headers)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["area_code"] == "KV3"
    assert created["effective_to"] is None

    # LIST (active) — phải thấy code vừa tạo.
    r = await client.get(
        BASE, params={"q": code, "active_only": True}, headers=admin_token_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    old_id = body["items"][0]["id"]

    # REPLACE-AREA (đổi KV temporal → dòng active MỚI).
    r = await client.post(
        f"{BASE}/{old_id}/replace-area",
        json={"area_code": "KV1"},
        headers=admin_token_headers,
    )
    assert r.status_code == 201, r.text
    new_row = r.json()
    assert new_row["area_code"] == "KV1"
    assert new_row["effective_to"] is None
    assert new_row["id"] != old_id

    # active list → CHỈ dòng KV1; full list (active_only=false) → 2 dòng.
    r_active = await client.get(
        BASE, params={"q": code, "active_only": True}, headers=admin_token_headers
    )
    assert r_active.json()["total"] == 1
    assert r_active.json()["items"][0]["area_code"] == "KV1"
    r_all = await client.get(
        BASE, params={"q": code, "active_only": False}, headers=admin_token_headers
    )
    assert r_all.json()["total"] == 2  # cũ (retired KV3) + mới (active KV1)

    # RETIRE dòng active mới.
    r = await client.delete(f"{BASE}/{new_row['id']}", headers=admin_token_headers)
    assert r.status_code == 200, r.text
    assert r.json()["effective_to"] is not None


async def test_create_duplicate_active_returns_409(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    code = "APISMK_DUP"
    r1 = await client.post(
        BASE, json=_payload(code, "KV3"), headers=admin_token_headers
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        BASE, json=_payload(code, "KV2"), headers=admin_token_headers
    )
    assert r2.status_code == 409, r2.text


async def test_update_missing_returns_404(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    r = await client.patch(
        f"{BASE}/999999", json={"ward": "X"}, headers=admin_token_headers
    )
    assert r.status_code == 404, r.text


async def test_patch_ignores_area_code(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    code = "APISMK_PATCH"
    r = await client.post(BASE, json=_payload(code, "KV3"), headers=admin_token_headers)
    cid = r.json()["id"]
    # Gửi kèm area_code (KHÔNG có trong schema Update → Pydantic loại) + đổi ward.
    r = await client.patch(
        f"{BASE}/{cid}",
        json={"ward": "Xã Đổi Tên", "area_code": "KV1"},
        headers=admin_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ward"] == "Xã Đổi Tên"
    assert r.json()["area_code"] == "KV3"  # KHÔNG đổi qua PATCH


async def test_create_invalid_area_code_rejected(
    client: AsyncClient, admin_token_headers: dict, setup_test_database
) -> None:
    # Zod/Pydantic regex chặn underscore → 422.
    r = await client.post(
        BASE, json=_payload("APISMK_BAD", "KV2_NT"), headers=admin_token_headers
    )
    assert r.status_code == 422, r.text


async def test_non_admin_forbidden(
    client: AsyncClient, officer_token_headers: dict, setup_test_database
) -> None:
    # require_admin → officer bị chặn (403). Clear cookie tránh contamination.
    client.cookies.clear()
    r = await client.post(
        BASE, json=_payload("APISMK_OFF", "KV3"), headers=officer_token_headers
    )
    assert r.status_code == 403, r.text
