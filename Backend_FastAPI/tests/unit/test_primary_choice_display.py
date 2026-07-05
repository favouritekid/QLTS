"""Unit tests for AdmissionProfileResponse.primary_choice_display (computed field).

Pure schema logic — no DB. Uses ``model_construct`` to set only the fields the
computed property reads (choices / uses_choice_engine / program_name) and passes
duck-typed choice stand-ins (SimpleNamespace) for the display attributes.
"""
from types import SimpleNamespace

import pytest

from app.schemas.admission import AdmissionProfileResponse


def _resp(**kwargs) -> AdmissionProfileResponse:
    return AdmissionProfileResponse.model_construct(**kwargs)


def _choice(order: int, program: str = "", path: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        display_order=order,
        display_program_name=program,
        display_path_name=path,
    )


@pytest.mark.unit
class TestPrimaryChoiceDisplay:
    def test_choice_engine_uses_lowest_display_order(self):
        r = _resp(
            choices=[_choice(2, "Dược"), _choice(1, "Điều dưỡng")],
            uses_choice_engine=True,
            program_name="stale lead offering",
        )
        assert r.primary_choice_display == "Điều dưỡng"

    def test_choice_engine_falls_back_to_path_when_program_blank(self):
        r = _resp(
            choices=[_choice(1, "  ", "Điều dưỡng - Chính quy - Học bạ")],
            uses_choice_engine=True,
            program_name=None,
        )
        assert r.primary_choice_display == "Điều dưỡng - Chính quy - Học bạ"

    def test_legacy_uses_program_name(self):
        r = _resp(choices=[], uses_choice_engine=False, program_name="Điều dưỡng")
        assert r.primary_choice_display == "Điều dưỡng"

    def test_empty_choice_engine_is_none_not_stale_program_name(self):
        # A choice-engine profile with no choices yet must NOT surface the
        # denormalized program_name (which may be a stale lead/offering value).
        r = _resp(choices=[], uses_choice_engine=True, program_name="stale")
        assert r.primary_choice_display is None

    def test_none_when_nothing_available(self):
        r = _resp(choices=[], uses_choice_engine=False, program_name=None)
        assert r.primary_choice_display is None

    def test_legacy_blank_program_name_is_none(self):
        r = _resp(choices=[], uses_choice_engine=False, program_name="   ")
        assert r.primary_choice_display is None
