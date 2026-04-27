"""ADM-010 regression: payment_status enum validation must be enforced
on list, status-counts and export endpoints alike.

Before the fix, only ``GET /api/admissions`` rejected invalid values; both
``GET /api/admissions/status-counts`` and ``GET /api/admissions/export``
silently dropped unknown values inside the repository helper, returning a
broader dataset than the user expected. The router now shares
``_validate_payment_status`` so all three endpoints fail closed.
"""

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")
    token = res.cookies.get("access_token")
    if not token:
        pytest.fail("Login succeeded but access_token cookie not found")
    return {"Authorization": f"Bearer {token}"}


class TestPaymentStatusValidationParity:
    """All admission filter endpoints must reject invalid payment_status."""

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/admissions",
            "/api/admissions/status-counts",
            "/api/admissions/export",
        ],
    )
    async def test_invalid_payment_status_returns_400(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        endpoint: str,
    ):
        headers = await _login(client, admin_user_in_db)
        response = await client.get(
            endpoint,
            params={"payment_status": "paidd"},
            headers=headers,
        )
        assert response.status_code == 400, (
            f"ADM-010 regression: {endpoint} must reject invalid "
            f"payment_status value, got {response.status_code}"
        )
        body = response.json()
        # Detail message names the allowed enum so clients can self-correct
        detail = (body.get("detail") or "").lower()
        assert "payment_status" in detail or "payment status" in detail

    @pytest.mark.parametrize(
        "endpoint",
        [
            "/api/admissions",
            "/api/admissions/status-counts",
            "/api/admissions/export",
        ],
    )
    @pytest.mark.parametrize("value", ["paid", "unpaid", "partial", "no_fee"])
    async def test_valid_payment_status_passes_validation(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        endpoint: str,
        value: str,
    ):
        """Sanity check: known enum values still pass the new gate.

        We only assert the response is not 400 (success or empty result is
        fine — this test fixates on validation, not data).
        """
        headers = await _login(client, admin_user_in_db)
        response = await client.get(
            endpoint,
            params={"payment_status": value},
            headers=headers,
        )
        assert response.status_code != 400, (
            f"ADM-010 regression: {endpoint} must accept {value!r}, "
            f"got {response.status_code} - {response.text[:200]}"
        )
