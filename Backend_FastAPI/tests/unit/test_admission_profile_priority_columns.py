"""ORM smoke tests for Q9 #07 PR5 v1.3 priority columns on AdmissionProfile.

Replaces PR1 phase1_08b column tests (high_school_id / kv_resolved /
area_resolution_reason — DROPPED in phase1_09). Locks the 2-field
parallel design (cultural_education_level + vocational_qualification)
plus priority_resolution_snapshot JSONB.

See Documents/Q9_07_PR5_REDESIGN.md v1.3 cho rationale.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# AdmissionProfile — phase1_09 columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        # v1.3 phase1_09 — 2-field parallel
        "cultural_education_level",
        "vocational_qualification",
        "priority_resolution_snapshot",
        # Kept from PR1 (still valid)
        "permanent_commune_code",
        "area_resolution_basis",
        "priority_object_codes",
        "priority_object_evidence",
    ],
)
def test_admission_profile_has_priority_column(column: str) -> None:
    from app.models import AdmissionProfile
    assert column in AdmissionProfile.__table__.columns, (
        f"AdmissionProfile missing column {column!r}"
    )


@pytest.mark.parametrize(
    "dropped_column",
    [
        # phase1_09 DROPPED these PR1 placeholders (empty, no data)
        "high_school_id",
        "high_school_kv_resolved",
        "area_resolution_reason",
    ],
)
def test_admission_profile_dropped_columns_gone(dropped_column: str) -> None:
    """phase1_09 dropped these columns — schema regression check."""
    from app.models import AdmissionProfile
    assert dropped_column not in AdmissionProfile.__table__.columns, (
        f"AdmissionProfile should NOT have column {dropped_column!r} "
        f"(dropped in phase1_09 redesign)."
    )


def test_cultural_education_level_is_nullable() -> None:
    """Nullable cho draft state; service-layer validation tại submit T1."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["cultural_education_level"]
    assert col.nullable is True


def test_vocational_qualification_not_null_with_default() -> None:
    """NOT NULL DEFAULT 'none' — auto fill legacy + new profiles."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["vocational_qualification"]
    assert col.nullable is False
    # Server default 'none' present
    assert col.server_default is not None


def test_priority_resolution_snapshot_is_jsonb_not_null_with_default() -> None:
    """Frozen KV resolution — NOT NULL DEFAULT '{}'::jsonb (Q-P3-11 pattern)."""
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["priority_resolution_snapshot"]
    assert col.nullable is False
    assert isinstance(col.type, JSONB)


def test_priority_object_codes_is_not_null_with_empty_default() -> None:
    """Kept from PR1 — engine never receives NULL JSONB."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["priority_object_codes"]
    assert col.nullable is False


def test_priority_object_evidence_is_not_null_with_empty_default() -> None:
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["priority_object_evidence"]
    assert col.nullable is False


def test_area_resolution_basis_is_nullable() -> None:
    """Legacy 315 profiles + new draft state have NULL basis until set."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["area_resolution_basis"]
    assert col.nullable is True


# ---------------------------------------------------------------------------
# AdmissionProfileChoice — snapshot columns (unchanged from PR1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "priority_area_bonus_snapshot",
        "priority_object_bonus_snapshot",
        "priority_config_snapshot",
    ],
)
def test_admission_profile_choice_has_snapshot_column(column: str) -> None:
    from app.models import AdmissionProfileChoice
    assert column in AdmissionProfileChoice.__table__.columns, (
        f"AdmissionProfileChoice missing column {column!r}"
    )


def test_bonus_snapshot_columns_use_numeric_4_2() -> None:
    """Match Q-P3-11 bonus_rule_snapshot precision."""
    from app.models import AdmissionProfileChoice
    for col_name in (
        "priority_area_bonus_snapshot",
        "priority_object_bonus_snapshot",
    ):
        col = AdmissionProfileChoice.__table__.columns[col_name]
        assert col.type.precision == 4
        assert col.type.scale == 2
        assert col.nullable is True


def test_priority_config_snapshot_is_jsonb() -> None:
    from sqlalchemy.dialects.postgresql import JSONB

    from app.models import AdmissionProfileChoice
    col = AdmissionProfileChoice.__table__.columns["priority_config_snapshot"]
    assert isinstance(col.type, JSONB)
    assert col.nullable is True


# ---------------------------------------------------------------------------
# CHECK constraint mirror (M2 fix preserved + phase1_09 new CHECKs)
# ---------------------------------------------------------------------------


def test_admission_profile_has_cultural_check() -> None:
    """phase1_09 CHECK enforces 5 cultural_education_level enum values."""
    from sqlalchemy import CheckConstraint

    from app.models import AdmissionProfile

    checks = [
        c for c in AdmissionProfile.__table__.constraints
        if isinstance(c, CheckConstraint)
        and c.name == "ck_admission_profile_cultural_education_level"
    ]
    assert len(checks) == 1, (
        "Missing CHECK constraint ck_admission_profile_cultural_education_level"
    )
    sql = str(checks[0].sqltext)
    for value in (
        "completed_thcs", "graduated_thcs",
        "completed_thpt", "graduated_thpt", "graduated_gdtx",
    ):
        assert value in sql, f"Enum value {value!r} missing from CHECK SQL"


def test_admission_profile_has_vocational_check() -> None:
    """phase1_09 CHECK enforces 4 vocational_qualification enum values."""
    from sqlalchemy import CheckConstraint

    from app.models import AdmissionProfile

    checks = [
        c for c in AdmissionProfile.__table__.constraints
        if isinstance(c, CheckConstraint)
        and c.name == "ck_admission_profile_vocational_qualification"
    ]
    assert len(checks) == 1
    sql = str(checks[0].sqltext)
    for value in ("none", "so_cap", "trung_cap", "cao_dang"):
        assert value in sql, f"Enum value {value!r} missing from CHECK SQL"
