"""Tests cho Q9 #07 PR5 v1.3 PUT /api/admissions/{id} priority fields.

Replaces PR1 phase1_08b tests (high_school_id / kv_resolved /
area_resolution_reason — DROPPED in phase1_09). Locks 2-field parallel
design (cultural_education_level + vocational_qualification).

Coverage:
* Schema-level: Pydantic enum validation cho 2 new fields
* H1 cross-field: basis='permanent_address_special' requires commune_code
* Dropped fields: legacy field names no longer in schema
* Field validator: empty_str_to_none for new fields
* Realistic matrix combinations
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Pydantic Update schema — cultural_education_level enum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valid_value",
    [
        "completed_thcs",
        "graduated_thcs",
        "completed_thpt",
        "graduated_thpt",
        "graduated_gdtx",
    ],
)
def test_cultural_education_level_accepts_5_canonical_values(valid_value: str) -> None:
    """phase1_09 enum: 5 trình độ văn hóa values per Luật GDNN + TT 05/2021."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(version=1, cultural_education_level=valid_value)
    assert obj.cultural_education_level == valid_value


@pytest.mark.parametrize(
    "invalid_value",
    [
        "tot_nghiep_thpt",  # wrong format (VN text instead of enum key)
        "THPT",  # missing prefix
        "completed_uni",  # not in enum
    ],
)
def test_cultural_education_level_rejects_invalid(invalid_value: str) -> None:
    """Pydantic regex pattern enforces 5-value enum."""
    from pydantic import ValidationError

    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError):
        AdmissionProfileUpdate(version=1, cultural_education_level=invalid_value)


def test_empty_string_cultural_converted_to_none() -> None:
    """Field validator: empty string → None to bypass enum pattern."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(version=1, cultural_education_level="")
    assert obj.cultural_education_level is None


# ---------------------------------------------------------------------------
# Pydantic Update schema — vocational_qualification enum
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valid_value",
    ["none", "so_cap", "trung_cap", "cao_dang"],
)
def test_vocational_qualification_accepts_4_canonical_values(valid_value: str) -> None:
    """phase1_09 enum: 4 trình độ chuyên môn values."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(version=1, vocational_qualification=valid_value)
    assert obj.vocational_qualification == valid_value


@pytest.mark.parametrize(
    "invalid_value",
    [
        "trung_cap_nghe",  # extra suffix
        "TRUNG_CAP",  # uppercase
        "dai_hoc",  # not in enum (ĐH out of scope GDNN)
    ],
)
def test_vocational_qualification_rejects_invalid(invalid_value: str) -> None:
    from pydantic import ValidationError

    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError):
        AdmissionProfileUpdate(version=1, vocational_qualification=invalid_value)


def test_empty_string_vocational_converted_to_none() -> None:
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(version=1, vocational_qualification="")
    assert obj.vocational_qualification is None


# ---------------------------------------------------------------------------
# H1 cross-field: basis='permanent_address_special' requires commune_code
# ---------------------------------------------------------------------------


def test_basis_permanent_address_special_requires_commune_code() -> None:
    """H1 invariant: 4 special cases (PT DTNT / dự bị / quân nhân / xuất ngũ)
    bypass diploma logic — phải khai permanent_commune_code."""
    from pydantic import ValidationError

    from app.schemas.admission import AdmissionProfileUpdate

    with pytest.raises(ValidationError, match="permanent_commune_code"):
        AdmissionProfileUpdate(
            version=1,
            area_resolution_basis="permanent_address_special",
        )


def test_basis_permanent_address_special_with_commune_passes() -> None:
    """H1 happy path: commune_code present → accepted."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        area_resolution_basis="permanent_address_special",
        permanent_commune_code="01001",
    )
    assert obj.area_resolution_basis == "permanent_address_special"
    assert obj.permanent_commune_code == "01001"


def test_basis_high_school_no_payload_validator_check() -> None:
    """v1.3 change: 'high_school' basis no longer validates supporting field
    at schema-level (moved to service-layer — needs academic_history context)."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(version=1, area_resolution_basis="high_school")
    assert obj.area_resolution_basis == "high_school"


def test_basis_manual_override_no_payload_validator_check() -> None:
    """v1.3 change: manual_override reason moved to priority_resolution_snapshot
    (set by admin/officer via separate endpoint, NOT candidate payload)."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(version=1, area_resolution_basis="manual_override")
    assert obj.area_resolution_basis == "manual_override"


# ---------------------------------------------------------------------------
# Dropped fields no longer in schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dropped_field",
    [
        "high_school_id",
        "high_school_kv_resolved",
        "area_resolution_reason",
    ],
)
def test_dropped_legacy_fields_not_in_update_schema(dropped_field: str) -> None:
    """phase1_09 dropped these — Pydantic schema regression check."""
    from app.schemas.admission import AdmissionProfileUpdate

    assert dropped_field not in AdmissionProfileUpdate.model_fields, (
        f"AdmissionProfileUpdate should NOT have field {dropped_field!r} "
        f"(dropped in phase1_09 redesign)."
    )


@pytest.mark.parametrize(
    "dropped_field",
    [
        "high_school_id",
        "high_school_kv_resolved",
        "area_resolution_reason",
    ],
)
def test_dropped_legacy_fields_not_in_response_schema(dropped_field: str) -> None:
    from app.schemas.admission import AdmissionProfileResponse

    assert dropped_field not in AdmissionProfileResponse.model_fields


@pytest.mark.parametrize(
    "added_field",
    [
        "cultural_education_level",
        "vocational_qualification",
    ],
)
def test_v1_3_fields_in_update_schema(added_field: str) -> None:
    """phase1_09 added these to Update schema."""
    from app.schemas.admission import AdmissionProfileUpdate

    assert added_field in AdmissionProfileUpdate.model_fields


@pytest.mark.parametrize(
    "added_field",
    [
        "cultural_education_level",
        "vocational_qualification",
        "priority_resolution_snapshot",
    ],
)
def test_v1_3_fields_in_response_schema(added_field: str) -> None:
    """phase1_09 added these to Response schema.
    Note: priority_resolution_snapshot in Response only (not Update — server-frozen)."""
    from app.schemas.admission import AdmissionProfileResponse

    assert added_field in AdmissionProfileResponse.model_fields


def test_priority_resolution_snapshot_NOT_in_update_schema() -> None:
    """Snapshot frozen by service (T1 + T6) — NOT mutable via candidate payload."""
    from app.schemas.admission import AdmissionProfileUpdate

    assert "priority_resolution_snapshot" not in AdmissionProfileUpdate.model_fields


# ---------------------------------------------------------------------------
# Realistic combinations from matrix
# ---------------------------------------------------------------------------


def test_typical_cd_candidate_graduated_thpt_no_vocational() -> None:
    """Row 1 matrix: graduated_thpt + none → THPT multi-school basis."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
    )
    assert obj.cultural_education_level == "graduated_thpt"
    assert obj.vocational_qualification == "none"


def test_typical_cd_lien_thong_completed_thpt_with_tc() -> None:
    """Row 2 matrix: completed_thpt + trung_cap → CĐ liên thông eligible."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        cultural_education_level="completed_thpt",
        vocational_qualification="trung_cap",
    )
    assert obj.cultural_education_level == "completed_thpt"


def test_typical_tc_candidate_graduated_thcs_no_vocational() -> None:
    """Row 5 matrix: graduated_thcs + none → commune_fallback (TC eligible)."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        cultural_education_level="graduated_thcs",
        vocational_qualification="none",
    )
    assert obj.cultural_education_level == "graduated_thcs"


def test_typical_special_case_dtnt_bypass() -> None:
    """Row 8 matrix: special case bypass (DTNT) → commune_code path."""
    from app.schemas.admission import AdmissionProfileUpdate

    obj = AdmissionProfileUpdate(
        version=1,
        cultural_education_level="graduated_thpt",
        vocational_qualification="none",
        area_resolution_basis="permanent_address_special",
        permanent_commune_code="02HG01",  # PT DTNT N'Trang Lơng commune
    )
    assert obj.area_resolution_basis == "permanent_address_special"
    assert obj.permanent_commune_code == "02HG01"
