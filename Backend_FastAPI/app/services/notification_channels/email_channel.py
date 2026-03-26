# app/services/notification_channels/email_channel.py
"""
✅ NOTIFICATION 2.0 - PHASE 3 + C1: Email Channel Implementation

Phase 3: send() — batch inline, reads from Notification row (legacy path for browser compat)
Phase C1: execute_delivery() — worker path, reads from payload_snapshot (no Notification dependency)
"""
import structlog
from typing import TYPE_CHECKING, Dict, Any, List

from .base import BaseChannel, ChannelResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.notification_delivery import NotificationDelivery

log = structlog.get_logger(__name__)


class EmailChannel(BaseChannel):
    """
    Email channel for sending notifications via email.

    Two entry points:
    - send(): Legacy batch path (used by inline dispatcher, depends on Notification rows)
    - execute_delivery(): Worker path (Phase C1, reads payload_snapshot, no Notification dependency)
    """

    channel_name = "email"

    # =========================================================================
    # Phase C1: Worker-compatible single-delivery execution
    # =========================================================================

    async def execute_delivery(
        self,
        delivery: "NotificationDelivery",
        db: "AsyncSession",
    ) -> ChannelResult:
        """
        Execute a single email delivery from payload_snapshot.

        - Internal recipients (user_id set): resolve email from User table
        - External recipients (destination set): use destination directly
        - Content: read from delivery.payload_snapshot

        Called by Celery worker task.
        """
        from app.services.email_service import email_service
        from app.models import User

        # 1. Extract content from payload_snapshot
        snapshot = delivery.payload_snapshot or {}
        title = snapshot.get("title", "Notification")
        message = snapshot.get("message", "")
        link = snapshot.get("link")
        notification_type = snapshot.get("type", "info")

        # 2. Resolve recipient email + name
        to_email = None
        recipient_name = "User"

        if delivery.destination:
            # External recipient — destination is the email address
            to_email = delivery.destination
            recipient_name = snapshot.get("recipient_name", "User")
        elif delivery.user_id:
            # Internal recipient — lookup User
            user = await db.get(User, delivery.user_id)
            if not user:
                log.warning(
                    "User not found for email delivery",
                    delivery_id=delivery.id,
                    user_id=delivery.user_id,
                )
                return ChannelResult(
                    success=False,
                    sent_count=0,
                    failed_ids=[delivery.user_id],
                    error_message=f"User {delivery.user_id} not found",
                    delivery_id=delivery.id,
                )
            if not user.email:
                log.warning(
                    "User has no email address",
                    delivery_id=delivery.id,
                    user_id=delivery.user_id,
                )
                return ChannelResult(
                    success=False,
                    sent_count=0,
                    failed_ids=[delivery.user_id],
                    error_message=f"User {delivery.user_id} has no email",
                    delivery_id=delivery.id,
                )
            to_email = user.email
            recipient_name = user.full_name or user.username or "User"
        else:
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[],
                error_message="Delivery has neither user_id nor destination",
                delivery_id=delivery.id,
            )

        # 3. Send via EmailService (sync — OK in Celery worker context)
        try:
            success = email_service.send_delivery_email(
                to_email=to_email,
                recipient_name=recipient_name,
                title=title,
                message=message,
                link=link,
                notification_type=notification_type,
            )

            if success:
                log.info(
                    "Email delivery sent",
                    delivery_id=delivery.id,
                    to_email=to_email,
                    user_id=delivery.user_id,
                )
                return ChannelResult(
                    success=True,
                    sent_count=1,
                    failed_ids=[],
                    delivery_id=delivery.id,
                )
            else:
                return ChannelResult(
                    success=False,
                    sent_count=0,
                    failed_ids=[delivery.user_id] if delivery.user_id else [],
                    error_message="EmailService.send_delivery_email returned False",
                    delivery_id=delivery.id,
                )

        except Exception as e:
            log.error(
                "Email delivery failed",
                delivery_id=delivery.id,
                to_email=to_email,
                error=str(e),
            )
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=[delivery.user_id] if delivery.user_id else [],
                error_message=str(e),
                delivery_id=delivery.id,
            )

    # =========================================================================
    # Legacy batch path (Phase 3 — kept for backward compat with inline dispatch)
    # =========================================================================

    async def send(
        self,
        notifications: List[Any],
        recipient_ids: List[int],
        context: Dict[str, Any]
    ) -> ChannelResult:
        """
        Send notifications via email (batch inline).

        Uses EmailService singleton to send notification emails.
        Legacy path — Phase C1 worker uses execute_delivery() instead.
        """
        from app.services.email_service import email_service
        from app.models import User
        from app.database import AsyncSessionLocal
        from sqlalchemy import select

        sent_count = 0
        failed_ids = []

        if not notifications:
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=recipient_ids,
                error_message="No notifications to send"
            )

        # Get users with their emails using async session
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    select(User).where(User.id.in_(recipient_ids))
                )
                users = result.scalars().all()
                user_dict = {user.id: user for user in users}

                # Send email to each recipient
                for user_id in recipient_ids:
                    user = user_dict.get(user_id)
                    if not user or not user.email:
                        log.warning(
                            "User not found or no email",
                            user_id=user_id
                        )
                        failed_ids.append(user_id)
                        continue

                    # Find notification for this user
                    notif = next(
                        (n for n in notifications if n.user_id == user_id),
                        None
                    )

                    if not notif:
                        failed_ids.append(user_id)
                        continue

                    try:
                        success = email_service.send_notification_email(
                            user_email=user.email,
                            user_name=user.full_name or user.username,
                            notification=notif
                        )
                        if success:
                            sent_count += 1
                            log.debug(
                                "Email notification sent",
                                user_id=user_id,
                                email=user.email,
                                notif_id=notif.id
                            )
                        else:
                            failed_ids.append(user_id)

                    except Exception as e:
                        log.error(
                            "Email send failed",
                            user_id=user_id,
                            email=user.email,
                            error=str(e)
                        )
                        failed_ids.append(user_id)

            except Exception as e:
                log.error("Failed to fetch users for email channel", error=str(e))
                return ChannelResult(
                    success=False,
                    sent_count=0,
                    failed_ids=recipient_ids,
                    error_message=str(e)
                )

        return ChannelResult(
            success=sent_count > 0,
            sent_count=sent_count,
            failed_ids=failed_ids
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Email channel has no special config requirements"""
        return True
