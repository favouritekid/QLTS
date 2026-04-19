"""Regression: AdmissionProfileResponse coerces NULL JSONB list fields to [].

Originally shipped in `b3134f94` (2026-04-18) to stop GET /api/admissions
from 500-ing when any single profile had NULL in `family_info` or
`academic_history`. DB-level NOT NULL DEFAULT '[]' now lives in migration
`nn20260419001` so new rows can't reproduce the NULL; this validator is
belt-and-suspenders for cached payloads, downgrade paths, or any
non-service write that might still send None through.

Tests hit the validator classmethod directly so they stay decoupled from
the response schema's 30+ other required fields.
"""
import pytest

from app.schemas.admission import AdmissionProfileResponse


def test_none_coerces_to_empty_list():
    assert (
        AdmissionProfileResponse._coerce_null_list_jsonb_to_empty(None) == []
    )


def test_existing_list_passes_through():
    payload = [{"a": 1}, {"b": 2}]
    result = AdmissionProfileResponse._coerce_null_list_jsonb_to_empty(payload)
    assert result is payload


def test_empty_list_passes_through():
    result = AdmissionProfileResponse._coerce_null_list_jsonb_to_empty([])
    assert result == []


def test_non_list_non_none_returned_as_is():
    # Validator only guards None; malformed non-list values are caught by
    # Pydantic's downstream list-type check (not this classmethod).
    result = AdmissionProfileResponse._coerce_null_list_jsonb_to_empty("bad")
    assert result == "bad"
