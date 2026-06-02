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

    # Parse body leniently.
    #
    # Zalo's generic OA webhook spec
    # (https://developers.zalo.me/docs/official-account/webhook/tong-quan)
    # does NOT define mandatory HMAC signature verification — it only
    # requires the endpoint to return HTTP 200 within 2 seconds. Signature
    # verification is therefore best-effort; we log but do not reject.
    try:
        body = await request.body()
        data = await request.json() if body else {}
    except Exception:
        log.warning("Zalo webhook invalid JSON body")
        # Still return 200 — Zalo will retry on non-2xx which amplifies failure.
        return {"status": "ok", "mode": "invalid_json"}

    event_name = data.get("event_name", "") if isinstance(data, dict) else ""
    signature = request.headers.get("X-ZEvent-Signature", "")
    # ZBS Template Message delivery callbacks carry ``X-ZEvent-Server: ZNS``;
    # chat events do not. Used below to disambiguate ``user_received_message``
    # (chat read receipt vs ZBS template delivery confirmation).
    zevent_server = request.headers.get("X-ZEvent-Server", "")

    if not event_name:
        log.info("Zalo webhook probe / heartbeat received", has_signature=bool(signature))
        return {"status": "ok", "mode": "probe"}

    # Record signature verification result for observability without blocking
    # the event. If the standard shifts back to strict signing, flip the
    # `if not sig_ok: return 401` gate in one place.
    sig_ok = False
    if signature:
        try:
            sig_ok = zalo_gateway.verify_webhook_signature(body, signature)
        except Exception as e:  # pragma: no cover — defensive
            log.warning("verify_webhook_signature raised", error=str(e))

    # Extract UID from common event shapes. Different event_name families put
    # the user identifier in different payload paths — capture the first hit.
    uid = None
    if isinstance(data, dict):
        uid = (
            (data.get("follower") or {}).get("id")              # follow / unfollow
            or (data.get("sender") or {}).get("id")             # user_send_text / image / etc
            or (data.get("recipient") or {}).get("id")          # oa_send_text / template callbacks
            or (data.get("user_id"))                            # fallback
        )
    # user_feedback carries applicant free-text (``message.note`` +
    # ``feedbacks``) — don't dump it into application logs. The DB row
    # is the audit record; the log just needs to say it happened.
    # Other event_name families have no PII so we keep raw_data for
    # ops visibility like before.
    if event_name == "user_feedback":
        _message = data.get("message", {}) if isinstance(data, dict) else {}
        log.info(
            "Zalo webhook received",
            event_name=event_name,
            signature_present=bool(signature),
            signature_valid=sig_ok,
            uid=uid,
            tracking_id=_message.get("tracking_id"),
            msg_id=_message.get("msg_id"),
            rate=_message.get("rate"),
        )
    else:
        log.info(
            "Zalo webhook received",
            event_name=event_name,
            signature_present=bool(signature),
            signature_valid=sig_ok,
            uid=uid,
            raw_data=data,
        )

    # 4. Handle delivery status events
    #
    # ZBS Template Message delivery confirmation arrives as
    # ``user_received_message`` with header ``X-ZEvent-Server: ZNS``
    # (per ZBS docs `webhook-gui-tin-qua-sdt/su-kien-nguoi-dung-nhan-tin-qua-sdt`).
    # The same event_name without the header is a chat read-receipt, which
    # we ignore. ``oa_send_text`` / ``oa_send_template`` are the chat-side
    # delivery hints retained for backward compatibility.
    is_zbs_delivery = (
        event_name == "user_received_message"
        and zevent_server == "ZNS"
    )
    if event_name in ("oa_send_text", "oa_send_template") or is_zbs_delivery:
        # PR1 Commit 4 (A08 Integrity / A10 fail-closed):
        # _handle_delivery_status mutates NotificationDelivery (status /
        # sent_at / error_reason) and commits — a durable write reachable from
        # this UNAUTHENTICATED public endpoint. Gate it on a valid signature
        # exactly like the user_feedback branch below; without this, anyone
        # could forge callbacks to flip any row's delivery status (lookup is
        # by msg_id or delivery_{id}). Every Zalo OA webhook event carries
        # X-ZEvent-Signature (sha256(appId+data+timeStamp+OAsecretKey)),
        # verified across chat + ZBS docs, so legit callbacks pass; only
        # forged/unsigned ones are dropped. Still 200-ack (no retry storm).
        if not sig_ok:
            log.warning(
                "Zalo delivery-status callback rejected: signature missing or "
                "invalid — 200-acked, NotificationDelivery NOT mutated",
                event_name=event_name,
                signature_present=bool(signature),
            )
        else:
            await _handle_delivery_status(db, data)

    # 5. Handle follow/unfollow events (future: update consent)
    elif event_name == "user_follow_oa":
        log.info("Zalo user followed OA", user_id=data.get("follower", {}).get("id"))

    elif event_name == "user_unfollow_oa":
        log.info("Zalo user unfollowed OA", user_id=data.get("follower", {}).get("id"))

    # 6. Handle rating-template feedback (Phase E — ZNS 426903 survey).
    #
    # Persistence is gated on a valid signature. Unlike the other
    # event_name branches (read-only log / status updates on rows we
    # already own), this branch is the only durable write path reachable
    # from an unauthenticated public endpoint: without the gate, anyone
    # could POST synthetic feedback and either plant rows with
    # profile_id=NULL or spray random tracking_ids to bloat the table.
    #
    # Still return 200 on sig-missing/invalid to avoid Zalo retry
    # storms — we just skip the write. Malformed payloads that pass
    # signature still 200-ack for the same reason.
    elif event_name == "user_feedback":
        if not sig_ok:
            log.warning(
                "Zalo user_feedback rejected: signature missing or invalid — 200-acked, not persisted",
                signature_present=bool(signature),
            )
        else:
            from app.services import admission_survey_service
            from app.utils.exceptions import ValidationError

            try:
                await admission_survey_service.record_feedback(
                    db, raw_payload=data
                )
                await db.commit()
            except ValidationError as e:
                log.warning(
                    "Zalo user_feedback malformed — 200-acked, not persisted",
                    error=str(e),
                )
            except Exception:
                log.exception("Zalo user_feedback handler failed unexpectedly")
                # Best-effort: swallow so Zalo doesn't retry on our own bug.

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
