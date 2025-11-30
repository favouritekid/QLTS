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

        Uses generic notification email template.
        """
        from app.services.email_service import send_email
        from app.models import User
        from app.database import SessionLocal

        sent_count = 0
        failed_ids = []

        if not notifications:
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=recipient_ids,
                error_message="No notifications to send"
            )

        # Get users with their emails
        db = SessionLocal()
        try:
            users = db.query(User).filter(User.id.in_(recipient_ids)).all()
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
                    await send_email(
                        to_email=user.email,
                        subject=notif.title,
                        template_name="notification_generic.html",
                        context={
                            "user_name": user.full_name or user.username,
                            "title": notif.title,
                            "message": notif.message,
                            "link": notif.link,
                            "notification_type": notif.type,
                            **context
                        }
                    )
                    sent_count += 1
                    log.debug(
                        "Email notification sent",
                        user_id=user_id,
                        email=user.email,
                        notif_id=notif.id
                    )

                except Exception as e:
                    log.error(
                        "Email send failed",
                        user_id=user_id,
                        email=user.email,
                        error=str(e)
                    )
                    failed_ids.append(user_id)

        finally:
            db.close()

        return ChannelResult(
            success=sent_count > 0,
            sent_count=sent_count,
            failed_ids=failed_ids
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Email channel has no special config requirements"""
        return True
