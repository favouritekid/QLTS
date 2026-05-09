"""Unit tests for OfferingAdmissionRound model + schema + builder
(Phase 2 v8.2 PR-2A v2 — Option A year-level).

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2 mandate).
"""
from __future__ import annotations

from datetime import date

import pytest


# ---------------------------------------------------------------------------
# 1. Model schema shape (Q1 year-level anchor)
# ---------------------------------------------------------------------------


def test_offering_admission_round_unique_per_year_code() -> None:
    """ANCHOR (P3-2 v8.2): Q1 v8.2 invariant — UNIQUE(academic_year, round_code)
    confirms round is year-level entity globally, NOT per-academic_info.

    v6 archived schema dùng UNIQUE(academic_info_id, round_code) — Option A
    pivot moves to year-level."""
    from app.models import OfferingAdmissionRound

    table_args = OfferingAdmissionRound.__table_args__
    unique_names = {
        c.name for c in table_args
        if hasattr(c, "name") and c.name and "uq_" in c.name
    }
    assert "uq_offering_admission_round_year_code" in unique_names

    # Verify columns of UNIQUE constraint
    for c in table_args:
        if hasattr(c, "name") and c.name == "uq_offering_admission_round_year_code":
            col_names = [col.name for col in c.columns]
            assert col_names == ["academic_year", "round_code"]
            return
    pytest.fail("UNIQUE constraint not found on (academic_year, round_code)")


def test_offering_admission_round_no_academic_info_id_column() -> None:
    """ANCHOR: Q1 v8.2 — round table KHÔNG có academic_info_id (moved to year-level)."""
    from app.models import OfferingAdmissionRound

    cols = {c.name for c in OfferingAdmissionRound.__table__.columns}
    assert "academic_info_id" not in cols, (
        "academic_info_id removed in v8.2 Option A — round at year level"
    )
    assert "academic_year" in cols


def test_offering_admission_round_no_quota_fields() -> None:
    """ANCHOR: v8.2 — quota fields (round_quota, admit_quota, submission_count)
    MOVED to admission_path (PR-2B v2). Round table chỉ giữ time-window/lifecycle."""
    from app.models import OfferingAdmissionRound

    cols = {c.name for c in OfferingAdmissionRound.__table__.columns}
    assert "round_quota" not in cols
    assert "admit_quota" not in cols
    assert "submission_count" not in cols


def test_offering_admission_round_columns_match_v8_spec() -> None:
    from app.models import OfferingAdmissionRound

    cols = {c.name for c in OfferingAdmissionRound.__table__.columns}
    expected = {
        "id", "academic_year",
        "round_code", "round_name",
        "start_date", "end_date",
        "is_active", "archived_at",
        # SPEC §2.1.a Rule 2 audit fields
        "extended_at", "extended_by_user_id", "extension_reason",
        "created_at", "updated_at",
    }
    assert expected.issubset(cols), f"Missing: {expected - cols}"


# ---------------------------------------------------------------------------
# 2. Pydantic schema validation
# ---------------------------------------------------------------------------


def test_create_schema_requires_round_code_and_name() -> None:
    from pydantic import ValidationError

    from app.schemas.admission_round import AdmissionRoundCreate

    with pytest.raises(ValidationError):
        AdmissionRoundCreate()  # missing required


def test_create_schema_accepts_minimal_dot1_payload() -> None:
    from app.schemas.admission_round import AdmissionRoundCreate

    payload = AdmissionRoundCreate(
        round_code="DOT_1", round_name="Đợt 1 - 2026"
    )
    assert payload.round_code == "DOT_1"
    assert payload.round_name == "Đợt 1 - 2026"
    assert payload.start_date is None
    assert payload.end_date is None
    assert payload.is_active is True


def test_extend_schema_rejects_short_reason_under_10_chars() -> None:
    from pydantic import ValidationError

    from app.schemas.admission_round import AdmissionRoundExtend

    with pytest.raises(ValidationError):
        AdmissionRoundExtend(end_date=date(2026, 12, 31), extension_reason="short")


def test_extend_schema_strips_whitespace_then_validates_length() -> None:
    from pydantic import ValidationError

    from app.schemas.admission_round import AdmissionRoundExtend

    with pytest.raises(ValidationError):
        AdmissionRoundExtend(
            end_date=date(2026, 12, 31),
            extension_reason="  9 chars  ",  # 9 visible chars after strip
        )


def test_extend_schema_accepts_10_char_reason() -> None:
    from app.schemas.admission_round import AdmissionRoundExtend

    payload = AdmissionRoundExtend(
        end_date=date(2026, 12, 31),
        extension_reason="exactly10c",
    )
    assert len(payload.extension_reason) == 10


def test_response_schema_includes_extension_audit_fields() -> None:
    from app.schemas.admission_round import AdmissionRoundResponse

    schema_fields = AdmissionRoundResponse.model_fields.keys()
    assert "academic_year" in schema_fields
    assert "extended_at" in schema_fields
    assert "extended_by_user_id" in schema_fields
    assert "extension_reason" in schema_fields
    assert "archived_at" in schema_fields
    # No quota fields (moved to admission_path PR-2B v2)
    assert "round_quota" not in schema_fields
    assert "admit_quota" not in schema_fields
    assert "submission_count" not in schema_fields


def test_bulk_create_schema_min_max_constraints() -> None:
    """Bulk-create accepts 1-10 rounds, atomic per academic_year."""
    from pydantic import ValidationError

    from app.schemas.admission_round import (
        AdmissionRoundBulkCreate,
        AdmissionRoundBulkCreateItem,
    )

    # Empty list rejected
    with pytest.raises(ValidationError):
        AdmissionRoundBulkCreate(rounds=[])

    # Valid 4-round payload
    payload = AdmissionRoundBulkCreate(
        rounds=[
            AdmissionRoundBulkCreateItem(round_code=code, round_name=f"Đợt {code} - 2026")
            for code in ["DOT_1", "DOT_2", "DOT_3", "BO_SUNG"]
        ]
    )
    assert len(payload.rounds) == 4


# ---------------------------------------------------------------------------
# 3. Builder factory defaults
# ---------------------------------------------------------------------------


def test_factory_admission_round_builder_year_level_defaults() -> None:
    """Q4 v6 + Q1 v8.2 — extend tests/fixtures/builders.py với
    AdmissionRoundBuilder year-level."""
    from tests.fixtures.builders import AdmissionRoundBuilder

    payload = AdmissionRoundBuilder.make(academic_year=2026)

    assert payload["academic_year"] == 2026
    assert payload["round_code"] == "DOT_1"
    assert payload["round_name"] == "Đợt 1 - 2026"
    assert payload["start_date"] is None
    assert payload["end_date"] is None
    assert payload["is_active"] is True
    assert payload["archived_at"] is None
    assert payload["extended_at"] is None
    assert payload["extended_by_user_id"] is None
    assert payload["extension_reason"] is None
    # NO quota fields (moved to path)
    assert "round_quota" not in payload
    assert "admit_quota" not in payload
    assert "submission_count" not in payload


def test_factory_admission_round_builder_dot2_overrides() -> None:
    from tests.fixtures.builders import AdmissionRoundBuilder

    payload = AdmissionRoundBuilder.make(
        academic_year=2026, round_code="DOT_2"
    )
    assert payload["round_code"] == "DOT_2"
    assert payload["round_name"] == "Đợt 2 - 2026"


def test_factory_admission_round_builder_year_2027() -> None:
    """Cross-year override (P3-1 v8.2 — academic_year explicit)."""
    from tests.fixtures.builders import AdmissionRoundBuilder

    payload = AdmissionRoundBuilder.make(academic_year=2027, round_code="DOT_1")
    assert payload["academic_year"] == 2027
    assert payload["round_name"] == "Đợt 1 - 2027"
