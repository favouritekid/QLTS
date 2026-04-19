"""Datetime formatting helpers for Vietnamese locale.

Used by notification payload builders when rendering into channels that
require specific formats (e.g., Zalo ZNS DATE fields capped at 20 chars).
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def _to_vn(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_VN_TZ)


def format_vn_date(dt: Optional[datetime]) -> str:
    """Return ``DD/MM/YYYY`` (10 chars) in Asia/Ho_Chi_Minh. Empty string if None."""
    if dt is None:
        return ""
    return _to_vn(dt).strftime("%d/%m/%Y")


def format_vn_datetime(dt: Optional[datetime]) -> str:
    """Return ``DD/MM/YYYY HH:MM`` (16 chars) in Asia/Ho_Chi_Minh. Empty string if None."""
    if dt is None:
        return ""
    return _to_vn(dt).strftime("%d/%m/%Y %H:%M")
