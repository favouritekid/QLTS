# tests/api/test_zalo_webhook.py
"""
Phase C1: API tests for Zalo webhook endpoint.

Tests:
- Missing signature → 401
- Invalid signature → 401
- Valid signature with mocked gateway → 200
"""
import hashlib
import hmac
import json
import pytest
from unittest.mock import patch, MagicMock

from httpx import AsyncClient


@pytest.mark.asyncio
class TestZaloWebhook:
    """Tests for POST /api/webhooks/zalo."""

    async def test_missing_signature_returns_401(self, client: AsyncClient):
        """Request without X-ZEvent-Signature header should be rejected."""
        response = await client.post(
            "/api/webhooks/zalo",
            json={"event_name": "oa_send_template"},
        )
        assert response.status_code == 401

    async def test_invalid_signature_returns_401(self, client: AsyncClient):
        """Request with wrong signature should be rejected."""
        response = await client.post(
            "/api/webhooks/zalo",
            json={"event_name": "oa_send_template"},
            headers={"X-ZEvent-Signature": "deadbeef"},
        )
        assert response.status_code == 401

    @patch("app.gateways.zalo.zalo_gateway")
    async def test_valid_signature_follow_event(self, mock_gw, client: AsyncClient):
        """Properly signed follow event should return 200."""
        # Mock the gateway's verify method on the module-level singleton
        mock_gw.verify_webhook_signature.return_value = True

        body = json.dumps({"event_name": "user_follow_oa", "follower": {"id": "u1"}})
        response = await client.post(
            "/api/webhooks/zalo",
            content=body.encode(),
            headers={
                "X-ZEvent-Signature": "anything",  # gateway mock returns True
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
