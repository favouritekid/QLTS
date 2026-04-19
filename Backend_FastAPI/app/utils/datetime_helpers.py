"""Datetime formatting helpers for Vietnamese locale.

Naive datetimes are treated as app-local time (``settings.TIMEZONE``) to
match the convention used by ``notification_tasks.py:239-240`` which
localises naive ``Consultation.scheduled_at`` with
``pytz.timezone(settings.TIMEZONE)``. Aware datetimes are converted to
``Asia/Ho_Chi_Minh`` for display.

Used by notification payload builders when rendering into channels that
require specific formats (e.g., Zalo ZNS DATE fields capped at 20 chars).
"""
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import settings

_APP_TZ = ZoneInfo(settings.TIMEZONE)  # source tz for naive inputs (app convention)
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # display tz for output


def _to_display(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Naive values are app-local time — matches notification_tasks.py:239-240.
        dt = dt.replace(tzinfo=_APP_TZ)
    return dt.astimezone(_VN_TZ)


def format_vn_date(dt: Optional[datetime]) -> str:
    """Return ``DD/MM/YYYY`` (10 chars). Empty string if None.

    Naive inputs treated as ``settings.TIMEZONE`` (app-local); aware
    inputs converted to ``Asia/Ho_Chi_Minh`` for display.
    """
    if dt is None:
        return ""
    return _to_display(dt).strftime("%d/%m/%Y")


def format_vn_datetime(dt: Optional[datetime]) -> str:
    """Return ``DD/MM/YYYY HH:MM`` (16 chars). Empty string if None.

    Naive inputs treated as ``settings.TIMEZONE`` (app-local); aware
    inputs converted to ``Asia/Ho_Chi_Minh`` for display.
    """
    if dt is None:
        return ""
    return _to_display(dt).strftime("%d/%m/%Y %H:%M")
