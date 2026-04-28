"""Staff link API tests — Step 19.

Authenticated endpoints under ``/api/zalo-bot``. Tests use the
``officer_token_headers`` fixture to confirm the auth gate, and patch
``zalo_bot_link_service`` + Redis helpers to drive the success and
rate-limit paths without standing up real link state.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestAuthRequired:
    async def test_link_code_anonymous_blocked(self, client: AsyncClient):
        resp = await client.post("/api/zalo-bot/link-code")
        assert resp.status_code == 401

    async def test_link_status_anonymous_blocked(self, client: AsyncClient):
        resp = await client.get("/api/zalo-bot/link-status")
        assert resp.status_code == 401

    async def test_unlink_anonymous_blocked(self, client: AsyncClient):
        resp = await client.post("/api/zalo-bot/unlink")
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestLinkCodeEndpoint:
    async def test_returns_code_with_ttl_600(
        self, client: AsyncClient, officer_token_headers: dict
    ):
        async def fake_incr(key, amount=1):
            return 1

        async def fake_expire(key, seconds):
            return True

        cb = AsyncMock()
        with patch(
            "app.services.zalo_bot_link_service.generate_link_code",
            new=AsyncMock(return_value=("ABC123", cb)),
        ), patch(
            "app.routers.zalo_bot_link.safe_redis_incr",
            new=AsyncMock(side_effect=fake_incr),
        ), patch(
            "app.routers.zalo_bot_link.safe_redis_expire",
            new=AsyncMock(side_effect=fake_expire),
        ):
            resp = await client.post(
                "/api/zalo-bot/link-code", headers=officer_token_headers
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == "ABC123"
        assert body["expires_in_seconds"] == 600
        assert "ABC123" in body["instructions"]
        cb.assert_awaited_once()

    async def test_sixth_request_in_window_rate_limited(
        self, client: AsyncClient, officer_token_headers: dict
    ):
        counters = {}

        async def fake_incr(key, amount=1):
            counters[key] = counters.get(key, 0) + amount
            return counters[key]

        async def fake_expire(key, seconds):
            return True

        cb = AsyncMock()
        gen_mock = AsyncMock(return_value=("CODE12", cb))

        with patch(
            "app.services.zalo_bot_link_service.generate_link_code", new=gen_mock
        ), patch(
            "app.routers.zalo_bot_link.safe_redis_incr",
            new=AsyncMock(side_effect=fake_incr),
        ), patch(
            "app.routers.zalo_bot_link.safe_redis_expire",
            new=AsyncMock(side_effect=fake_expire),
        ):
            for i in range(5):
                resp = await client.post(
                    "/api/zalo-bot/link-code", headers=officer_token_headers
                )
                assert resp.status_code == 200, f"request {i + 1} should pass"

            resp = await client.post(
                "/api/zalo-bot/link-code", headers=officer_token_headers
            )
            assert resp.status_code == 400
            assert "Quá nhiều" in resp.json()["detail"]

        # Generator must NOT have been called for the throttled call.
        assert gen_mock.await_count == 5


@pytest.mark.asyncio
class TestLinkStatusEndpoint:
    async def test_returns_unlinked_shape_when_no_record(
        self, client: AsyncClient, officer_token_headers: dict
    ):
        with patch(
            "app.services.zalo_bot_link_service.get_link_status",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get(
                "/api/zalo-bot/link-status", headers=officer_token_headers
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"is_linked": False, "display_name": None, "linked_at": None}

    async def test_returns_linked_payload_from_service(
        self, client: AsyncClient, officer_token_headers: dict
    ):
        payload = {
            "is_linked": True,
            "display_name": "Officer A",
            "linked_at": "2026-04-26T10:00:00+00:00",
        }
        with patch(
            "app.services.zalo_bot_link_service.get_link_status",
            new=AsyncMock(return_value=payload),
        ):
            resp = await client.get(
                "/api/zalo-bot/link-status", headers=officer_token_headers
            )
        assert resp.status_code == 200
        assert resp.json() == payload


@pytest.mark.asyncio
class TestUnlinkEndpoint:
    async def test_unlink_success_calls_service(
        self, client: AsyncClient, officer_token_headers: dict
    ):
        with patch(
            "app.services.zalo_bot_link_service.unlink",
            new=AsyncMock(return_value=(True, "Đã huỷ liên kết.", None)),
        ) as svc:
            resp = await client.post(
                "/api/zalo-bot/unlink", headers=officer_token_headers
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["unlinked"] is True
        assert body["message"] == "Đã huỷ liên kết."
        svc.assert_awaited_once()

    async def test_unlink_when_not_linked_idempotent(
        self, client: AsyncClient, officer_token_headers: dict
    ):
        with patch(
            "app.services.zalo_bot_link_service.unlink",
            new=AsyncMock(return_value=(False, "Tài khoản chưa được liên kết.", None)),
        ):
            resp = await client.post(
                "/api/zalo-bot/unlink", headers=officer_token_headers
            )
        assert resp.status_code == 200
        assert resp.json()["unlinked"] is False
