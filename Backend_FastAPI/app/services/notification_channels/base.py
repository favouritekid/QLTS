# app/services/notification_channels/base.py
"""
✅ NOTIFICATION 2.0 - PHASE 3: Base Channel Interface

Defines the contract that all notification channels must implement.
Supports Strategy Pattern for easy channel addition.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass


@dataclass
class ChannelResult:
    """Result of sending notifications through a channel"""
    success: bool
    sent_count: int
    failed_ids: List[int]
    error_message: str = ""


class BaseChannel(ABC):
    """
    Abstract base class for all notification channels.

    Each channel implementation must:
        1. Define a unique channel_name
        2. Implement send() method
        3. Implement validate_config() method

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
        Send notifications to recipients through this channel.

        Args:
            notifications: List of Notification model instances
            recipient_ids: List of user IDs to send to
            context: Additional context data from event payload

        Returns:
            ChannelResult with send statistics
        """
        pass

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
