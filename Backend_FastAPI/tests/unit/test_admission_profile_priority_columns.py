"""ORM smoke tests for Q9 #07 PR1 — verifies new columns are wired on
``AdmissionProfile`` and ``AdmissionProfileChoice`` models.

Catches "I added the alembic migration but forgot to update the ORM"
regressions before they surface as runtime AttributeError in the
service layer.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# AdmissionProfile — 7 new columns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "high_school_id",
        "high_school_kv_resolved",
        "permanent_commune_code",
        "area_resolution_basis",
        "area_resolution_reason",
        "priority_object_codes",
        "priority_object_evidence",
    ],
)
def test_admission_profile_has_column(column: str) -> None:
    from app.models import AdmissionProfile
    assert column in AdmissionProfile.__table__.columns, (
        f"AdmissionProfile missing column {column!r}"
    )


def test_high_school_id_is_fk_with_restrict() -> None:
    """RESTRICT prevents hard DELETE on vn_high_school while a profile
    references it — admin must use is_active=false soft-delete."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["high_school_id"]
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    fk = fks[0]
    assert fk.column.table.name == "vn_high_school"
    assert fk.ondelete == "RESTRICT"


def test_priority_object_codes_is_not_null_with_empty_default() -> None:
    """NOT NULL with empty JSONB default — engine never receives NULL,
    legacy 315 profiles get [] which means "no UT claimed"."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["priority_object_codes"]
    assert col.nullable is False


def test_priority_object_evidence_is_not_null_with_empty_default() -> None:
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["priority_object_evidence"]
    assert col.nullable is False


def test_area_resolution_basis_is_nullable() -> None:
    """Legacy 315 profiles have NULL basis until admin backfill PR7."""
    from app.models import AdmissionProfile
    col = AdmissionProfile.__table__.columns["area_resolution_basis"]
    assert col.nullable is True


# ---------------------------------------------------------------------------
# AdmissionProfileChoice — 3 snapshot columns (Q-P3-11 pattern)
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
    """Match the existing Q-P3-11 bonus_rule_snapshot semantic — precision
    (4, 2) matches priority_area_config / priority_object_config rates."""
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
    from app.models import AdmissionProfileChoice
    from sqlalchemy.dialects.postgresql import JSONB
    col = AdmissionProfileChoice.__table__.columns["priority_config_snapshot"]
    assert isinstance(col.type, JSONB)
    assert col.nullable is True
