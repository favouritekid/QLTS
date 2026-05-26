"""Datetime formatting helpers for Vietnamese locale.

Naive datetimes are treated as app-local time (``settings.TIMEZONE``) to
match the convention used by ``notification_tasks.py:239-240`` which
localises naive ``Consultation.scheduled_at`` with
``pytz.timezone(settings.TIMEZONE)``. Aware datetimes are converted to
``Asia/Ho_Chi_Minh`` for display.

Used by notification payload builders when rendering into channels that
require specific formats (e.g., Zalo ZNS DATE fields capped at 20 chars).
"""
from datetime import date, datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

from app.config import settings

_APP_TZ = ZoneInfo(settings.TIMEZONE)  # source tz for naive inputs (app convention)
_VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # display tz for output


def _to_display(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Naive values are app-local time — matches notification_tasks.py:239-240.
        dt = dt.replace(tzinfo=_APP_TZ)
    return dt.astimezone(_VN_TZ)


def today_vn() -> date:
    """Current calendar day in ``Asia/Ho_Chi_Minh``.

    Use when comparing against ``Date`` columns (admission-round windows,
    due dates) so the day boundary doesn't drift by one around UTC
    midnight on a container running in UTC. ``date.today()`` reads the
    container clock (UTC in prod) and would flip a day early/late near
    midnight VN time. See the public-admissions round-eligibility filter.
    """
    return datetime.now(_VN_TZ).date()


def format_vn_date(dt: Optional[Union[date, datetime]]) -> str:
    """Return ``DD/MM/YYYY`` (10 chars). Empty string if None.

    Accepts both ``date`` and ``datetime``. ``Invoice.due_date`` and a
    handful of other DB columns are typed ``Mapped[date]`` (no tzinfo,
    just calendar day) — for those the timezone conversion is a no-op
    and we format directly. ``datetime`` inputs go through
    ``_to_display``: naive treated as ``settings.TIMEZONE``, aware
    converted to ``Asia/Ho_Chi_Minh``.

    Order of ``isinstance`` matters: ``datetime`` is a subclass of
    ``date``, so check ``datetime`` first to avoid stripping tzinfo
    from aware datetimes.
    """
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return _to_display(dt).strftime("%d/%m/%Y")
    # Plain ``date``: no timezone semantics, format the calendar day
    # as-is. Avoids the ``AttributeError: 'datetime.date' object has
    # no attribute 'tzinfo'`` regression.
    return dt.strftime("%d/%m/%Y")


def format_vn_datetime(dt: Optional[datetime]) -> str:
    """Return ``DD/MM/YYYY HH:MM`` (16 chars). Empty string if None.

    Naive inputs treated as ``settings.TIMEZONE`` (app-local); aware
    inputs converted to ``Asia/Ho_Chi_Minh`` for display. Unlike
    ``format_vn_date``, this requires a ``datetime`` because the
    output renders a clock time — passing a plain ``date`` would
    silently print ``00:00`` and hide the call-site bug.
    """
    if dt is None:
        return ""
    return _to_display(dt).strftime("%d/%m/%Y %H:%M")
