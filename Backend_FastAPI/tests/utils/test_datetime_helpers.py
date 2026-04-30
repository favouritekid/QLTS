"""Tests for app.utils.datetime_helpers.

Semantic under test: naive datetimes are treated as app-local time (matching
``notification_tasks.py:239-240`` convention). With ``settings.TIMEZONE`` =
``Asia/Ho_Chi_Minh`` (default), that means naive wall-clock is preserved
through formatting — no unintended shift.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.utils.datetime_helpers import format_vn_date, format_vn_datetime


class TestFormatVnDate:
    def test_none_returns_empty(self):
        assert format_vn_date(None) == ""

    def test_utc_aware_datetime_converted_to_vn(self):
        # 2026-04-20 17:00 UTC → 2026-04-21 00:00 Asia/Ho_Chi_Minh (date rolls over).
        dt = datetime(2026, 4, 20, 17, 0, tzinfo=timezone.utc)
        assert format_vn_date(dt) == "21/04/2026"

    def test_naive_datetime_treated_as_app_local(self):
        # Naive = app-local. With TIMEZONE=Asia/Ho_Chi_Minh default, no conversion;
        # wall-clock is preserved so the date does NOT roll over.
        dt = datetime(2026, 4, 20, 17, 0)
        assert format_vn_date(dt) == "20/04/2026"

    def test_vn_aware_datetime(self):
        dt = datetime(2026, 4, 20, 10, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        assert format_vn_date(dt) == "20/04/2026"

    def test_length_within_zalo_date_limit(self):
        dt = datetime(2999, 12, 31, tzinfo=timezone.utc)
        assert len(format_vn_date(dt)) <= 20

    def test_plain_date_input_does_not_raise(self):
        """``Invoice.due_date`` is typed ``Mapped[date]`` — passing a
        plain ``date`` to the formatter must not raise
        ``AttributeError: 'datetime.date' object has no attribute
        'tzinfo'``. Anchor for the bug surfaced by
        TestPhase3Finance::test_step12_issue_invoice (memory:
        ``project_test_debt_admission_workflow_e2e``).
        """
        d = date(2026, 4, 20)
        assert format_vn_date(d) == "20/04/2026"

    def test_plain_date_no_timezone_shift(self):
        """A plain ``date`` carries no time-of-day, so the formatter
        must NOT pretend it's midnight UTC and roll the date over —
        that would silently misreport invoice due dates near midnight.
        """
        d = date(2026, 12, 31)
        assert format_vn_date(d) == "31/12/2026"


class TestFormatVnDatetime:
    def test_none_returns_empty(self):
        assert format_vn_datetime(None) == ""

    def test_utc_aware_converted_to_vn(self):
        # UTC 03:30 → VN 10:30
        dt = datetime(2026, 4, 20, 3, 30, tzinfo=timezone.utc)
        assert format_vn_datetime(dt) == "20/04/2026 10:30"

    def test_naive_datetime_treated_as_app_local(self):
        # Naive 10:30 = app-local 10:30 (no shift when TIMEZONE=Asia/Ho_Chi_Minh).
        dt = datetime(2026, 4, 20, 10, 30)
        assert format_vn_datetime(dt) == "20/04/2026 10:30"

    def test_length_within_zalo_date_limit(self):
        dt = datetime(2999, 12, 31, 23, 59, tzinfo=timezone.utc)
        assert len(format_vn_datetime(dt)) <= 20

    def test_preserves_minutes(self):
        dt = datetime(2026, 4, 20, 10, 30, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
        assert format_vn_datetime(dt) == "20/04/2026 10:30"
