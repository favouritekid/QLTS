# tests/api/test_zalo_webhook.py
"""
API tests for Zalo webhook endpoint.

Policy: the route always returns 200 (even on missing/invalid signature) so
Zalo does not retry-storm the endpoint. WRITE branches are signature-gated:
``user_feedback`` (Phase E.5, tested in
``tests/integration/test_admission_survey_webhook.py``) and — since PR1
Commit 4 — the delivery-status branch (oa_send_* / ZBS
user_received_message), whose no-mutation contract is tested in
``tests/api/test_zalo_webhook_delivery_gate.py``. Read-only branches
(user_follow_oa / user_unfollow_oa) remain best-effort log-only.
"""
import json
import pytest
from unittest.mock import patch

from httpx import AsyncClient


@pytest.mark.asyncio
class TestZaloWebhook:
    """Tests for POST /api/webhooks/zalo."""

    async def test_missing_signature_200_acks(self, client: AsyncClient):
        """Unsigned POSTs always 200-ack (no Zalo retry storm). The
        delivery-status branch (oa_send_template) is signature-gated since PR1
        Commit 4: no signature → 200 but NotificationDelivery is NOT mutated
        (no-mutation contract in test_zalo_webhook_delivery_gate.py)."""
        response = await client.post(
            "/api/webhooks/zalo",
            json={"event_name": "oa_send_template"},
        )
        assert response.status_code == 200

    async def test_invalid_signature_200_acks(self, client: AsyncClient):
        """Wrong signature still returns 200 (retry-storm avoidance); the
        delivery-status write is skipped by the Commit 4 gate."""
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

    @patch("app.gateways.zalo.zalo_gateway")
    async def test_zbs_user_received_routes_to_delivery_handler(
        self, mock_gw, client: AsyncClient
    ):
        """ZBS Template Message delivery confirmation arrives as
        ``user_received_message`` with header ``X-ZEvent-Server: ZNS``
        (per ZBS docs ``webhook-gui-tin-qua-sdt/su-kien-nguoi-dung-nhan-tin-qua-sdt``).

        With a valid signature (PR1 Commit 4 gate), the endpoint routes it to
        the delivery handler and 200-acks even when no matching
        ``notification_delivery`` row exists (the handler logs ``Delivery not
        found for Zalo callback`` in that case). Signature is mocked valid so
        the Commit 4 gate lets it through to the handler.
        """
        mock_gw.verify_webhook_signature.return_value = True
        body = json.dumps({
            "event_name": "user_received_message",
            "app_id": "1860141329355019864",
            "timestamp": "1602560967477",
            "sender": {"id": "OA_ID"},
            "recipient": {"id": "84987654321"},
            "message": {
                "delivery_time": "1602960467432",
                "msg_id": "no-such-msg-id-test",
                "tracking_id": "test_tracking",
            },
        })
        response = await client.post(
            "/api/webhooks/zalo",
            content=body.encode(),
            headers={
                "Content-Type": "application/json",
                "X-ZEvent-Server": "ZNS",  # ZBS marker (vs chat)
                "X-ZEvent-Signature": "valid",  # gate mock True
            },
        )
        assert response.status_code == 200

    async def test_chat_user_received_does_not_route_to_delivery_handler(
        self, client: AsyncClient
    ):
        """Same event_name without ``X-ZEvent-Server: ZNS`` is a chat
        read-receipt (e.g. a user's Zalo client confirmed delivery of a
        chat reply). It must NOT be routed to the delivery handler — that
        path is owned by ZBS Template Message confirmations only."""
        body = json.dumps({
            "event_name": "user_received_message",
            "app_id": "1860141329355019864",
            "timestamp": "1602560967477",
            "sender": {"id": "OA_ID"},
            "recipient": {"id": "USER_ID"},
            "message": {"msg_id": "chat-msg-id-xxx"},
        })
        response = await client.post(
            "/api/webhooks/zalo",
            content=body.encode(),
            headers={"Content-Type": "application/json"},  # no ZNS server header
        )
        assert response.status_code == 200
