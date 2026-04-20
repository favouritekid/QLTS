# tests/api/test_zalo_webhook.py
"""
API tests for Zalo webhook endpoint.

Policy (commit bdd57f1f): the route is best-effort on signature for
the read-only branches (oa_send_* / user_follow_oa) — missing or
invalid signature still returns 200 so Zalo does not retry-storm
the endpoint. Strict persistence gating now lives only on the
``user_feedback`` branch (Phase E.5), tested in
``tests/integration/test_admission_survey_webhook.py``.
"""
import json
import pytest
from unittest.mock import patch

from httpx import AsyncClient


@pytest.mark.asyncio
class TestZaloWebhook:
    """Tests for POST /api/webhooks/zalo."""

    async def test_missing_signature_200_acks(self, client: AsyncClient):
        """Read-only branches accept unsigned POSTs — 200 ack, logged as
        signature_valid=false for observability. Persistence branches
        (user_feedback) have their own gate tested separately."""
        response = await client.post(
            "/api/webhooks/zalo",
            json={"event_name": "oa_send_template"},
        )
        assert response.status_code == 200

    async def test_invalid_signature_200_acks(self, client: AsyncClient):
        """Wrong signature still returns 200 for the same retry-storm reason."""
        response = await client.post(
            "/api/webhooks/zalo",
            json={"event_name": "oa_send_template"},
            headers={"X-ZEvent-Signature": "deadbeef"},
        )
        assert response.status_code == 200

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
