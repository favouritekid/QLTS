"""PR1 Commit 4 anchor: Zalo delivery-status callbacks are fail-closed
(A08 Integrity / A10).

``_handle_delivery_status`` mutates ``NotificationDelivery`` (status /
sent_at / error_reason) and commits — a durable write reachable from the
unauthenticated public webhook. After Commit 4 it runs ONLY when the
X-ZEvent-Signature verifies; a forged/unsigned callback is still 200-acked
(no Zalo retry storm) but must NOT mutate any row.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.notification_delivery import NotificationDelivery

WEBHOOK = "/api/webhooks/zalo"


async def _make_delivery(msg_id: str, status: str = "sent") -> int:
    async with AsyncSessionLocal() as s:
        async with s.begin():
            d = NotificationDelivery(
                event="test_delivery_gate",
                channel="zalo",
                status=status,
                provider_message_id=msg_id,
            )
            s.add(d)
            await s.flush()
            return d.id


async def _status_of(delivery_id: int) -> str:
    async with AsyncSessionLocal() as s:
        row = await s.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.id == delivery_id
            )
        )
        return row.scalar_one().status


@pytest.mark.asyncio
async def test_forged_delivery_callback_does_not_mutate(client: AsyncClient):
    """Unsigned callback claiming error=1 must NOT flip the row to failed."""
    did = await _make_delivery("msg_forge_gate", status="sent")
    body = json.dumps(
        {
            "event_name": "oa_send_template",
            "msg_id": "msg_forge_gate",
            "error": 1,
            "status": "FAILED",
        }
    )
    resp = await client.post(
        WEBHOOK,
        content=body.encode(),
        headers={"Content-Type": "application/json"},
    )
    # Still 200-ack (no Zalo retry storm) but the row is untouched.
    assert resp.status_code == 200
    assert await _status_of(did) == "sent", (
        "forged unsigned callback must NOT mutate NotificationDelivery"
    )


@pytest.mark.asyncio
@patch("app.gateways.zalo.zalo_gateway")
async def test_signed_delivery_callback_still_mutates(
    mock_gw, client: AsyncClient
):
    """A validly-signed callback still processes (sent -> delivered) — the
    gate must not break legitimate delivery tracking."""
    mock_gw.verify_webhook_signature.return_value = True
    did = await _make_delivery("msg_valid_gate", status="sent")
    body = json.dumps(
        {
            "event_name": "oa_send_template",
            "msg_id": "msg_valid_gate",
            "error": 0,
        }
    )
    resp = await client.post(
        WEBHOOK,
        content=body.encode(),
        headers={
            "Content-Type": "application/json",
            "X-ZEvent-Signature": "valid",
        },
    )
    assert resp.status_code == 200
    assert await _status_of(did) == "delivered", (
        "validly-signed callback must still update the row (sent->delivered)"
    )
