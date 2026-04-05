# app/services/notification_channels/base.py
"""
✅ NOTIFICATION 2.0 - PHASE 3: Base Channel Interface

Defines the contract that all notification channels must implement.
Supports Strategy Pattern for easy channel addition.

Phase C1 adds execute_delivery() — worker-compatible single-delivery entry point.
Browser channel uses send() (batch inline). Email/Zalo/SMS use execute_delivery() via worker.
"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Any, List, Optional
from dataclasses import dataclass

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.notification_delivery import NotificationDelivery


@dataclass
class ChannelResult:
    """Result of sending notifications through a channel"""
    success: bool
    sent_count: int
    failed_ids: List[int]
    error_message: str = ""
    delivery_id: Optional[int] = None  # Phase C1: for single-delivery tracking
    provider_message_id: Optional[str] = None  # Phase C1: Zalo/SMS msg ID


class BaseChannel(ABC):
    """
    Abstract base class for all notification channels.

    Each channel implementation must:
        1. Define a unique channel_name
        2. Implement send() method (batch inline, used by browser)
        3. Implement validate_config() method
        4. Optionally implement execute_delivery() (Phase C1 worker path)

    Example usage:
        channel = SocketChannel()
        result = await channel.send(
            notifications=[notif1, notif2],
            recipient_ids=[1, 2, 3],
            context={"lead_name": "John"}
        )
    """

    channel_name: str  # e.g., "browser", "email", "zalo", "sms"

    @abstractmethod
    async def send(
        self,
        notifications: List[Any],  # List[Notification] models
        recipient_ids: List[int],
        context: Dict[str, Any]
    ) -> ChannelResult:
        """
        Send notifications to recipients through this channel (batch inline).

        Used by browser channel in the dispatcher post-commit callback.
        Non-browser channels should prefer execute_delivery() via worker.

        Args:
            notifications: List of Notification model instances
            recipient_ids: List of user IDs to send to
            context: Additional context data from event payload

        Returns:
            ChannelResult with send statistics
        """
        pass

    async def execute_delivery(
        self,
        delivery: "NotificationDelivery",
        db: "AsyncSession",
    ) -> ChannelResult:
        """
        Execute a single delivery (Phase C1 worker-compatible entry point).

        Reads content from delivery.payload_snapshot instead of Notification row.
        Called by the Celery worker task for non-browser channels.

        Browser channel does NOT implement this (stays inline via send()).
        Email/Zalo/SMS channels implement this for worker execution.

        Args:
            delivery: NotificationDelivery row with payload_snapshot
            db: Async database session for lookups (e.g., resolve user email)

        Returns:
            ChannelResult with send statistics
        """
        raise NotImplementedError(
            f"Channel '{self.channel_name}' does not support execute_delivery(). "
            "Only non-browser channels implement this for worker execution."
        )

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Validate channel-specific configuration.

        Args:
            config: Channel config from NotificationAction.config

        Returns:
            True if config is valid, False otherwise
        """
        pass
