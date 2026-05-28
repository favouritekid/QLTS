"""
Public admissions schemas for the read-only recruitment site.

These contracts intentionally expose only the data needed by the
public-facing admissions pages. They avoid reusing internal admin
schemas so the public API can remain stable and fail-closed.
"""
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class PublicAdmissionsAudience(str, Enum):
    """Audience filter values mirror AdmissionPath.applicable_to ENUM
    (phase1_03 / #184 Wave 1 PR-1B'). Storefront accepts as query param;
    when provided, paths must contain the value in applicable_to OR
    have applicable_to NULL (= legacy / applies to every audience).
    """
    POST_THCS = "POST_THCS"
    POST_THPT = "POST_THPT"
    LIEN_THONG_TC = "LIEN_THONG_TC"
    LIEN_THONG_CD = "LIEN_THONG_CD"
    VLVH = "VLVH"

    @classmethod
    def _missing_(cls, value):
        """Case-insensitive match for storefront query params.

        PR #348 review C1 (2026-05-28): default strict Enum rejects
        `?audience=post_thpt` lowercase → BE 422 → FE silent empty
        fallback. User typing wrong case got "Danh mục đang được cập
        nhật" without knowing why.

        Now `post_thpt`, `Post_Thpt`, `POST_THPT` all resolve to
        POST_THPT. Pure case-variant only — KHÔNG alias short-form
        (e.g. `thpt` ≠ POST_THPT); that's a separate UX product decision.
        """
        if not isinstance(value, str):
            return None
        upper = value.upper()
        for member in cls:
            if member.value.upper() == upper:
                return member
        return None


class PublicAdmissionsMethodTag(BaseModel):
    id: int
    code: str
    name: str


class PublicSemesterTuitionItem(BaseModel):
    """Per-semester tuition row for public display (PR 6 — ADR-002)."""
    semester_no: int = Field(..., ge=1)
    amount: Decimal = Field(..., ge=0)


class PublicAdmissionsAcademicInfoSummary(BaseModel):
    id: int
    academic_year: int = Field(..., ge=2000, le=2100)
    tuition_fee_per_year: Optional[Decimal] = Field(default=None, ge=0)
    annual_admission_quota: Optional[int] = Field(default=None, ge=0)
    cutoff_score_previous_year: Optional[Decimal] = Field(default=None, ge=0)
    target_audience: Optional[str] = None
    applied_discount_policy_ids: List[int] = Field(default_factory=list)
    # PR 6 (ADR-002 Decision 5): additive semester tuition fields
    semester_tuitions: List[PublicSemesterTuitionItem] = Field(default_factory=list)
    semester_1_tuition: Optional[Decimal] = Field(default=None, ge=0)


class PublicAdmissionsOfferingSummary(BaseModel):
    id: int
    offering_type: str
    duration_semesters: Optional[int] = Field(default=None, ge=0)
    total_credits: Optional[int] = Field(default=None, ge=0)
    academic_info: PublicAdmissionsAcademicInfoSummary
    admission_methods: List[PublicAdmissionsMethodTag] = Field(default_factory=list)


class PublicAdmissionsProgramSummary(BaseModel):
    id: int
    code: str
    name: str
    degree_level: str
    is_heavy: bool = False
    offering_count: int = Field(default=0, ge=0)
    academic_years: List[int] = Field(default_factory=list)
    tuition_min: Optional[Decimal] = Field(default=None, ge=0)
    tuition_max: Optional[Decimal] = Field(default=None, ge=0)
    semester_1_tuition_min: Optional[Decimal] = Field(default=None, ge=0)
    semester_1_tuition_max: Optional[Decimal] = Field(default=None, ge=0)
    offerings: List[PublicAdmissionsOfferingSummary] = Field(default_factory=list)


class PublicAdmissionsDegreeLevelGroup(BaseModel):
    degree_level: str
    program_count: int = Field(default=0, ge=0)
    offering_count: int = Field(default=0, ge=0)
    offering_types: List[str] = Field(default_factory=list)
    academic_years: List[int] = Field(default_factory=list)
    tuition_min: Optional[Decimal] = Field(default=None, ge=0)
    tuition_max: Optional[Decimal] = Field(default=None, ge=0)
    semester_1_tuition_min: Optional[Decimal] = Field(default=None, ge=0)
    semester_1_tuition_max: Optional[Decimal] = Field(default=None, ge=0)
    programs: List[PublicAdmissionsProgramSummary] = Field(default_factory=list)


class PublicAdmissionsProgramsMeta(BaseModel):
    degree_level_count: int = Field(default=0, ge=0)
    program_count: int = Field(default=0, ge=0)
    offering_count: int = Field(default=0, ge=0)
    latest_academic_year: Optional[int] = None
    offering_types: List[str] = Field(default_factory=list)


class PublicAdmissionsProgramsResponse(BaseModel):
    summary: PublicAdmissionsProgramsMeta
    degree_levels: List[PublicAdmissionsDegreeLevelGroup] = Field(default_factory=list)


class PublicAdmissionsMethodUsage(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    requires_gpa: bool = False
    requires_subject_scores: bool = False
    public_program_count: int = Field(default=0, ge=0)
    public_offering_count: int = Field(default=0, ge=0)
    public_path_count: int = Field(default=0, ge=0)
    academic_years: List[int] = Field(default_factory=list)


class PublicAdmissionsSubjectGroupUsage(BaseModel):
    id: int
    code: str
    name: str
    subjects: List[str] = Field(default_factory=list)
    method_codes: List[str] = Field(default_factory=list)
    public_path_count: int = Field(default=0, ge=0)


class PublicAdmissionsMethodsMeta(BaseModel):
    method_count: int = Field(default=0, ge=0)
    subject_group_count: int = Field(default=0, ge=0)
    public_path_count: int = Field(default=0, ge=0)


class PublicAdmissionsMethodsResponse(BaseModel):
    summary: PublicAdmissionsMethodsMeta
    methods: List[PublicAdmissionsMethodUsage] = Field(default_factory=list)
    subject_groups: List[PublicAdmissionsSubjectGroupUsage] = Field(default_factory=list)


class PublicAdmissionsDocumentRequirement(BaseModel):
    document_type_id: int
    document_type_code: str
    document_type_name: str
    document_type_description: Optional[str] = None
    is_mandatory: bool = True
    requires_upload: bool = True
    submission_format: Optional[str] = None
    display_order: int = 0
    source: str


class PublicAdmissionsMethodDocumentChecklist(BaseModel):
    method_id: int
    method_code: str
    method_name: str
    source: str
    public_program_count: int = Field(default=0, ge=0)
    public_offering_count: int = Field(default=0, ge=0)
    public_path_count: int = Field(default=0, ge=0)
    documents: List[PublicAdmissionsDocumentRequirement] = Field(default_factory=list)


class PublicAdmissionsOfferingTypeDocumentChecklist(BaseModel):
    offering_type_id: int
    offering_type_code: str
    offering_type_name: str
    public_program_count: int = Field(default=0, ge=0)
    public_offering_count: int = Field(default=0, ge=0)
    public_method_count: int = Field(default=0, ge=0)
    sample_programs: List[str] = Field(default_factory=list)
    shared_documents: List[PublicAdmissionsDocumentRequirement] = Field(default_factory=list)
    method_documents: List[PublicAdmissionsMethodDocumentChecklist] = Field(default_factory=list)


class PublicAdmissionsDocumentsMeta(BaseModel):
    offering_type_count: int = Field(default=0, ge=0)
    method_count: int = Field(default=0, ge=0)
    document_type_count: int = Field(default=0, ge=0)
    public_path_count: int = Field(default=0, ge=0)


class PublicAdmissionsDocumentsResponse(BaseModel):
    summary: PublicAdmissionsDocumentsMeta
    offering_types: List[PublicAdmissionsOfferingTypeDocumentChecklist] = Field(default_factory=list)


class PublicAdmissionsDiscountPolicySummary(BaseModel):
    id: int
    code: str
    name: str
    description: Optional[str] = None
    discount_type: str
    discount_value: Decimal = Field(..., ge=0)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_stackable: bool = False
    priority: int = 0


class PublicAdmissionsTuitionOffering(BaseModel):
    program_id: int
    program_name: str
    program_code: str
    degree_level: str
    offering_id: int
    offering_type: str
    academic_info_id: int
    academic_year: int = Field(..., ge=2000, le=2100)
    tuition_fee_per_year: Optional[Decimal] = Field(default=None, ge=0)
    annual_admission_quota: Optional[int] = Field(default=None, ge=0)
    applied_discount_policy_ids: List[int] = Field(default_factory=list)
    semester_tuitions: List[PublicSemesterTuitionItem] = Field(default_factory=list)
    semester_1_tuition: Optional[Decimal] = Field(default=None, ge=0)


class PublicAdmissionsTuitionBand(BaseModel):
    degree_level: str
    published_offering_count: int = Field(default=0, ge=0)
    academic_years: List[int] = Field(default_factory=list)
    tuition_min: Optional[Decimal] = Field(default=None, ge=0)
    tuition_max: Optional[Decimal] = Field(default=None, ge=0)
    semester_1_tuition_min: Optional[Decimal] = Field(default=None, ge=0)
    semester_1_tuition_max: Optional[Decimal] = Field(default=None, ge=0)


class PublicAdmissionsTuitionMeta(BaseModel):
    program_count: int = Field(default=0, ge=0)
    offering_count: int = Field(default=0, ge=0)
    policy_count: int = Field(default=0, ge=0)
    latest_academic_year: Optional[int] = None


class PublicAdmissionsTuitionResponse(BaseModel):
    summary: PublicAdmissionsTuitionMeta
    degree_levels: List[PublicAdmissionsTuitionBand] = Field(default_factory=list)
    offerings: List[PublicAdmissionsTuitionOffering] = Field(default_factory=list)
    discount_policies: List[PublicAdmissionsDiscountPolicySummary] = Field(default_factory=list)
