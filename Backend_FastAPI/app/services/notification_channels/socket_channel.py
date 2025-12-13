# app/services/notification_channels/socket_channel.py
"""
✅ NOTIFICATION 2.0 - PHASE 3: Socket.IO Channel Implementation

Sends real-time notifications to browser/app via Socket.IO
"""
import structlog
from typing import Dict, Any, List

from .base import BaseChannel, ChannelResult

log = structlog.get_logger(__name__)


class SocketChannel(BaseChannel):
    """
    Socket.IO channel for real-time browser/app notifications.

    Uses existing Socket.IO infrastructure to emit notifications
    to user rooms.
    """

    channel_name = "socket"

    async def send(
        self,
        notifications: List[Any],
        recipient_ids: List[int],
        context: Dict[str, Any]
    ) -> ChannelResult:
        """
        Send notifications via Socket.IO to online users.

        Emits 'new_notification' event to each user's room.
        """
        from app.socket_manager import sio

        sent_count = 0
        failed_ids = []

        # Get first notification for payload
        # (All notifications in this batch have same content)
        if not notifications:
            return ChannelResult(
                success=False,
                sent_count=0,
                failed_ids=recipient_ids,
                error_message="No notifications to send"
            )

        # Emit to each recipient
        for user_id in recipient_ids:
            try:
                # Find notification for this user
                notif = next(
                    (n for n in notifications if n.user_id == user_id),
                    None
                )

                if notif:
                    await sio.emit(
                        'notification',  # Must match frontend: socket.on("notification", ...)
                        {
                            "id": notif.id,
                            "user_id": notif.user_id,
                            "type": notif.type,
                            "title": notif.title,
                            "message": notif.message,
                            "link": notif.link,
                            "data": notif.data,
                            "is_read": notif.is_read,
                            "created_at": notif.created_at.isoformat(),
                        },
                        room=f"user_room_{user_id}"
                    )
                    sent_count += 1
                    log.debug(
                        "Socket notification sent",
                        user_id=user_id,
                        notif_id=notif.id
                    )

            except Exception as e:
                log.error(
                    "Socket send failed",
                    user_id=user_id,
                    error=str(e)
                )
                failed_ids.append(user_id)

        return ChannelResult(
            success=sent_count > 0,
            sent_count=sent_count,
            failed_ids=failed_ids
        )

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """Socket channel has no special config requirements"""
        return True
