# app/services/notification_channels/email_channel.py
"""
✅ NOTIFICATION 2.0 - PHASE 3: Email Channel Implementation

Sends notifications via email using existing EmailService
"""
import structlog
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from .base import BaseChannel, ChannelResult

log = structlog.get_logger(__name__)


class EmailChannel(BaseChannel):
    """
    Email channel for sending notifications via email.

    Uses existing EmailService infrastructure to send templated emails.
    """

    channel_name = "email"

    async def send(
        self,
        notifications: List[Any],
        recipient_ids: List[int],
        context: Dict[str, Any]
    ) -> ChannelResult:
        """
        Send notifications via email.

        Uses EmailService singleton to send notification emails.
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
                        # Use the singleton email_service's send_notification_email method
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
