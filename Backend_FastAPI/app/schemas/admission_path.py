# app/schemas/admission_path.py
"""
Admission Path Schemas.

Pydantic schemas for AdmissionPath API request/response.

FRONTEND_ARCHITECTURE_V3.md Compliance:
- Response includes control fields: status, available_actions, can_*, validation_errors
- FE reads these, not computes them
"""

from datetime import datetime, date
from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.admission_correction_constants import SAFE_MINOR_CORRECTION_FIELDS


def _validate_minor_correction_allowlist(
    cls, v: Optional[List[str]]
) -> Optional[List[str]]:
    """Reject fields outside the SAFE catalog.

    Module-level helper attached to Create + Update via ``field_validator``
    inside each class. Defining once and binding twice keeps the rule
    in lockstep without relying on pydantic v2's ``check_fields=False``
    escape hatch (which silently skips validation on classes that don't
    declare the field).
    """
    if v is None:
        return v
    invalid = set(v) - SAFE_MINOR_CORRECTION_FIELDS
    if invalid:
        raise ValueError(
            f"Fields outside safe catalog: {sorted(invalid)}. "
            f"Allowed: {sorted(SAFE_MINOR_CORRECTION_FIELDS)}"
        )
    return list(v)


# =============================================================================
# STATUS ENUM
# =============================================================================

AdmissionPathStatus = Literal["draft", "active", "inactive", "archived"]
VisibilityStatus = Literal["internal", "public"]
DocumentSource = Literal["shared", "method_override", "path_override"]


# =============================================================================
# AUDIENCE ENUM (phase1_03 / #184 Wave 1 PR-1B')
# =============================================================================

# admission_audience PG ENUM. Values mirror alembic phase1_03 +
# PLAN line 605-606. Frozen here as a Literal so Pydantic rejects
# unknown values at the API boundary, and so the FE Zod can pin the
# same union shape via a generated type. Adding a new audience =
# update both this Literal AND the alembic migration AND the FE
# Zod schema in lockstep (no silent extension via direct DB ALTER).
AdmissionAudience = Literal[
    "POST_THCS",
    "POST_THPT",
    "LIEN_THONG_TC",
    "LIEN_THONG_CD",
    "VLVH",
]


# =============================================================================
# BONUS RULE OVERRIDE SHAPE (phase1_02 wired in PR-1B' per Codex P2)
# =============================================================================


class BonusRuleOverride(BaseModel):
    """Path-level / method-default bonus rule shape.

    PLAN line 768-789. Shape is shared by
    ``AdmissionMethod.default_bonus_rule`` and
    ``AdmissionPath.bonus_rule_override`` (path takes precedence).

    Per Codex P2 review on PR-1B': we ship a structured Pydantic
    shape rather than a raw JSONB blob so the admin UI can render
    a typed form (3 fields) and the API rejects malformed payload
    at the boundary instead of letting bad shapes reach the
    scoring engine.
    """

    model_config = ConfigDict(extra="forbid")

    apply_area_bonus: bool = Field(
        description=(
            "Apply the area bonus (KV1 / KV2_NT / KV2 / KV3) when "
            "computing the effective score for this path."
        ),
    )
    apply_subject_bonus: bool = Field(
        description=(
            "Apply per-subject bonus (priority objects 01..07) when "
            "computing the effective score."
        ),
    )
    max_total_bonus: Optional[float] = Field(
        default=None,
        ge=0,
        le=10,
        description=(
            "Cap on the combined bonus (area + subject) in points. "
            "NULL = no cap. Range 0..10 matches the GPA scale."
        ),
    )


# =============================================================================
# NESTED SCHEMAS (for response)
# =============================================================================

class AdmissionMethodNested(BaseModel):
    """Nested admission method info."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    requires_gpa: bool
    requires_subject_scores: bool


class OfferingAcademicInfoNested(BaseModel):
    """Nested academic info with offering details."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    academic_year: int
    annual_admission_quota: Optional[int] = None
    # offering details will be added when needed


class UserNested(BaseModel):
    """Nested user info for activator."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    full_name: str


class SubjectGroupNested(BaseModel):
    """Nested subject group info for criteria."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str


class AdmissionCriteriaNested(BaseModel):
    """
    Nested criteria info for AdmissionPath response.
    
    Used by LeadApplicationForm to initialize subject scores.
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    
    # Thresholds
    min_gpa: Optional[float] = None
    min_score: Optional[float] = None
    min_subject_score: Optional[float] = None
    max_possible_score: Optional[float] = None
    conditions: Optional[str] = None
    
    # Rule Engine config
    required_subject_count: Optional[int] = None
    subject_selection_mode: str = "fixed"
    scoring_method: str = "sum"

    # Validity
    policy_version: Optional[str] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    
    # Subject groups for score initialization
    subject_groups: List[SubjectGroupNested] = Field(
        default_factory=list,
        description="Allowed subject groups for this criteria (A00, D01, etc.)"
    )


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class AdmissionPathCreate(BaseModel):
    """Request schema for creating a new AdmissionPath."""
    academic_info_id: int
    admission_method_id: int
    # Phase 2 v8.2 PR-2B v2 — optional admission_round_id; nếu None,
    # service layer auto-resolve DOT_1 của academic_info's year (year-
    # level lookup, Option A). NOT NULL post PR-2C v2 swap.
    admission_round_id: Optional[int] = Field(
        default=None,
        description=(
            "Round FK. NULL = auto-resolve DOT_1 của academic_info's "
            "academic_year tại service layer."
        ),
    )
    round_quota: Optional[int] = Field(
        default=None, ge=0,
        description="Per-path submission cap. NULL = unbounded.",
    )
    admit_quota: Optional[int] = Field(
        default=None, ge=0,
        description="Per-path admit cap (Tier 1 chain root per academic_info).",
    )
    display_name: Optional[str] = None
    display_order: int = 0
    visibility: VisibilityStatus = "internal"
    application_fee: Optional[Decimal] = Field(
        default=None,
        ge=0,
        description="Lệ phí xét tuyển (VND). 0 hoặc NULL = miễn phí"
    )
    # PR #6 — new paths default to strict (False) unless the admin
    # explicitly opts into the legacy lax behaviour. Snapshotted onto
    # every profile created under this path.
    allow_unverified_submission: bool = Field(
        default=False,
        description=(
            "When True, applicants may submit the profile as soon as "
            "documents are uploaded (pre-PR #6 behaviour). When False "
            "(default), only verified or paper-submitted docs satisfy "
            "the submit gate."
        ),
    )
    # Per-path post-approval correction allowlist (governance setting).
    # Empty default = corrections disabled for the path. Admin opts in
    # field-by-field; effective set = SAFE catalog ∩ this list.
    minor_correction_allowed_fields: List[str] = Field(
        default_factory=list,
        description=(
            "Fields admin allows officer/manager to correct on profiles "
            "in approved/confirmed status under this path. Must be a "
            "subset of SAFE_MINOR_CORRECTION_FIELDS."
        ),
    )

    # phase1_03 (#184 Wave 1 PR-1B') — audience filter. Optional on
    # create; admin sets later via update once the storefront Phase
    # 3 validator gate is enabled. NULL = legacy / applicable to
    # every audience (Phase 1+2 query contract preserves NULL).
    applicable_to: Optional[List[AdmissionAudience]] = Field(
        default=None,
        description=(
            "Audience filter list. NULL = applicable to every audience. "
            "Phase 3 enables strict filter only after admin sets this."
        ),
    )
    method_quota: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Per-method admission quota. NULL = no method-level cap; "
            "round.admit_quota / group_quota provide fallback."
        ),
    )
    # phase1_02 wired in PR-1B' — typed shape (NOT raw JSONB) per
    # Codex P2. NULL = inherit from admission_method.default_bonus_rule.
    bonus_rule_override: Optional[BonusRuleOverride] = Field(
        default=None,
        description=(
            "Path-level override above admission_method.default_bonus_rule. "
            "NULL = inherit from method default."
        ),
    )

    _v_minor_correction_allowlist = field_validator(
        "minor_correction_allowed_fields"
    )(_validate_minor_correction_allowlist)


class AdmissionPathQuotaUpdate(BaseModel):
    """Phase 2 v8.2 PR-2D.1 — dedicated quota PATCH payload cho QuotaMatrix
    inline edit. Allows admin update round_quota/admit_quota independently
    với Tier 1+2 chain validation real-time per cell change."""
    round_quota: Optional[int] = Field(
        default=None, ge=0,
        description="Per-path submission cap. NULL = unbounded; explicit None to clear.",
    )
    admit_quota: Optional[int] = Field(
        default=None, ge=0,
        description="Per-path admit cap. Triggers Tier 1 chain re-validation on change.",
    )


class AdmissionPathUpdate(BaseModel):
    """Request schema for updating an AdmissionPath."""
    display_name: Optional[str] = None
    display_order: Optional[int] = None
    visibility: Optional[VisibilityStatus] = None
    application_fee: Optional[Decimal] = Field(
        default=None,
        ge=0,
        description="Lệ phí xét tuyển (VND). 0 hoặc NULL = miễn phí"
    )
    # Optional on update — callers that don't want to change the flag
    # omit it entirely.
    allow_unverified_submission: Optional[bool] = Field(
        default=None,
        description=(
            "Flip between strict (False) and legacy (True) submit rules. "
            "Existing profiles retain the snapshotted value; only "
            "profiles created after the flip inherit the new setting."
        ),
    )
    # Optional on update so partial PATCH-style updates don't accidentally
    # clear the config. Service-side guard rejects this field unless the
    # caller is admin (governance setting).
    minor_correction_allowed_fields: Optional[List[str]] = Field(
        default=None,
        description=(
            "Replace the per-path correction allowlist. Admin-only — "
            "service raises BusinessRuleViolation for non-admin callers. "
            "Pass `[]` to clear; omit to leave unchanged."
        ),
    )

    # phase1_03 — Optional on update so partial PATCH-style updates
    # don't accidentally clear the audience filter / quota. Pass an
    # explicit empty list to ``applicable_to`` to clear, or pass
    # ``None`` to leave unchanged. Same pattern for ``method_quota``
    # and ``bonus_rule_override`` — None means "do not touch", which
    # the service distinguishes via ``model_dump(exclude_unset=True)``.
    applicable_to: Optional[List[AdmissionAudience]] = Field(
        default=None,
        description=(
            "Replace the audience filter. Pass `[]` to clear (NULL "
            "= every audience), or omit to leave unchanged."
        ),
    )
    method_quota: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Replace per-method quota. Pass 0 to mark exhausted, "
            "or omit to leave unchanged."
        ),
    )
    bonus_rule_override: Optional[BonusRuleOverride] = Field(
        default=None,
        description=(
            "Replace path-level bonus override. Pass `null` to fall "
            "back to method default, or omit to leave unchanged."
        ),
    )

    _v_minor_correction_allowlist = field_validator(
        "minor_correction_allowed_fields"
    )(_validate_minor_correction_allowlist)


class AdmissionCriteriaCreate(BaseModel):
    """Schema for creating/updating criteria."""
    min_gpa: Optional[float] = Field(None, ge=0, le=10)
    min_score: Optional[float] = Field(None, ge=0, le=1500)
    min_subject_score: Optional[float] = Field(None, ge=0, le=10)
    max_possible_score: Optional[float] = Field(None, ge=0, le=1500)
    conditions: Optional[str] = None
    required_subject_count: Optional[int] = Field(None, ge=1)
    subject_selection_mode: Literal["fixed", "best_n", "any_n"] = "fixed"
    scoring_method: Literal["sum", "average", "weighted"] = "sum"
    subject_groups: List[int] = Field(
        default_factory=list,
        description="List of Subject Group IDs"
    )

    # Validity
    policy_version: Optional[str] = "2025.1"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class AdmissionPathDocumentUpsert(BaseModel):
    """Schema for updating document requirement."""
    document_type_id: int
    is_mandatory: bool = True
    requires_upload: bool = True
    submission_format: Optional[str] = None
    display_order: int = 0


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class AdmissionPathResponse(BaseModel):
    """
    Response schema for AdmissionPath.
    
    FRONTEND_ARCHITECTURE_V3.md Compliance:
    - available_actions: FE checks this, not user.role
    - can_edit, can_activate: FE reads, not computes
    - validation_errors: Why activation is blocked
    """
    model_config = ConfigDict(from_attributes=True)
    
    # Core fields
    id: int
    academic_info_id: int
    admission_method_id: int
    status: AdmissionPathStatus
    display_name: Optional[str] = None
    display_order: int
    visibility: VisibilityStatus

    # Phase 2 v8.2 PR-2B v2 / PR-2C v2 — round + per-path quota fields.
    admission_round_id: int = Field(
        description="Round FK (NOT NULL post PR-2C v2 3-col UNIQUE swap)."
    )
    round_quota: Optional[int] = Field(
        default=None,
        description="Per-path submission cap. NULL = unbounded.",
    )
    admit_quota: Optional[int] = Field(
        default=None,
        description="Per-path admit cap. Tier 1 chain root (per academic_info).",
    )
    submission_count: int = Field(
        default=0,
        description="Atomic submission counter; incremented on profile create.",
    )

    # Application Fee
    application_fee: Optional[Decimal] = Field(
        default=None,
        description="Lệ phí xét tuyển (VND). 0 hoặc NULL = miễn phí"
    )
    requires_application_fee: bool = Field(
        default=False,
        description="True nếu lệ phí > 0, FE dùng để hiển thị flow thanh toán"
    )

    # PR #6 — required in the response so FE Zod parse fails loudly
    # if backend forgot to emit the field, rather than silently
    # defaulting to False and letting admin tooling flip between modes
    # blind.
    allow_unverified_submission: bool = Field(
        description=(
            "Current strict-mode setting for this path. False means "
            "the submit validator requires verified / paper-submitted "
            "documents; True allows uploaded."
        ),
    )
    # Required (no default) so a backend that forgets to map the column
    # surfaces in Zod parse on the FE side rather than silently rendering
    # an empty allowlist. No validator on the response — data from DB has
    # already passed the Create/Update gate.
    minor_correction_allowed_fields: List[str] = Field(
        description=(
            "Per-path allowlist for post-approval minor corrections. "
            "Subset of SAFE_MINOR_CORRECTION_FIELDS."
        ),
    )

    # phase1_03 — REQUIRED in the response (non-default) so Zod parse
    # on FE side fails loudly when the BE forgets to emit the field
    # rather than silently rendering an empty audience filter / NULL
    # quota. Following the same pattern as
    # ``allow_unverified_submission`` / ``minor_correction_allowed_fields``.
    applicable_to: Optional[List[AdmissionAudience]] = Field(
        description=(
            "Audience filter list, or NULL = applicable to every "
            "audience (Phase 1+2 legacy)."
        ),
    )
    method_quota: Optional[int] = Field(
        description=(
            "Per-method admission quota, or NULL if no cap configured."
        ),
    )
    bonus_rule_override: Optional[BonusRuleOverride] = Field(
        description=(
            "Path-level bonus override, or NULL if inherited from "
            "admission_method.default_bonus_rule."
        ),
    )

    # Relationships
    academic_info: Optional[OfferingAcademicInfoNested] = None
    admission_method: Optional[AdmissionMethodNested] = None
    
    # Nested criteria (for LeadApplicationForm - GAP-D fix)
    criteria: Optional[AdmissionCriteriaNested] = None
    
    # Audit fields
    activated_at: Optional[datetime] = None
    activator: Optional[UserNested] = None
    created_at: datetime
    updated_at: datetime
    
    # === CONTROL FIELDS (Required by FRONTEND_ARCHITECTURE_V3.md) ===
    available_actions: List[str] = Field(
        default_factory=list,
        description="Actions available for this path: save, activate, deactivate, archive"
    )
    can_edit: bool = Field(
        default=True,
        description="Whether the path can be edited"
    )
    can_activate: bool = Field(
        default=False,
        description="Whether the path can be activated"
    )
    validation_errors: List[str] = Field(
        default_factory=list,
        description="Reasons why activation is blocked"
    )


class AdmissionPathListResponse(BaseModel):
    """Response for list of paths with pagination."""
    total: int
    items: List[AdmissionPathResponse]


# =============================================================================
# ACADEMIC YEAR SCHEMAS
# =============================================================================

class AcademicYearListResponse(BaseModel):
    """Response for academic years endpoint."""
    years: List[int]
    current_year: int


# =============================================================================
# DOCUMENT RESOLUTION SCHEMAS
# =============================================================================

class ResolvedDocumentResponse(BaseModel):
    """
    Response for a single resolved document.
    
    Shows whether document is from shared config or method-specific override.
    """
    model_config = ConfigDict(from_attributes=True)
    
    document_type_id: int
    document_type_code: str
    document_type_name: str
    is_mandatory: bool
    requires_upload: bool
    submission_format: Optional[str] = None
    display_order: int = 0
    source: DocumentSource = Field(
        description="Where this doc requirement comes from: shared or method_override"
    )


class ResolvedDocumentListResponse(BaseModel):
    """Response for resolved documents endpoint."""
    path_id: int
    offering_type_id: int
    admission_method_id: int
    documents: List[ResolvedDocumentResponse]


# =============================================================================
# ACTIVATION SCHEMAS
# =============================================================================

class ActivationValidationResponse(BaseModel):
    """Response for activation validation check."""
    can_activate: bool
    validation_errors: List[str] = Field(
        default_factory=list,
        description="List of reasons why activation is blocked"
    )


class ActivationRequest(BaseModel):
    """Request for activating a path (optional notes)."""
    notes: Optional[str] = None


# =============================================================================
# COVERAGE MATRIX SCHEMAS
# =============================================================================

class CoverageRow(BaseModel):
    """
    Single row in coverage matrix = one AdmissionPath.
    
    Used by Config Console to show path readiness status.
    """
    path_id: int
    method_name: str
    method_code: str
    status: AdmissionPathStatus
    
    # Readiness indicators
    has_criteria: bool = Field(
        description="Whether criteria_id is set"
    )
    has_documents: bool = Field(
        description="Whether document group exists for method"
    )
    has_quota: bool = Field(
        description="Whether quota > 0"
    )
    
    # Computed from above
    can_activate: bool = Field(
        description="has_criteria AND has_documents AND has_quota"
    )
    
    # Validation errors if cannot activate
    validation_errors: List[str] = Field(default_factory=list)


class CoverageMatrixResponse(BaseModel):
    """
    Response for coverage matrix view.
    
    Shows all paths for an academic_info with their readiness status.
    FE uses this to display audit table and bulk activate button.
    """
    academic_info_id: int
    rows: List[CoverageRow]
    
    # Summary
    total_paths: int
    paths_ready: int
    all_ready: bool = Field(
        description="True only if all paths can be activated"
    )

