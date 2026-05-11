# app/schemas/admission_profile_choice.py
"""Pydantic schemas cho AdmissionProfileChoice + ProfileChoiceScore.

Phase 3 PR-3A (#184 Wave 3) — implements:

- **Contract-06 v0.6**: computed display fields qua field_validator/
  model_validator joining admission_path + path_subject_group_config.
  Avoids N+1 — repository selectinload chain pre-loads relations.

- **CHOICE_DECISIONS**: 5 values match DB CHECK constraint
  + AdmissionProfileChoice model.

Schemas:
- ChoiceScoreSummary — nested per-subject score view
- AdmissionProfileChoiceResponse — GET response với 3 computed fields
- AdmissionProfileChoiceCreate — POST payload (admin/officer/candidate)
- AdmissionProfileChoiceUpdate — PATCH payload (engine writer)
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Match model CHOICE_DECISIONS + DB CHECK constraint
ChoiceDecisionLiteral = Literal[
    "pending", "admitted", "waitlisted", "rejected", "skip"
]


class ChoiceScoreSummary(BaseModel):
    """Per-subject score nested trong ChoiceResponse.

    Contract-06: BE Pydantic serialize ProfileChoiceScore + nested
    Subject relation. FE renders trong ChoiceScoreCard component.
    """

    subject_id: int
    subject_code: str
    subject_name: str
    score: Decimal = Field(..., description="V-ACT/DGNL 1200-point precision")
    max_score_snapshot: Decimal
    min_possible_score_snapshot: Optional[Decimal] = None
    weight_snapshot: Decimal

    model_config = ConfigDict(from_attributes=True)


class AdmissionProfileChoiceResponse(BaseModel):
    """GET response cho AdmissionProfileChoice.

    Contract-06 v0.6 computed display fields qua model_validator:
    - display_path_name: join admission_path → academic_info +
      admission_method + offering_admission_round
    - display_subject_group_name: join path_subject_group_config →
      subject_group
    - scores: nested ChoiceScoreSummary[]

    Repository MUST eager-load relations qua selectinload chain
    (GAP-22 v0.6 anti-N+1).
    """

    id: int
    admission_profile_id: int
    admission_path_id: int
    path_subject_group_config_id: int
    display_order: int = Field(..., ge=1, le=10)
    decision: ChoiceDecisionLiteral
    waitlist_rank: Optional[int] = None
    eligibility_check_result: Optional[dict[str, Any]] = None
    bonus_rule_snapshot: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    # Computed display fields (Contract-06)
    display_path_name: str = Field(
        default="",
        description='Format: "{program_name} {academic_year} - {method_code} - {round_code}"',
    )
    display_subject_group_name: str = Field(
        default="",
        description="Format: subject_group.name (vd 'Toán-Lý-Hoá')",
    )
    scores: list[ChoiceScoreSummary] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def _compute_display_fields(cls, data: Any) -> Any:
        """Compute display_path_name + display_subject_group_name từ relations.

        Expects repository selectinload-ed:
        - admission_path.academic_info.program (MajorProgram)
        - admission_path.admission_method
        - admission_path.admission_round (OfferingAdmissionRound)
        - path_subject_group_config.subject_group

        Falls back gracefully nếu relations chưa loaded (return empty).
        """
        # Skip nếu input là dict (test fixture, not ORM)
        if isinstance(data, dict):
            return data

        # ORM instance — compute computed fields
        try:
            path = getattr(data, "admission_path", None)
            config = getattr(data, "path_subject_group_config", None)

            if path is not None:
                academic_info = getattr(path, "academic_info", None)
                program = (
                    getattr(academic_info, "program", None)
                    if academic_info
                    else None
                )
                method = getattr(path, "admission_method", None)
                round_obj = getattr(path, "admission_round", None)

                parts = []
                if program is not None:
                    program_name = getattr(program, "name", "") or ""
                    parts.append(program_name)
                if academic_info is not None:
                    parts.append(str(getattr(academic_info, "academic_year", "")))
                if method is not None:
                    method_code = getattr(method, "code", "") or ""
                    if method_code:
                        parts.append(method_code)
                if round_obj is not None:
                    round_code = getattr(round_obj, "round_code", "") or ""
                    if round_code:
                        parts.append(round_code)

                display_path_name = " - ".join(p for p in parts if p)
            else:
                display_path_name = ""

            if config is not None:
                subject_group = getattr(config, "subject_group", None)
                display_subject_group_name = (
                    getattr(subject_group, "name", "") or ""
                    if subject_group
                    else ""
                )
            else:
                display_subject_group_name = ""

            # Attach computed values to ORM-derived dict
            # Pydantic from_attributes mode: convert ORM → dict-like via
            # __dict__; we monkey-patch attributes so subsequent field
            # binding picks them up.
            try:
                data.display_path_name = display_path_name
                data.display_subject_group_name = display_subject_group_name
            except (AttributeError, TypeError):
                # Read-only ORM (rare) — fall back to dict construction
                # below; this path is defensive only.
                pass
        except Exception:
            # Defensive: KHÔNG raise vì computed fields là display-only;
            # FE fallback render rỗng nếu compute fail.
            pass

        return data


class AdmissionProfileChoiceCreate(BaseModel):
    """POST /api/v2/admissions/{profile_id}/choices payload.

    Service-layer guard ``add_choice`` (G7 v0.6) enforce:
    - profile.uses_choice_engine = true
    - allow_multi_nv per-round
    - count_choices < system_config.max_choices_per_profile
    - service invariant path_subject_group_config.admission_path_id ==
      admission_path_id (P1 fix #4 v1.3)
    """

    admission_path_id: int
    path_subject_group_config_id: int
    display_order: int = Field(..., ge=1, le=10)
    scores: list["ChoiceScoreInput"] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ChoiceScoreInput(BaseModel):
    """Score input cho ChoiceCreate/Update payload."""

    subject_id: int
    score: Decimal = Field(..., ge=0)

    model_config = ConfigDict(extra="forbid")


class AdmissionProfileChoiceUpdate(BaseModel):
    """PATCH cho engine writer + admin manual.

    Engine writes decision + waitlist_rank + eligibility_check_result +
    bonus_rule_snapshot tại T6 publish.

    Admin manual update display_order (reorder) hoặc decision (T10
    promote/T11 reject via service endpoint, NOT direct PATCH).
    """

    display_order: Optional[int] = Field(None, ge=1, le=10)
    decision: Optional[ChoiceDecisionLiteral] = None
    waitlist_rank: Optional[int] = None
    eligibility_check_result: Optional[dict[str, Any]] = None
    bonus_rule_snapshot: Optional[dict[str, Any]] = None

    model_config = ConfigDict(extra="forbid")


# Resolve forward reference
AdmissionProfileChoiceCreate.model_rebuild()
