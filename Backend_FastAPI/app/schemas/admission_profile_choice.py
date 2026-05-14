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

        Strategy v0.6: convert ORM instance → dict explicit + inject
        computed fields. Pydantic field-binds from dict reliably (avoids
        from_attributes ambiguity với ORM monkey-patch).
        """
        # Skip nếu input đã là dict
        if isinstance(data, dict):
            return data

        # ORM instance — build dict from attributes
        out: dict[str, Any] = {}
        for field_name in (
            "id", "admission_profile_id", "admission_path_id",
            "path_subject_group_config_id", "display_order", "decision",
            "waitlist_rank", "eligibility_check_result",
            "bonus_rule_snapshot", "created_at", "updated_at",
        ):
            out[field_name] = getattr(data, field_name, None)

        # Compute display fields từ eager-loaded relations
        path = getattr(data, "admission_path", None)
        config = getattr(data, "path_subject_group_config", None)

        display_path_parts: list[str] = []
        if path is not None:
            academic_info = getattr(path, "academic_info", None)
            program = (
                getattr(academic_info, "program", None)
                if academic_info is not None
                else None
            )
            method = getattr(path, "admission_method", None)
            round_obj = getattr(path, "admission_round", None)

            if program is not None:
                program_name = getattr(program, "name", None) or ""
                if program_name:
                    display_path_parts.append(program_name)
            if academic_info is not None:
                year = getattr(academic_info, "academic_year", None)
                if year:
                    display_path_parts.append(str(year))
            if method is not None:
                method_code = getattr(method, "code", None) or ""
                if method_code:
                    display_path_parts.append(method_code)
            if round_obj is not None:
                round_code = getattr(round_obj, "round_code", None) or ""
                if round_code:
                    display_path_parts.append(round_code)

        out["display_path_name"] = " - ".join(display_path_parts)

        subject_group_name = ""
        if config is not None:
            subject_group = getattr(config, "subject_group", None)
            if subject_group is not None:
                subject_group_name = getattr(subject_group, "name", None) or ""
        out["display_subject_group_name"] = subject_group_name

        # Nested scores — list[ChoiceScoreSummary] built from ProfileChoiceScore
        scores_list: list[dict[str, Any]] = []
        scores = getattr(data, "scores", None) or []
        for score_row in scores:
            subject = getattr(score_row, "subject", None)
            scores_list.append({
                "subject_id": getattr(score_row, "subject_id", None),
                "subject_code": getattr(subject, "code", "") if subject else "",
                "subject_name": getattr(subject, "name_vi", "") if subject else "",
                "score": getattr(score_row, "score", None),
                "max_score_snapshot": getattr(
                    score_row, "max_score_snapshot", None
                ),
                "min_possible_score_snapshot": getattr(
                    score_row, "min_possible_score_snapshot", None
                ),
                "weight_snapshot": getattr(score_row, "weight_snapshot", None),
            })
        out["scores"] = scores_list

        return out


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


class ChoiceUpdateDisplayOrderRequest(BaseModel):
    """PATCH /api/v2/admissions/{pid}/choices/{cid} payload.

    PR-3D-B BE-1 — admin/officer/manager manual reorder. Single-row update
    (FE batch reorder sends N PATCHes; DB UNIQUE(profile, display_order) is
    safety net for transient duplicate).
    """

    display_order: int = Field(..., ge=1, le=10)

    model_config = ConfigDict(extra="forbid")


class ChoiceScoresReplaceRequest(BaseModel):
    """PATCH /api/v2/admissions/{pid}/choices/{cid}/scores payload.

    PR-3D-B BE-1 — replace ALL scores on a choice (idempotent set semantics).
    Service clears existing rows + reinserts with fresh snapshots from
    Subject + SubjectGroupSubject (max_score, weight).

    Empty list is a valid "clear scores" intent.
    """

    scores: list["ChoiceScoreInput"] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class ChoiceDeleteRequest(BaseModel):
    """PR-CO-3 (FU #114) — optional audit body for DELETE choice.

    Captured into ``user_activity_log.description`` + ``changes`` so a
    candidate "where did NV 3 go?" complaint 3 months later has a
    forensic trace (actor + reason + before-snapshot). Reason is
    OPTIONAL — the audit row is still written without it; the body
    itself is also optional on the wire so callers without a reason
    can just ``DELETE`` with no payload.
    """

    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional reason for deletion (audit trail)",
    )

    model_config = ConfigDict(extra="forbid")


class ChoiceDeleteResponse(BaseModel):
    """DELETE /api/v2/admissions/{pid}/choices/{cid} response."""

    choice_id: int
    profile_id: int


# Resolve forward references
AdmissionProfileChoiceCreate.model_rebuild()
ChoiceScoresReplaceRequest.model_rebuild()
