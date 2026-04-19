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

    # 2. Parse body once — we need event_name both to identify Zalo's
    #    connectivity probe (no event_name / empty body) and for dispatch.
    try:
        data = await request.json() if body else {}
    except Exception:
        log.warning("Zalo webhook invalid JSON body")
        return Response(status_code=400, content="Invalid JSON")

    event_name = data.get("event_name", "") if isinstance(data, dict) else ""

    # 3. Connectivity probe from Zalo Developer Console ("Kiểm tra" button)
    #    sends POST without X-ZEvent-Signature + empty body. Accept with 200
    #    so the admin can save the webhook URL. Real events always carry an
    #    event_name AND signature — we enforce signature only for those.
    if not event_name:
        log.info("Zalo webhook probe / heartbeat received", has_signature=bool(signature))
        return {"status": "ok", "mode": "probe"}

    if not signature:
        log.warning("Zalo webhook missing signature header", event_name=event_name)
        return Response(status_code=401, content="Missing signature")

    # 4. Verify HMAC signature for real events
    if not zalo_gateway.verify_webhook_signature(body, signature):
        log.warning("Zalo webhook signature verification failed", event_name=event_name)
        return Response(status_code=401, content="Invalid signature")

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

    Lookup strategy:
    1. If msg_id present → query by provider_message_id
    2. If step 1 misses AND tracking_id is valid → fallback query by delivery ID
    3. If tracking_id only (no msg_id) → query by delivery ID directly
    """
    from app.models.notification_delivery import NotificationDelivery

    msg_id = data.get("msg_id") or data.get("message", {}).get("msg_id")
    tracking_id = data.get("tracking_id")
    status = data.get("status")
    error_code = data.get("error", 0)

    if not msg_id and not tracking_id:
        log.warning("Zalo delivery status callback without msg_id or tracking_id")
        return

    delivery = None

    # Step 1: try msg_id lookup
    if msg_id:
        result = await db.execute(
            select(NotificationDelivery)
            .where(NotificationDelivery.provider_message_id == msg_id)
        )
        delivery = result.scalar_one_or_none()

    # Step 2: fallback to tracking_id if msg_id missed or absent
    if delivery is None and tracking_id and tracking_id.startswith("delivery_"):
        try:
            parsed_id = int(tracking_id.replace("delivery_", ""))
            result = await db.execute(
                select(NotificationDelivery)
                .where(NotificationDelivery.id == parsed_id)
            )
            delivery = result.scalar_one_or_none()
            if delivery and msg_id:
                log.info(
                    "Webhook fallback: msg_id lookup missed, found via tracking_id",
                    msg_id=msg_id,
                    tracking_id=tracking_id,
                    delivery_id=delivery.id,
                )
        except ValueError:
            log.warning("Invalid tracking_id format", tracking_id=tracking_id)

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
        if delivery.status == "sent":
            delivery.status = "delivered"
        else:
            delivery.status = "sent"
            delivery.sent_at = datetime.now(timezone.utc)
        # Persist msg_id (covers both direct hit and fallback paths)
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
