# tests/unit/test_masking.py
"""
Unit tests for Data Masking Utilities.

Tests the masking functions for sensitive PII data:
- citizen_id (CCCD/CMND)
- phone numbers
- email addresses
"""

import pytest
from app.utils.masking import mask_citizen_id, mask_phone, mask_email


class TestMaskCitizenId:
    """Test mask_citizen_id function."""

    def test_masks_standard_12_digit_cccd(self):
        """Standard 12-digit CCCD should be masked showing last 4 digits."""
        result = mask_citizen_id("034567891234")
        assert result == "********1234"

    def test_masks_with_custom_visible_digits(self):
        """Should support custom number of visible digits."""
        result = mask_citizen_id("034567891234", visible_digits=6)
        assert result == "******891234"

    def test_masks_with_2_visible_digits(self):
        """Should work with 2 visible digits."""
        result = mask_citizen_id("034567891234", visible_digits=2)
        assert result == "**********34"

    def test_returns_none_for_none_input(self):
        """Should return None when input is None."""
        result = mask_citizen_id(None)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Should return None when input is empty string."""
        result = mask_citizen_id("")
        assert result is None

    def test_returns_original_if_too_short(self):
        """Should return original if shorter than visible_digits."""
        result = mask_citizen_id("123", visible_digits=4)
        assert result == "123"

    def test_returns_original_if_equal_to_visible_digits(self):
        """Should return original if length equals visible_digits."""
        result = mask_citizen_id("1234", visible_digits=4)
        assert result == "1234"

    def test_masks_9_digit_cmnd(self):
        """Old 9-digit CMND should also be masked."""
        result = mask_citizen_id("123456789")
        assert result == "*****6789"

    def test_default_visible_digits_is_4(self):
        """Default visible digits should be 4."""
        result = mask_citizen_id("123456789012")
        assert result == "********9012"
        assert result.endswith("9012")


class TestMaskPhone:
    """Test mask_phone function."""

    def test_masks_standard_10_digit_phone(self):
        """Standard 10-digit Vietnamese phone should be masked."""
        result = mask_phone("0901234567")
        assert result == "******4567"

    def test_masks_with_custom_visible_digits(self):
        """Should support custom number of visible digits."""
        result = mask_phone("0901234567", visible_digits=3)
        assert result == "*******567"

    def test_returns_none_for_none_input(self):
        """Should return None when input is None."""
        result = mask_phone(None)
        assert result is None

    def test_returns_none_for_empty_string(self):
        """Should return None when input is empty string."""
        result = mask_phone("")
        assert result is None

    def test_returns_original_if_too_short(self):
        """Should return original if shorter than visible_digits."""
        result = mask_phone("123", visible_digits=4)
        assert result == "123"

    def test_handles_phone_with_country_code(self):
        """Should handle phone with country code (+84)."""
        result = mask_phone("+84901234567")
        # Extracts digits: 84901234567 (11 digits)
        assert result == "*******4567"

    def test_handles_phone_with_spaces(self):
        """Should handle phone with spaces."""
        result = mask_phone("090 123 4567")
        # Extracts digits: 0901234567 (10 digits)
        assert result == "******4567"

    def test_handles_phone_with_dashes(self):
        """Should handle phone with dashes."""
        result = mask_phone("090-123-4567")
        assert result == "******4567"


class TestMaskEmail:
    """Test mask_email function."""

    def test_masks_standard_email(self):
        """Standard email should show first 2 chars + masked + domain."""
        result = mask_email("nguyenvana@example.com")
        # "nguyenvana" = 10 chars, show 2, mask 8
        assert result == "ng********@example.com"

    def test_masks_short_local_part(self):
        """Email with 3-char local part should still be masked."""
        result = mask_email("abc@test.com")
        assert result == "ab*@test.com"

    def test_returns_original_if_local_part_too_short(self):
        """Should return original if local part is 2 chars or less."""
        result = mask_email("ab@test.com")
        assert result == "ab@test.com"

    def test_returns_none_for_none_input(self):
        """Should return None when input is None."""
        result = mask_email(None)
        assert result is None

    def test_returns_original_for_invalid_email(self):
        """Should return original if no @ symbol."""
        result = mask_email("notanemail")
        assert result == "notanemail"

    def test_handles_subdomain_email(self):
        """Should handle email with subdomain."""
        result = mask_email("user@mail.example.com")
        assert result == "us**@mail.example.com"

    def test_handles_email_with_dots_in_local(self):
        """Should handle email with dots in local part."""
        result = mask_email("nguyen.van.a@example.com")
        # "nguyen.van.a" = 12 chars, show 2, mask 10
        assert result == "ng**********@example.com"

    def test_handles_email_with_plus(self):
        """Should handle email with plus sign."""
        result = mask_email("user+tag@example.com")
        assert result == "us******@example.com"


class TestMaskingIntegration:
    """Integration tests for masking in admission context."""

    def test_cccd_masking_preserves_length_info(self):
        """Masked CCCD should have same total length as original."""
        original = "034567891234"
        masked = mask_citizen_id(original)
        assert len(masked) == len(original)

    def test_masked_cccd_can_verify_last_digits(self):
        """User can verify CCCD by comparing last 4 digits."""
        full_cccd = "034567891234"
        masked = mask_citizen_id(full_cccd)

        # User provides last 4 digits for verification
        user_input = "1234"
        assert masked.endswith(user_input)

    def test_different_cccds_have_different_masks(self):
        """Different CCCDs should produce different masked values."""
        cccd1 = "034567891234"
        cccd2 = "034567895678"

        masked1 = mask_citizen_id(cccd1)
        masked2 = mask_citizen_id(cccd2)

        assert masked1 != masked2
        assert masked1 == "********1234"
        assert masked2 == "********5678"

    def test_masking_is_deterministic(self):
        """Same input should always produce same masked output."""
        cccd = "034567891234"

        result1 = mask_citizen_id(cccd)
        result2 = mask_citizen_id(cccd)
        result3 = mask_citizen_id(cccd)

        assert result1 == result2 == result3
