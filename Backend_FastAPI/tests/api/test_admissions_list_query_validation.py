"""Q-INFO-1 anchor: /api/admissions list query param validation.

Wave 5 (2026-05-16) adversarial bug hunting surfaced:
- `sort_by=invalid_field` → 200 silent ignore (repo fallback to created_at)
- `order=BAD` → 200 silent ignore (repo defaulted to asc for any non-`desc`)

Both fixed by promoting Query type to Literal[...] enum in router so
FastAPI/Pydantic auto-422 với clear "Input should be ..." message.

Anchor verifies:
1. Invalid sort_by → 422 với literal_error
2. Invalid order → 422 với literal_error
3. All 4 valid sort_by values accepted → 200
4. Both valid order values accepted → 200

Non-tautological: hits real route, not just schema introspection.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_list_admissions_sort_by_invalid_returns_422(
    client: AsyncClient, admin_token_headers: dict
):
    """sort_by=invalid → 422 literal_error (Q-INFO-1 fix)."""
    response = await client.get(
        "/api/admissions?sort_by=invalid_field&page_size=1",
        headers=admin_token_headers,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    # Validate the literal_error type + sort_by location
    errors = body["errors"]
    sort_err = next((e for e in errors if e["loc"] == ["query", "sort_by"]), None)
    assert sort_err is not None, f"No sort_by error in: {errors}"
    assert sort_err["type"] == "literal_error"


async def test_list_admissions_order_invalid_returns_422(
    client: AsyncClient, admin_token_headers: dict
):
    """order=BAD → 422 literal_error (Q-INFO-1 fix)."""
    response = await client.get(
        "/api/admissions?order=BAD&page_size=1",
        headers=admin_token_headers,
    )
    assert response.status_code == 422, response.text
    errors = response.json()["errors"]
    order_err = next((e for e in errors if e["loc"] == ["query", "order"]), None)
    assert order_err is not None, f"No order error in: {errors}"
    assert order_err["type"] == "literal_error"


@pytest.mark.parametrize(
    "sort_by", ["created_at", "updated_at", "full_name", "status"]
)
async def test_list_admissions_all_valid_sort_by_accepted(
    client: AsyncClient, admin_token_headers: dict, sort_by: str
):
    """4 valid sort_by values from FE Zod AdmissionListParams accepted."""
    response = await client.get(
        f"/api/admissions?sort_by={sort_by}&page_size=1",
        headers=admin_token_headers,
    )
    assert response.status_code == 200, (
        f"Valid sort_by={sort_by!r} rejected: {response.text}"
    )


@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_list_admissions_both_order_values_accepted(
    client: AsyncClient, admin_token_headers: dict, order: str
):
    """Both order values from FE Zod accepted."""
    response = await client.get(
        f"/api/admissions?order={order}&page_size=1",
        headers=admin_token_headers,
    )
    assert response.status_code == 200, (
        f"Valid order={order!r} rejected: {response.text}"
    )
