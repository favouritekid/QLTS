# app/services/notification_channels/zalo_channel.py
"""
Phase C1: Zalo ZNS Channel — sends ZBS Template Messages via Zalo gateway.

Zalo channel is worker-only: send() returns an error (no inline execution).
execute_delivery() is the entry point called by the Celery worker task.

Flow:
  1. Extract phone from delivery.destination (external) or user.phone_number (internal)
  2. Normalize to Zalo format (84xxx)
  3. Check consent (external recipients)
  4. Get template_id from delivery metadata
  5. Build template_data from payload_snapshot
  6. Call zalo_gateway.send_template_message()
  7. Return ChannelResult with provider_message_id
"""
import structlog
from typing import TYPE_CHECKING, Dict, Any, List

from .base import BaseChannel, ChannelResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.notification_delivery import NotificationDelivery

log = structlog.get_logger(__name__)


class ZaloChannel(BaseChannel):
    """
    Zalo ZNS channel for sending template messages via Zalo Business Solutions.

    Worker-only: all Zalo sends go through the Celery delivery worker.
    """

    channel_name = "zalo"

    async def execute_delivery(
        self,
        delivery: "NotificationDelivery",
        db: "AsyncSession",
    ) -> ChannelResult:
        """
        Execute a single Zalo delivery.

        Resolves phone, checks consent, sends via ZBS Template Message API.
        """
        from app.gateways.zalo import zalo_gateway
        from app.utils.phone_helpers import to_zalo_phone

        # 1. Extract phone number
        phone = None
        if delivery.destination:
            # External recipient — destination is the phone number
            phone = to_zalo_phone(delivery.destination)
        elif delivery.user_id:
            # Internal recipient — lookup user's phone
            from app.models import User
            user = await db.get(User, delivery.user_id)
            if user and user.phone_number:
                phone = to_zalo_phone(user.phone_number)

        if not phone:
            msg = "No valid phone number for Zalo delivery"
            log.warning(msg, delivery_id=delivery.id, user_id=delivery.user_id)
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[delivery.user_id] if delivery.user_id else [],
                error_message=msg,
                delivery_id=delivery.id,
            )

        # 2. Check consent for external recipients
        if delivery.recipient_kind == "external" and delivery.source_type and delivery.source_id:
            from app.repositories.notification_consent_repository import NotificationConsentRepository
            consent_repo = NotificationConsentRepository(db)
            granted = await consent_repo.is_consent_granted(
                channel="zalo",
                source_type=delivery.source_type,
                source_id=delivery.source_id,
            )
            if not granted:
                log.info(
                    "Zalo delivery skipped — no consent",
                    delivery_id=delivery.id,
                    source_type=delivery.source_type,
                    source_id=delivery.source_id,
                )
                return ChannelResult(
                    success=False,
                    sent_count=0,
                    failed_ids=[delivery.user_id] if delivery.user_id else [],
                    error_message="consent_not_granted",
                    delivery_id=delivery.id,
                )

        # 3. Extract template_id and template_data
        snapshot = delivery.payload_snapshot or {}
        # template_id can come from action config stored in snapshot,
        # or from a dedicated field on the delivery
        template_id = snapshot.get("zalo_template_id") or snapshot.get("template_id")
        if not template_id:
            msg = "No zalo_template_id in payload_snapshot"
            log.warning(msg, delivery_id=delivery.id)
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[delivery.user_id] if delivery.user_id else [],
                error_message=msg,
                delivery_id=delivery.id,
            )

        # Build template_data from snapshot
        template_data = snapshot.get("zalo_template_data", {})
        if not template_data:
            # Fallback: use standard notification fields as template vars
            template_data = {
                "title": snapshot.get("title", ""),
                "message": snapshot.get("message", ""),
            }

        # 4. Send via Zalo gateway
        tracking_id = f"delivery_{delivery.id}"
        result = await zalo_gateway.send_template_message(
            phone=phone,
            template_id=template_id,
            template_data=template_data,
            tracking_id=tracking_id,
        )

        if result.success:
            log.info(
                "Zalo delivery sent",
                delivery_id=delivery.id,
                msg_id=result.msg_id,
                phone=phone[:6] + "****",  # Mask for logging
                quota_remaining=result.quota_remaining,
            )
            return ChannelResult(
                success=True,
                sent_count=1,
                failed_ids=[],
                delivery_id=delivery.id,
                provider_message_id=result.msg_id,
            )
        else:
            log.warning(
                "Zalo delivery failed",
                delivery_id=delivery.id,
                error_code=result.error_code,
                error_message=result.error_message,
            )
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[delivery.user_id] if delivery.user_id else [],
                error_message=f"Zalo error {result.error_code}: {result.error_message}",
                delivery_id=delivery.id,
            )

    async def send(
        self,
        notifications: List[Any],
        recipient_ids: List[int],
        context: Dict[str, Any],
    ) -> ChannelResult:
        """
        Batch send — NOT used for Zalo.

        Zalo sends go through execute_delivery() via Celery worker.
        This method exists only to satisfy the BaseChannel interface.
        """
        return ChannelResult(
            success=False,
            sent_count=0,
            failed_ids=recipient_ids,
            error_message="Zalo channel uses execute_delivery() via worker, not batch send()",
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Validate Zalo channel config — requires zalo_template_id."""
        if not config:
            return False
        return bool(config.get("zalo_template_id"))
