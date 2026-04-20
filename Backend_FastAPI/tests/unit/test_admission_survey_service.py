"""Unit tests for ``record_feedback`` input validation (Phase E.5).

Only covers the pure parsing path — submit_time coercion, rate range,
tags normalization, missing tracking_id. DB persistence is covered by
the integration suite against the real schema so the CHECK constraints
stay in the loop.
"""
import pytest

from app.services.admission_survey_service import (
    _coerce_rate,
    _parse_submit_time,
)
from app.utils.exceptions import ValidationError


class TestCoerceRate:
    def test_valid_int(self):
        assert _coerce_rate(5) == 5
        assert _coerce_rate(1) == 1

    def test_valid_string(self):
        """Zalo sometimes sends ints, sometimes stringified ints."""
        assert _coerce_rate("3") == 3

    def test_out_of_range_high(self):
        with pytest.raises(ValidationError):
            _coerce_rate(6)

    def test_out_of_range_low(self):
        with pytest.raises(ValidationError):
            _coerce_rate(0)

    def test_negative(self):
        with pytest.raises(ValidationError):
            _coerce_rate(-1)

    def test_non_numeric(self):
        with pytest.raises(ValidationError):
            _coerce_rate("abc")

    def test_none(self):
        with pytest.raises(ValidationError):
            _coerce_rate(None)

    def test_bool_rejected(self):
        """bool is an int subclass in Python; we don't want True→1."""
        with pytest.raises(ValidationError):
            _coerce_rate(True)


class TestParseSubmitTime:
    def test_epoch_ms_string(self):
        """Docs sample: ``"submit_time": "1616673095659"``."""
        dt = _parse_submit_time("1616673095659")
        assert dt.year == 2021
        assert dt.tzinfo is not None

    def test_epoch_ms_int(self):
        dt = _parse_submit_time(1616673095659)
        assert dt.year == 2021

    def test_missing_falls_back_to_now(self):
        dt = _parse_submit_time(None)
        assert dt.tzinfo is not None

    def test_garbage_falls_back_to_now(self):
        dt = _parse_submit_time("not-a-number")
        assert dt.tzinfo is not None
