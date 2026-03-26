# app/routers/zalo_webhooks.py
"""
Phase C1: Zalo webhook receiver.

Receives delivery status callbacks and other events from Zalo.
No auth required — requests are verified via HMAC-SHA256 signature.

Endpoint:
  POST /api/webhooks/zalo
"""
import structlog
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from fastapi import Depends

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


@router.post("/zalo")
async def zalo_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive webhook events from Zalo.

    Verifies HMAC-SHA256 signature before processing.
    Returns 200 immediately to avoid Zalo retry storms.
    """
    from app.gateways.zalo import zalo_gateway
    from app.models.notification_delivery import NotificationDelivery

    # 1. Read raw body for signature verification
    body = await request.body()
    signature = request.headers.get("X-ZEvent-Signature", "")

    if not signature:
        log.warning("Zalo webhook missing signature header")
        return Response(status_code=401, content="Missing signature")

    # 2. Verify HMAC signature
    if not zalo_gateway.verify_webhook_signature(body, signature):
        log.warning("Zalo webhook signature verification failed")
        return Response(status_code=401, content="Invalid signature")

    # 3. Parse event
    try:
        data = await request.json()
    except Exception:
        log.warning("Zalo webhook invalid JSON body")
        return Response(status_code=400, content="Invalid JSON")

    event_name = data.get("event_name", "")
    log.info("Zalo webhook received", event_name=event_name)

    # 4. Handle delivery status events
    if event_name in ("oa_send_text", "oa_send_template"):
        await _handle_delivery_status(db, data)

    # 5. Handle follow/unfollow events (future: update consent)
    elif event_name == "user_follow_oa":
        log.info("Zalo user followed OA", user_id=data.get("follower", {}).get("id"))

    elif event_name == "user_unfollow_oa":
        log.info("Zalo user unfollowed OA", user_id=data.get("follower", {}).get("id"))

    # Always return 200 to acknowledge receipt
    return {"status": "ok"}


async def _handle_delivery_status(db: AsyncSession, data: dict):
    """
    Update delivery status based on Zalo callback.

    Looks up delivery by provider_message_id or tracking_id.
    """
    from app.models.notification_delivery import NotificationDelivery

    msg_id = data.get("msg_id") or data.get("message", {}).get("msg_id")
    tracking_id = data.get("tracking_id")
    status = data.get("status")
    error_code = data.get("error", 0)

    if not msg_id and not tracking_id:
        log.warning("Zalo delivery status callback without msg_id or tracking_id")
        return

    # Find delivery by provider_message_id
    query = select(NotificationDelivery)
    if msg_id:
        query = query.where(NotificationDelivery.provider_message_id == msg_id)
    elif tracking_id and tracking_id.startswith("delivery_"):
        # tracking_id format: "delivery_{id}"
        try:
            delivery_id = int(tracking_id.replace("delivery_", ""))
            query = query.where(NotificationDelivery.id == delivery_id)
        except ValueError:
            log.warning("Invalid tracking_id format", tracking_id=tracking_id)
            return

    result = await db.execute(query)
    delivery = result.scalar_one_or_none()

    if not delivery:
        log.warning(
            "Delivery not found for Zalo callback",
            msg_id=msg_id,
            tracking_id=tracking_id,
        )
        return

    # Update delivery status
    # C2-7: distinguish sent (API accepted) vs delivered (recipient received)
    if error_code == 0:
        # If delivery was already "sent" (by worker), upgrade to "delivered"
        if delivery.status == "sent":
            delivery.status = "delivered"
        else:
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
        if msg_id:
            delivery.provider_message_id = msg_id
    else:
        delivery.status = "failed"
        delivery.error_reason = f"Zalo callback error {error_code}: {status}"

    await db.commit()

    log.info(
        "Delivery status updated via Zalo webhook",
        delivery_id=delivery.id,
        new_status=delivery.status,
        msg_id=msg_id,
    )
