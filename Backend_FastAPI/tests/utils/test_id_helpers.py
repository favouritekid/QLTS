"""Tests for app.utils.id_helpers."""
from app.utils.id_helpers import (
    format_booking_code,
    format_lead_code,
    format_profile_code,
)


class TestFormatLeadCode:
    def test_zero_padding(self):
        assert format_lead_code(7) == "LEAD-000007"

    def test_large_id(self):
        assert format_lead_code(999999) == "LEAD-999999"

    def test_length_within_zalo_string_limit(self):
        assert len(format_lead_code(999999)) <= 30


class TestFormatProfileCode:
    def test_zero_padding(self):
        assert format_profile_code(1) == "HS-000001"

    def test_length_within_zalo_string_limit(self):
        assert len(format_profile_code(999999)) <= 30


class TestFormatBookingCode:
    def test_zero_padding(self):
        assert format_booking_code(42) == "CONS-000042"

    def test_length_within_zalo_string_limit(self):
        assert len(format_booking_code(999999)) <= 30
