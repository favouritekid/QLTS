"""Tests for app.utils.datetime_helpers."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.utils.datetime_helpers import format_vn_date, format_vn_datetime


class TestFormatVnDate:
    def test_none_returns_empty(self):
        assert format_vn_date(None) == ""

    def test_utc_aware_datetime_converted_to_vn(self):
        # 2026-04-20 17:00 UTC → 2026-04-21 00:00 Asia/Ho_Chi_Minh (date rolls over)
        dt = datetime(2026, 4, 20, 17, 0, tzinfo=timezone.utc)
        assert format_vn_date(dt) == "21/04/2026"

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 4, 20, 17, 0)  # naive → assumed UTC
        assert format_vn_date(dt) == "21/04/2026"

    def test_vn_aware_datetime(self):
        dt = datetime(2026, 4, 20, 10, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        assert format_vn_date(dt) == "20/04/2026"

    def test_length_within_zalo_date_limit(self):
        dt = datetime(2999, 12, 31, tzinfo=timezone.utc)
        assert len(format_vn_date(dt)) <= 20


class TestFormatVnDatetime:
    def test_none_returns_empty(self):
        assert format_vn_datetime(None) == ""

    def test_format_exact(self):
        dt = datetime(2026, 4, 20, 3, 30, tzinfo=timezone.utc)
        # UTC 03:30 → VN 10:30
        assert format_vn_datetime(dt) == "20/04/2026 10:30"

    def test_naive_datetime_treated_as_utc(self):
        dt = datetime(2026, 4, 20, 3, 30)  # naive
        assert format_vn_datetime(dt) == "20/04/2026 10:30"

    def test_length_within_zalo_date_limit(self):
        dt = datetime(2999, 12, 31, 23, 59, tzinfo=timezone.utc)
        # Longest realistic output is exactly 16 chars
        assert len(format_vn_datetime(dt)) <= 20

    def test_preserves_minutes(self):
        dt = datetime(2026, 4, 20, 10, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        assert format_vn_datetime(dt) == "20/04/2026 10:30"
