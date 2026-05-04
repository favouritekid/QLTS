"""Unit tests for ``BonusRuleOverride`` Pydantic shape + the 3 new
fields on ``AdmissionPathCreate`` / ``AdmissionPathUpdate`` /
``AdmissionPathResponse`` (#184 Wave 1 PR-1B' / phase1_03 + wired
phase1_02).

Codex P2 review on PR-1B' chốt: ``bonus_rule_override`` ships as a
typed Pydantic shape (``apply_area_bonus`` / ``apply_subject_bonus``
/ ``max_total_bonus``) instead of a raw JSONB blob. This file
locks:

* The 3-field shape — exact field set, types, defaults, range guards.
* ``extra="forbid"`` — Pydantic rejects unknown keys at the
  boundary so the admin UI can't silently round-trip stray fields
  the scoring engine ignores.
* The Create / Update / Response wiring — the 3 new fields
  (``applicable_to`` / ``method_quota`` / ``bonus_rule_override``)
  are present, with the correct optional / required semantic.

What does NOT live here:
* DB migration shape — see ``test_phase1_03_revision_chain.py``.
* Repository operator (@>/&&) — see
  ``test_admission_path_repository_audience.py``.
* applied_rules snapshot — see ``test_admission_service_applied_rules_phase1_03.py``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.admission_path import (
    AdmissionAudience,
    AdmissionPathCreate,
    AdmissionPathResponse,
    AdmissionPathUpdate,
    BonusRuleOverride,
)


# ---------------------------------------------------------------------------
# 1. BonusRuleOverride — shape + validation
# ---------------------------------------------------------------------------


def test_bonus_rule_override_accepts_all_three_fields() -> None:
    payload = {
        "apply_area_bonus": True,
        "apply_subject_bonus": False,
        "max_total_bonus": 2.75,
    }
    rule = BonusRuleOverride.model_validate(payload)
    assert rule.apply_area_bonus is True
    assert rule.apply_subject_bonus is False
    assert rule.max_total_bonus == pytest.approx(2.75)


def test_bonus_rule_override_max_total_bonus_optional_null() -> None:
    """``max_total_bonus`` is the only optional field — NULL = no
    cap on the combined area + subject bonus."""
    rule = BonusRuleOverride.model_validate(
        {"apply_area_bonus": False, "apply_subject_bonus": False}
    )
    assert rule.max_total_bonus is None


def test_bonus_rule_override_requires_apply_area_bonus() -> None:
    """``apply_area_bonus`` is required — admin form must commit a
    boolean choice rather than implying False via omission."""
    with pytest.raises(ValidationError):
        BonusRuleOverride.model_validate(
            {"apply_subject_bonus": True, "max_total_bonus": 1.0}
        )


def test_bonus_rule_override_requires_apply_subject_bonus() -> None:
    with pytest.raises(ValidationError):
        BonusRuleOverride.model_validate(
            {"apply_area_bonus": True, "max_total_bonus": 1.0}
        )


def test_bonus_rule_override_max_total_bonus_lower_bound() -> None:
    """Lower bound 0 — bonus is additive; negative makes no sense."""
    with pytest.raises(ValidationError):
        BonusRuleOverride.model_validate(
            {
                "apply_area_bonus": True,
                "apply_subject_bonus": True,
                "max_total_bonus": -0.1,
            }
        )


def test_bonus_rule_override_max_total_bonus_upper_bound() -> None:
    """Upper bound 10 — matches the GPA scale; > 10 means the rule
    is effectively unbounded and admin should pass NULL instead."""
    with pytest.raises(ValidationError):
        BonusRuleOverride.model_validate(
            {
                "apply_area_bonus": True,
                "apply_subject_bonus": True,
                "max_total_bonus": 10.01,
            }
        )


def test_bonus_rule_override_rejects_extra_keys() -> None:
    """``extra="forbid"`` (Codex P2 rationale) — admin form must
    not silently round-trip stray fields. Any key the scoring
    engine doesn't read is a bug, not a feature."""
    with pytest.raises(ValidationError):
        BonusRuleOverride.model_validate(
            {
                "apply_area_bonus": True,
                "apply_subject_bonus": True,
                "max_total_bonus": 1.0,
                "stray_key": "ignored_silently?",
            }
        )


# ---------------------------------------------------------------------------
# 2. AdmissionPathCreate — 3 new fields wired
# ---------------------------------------------------------------------------


def _create_baseline_payload() -> dict:
    """Minimum valid Create payload — extracted so each test focuses
    on the field under inspection without re-stating the boilerplate."""
    return {
        "academic_info_id": 1,
        "admission_method_id": 1,
    }


def test_create_accepts_applicable_to_audience_list() -> None:
    payload = _create_baseline_payload() | {
        "applicable_to": ["POST_THPT", "LIEN_THONG_TC"],
    }
    obj = AdmissionPathCreate.model_validate(payload)
    assert obj.applicable_to == ["POST_THPT", "LIEN_THONG_TC"]


def test_create_rejects_unknown_audience() -> None:
    """Unknown audience = enum drift; FE must update lockstep with BE."""
    payload = _create_baseline_payload() | {
        "applicable_to": ["NOT_A_REAL_AUDIENCE"],
    }
    with pytest.raises(ValidationError):
        AdmissionPathCreate.model_validate(payload)


def test_create_applicable_to_defaults_to_none() -> None:
    """NULL on the wire = applicable to every audience (Phase 1+2
    contract). Optional on Create — admin sets via update later."""
    obj = AdmissionPathCreate.model_validate(_create_baseline_payload())
    assert obj.applicable_to is None


def test_create_method_quota_accepts_zero() -> None:
    """0 is a legitimate value (admin marks the method exhausted)."""
    payload = _create_baseline_payload() | {"method_quota": 0}
    obj = AdmissionPathCreate.model_validate(payload)
    assert obj.method_quota == 0


def test_create_method_quota_rejects_negative() -> None:
    payload = _create_baseline_payload() | {"method_quota": -1}
    with pytest.raises(ValidationError):
        AdmissionPathCreate.model_validate(payload)


def test_create_bonus_rule_override_passes_through_typed() -> None:
    payload = _create_baseline_payload() | {
        "bonus_rule_override": {
            "apply_area_bonus": True,
            "apply_subject_bonus": True,
            "max_total_bonus": 2.0,
        },
    }
    obj = AdmissionPathCreate.model_validate(payload)
    assert isinstance(obj.bonus_rule_override, BonusRuleOverride)
    assert obj.bonus_rule_override.max_total_bonus == 2.0


def test_create_bonus_rule_override_rejects_raw_blob() -> None:
    """Raw JSONB blob (no shape) must be rejected — Codex P2."""
    payload = _create_baseline_payload() | {
        "bonus_rule_override": {"random_blob": "no_shape"},
    }
    with pytest.raises(ValidationError):
        AdmissionPathCreate.model_validate(payload)


# ---------------------------------------------------------------------------
# 3. AdmissionPathUpdate — partial PATCH semantic
# ---------------------------------------------------------------------------


def test_update_all_three_fields_optional() -> None:
    """Update with empty body = leave everything unchanged. Service
    distinguishes "key absent" vs "key=null" via
    model_dump(exclude_unset=True) — but the Pydantic shape itself
    must accept the omission cleanly."""
    obj = AdmissionPathUpdate.model_validate({})
    assert obj.applicable_to is None
    assert obj.method_quota is None
    assert obj.bonus_rule_override is None


def test_update_applicable_to_explicit_empty_list_clears() -> None:
    """``[]`` is the explicit "clear the audience filter" signal —
    distinct from omitting the key (= leave unchanged). The schema
    parses both shapes; the service distinguishes via exclude_unset."""
    obj = AdmissionPathUpdate.model_validate({"applicable_to": []})
    assert obj.applicable_to == []


def test_update_bonus_rule_override_typed() -> None:
    obj = AdmissionPathUpdate.model_validate(
        {
            "bonus_rule_override": {
                "apply_area_bonus": False,
                "apply_subject_bonus": True,
                "max_total_bonus": None,
            }
        }
    )
    assert isinstance(obj.bonus_rule_override, BonusRuleOverride)
    assert obj.bonus_rule_override.max_total_bonus is None


# ---------------------------------------------------------------------------
# 4. AdmissionPathResponse — required (no default) so parse fails loudly
# ---------------------------------------------------------------------------


def _response_baseline_payload() -> dict:
    """Minimum valid response payload mirroring what the BE emits."""
    return {
        "id": 1,
        "status": "draft",
        "display_name": "CNTT 2026 — Xét học bạ",
        "display_order": 0,
        "visibility": "internal",
        "application_fee": None,
        "requires_application_fee": False,
        "allow_unverified_submission": False,
        "minor_correction_allowed_fields": [],
        "applicable_to": None,
        "method_quota": None,
        "bonus_rule_override": None,
        "academic_info": None,
        "admission_method": None,
        "criteria": None,
        "activated_at": None,
        "activator": None,
        "created_at": "2026-05-04T00:00:00+00:00",
        "updated_at": "2026-05-04T00:00:00+00:00",
    }


def test_response_accepts_null_for_all_three_new_fields() -> None:
    """NULL is the legacy / "no-config" signal for all three. Response
    parse must accept it — Phase 1+2 has paths not yet backfilled."""
    obj = AdmissionPathResponse.model_validate(_response_baseline_payload())
    assert obj.applicable_to is None
    assert obj.method_quota is None
    assert obj.bonus_rule_override is None


def test_response_fails_when_applicable_to_missing() -> None:
    """REQUIRED (no default) — a BE that forgets to map the column
    must surface as Zod / Pydantic parse error, not a silent empty
    list. Same pattern as ``allow_unverified_submission``."""
    payload = _response_baseline_payload()
    payload.pop("applicable_to")
    with pytest.raises(ValidationError):
        AdmissionPathResponse.model_validate(payload)


def test_response_fails_when_method_quota_missing() -> None:
    payload = _response_baseline_payload()
    payload.pop("method_quota")
    with pytest.raises(ValidationError):
        AdmissionPathResponse.model_validate(payload)


def test_response_fails_when_bonus_rule_override_missing() -> None:
    payload = _response_baseline_payload()
    payload.pop("bonus_rule_override")
    with pytest.raises(ValidationError):
        AdmissionPathResponse.model_validate(payload)


def test_response_round_trips_typed_bonus_rule_override() -> None:
    payload = _response_baseline_payload() | {
        "bonus_rule_override": {
            "apply_area_bonus": True,
            "apply_subject_bonus": True,
            "max_total_bonus": 2.75,
        },
    }
    obj = AdmissionPathResponse.model_validate(payload)
    assert isinstance(obj.bonus_rule_override, BonusRuleOverride)
    assert obj.bonus_rule_override.apply_area_bonus is True


# ---------------------------------------------------------------------------
# 5. AdmissionAudience — Literal pinned to alembic phase1_03
# ---------------------------------------------------------------------------


def test_admission_audience_literal_has_5_values() -> None:
    """Literal __args__ exposes the union members; lock the 5 values
    so any drift between BE Literal and alembic ENUM is caught
    pre-merge. Pulling values via ``typing.get_args`` is the
    Pydantic-supported way."""
    from typing import get_args

    members = set(get_args(AdmissionAudience))
    assert members == {
        "POST_THCS",
        "POST_THPT",
        "LIEN_THONG_TC",
        "LIEN_THONG_CD",
        "VLVH",
    }
