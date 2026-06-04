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
    display_program_name: str = Field(
        default="",
        description="Tên ngành (vd 'Y sỹ đa khoa') — separate cho FE render badge",
    )
    display_degree_level: str = Field(
        default="",
        description="Trình độ (vd 'Cao đẳng', 'Trung cấp') — render badge cạnh ngành",
    )
    display_subject_group_name: str = Field(
        default="",
        description="Format: subject_group.name (vd 'Toán-Lý-Hoá')",
    )
    scores: list[ChoiceScoreSummary] = Field(default_factory=list)

    # P0 hotfix multi-NV (2026-06-04) — per-NV computed score for DISPLAY.
    # profile.total_score is None for multi-NV (scores live per choice), so
    # the FE renders these per NV instead of the profile-level total. Names
    # are deliberately unambiguous: ``data_complete`` is the submit gate
    # signal (NO sàn), ``admission_threshold_passed`` is DISPLAY-ONLY (the
    # min_score floor is enforced by the T6 publish cascade, never by submit).
    data_complete: bool = Field(
        default=False,
        description=(
            "Đủ điểm để NỘP (|submitted∩allowed| ≥ required_subject_count) — "
            "KHÔNG xét sàn min_score. Mirror submit gate per-NV."
        ),
    )
    computed_total_score: Optional[Decimal] = Field(
        default=None,
        description=(
            "Điểm tổng NV tính được (no priority bonus); None khi thiếu "
            "data / invalid / chưa cấu hình criteria."
        ),
    )
    admission_threshold_passed: Optional[bool] = Field(
        default=None,
        description=(
            "Đạt sàn min_score — DISPLAY ONLY, KHÔNG dùng để gate submit. "
            "None khi data chưa đủ để chấm."
        ),
    )
    threshold_failure_reasons: list[str] = Field(default_factory=list)

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
        program_name_out = ""
        degree_level_out = ""
        if path is not None:
            academic_info = getattr(path, "academic_info", None)
            # Phase 3 follow-up Q1: program lives at offering.program (not
            # academic_info.program directly). Try both paths defensively
            # — eager-load chain admission_repository._choices_eager_load_options
            # now chains academic_info → offering → program for new code,
            # but legacy callers may still pass shallow object.
            program = None
            if academic_info is not None:
                offering = getattr(academic_info, "offering", None)
                if offering is not None:
                    program = getattr(offering, "program", None)
                if program is None:
                    program = getattr(academic_info, "program", None)
            method = getattr(path, "admission_method", None)
            round_obj = getattr(path, "admission_round", None)

            if program is not None:
                program_name_out = getattr(program, "name", None) or ""
                degree_level_out = getattr(program, "degree_level", None) or ""
                if program_name_out:
                    display_path_parts.append(program_name_out)
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
        out["display_program_name"] = program_name_out
        out["display_degree_level"] = degree_level_out

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

        # ----------------------------------------------------------------
        # P0 hotfix multi-NV — per-NV computed score (DISPLAY).
        # ----------------------------------------------------------------
        # Defensive: ANY failure (missing eager-loaded criteria / group,
        # scoring edge) falls back to safe defaults so response never 500s.
        # Reuses AdmissionScoringService.calculate_score (respects
        # subject_selection_mode + required_subject_count) — no new math.
        data_complete = False
        computed_total_score = None
        admission_threshold_passed = None
        threshold_failure_reasons: list[str] = []
        try:
            # data_complete = the SUBMIT GATE verdict for THIS choice. Reuse
            # validate_choice_scores_complete so the display badge can NEVER
            # disagree with whether Submit is actually allowed — range-check,
            # config-gap fail-closed, and per-choice-criteria required-count
            # all live in ONE place. applied_rules is unavailable in the schema
            # layer → pass {}; the gate then derives `required` from the
            # choice's own criteria (the normal case), falling back to
            # len(allowed) for a criteria-less choice exactly as the gate does
            # when applied_rules also lacks the count.
            from app.services.admission_choice_engine_service import (
                validate_choice_scores_complete,
            )
            data_complete = not validate_choice_scores_complete([data], {})

            # computed score (DISPLAY) via the scoring service — respects
            # subject_selection_mode + required_subject_count; raw combo score
            # (no priority bonus). None when data is incomplete / INVALID.
            allowed_codes: list[str] = []
            if config is not None:
                sg = getattr(config, "subject_group", None)
                if sg is not None:
                    for sgs in (getattr(sg, "subject_mappings", None) or []):
                        subj = getattr(sgs, "subject", None)
                        code = getattr(subj, "code", None) if subj else None
                        if code:
                            allowed_codes.append(code)
            submitted_map: dict[str, Any] = {}
            for srow in (getattr(data, "scores", None) or []):
                subj = getattr(srow, "subject", None)
                code = getattr(subj, "code", None) if subj else None
                if code is not None:
                    submitted_map[code] = getattr(srow, "score", None)

            criteria = getattr(path, "criteria", None) if path is not None else None
            if criteria is not None and allowed_codes and submitted_map:
                from app.services.admission_scoring_service import (
                    AdmissionScoringService,
                    ProfileStatus as _ProfileStatus,
                )

                score_input = {
                    c: Decimal(str(v))
                    for c, v in submitted_map.items()
                    if v is not None
                }
                result = AdmissionScoringService.calculate_score(
                    criteria=criteria,
                    subject_scores=score_input,
                    allowed_subjects=allowed_codes,
                    # subject_weights=None MIRRORS the T6 publish cascade
                    # (admission_choice_engine_service._evaluate_single_choice
                    # passes None too — "Phase 4: read from path snapshot").
                    # Both call sites are unweighted today; keep them in
                    # LOCKSTEP. Wiring weight_snapshot into this DISPLAY call
                    # alone would make computed_total_score diverge from the
                    # actual admission decision. When Phase 4 wires weights,
                    # update both sites together.
                    subject_weights=None,
                )
                computed_total_score = result.final_score
                # A sàn verdict is only meaningful for a VALID result. When
                # INVALID (missing subject / điểm liệt) leave threshold_passed
                # None AND threshold_failure_reasons empty — a data-completeness
                # reason must NOT be mislabelled as a sàn (min_score) failure;
                # completeness is conveyed by data_complete instead.
                if result.status == _ProfileStatus.VALID:
                    admission_threshold_passed = bool(result.passed)
                    threshold_failure_reasons = list(
                        result.failure_reasons or []
                    )
        except Exception:  # noqa: BLE001 — display-only; never break response
            data_complete = False
            computed_total_score = None
            admission_threshold_passed = None
            threshold_failure_reasons = []

        out["data_complete"] = data_complete
        out["computed_total_score"] = computed_total_score
        out["admission_threshold_passed"] = admission_threshold_passed
        out["threshold_failure_reasons"] = threshold_failure_reasons

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
