# app/services/notification_channels/__init__.py
"""
✅ NOTIFICATION 2.0 - PHASE 3: Channel Registry

Central registry for all notification channels.
Provides factory function to get channel instances.

Canonical channel names: browser, email, zalo, zalo_bot, sms
Legacy value "socket" is normalized to "browser" on read and rejected on write.
"""
from typing import Dict, List, Optional, Type
from .base import BaseChannel, ChannelResult
from .socket_channel import SocketChannel
from .email_channel import EmailChannel
# from .sms_channel import SMSChannel    # TODO: Future


# =============================================================================
# Canonical channel values
# =============================================================================

CANONICAL_CHANNELS = frozenset({"browser", "email", "zalo", "zalo_bot", "sms"})

_CHANNEL_ALIASES = {
    "socket": "browser",  # Legacy alias — normalize on read, reject on write
}


def normalize_channel(value: str) -> str:
    """
    Normalize a channel value to its canonical form.

    - "socket" → "browser" (legacy compat)
    - "browser", "email", "zalo", "sms" → returned as-is
    - anything else → raises ValueError

    Use this on every read path for rules/actions/templates that may contain
    legacy "socket" values persisted before the migration.
    """
    if value in CANONICAL_CHANNELS:
        return value
    canonical = _CHANNEL_ALIASES.get(value)
    if canonical:
        return canonical
    raise ValueError(
        f"Unknown channel: '{value}'. "
        f"Canonical channels: {sorted(CANONICAL_CHANNELS)}"
    )


def normalize_channels(values: List[str]) -> List[str]:
    """Normalize a list of channel values, preserving order and removing duplicates."""
    seen = set()
    result = []
    for v in values:
        canonical = normalize_channel(v)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def validate_channel_for_write(value: str) -> str:
    """
    Validate a channel value for new writes (create/update).

    Rejects legacy "socket" — new data must use "browser".
    Returns the canonical value on success.

    Raises:
        ValueError: If value is "socket" or unknown
    """
    if value in _CHANNEL_ALIASES:
        raise ValueError(
            f"Channel '{value}' is deprecated. Use '{_CHANNEL_ALIASES[value]}' instead."
        )
    if value not in CANONICAL_CHANNELS:
        raise ValueError(
            f"Unknown channel: '{value}'. "
            f"Allowed channels: {sorted(CANONICAL_CHANNELS)}"
        )
    return value


def validate_channels_for_write(values: List[str]) -> List[str]:
    """Validate a list of channel values for new writes."""
    return [validate_channel_for_write(v) for v in values]


# =============================================================================
# Channel Registry: Maps channel names to channel classes
# =============================================================================

CHANNEL_REGISTRY: Dict[str, Type[BaseChannel]] = {
    "browser": SocketChannel,  # Real-time notifications via Socket.IO
    "email": EmailChannel,
    # "sms": SMSChannel,      # TODO: Future
}

# Phase C1: Register Zalo channel conditionally
def _register_zalo_channel():
    """Register ZaloChannel if ZALO_ENABLED is True."""
    try:
        from app.config import settings
        if settings.ZALO_ENABLED:
            from .zalo_channel import ZaloChannel
            CHANNEL_REGISTRY["zalo"] = ZaloChannel
    except Exception:
        pass  # Config not available yet (import time)


def _register_zalo_bot_channel():
    """v5 Step 9: register ZaloBotChannel only when ``ZALO_BOT_ENABLED``.

    Channel sender is gated by env flag so accidental notification rule
    creation while the bot is unconfigured cannot mass-fire deliveries
    that would all immediately dead-letter.
    """
    try:
        from app.config import settings
        if settings.ZALO_BOT_ENABLED:
            from .zalo_bot_channel import ZaloBotChannel
            CHANNEL_REGISTRY["zalo_bot"] = ZaloBotChannel
    except Exception:
        pass  # Config not available yet (import time)


_register_zalo_channel()
_register_zalo_bot_channel()


def get_channel(channel_name: str) -> Optional[BaseChannel]:
    """
    Get a channel instance by canonical name.

    Normalizes legacy values before lookup.
    Returns None if channel is known but not yet implemented (e.g. zalo, sms).
    Raises ValueError for completely unknown channels.
    """
    canonical = normalize_channel(channel_name)
    channel_class = CHANNEL_REGISTRY.get(canonical)
    if not channel_class:
        return None  # Known channel but not yet implemented
    return channel_class()


def get_available_channels() -> list[str]:
    """Get list of currently implemented channel names."""
    return list(CHANNEL_REGISTRY.keys())


__all__ = [
    "BaseChannel",
    "ChannelResult",
    "CANONICAL_CHANNELS",
    "normalize_channel",
    "normalize_channels",
    "validate_channel_for_write",
    "validate_channels_for_write",
    "get_channel",
    "get_available_channels",
    "SocketChannel",
    "EmailChannel",
    # Phase C1: ZaloChannel registered conditionally in CHANNEL_REGISTRY
]
