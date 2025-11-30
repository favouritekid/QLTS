# app/services/notification_channels/__init__.py
"""
✅ NOTIFICATION 2.0 - PHASE 3: Channel Registry

Central registry for all notification channels.
Provides factory function to get channel instances.
"""
from typing import Dict, Type
from .base import BaseChannel, ChannelResult
from .socket_channel import SocketChannel
from .email_channel import EmailChannel
# from .zalo_channel import ZaloChannel  # TODO: Phase 2
# from .sms_channel import SMSChannel    # TODO: Phase 2


# Channel Registry: Maps channel names to channel classes
CHANNEL_REGISTRY: Dict[str, Type[BaseChannel]] = {
    "socket": SocketChannel,
    "email": EmailChannel,
    # "zalo": ZaloChannel,    # TODO
    # "sms": SMSChannel,      # TODO
}


def get_channel(channel_name: str) -> BaseChannel:
    """
    Get a channel instance by name.

    Args:
        channel_name: Name of the channel ("socket", "email", etc.)

    Returns:
        Channel instance

    Raises:
        ValueError: If channel name is not registered
    """
    channel_class = CHANNEL_REGISTRY.get(channel_name)
    if not channel_class:
        raise ValueError(
            f"Unknown channel: {channel_name}. "
            f"Available channels: {list(CHANNEL_REGISTRY.keys())}"
        )
    return channel_class()


def get_available_channels() -> list[str]:
    """Get list of available channel names"""
    return list(CHANNEL_REGISTRY.keys())


__all__ = [
    "BaseChannel",
    "ChannelResult",
    "get_channel",
    "get_available_channels",
    "SocketChannel",
    "EmailChannel",
]
