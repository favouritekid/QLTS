# app/utils/tz.py
"""Chuẩn hoá timezone dùng chung — gộp các bản sao `_aware` rải khắp SMS.

Khác `datetime_helpers.py` (quy ước naive = giờ-app VN, dùng cho HIỂN THỊ):
`ensure_aware` coi naive là **UTC** — hợp với các cột SMS lưu `datetime.now(
timezone.utc)` rồi so với `datetime.now(timezone.utc)` khi tính hết hạn/dwell.
"""
from datetime import datetime, timezone


def ensure_aware(dt: datetime) -> datetime:
    """Trả datetime tz-aware; naive được coi là UTC (không đổi wall-clock)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
