"""Unit tests for OfferingAdmissionRound model + schema + builder
fixtures (Phase 2 PR-2A).

Covers schema-level shape (no DB required), Pydantic validation,
factory defaults. Service + API tests live separately.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# 1. Model schema shape
# ---------------------------------------------------------------------------


def test_offering_admission_round_model_table_name() -> None:
    from app.models import OfferingAdmissionRound

    assert OfferingAdmissionRound.__tablename__ == "offering_admission_round"


def test_offering_admission_round_has_unique_constraint_on_code() -> None:
    """SPEC line 535 + 558 — UNIQUE(academic_info_id, round_code) bắt
    candidate INSERT ON CONFLICT idempotent."""
    from app.models import OfferingAdmissionRound

    table_args = OfferingAdmissionRound.__table_args__
    unique_names = {
        c.name for c in table_args
        if hasattr(c, "name") and c.name and "uq_" in c.name
    }
    assert "uq_offering_admission_round_code" in unique_names


def test_offering_admission_round_columns_match_spec() -> None:
    """SPEC line 530-560 + Concern A v4 audit fields."""
    from app.models import OfferingAdmissionRound

    cols = {c.name for c in OfferingAdmissionRound.__table__.columns}
    expected = {
        "id", "academic_info_id",
        "round_code", "round_name",
        "start_date", "end_date",
        "round_quota", "admit_quota",
        "submission_count",
        "is_active", "archived_at",
        # Concern A v4: extension audit fields per SPEC line 552-557
        "extended_at", "extended_by_user_id", "extension_reason",
        "created_at", "updated_at",
    }
    assert expected.issubset(cols), f"Missing: {expected - cols}"


def test_offering_admission_round_back_populates_to_academic_info() -> None:
    from app.models import OfferingAcademicInfo, OfferingAdmissionRound

    rels = set(OfferingAcademicInfo.__mapper__.relationships.keys())
    assert "admission_rounds" in rels

    rel = OfferingAcademicInfo.__mapper__.relationships["admission_rounds"]
    assert rel.uselist is True
    cascade_set = set(rel.cascade)
    assert "delete-orphan" in cascade_set


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
    assert payload.round_quota is None
    assert payload.admit_quota is None
    assert payload.is_active is True


def test_extend_schema_rejects_short_reason_under_10_chars() -> None:
    """Concern A v4 — SPEC §2.1.a Rule 2 reason ≥10 chars mandatory."""
    from pydantic import ValidationError

    from app.schemas.admission_round import AdmissionRoundExtend

    with pytest.raises(ValidationError):
        AdmissionRoundExtend(end_date=date(2026, 12, 31), extension_reason="short")


def test_extend_schema_strips_whitespace_then_validates_length() -> None:
    from pydantic import ValidationError

    from app.schemas.admission_round import AdmissionRoundExtend

    # 9 chars after strip → reject
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
    """v6 test — response shape covers Concern A v4 fields."""
    from app.schemas.admission_round import AdmissionRoundResponse

    schema_fields = AdmissionRoundResponse.model_fields.keys()
    assert "extended_at" in schema_fields
    assert "extended_by_user_id" in schema_fields
    assert "extension_reason" in schema_fields
    assert "archived_at" in schema_fields
    assert "submission_count" in schema_fields


def test_update_schema_override_flag_default_false() -> None:
    """v2.12 P1 fix #4 — override flag để admin reduce quota dưới
    submission_count, default False."""
    from app.schemas.admission_round import AdmissionRoundUpdate

    payload = AdmissionRoundUpdate()
    assert payload.override is False


# ---------------------------------------------------------------------------
# 3. Builder factory defaults
# ---------------------------------------------------------------------------


def test_factory_admission_round_builder_defaults() -> None:
    """Q4 v6 — extend tests/fixtures/builders.py với
    AdmissionRoundBuilder, no _factories/ namespace."""
    from tests.fixtures.builders import AdmissionRoundBuilder

    payload = AdmissionRoundBuilder.make(academic_info_id=42)

    assert payload["academic_info_id"] == 42
    assert payload["round_code"] == "DOT_1"
    assert payload["round_name"] == "Đợt 1 - 2026"
    assert payload["start_date"] is None
    assert payload["end_date"] is None
    assert payload["round_quota"] is None
    assert payload["admit_quota"] is None
    assert payload["submission_count"] == 0
    assert payload["is_active"] is True
    assert payload["archived_at"] is None
    assert payload["extended_at"] is None
    assert payload["extended_by_user_id"] is None
    assert payload["extension_reason"] is None


def test_factory_admission_round_builder_dot2_overrides() -> None:
    from tests.fixtures.builders import AdmissionRoundBuilder

    payload = AdmissionRoundBuilder.make(
        academic_info_id=99,
        round_code="DOT_2",
        round_quota=50,
        admit_quota=30,
    )
    assert payload["round_code"] == "DOT_2"
    assert payload["round_name"] == "Đợt 2 - 2026"
    assert payload["round_quota"] == 50
    assert payload["admit_quota"] == 30
