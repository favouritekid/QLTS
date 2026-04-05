# tests/unit/test_channel_normalization.py
"""
Unit tests for channel normalization (Task 1.1).

Covers:
- normalize_channel: socket→browser, canonical passthrough, unknown rejection
- normalize_channels: list normalization with dedup
- validate_channel_for_write: reject socket on new writes
- validate_channels_for_write: list validation
"""
import pytest

from app.services.notification_channels import (
    CANONICAL_CHANNELS,
    normalize_channel,
    normalize_channels,
    validate_channel_for_write,
    validate_channels_for_write,
)


class TestNormalizeChannel:
    """Tests for single channel value normalization."""

    def test_socket_normalizes_to_browser(self):
        assert normalize_channel("socket") == "browser"

    def test_browser_passthrough(self):
        assert normalize_channel("browser") == "browser"

    def test_email_passthrough(self):
        assert normalize_channel("email") == "email"

    def test_zalo_passthrough(self):
        assert normalize_channel("zalo") == "zalo"

    def test_sms_passthrough(self):
        assert normalize_channel("sms") == "sms"

    def test_unknown_channel_raises(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            normalize_channel("push")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            normalize_channel("")

    def test_case_sensitive(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            normalize_channel("Browser")

    def test_whitespace_raises(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            normalize_channel(" browser ")


class TestNormalizeChannels:
    """Tests for list of channel values normalization."""

    def test_mixed_socket_and_email(self):
        result = normalize_channels(["socket", "email"])
        assert result == ["browser", "email"]

    def test_dedup_socket_and_browser(self):
        result = normalize_channels(["socket", "browser", "email"])
        assert result == ["browser", "email"]

    def test_preserves_order(self):
        result = normalize_channels(["email", "browser", "zalo"])
        assert result == ["email", "browser", "zalo"]

    def test_empty_list(self):
        assert normalize_channels([]) == []

    def test_all_canonical(self):
        result = normalize_channels(["browser", "email", "zalo", "sms"])
        assert result == ["browser", "email", "zalo", "sms"]

    def test_unknown_in_list_raises(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            normalize_channels(["browser", "push"])


class TestValidateChannelForWrite:
    """Tests for write validation — reject legacy values."""

    def test_socket_rejected(self):
        with pytest.raises(ValueError, match="deprecated.*Use 'browser'"):
            validate_channel_for_write("socket")

    def test_browser_accepted(self):
        assert validate_channel_for_write("browser") == "browser"

    def test_email_accepted(self):
        assert validate_channel_for_write("email") == "email"

    def test_zalo_accepted(self):
        assert validate_channel_for_write("zalo") == "zalo"

    def test_sms_accepted(self):
        assert validate_channel_for_write("sms") == "sms"

    def test_unknown_rejected(self):
        with pytest.raises(ValueError, match="Unknown channel"):
            validate_channel_for_write("telegram")


class TestValidateChannelsForWrite:
    """Tests for list write validation."""

    def test_all_canonical_accepted(self):
        result = validate_channels_for_write(["browser", "email"])
        assert result == ["browser", "email"]

    def test_socket_in_list_rejected(self):
        with pytest.raises(ValueError, match="deprecated"):
            validate_channels_for_write(["browser", "socket"])

    def test_empty_list_accepted(self):
        assert validate_channels_for_write([]) == []


class TestCanonicalChannelsConstant:
    """Tests for the CANONICAL_CHANNELS constant."""

    def test_contains_four_values(self):
        assert CANONICAL_CHANNELS == {"browser", "email", "zalo", "sms"}

    def test_is_frozenset(self):
        assert isinstance(CANONICAL_CHANNELS, frozenset)
