# app/schemas/admission.py
"""
Pydantic Schemas for Admission Module.

Security Features:
- Input Sanitization: html.escape() for all text fields (prevent XSS)
- Strict Validation: Regex patterns, length limits, GPA range (0-10)
- Type Safety: Pydantic v2 with strict mode

Architecture Compliance:
- No HTTPException imports (service layer raises custom exceptions)
- Schemas used for request/response validation only
- Field validators sanitize inputs at schema level
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Dict, List, Literal, Optional
import html

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
    ConfigDict,
    computed_field,
)

from app.schemas.admission_profile_choice import AdmissionProfileChoiceResponse


# ==============================================================================
# NESTED SCHEMAS (for JSONB fields)
# ==============================================================================

class FamilyMemberSchema(BaseModel):
    """
    Family member information (stored in admission_profile.family_info JSONB array).

    Security:
    - Text fields trim-only; HTML escape ở tầng render (KHÔNG tầng lưu —
      tránh bug double-escape "amp"). Xem ``sanitize_text``.
    - Phone Validation: Vietnam format (0 + 9-10 digits)
    """
    relationship: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Relationship type (father, mother, sibling, etc.)"
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full name of family member"
    )
    occupation: str = Field(
        default="",
        max_length=255,
        description="Occupation/job title"
    )
    phone: str = Field(
        ...,
        pattern=r"^0\d{9,10}$",
        description="Vietnam phone number (0 + 9-10 digits)"
    )
    is_primary_guardian: bool = Field(
        False,
        description="Identify if this is the primary guardian"
    )

    @field_validator('full_name', 'occupation', 'relationship')
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        """Trim khoảng trắng — KHÔNG html.escape.

        Schema này dùng chung cho cả request LẪN response. html.escape
        không idempotent (``&`` → ``&amp;``) nên escape ở tầng lưu khiến
        giá trị tích lũy thêm một lớp ``&amp;`` mỗi vòng đọc/lưu (bug
        "amp"). Escape HTML là việc của tầng render (React/JSX, Jinja
        autoescape của email_service), KHÔNG phải tầng lưu.
        """
        if not v:
            return v
        return v.strip()

    model_config = ConfigDict(
        str_strip_whitespace=True,
        str_min_length=0
    )


class AcademicRecordSchema(BaseModel):
    """
    Academic history (stored in admission_profile.academic_history JSONB array).

    Q9 #07 Phase D.1 extensions (2026-05-18):
    - ``school_id``: FK to vn_school.id (optional — None for non-Vietnam
      schools or legacy entries pre-Phase B)
    - ``level``: filter for engine resolve_kv (THCS/THPT/THCS_THPT/etc.)
    - ``grade_to``: engine tiebreak (lớp cuối tại trường này — 9 for
      THCS, 12 for THPT). Used by `resolve_kv_for_profile()` Phase C.

    Security:
    - school_name trim-only; HTML escape ở tầng render (KHÔNG tầng lưu —
      tránh bug double-escape "amp"). Xem ``sanitize_school_name``.
    - Year Validation: year_from <= year_to, reasonable range (1900-2100)
    - GPA Validation: 0.0 - 10.0 range
    """
    school_id: Optional[int] = Field(
        None,
        description="FK to vn_school.id — links entry to canonical school for KV resolution. None = manual entry / non-VN school.",
    )
    school_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of school/institution (display fallback when school_id NULL)"
    )
    level: Optional[str] = Field(
        None,
        description="School level (THCS | THPT | THCS_THPT | TRUNG_HOC_NGHE | OTHER) — auto-derived when school_id set",
    )
    year_from: int = Field(
        ...,
        ge=1900,
        le=2100,
        description="Start year (e.g., 2020)"
    )
    year_to: int = Field(
        ...,
        ge=1900,
        le=2100,
        description="End year (e.g., 2023)"
    )
    grade_to: Optional[int] = Field(
        None,
        ge=1,
        le=12,
        description="Final grade at this school (vd 9 for THCS, 12 for THPT) — used by engine tiebreak",
    )
    gpa: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="GPA (0.0 - 10.0)"
    )
    graduation_type: Optional[str] = Field(
        None,
        max_length=50,
        description="Type of graduation (THPT, Dai hoc, etc.)"
    )


    @field_validator('school_name')
    @classmethod
    def sanitize_school_name(cls, v: str) -> str:
        """Trim khoảng trắng — KHÔNG html.escape.

        Xem ghi chú ``FamilyMemberSchema.sanitize_text``: ``AcademicRecordSchema``
        dùng chung cho request + response, html.escape không idempotent nên
        escape ở tầng lưu sinh bug "amp" (``&#x27;`` → ``&amp;#x27;`` → …).
        Escape thuộc tầng render, không phải tầng lưu.
        """
        return v.strip()

    @field_validator('level')
    @classmethod
    def validate_level(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        valid = {"THCS", "THPT", "THCS_THPT", "TRUNG_HOC_NGHE", "OTHER"}
        if v not in valid:
            raise ValueError(f"level must be one of {sorted(valid)}")
        return v

    @field_validator('year_to')
    @classmethod
    def validate_year_range(cls, v: int, info) -> int:
        """Ensure year_from <= year_to."""
        year_from = info.data.get('year_from')
        if year_from and v < year_from:
            raise ValueError(f"year_to ({v}) must be >= year_from ({year_from})")
        return v

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionScoreSchema(BaseModel):
    """
    Admission scores (stored in admission_profile.admission_scores JSONB object).

    Supports two scoring modes:
    1. GPA-only: For "học bạ" methods without subject groups
    2. Subject-based: For methods with subject_groups (e.g., A00, D01)

    Phase 6: Dynamic Admission Scoring
    """
    # Selected admission criterion and subject group
    selected_criterion_id: Optional[str] = Field(
        None,
        description="ID of selected admission criterion from applied_rules.criteria"
    )
    selected_group: Optional[str] = Field(
        None,
        description="Selected subject group code (e.g., 'A00', 'D01')"
    )
    
    # GPA for học bạ-based methods
    gpa: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="Overall GPA (for học bạ/GPA-based methods)"
    )
    
    # Dynamic subject scores (e.g., {"math": 8.5, "physics": 7.0, "chemistry": 9.0})
    subject_scores: Optional[Dict[str, Optional[float]]] = Field(
        None,
        description="Subject scores keyed by subject code (e.g., 'math', 'physics')"
    )

    @field_validator('subject_scores')
    @classmethod
    def validate_scores(cls, v: Optional[Dict[str, Optional[float]]]) -> Optional[Dict[str, Optional[float]]]:
        if not v:
            return v
        for code, score in v.items():
            if score is not None and (score < 0 or score > 10):
                raise ValueError(f"Score for {code} must be between 0 and 10")
        return v
    
    # Legacy fields (kept for backward compatibility)
    math_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    literature_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    english_score: Optional[float] = Field(None, ge=0.0, le=10.0)
    
    # Computed fields (optional, for display)
    total_score: Optional[float] = Field(None, ge=0.0, description="Total of subject scores")
    average_score: Optional[float] = Field(None, ge=0.0, le=10.0, description="Average score")

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="ignore"  # Ignore extra fields for safety
    )


class DocumentItemSchema(BaseModel):
    """
    Document checklist item (stored in admission_profile.documents_checklist JSONB array).

    Status Lifecycle:
    - missing: Document not yet uploaded
    - uploaded: File uploaded, pending verification
    - verified: Officer verified the document
    - rejected: Officer rejected the document
    - paper_submitted: Applicant submitted a paper copy (not a digital upload)

    Security:
    - File Path Validation: Max 512 chars (prevent path traversal in display)
    - Status Enum: Only allowed values accepted
    """
    code: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Document code (HOC_BA, CCCD, BANG_TN, etc.)"
    )
    label: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable label (e.g., 'Học bạ THPT')"
    )
    status: Literal["missing", "uploaded", "verified", "rejected", "paper_submitted"] = Field(
        default="missing",
        description="Upload status"
    )
    # PR1 Commit 1: ProfileDocument PK, present only when a downloadable file
    # artifact exists. The FE builds the authed download URL
    # /api/admissions/{profile_id}/documents/{document_id}/download from it
    # (file_path is no longer publicly servable). Null → no file to view, FE
    # hides the "Xem PDF" button. Declared on the schema so the response_model
    # doesn't silently drop it (Pydantic only serializes declared fields).
    document_id: Optional[int] = Field(
        None,
        description="ProfileDocument PK for the authed download endpoint (null when no file artifact)",
    )
    file_path: Optional[str] = Field(
        None,
        max_length=512,
        description="S3 path or local file path (null if not uploaded)"
    )
    file_size: Optional[int] = Field(
        None,
        ge=0,
        le=10_485_760,  # 10MB max (10 * 1024 * 1024)
        description="File size in bytes (max 10MB, null if not uploaded)"
    )
    uploaded_at: Optional[datetime] = Field(
        None,
        description="Upload timestamp (UTC)"
    )
    # ADM-031 round 7: paper-receipt timestamp
    paper_submitted_at: Optional[datetime] = Field(
        None,
        description="Timestamp when officer marked the paper document as received"
    )
    # ✅ FIX Finding 2.3: Document Internal Verification
    verified_format: Optional[Literal["original", "certified_copy", "photo"]] = Field(
        None,
        description="Format verified by officer (original/certified_copy/photo)"
    )
    # ADM-031 round 4: officer-declared actual format. Captured at upload /
    # paper-receipt time; surfaced in the FE row badge so officers can see
    # what was actually recorded vs the path-required submission_format.
    actual_submission_format: Optional[Literal["original", "certified_copy", "photo"]] = Field(
        None,
        description="Format actually declared by the officer at upload/paper-receipt time"
    )
    # ADM-031 round 10: surface the verifier identity + timestamp so the FE
    # row can render "Đã duyệt — <Tên> · <ngày>" under the status badge and
    # show full datetime on hover. verified_at + verified_by come straight
    # from ProfileDocument; verified_by_name is resolved server-side via a
    # batched User lookup to keep the listing N+1-free.
    verified_at: Optional[datetime] = Field(
        None,
        description="Timestamp when officer marked status=verified",
    )
    verified_by: Optional[int] = Field(
        None,
        description="User id of the officer who verified the document",
    )
    verified_by_name: Optional[str] = Field(
        None,
        description=(
            "Display name of the verifier — backend resolves "
            "full_name → username via a batched User lookup. Null when the "
            "verifier no longer exists or has neither field set; FE then "
            "falls back to 'User #<verified_by>'. Email is never exposed "
            "here (staff-to-staff privacy)."
        ),
    )
    # PR #13 — loại giấy tốt nghiệp + hạn "nợ bằng" + cờ cho phép cập nhật.
    graduation_proof_kind: Optional[
        Literal["official_diploma", "provisional_cert"]
    ] = Field(None, description="Loại giấy tốt nghiệp THPT (PR#13)")
    supplement_due_date: Optional[date] = Field(
        None, description="Hạn bổ sung bằng khi provisional_cert (PR#13)"
    )
    can_update_graduation_kind: Optional[bool] = Field(
        None, description="FE hiện nút 'Đã nhận bằng chính thức' (PR#13)"
    )

    # =========================================================================
    # Checklist-only display fields populated by _compute_frontend_fields.
    # These live alongside the raw document status so the FE can render the
    # row without a second API call.
    # =========================================================================
    is_mandatory: Optional[bool] = Field(
        default=None,
        description="Whether this document is mandatory for the admission path",
    )
    is_extra: Optional[bool] = Field(
        default=False,
        description=(
            "BR2 (2026-04-29): True when this row is a ProfileDocument that "
            "exists in the DB but is NOT in the current "
            "applied_rules.mandatory_docs snapshot — typically because the "
            "AdmissionPath was edited after the profile was created. Extras "
            "are read-only (all can_* flags false); the FE renders them in "
            "a separate 'Tài liệu ngoài yêu cầu hiện tại' section so "
            "officers see prior evidence isn't silently dropped."
        ),
    )
    requires_upload: Optional[bool] = Field(
        default=None,
        description="True if an online upload is required; False for paper-only docs",
    )
    submission_format: Optional[str] = Field(
        default=None,
        description="Allowed physical format (original/certified_copy/photo) when specified",
    )
    rejection_reason: Optional[str] = Field(
        default=None,
        description="Reason shown to the applicant when status = rejected",
    )
    submission_format_confirmed: Optional[bool] = Field(
        default=None,
        description="True once the officer verified the physical format",
    )

    # =========================================================================
    # PR #5 — explicit per-document permission flags
    # FE previously inferred action visibility from a generic `can('edit')`
    # check, which leaked buttons for roles that couldn't actually invoke the
    # underlying endpoint. The flags below are authoritative: backend computes
    # them per (role × doc status × profile status × unit/assignment scope),
    # and FE renders Upload / Verify / Reject / Reset / Paper-submit buttons
    # iff the matching flag is true.
    # =========================================================================
    can_upload: Optional[bool] = Field(
        default=None,
        description="Officer may upload a file for this doc (profile editable + owning officer)",
    )
    can_verify: Optional[bool] = Field(
        default=None,
        description="Manager/admin may mark status=verified (requires uploaded or paper_submitted)",
    )
    can_reject: Optional[bool] = Field(
        default=None,
        description="Manager/admin may mark status=rejected (requires uploaded/paper_submitted/verified)",
    )
    can_reset: Optional[bool] = Field(
        default=None,
        description="Manager/admin may clear the doc back to status=missing",
    )
    can_mark_paper_submitted: Optional[bool] = Field(
        default=None,
        description="Officer may record paper submission (paper-doc + missing status + owning officer)",
    )

    @field_validator('label')
    @classmethod
    def sanitize_label(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )


# ==============================================================================
# ADMISSION PROFILE SCHEMAS
# ==============================================================================

class AdmissionProfileCreate(BaseModel):
    """
    Schema for creating new AdmissionProfile.

    REFACTORED (Phase 2): Now requires admission_method_id for relational lookup.
    
    Fields populated by service:
    - applied_rules: Snapshot from AdmissionPath + AdmissionCriteria
    - ProfileDocument records: Auto-generated from DocumentGroup resolution
    - status: Default = 'draft'
    """
    lead_id: int = Field(
        ...,
        gt=0,
        description="Lead ID (must exist and belong to current user's unit)"
    )
    admission_method_id: int = Field(
        ...,
        gt=0,
        description="Admission method ID (required for AdmissionPath lookup)"
    )
    # Round contract hardening (plan v4 Section A, 2026-05-25): the
    # admission round is now REQUIRED. AdmissionPath is identified by the
    # 3-col UNIQUE (admission_round_id, academic_info_id, admission_method_id),
    # so binding the profile needs an explicit round — the old 2-col
    # ``.first()`` lookup silently picked an arbitrary round (DOT_1 vs
    # DOT_2) when both existed for the same (offering, year, method).
    admission_round_id: int = Field(
        ...,
        gt=0,
        description=(
            "Admission round ID (REQUIRED). Binds the profile to the exact "
            "(round, offering, method) AdmissionPath. Validated server-side: "
            "must exist, match academic_year, be active and not archived."
        ),
    )
    # Round contract hardening (plan v4): academic_year is now REQUIRED.
    # The legacy "first published OfferingAcademicInfo" fallback and the
    # ``current_intake_year`` race-check fallback have both been removed
    # from ``create_profile``, so the year must be explicit to validate
    # the selected round (round.academic_year == academic_year)
    # deterministically. FE already always sends academic_year (ADM-017).
    academic_year: int = Field(
        ...,
        ge=2000,
        le=2100,
        description=(
            "Academic year for the profile (e.g., 2026). Service validates "
            "a published OfferingAcademicInfo row exists for "
            "``(lead.offering_id, academic_year)`` AND that "
            "admission_round_id belongs to this year."
        ),
    )

    model_config = ConfigDict(str_strip_whitespace=True)


# =============================================================================
# Q9 #07 W11-BE.F.7 — priority bonus support types (M1 + M2 review-2 fix)
# =============================================================================

# M1: per-item regex for priority_object_codes — mirror of phase1_08b
# CHECK constraint ``sub_code ~ '^[0-9]{2}$'``. Without this annotation
# Pydantic accepts any string and the engine silently sees no matches
# (graceful 0đ but undiscoverable from API response).
PrioritySubCode = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{2}$")
]


class PriorityAuditEntry(BaseModel):
    """Q9 #07 Phase E.4 — read-only projection of a priority_audit_log row.

    Mirrors FE `priorityAuditEntrySchema` in zod/admissions.ts. Returned via
    `AdmissionProfileResponse.priority_audit_log` (last 20 entries DESC) so
    the workbench can render the audit timeline without an extra round-trip.
    """
    id: int
    action_type: str = Field(
        ...,
        description=(
            "Whitelist: kv_manual_override | ut_evidence_verified | "
            "ut_evidence_rejected | admin_bulk_fill"
        ),
    )
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    old_value: Optional[Dict[str, Any]] = None
    new_value: Optional[Dict[str, Any]] = None
    audit_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PriorityObjectEvidenceEntry(BaseModel):
    """M2: enforce shape of each evidence dict value.

    Without this nested model, ``Dict[str, Dict[str, Any]]`` admitted any
    inner dict (vd: ``{'random': 'stuff'}``) — engine read ``.get('status')``
    and silently treated as unverified. Strict shape catches typos at the
    Pydantic boundary so admin/candidate get a clear 422 instead of a
    silent 0đ on calculation day.
    """
    status: Literal["pending", "verified", "rejected"] = Field(
        ...,
        description="Verification state. Engine only counts 'verified' for bonus."
    )
    document_id: Optional[int] = Field(
        default=None,
        description="FK to profile_document (the uploaded evidence file)"
    )
    verified_by: Optional[int] = Field(
        default=None,
        description="user.id who flipped status to verified/rejected"
    )
    verified_at: Optional[datetime] = Field(
        default=None,
        description="When officer recorded verify/reject decision"
    )
    reject_reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Required if status='rejected'"
    )
    # Phase E.4 fix (smoke 2026-05-20): reject service persists rejected_by
    # + rejected_at into the evidence JSONB entry, but the read schema had
    # only verified_by/verified_at. After PATCH reject, every subsequent GET
    # raised ResponseValidationError extra_forbidden — cascading 500 on the
    # whole profile detail page until the reject was undone.
    rejected_by: Optional[int] = Field(
        default=None,
        description="user.id who flipped status to rejected (parity với verified_by)",
    )
    rejected_at: Optional[datetime] = Field(
        default=None,
        description="When officer recorded reject decision",
    )
    requested_at: Optional[datetime] = Field(
        default=None,
        description="When candidate submitted the UT claim"
    )
    # Phase E.4 — paper_only verify flag (PERSISTED, set by verify service)
    paper_only_verification: bool = Field(
        default=False,
        description=(
            "Officer verify UT cho hồ sơ giấy (chưa scan file vào hệ thống). "
            "Default case trong nghiệp vụ VN — KHÔNG phải bypass. Audit log "
            "ghi flag để thanh tra truy được khi không có document_id."
        )
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode='after')
    def validate_status_dependencies(self) -> 'PriorityObjectEvidenceEntry':
        """m-RV2-1 polish: enforce audit trail completeness per status.

        * status='rejected' → reject_reason required (non-empty after
          strip). Without this, officer can reject a UT claim without
          logging WHY — the candidate has no recourse and audit shows
          a bare rejection.
        * status='verified' → verified_by required (user.id of the
          officer who approved). Without this, the engine snapshot
          + bonus calculation has no chain of responsibility.

        Note: ``pending`` (the initial candidate-submitted state) needs
        neither — that's the whole point of a pending evidence row.
        """
        if self.status == "rejected":
            if not (self.reject_reason and self.reject_reason.strip()):
                raise ValueError(
                    "status='rejected' yêu cầu reject_reason (officer "
                    "phải ghi rõ lý do từ chối chứng cứ UT)."
                )
        elif self.status == "verified":
            if self.verified_by is None:
                raise ValueError(
                    "status='verified' yêu cầu verified_by (user.id "
                    "của officer xác minh)."
                )
        return self


class PriorityObjectEvidenceDisplayEntry(PriorityObjectEvidenceEntry):
    """Phase E.4 — READ-only display projection schema.

    Extends write schema (PriorityObjectEvidenceEntry) với 2 denormalized
    display fields (verified_by_name + document_file_path). CHỈ dùng cho
    AdmissionProfileResponse.priority_object_evidence_display transient
    attribute — KHÔNG persist vào JSONB column.

    Why separate schema (G3a fix cycle 5):
    - PriorityObjectEvidenceEntry reuse trong AdmissionProfileUpdate.priority_
      object_evidence (PATCH body). Thêm display fields vào WRITE schema sẽ
      cho phép FE PATCH leak qua update_profile path → display data persist
      xuống DB → schema drift.
    - Tách READ-only DisplayEntry ngăn FE PATCH gửi display fields (extra=
      "forbid" trên cả 2 schemas).
    """
    verified_by_name: Optional[str] = Field(
        default=None,
        description="Full name của officer verified (denormalized từ user.full_name)"
    )
    document_file_path: Optional[str] = Field(
        default=None,
        description="S3 file_path của evidence document (FE basename extract)"
    )

    model_config = ConfigDict(extra="forbid")


class PriorityEvidenceDocumentItem(BaseModel):
    """Phase E.4 — Per-priority-UT document item for DocumentsTab Priority section.

    Server-computed pre-projection trong _populate_response_fields. FE
    DocumentsTab consume directly thay vì raw query profile_documents.

    Spec G0a (audit cycle 5): response contract clarification — without this
    field, FE phải tự join priority_object_codes + catalog + documents from
    raw response shape (3 sources). G0a centralizes BE compute.
    """
    sub_code: str = Field(..., description="UT sub_code (vd '04','07')")
    bonus_points: float = Field(..., description="Bonus rate từ PriorityObjectConfig")
    label: str = Field(
        ...,
        description="Evidence doc label từ PriorityObjectConfig.evidence_doc_type"
    )
    document_id: Optional[int] = Field(
        default=None,
        description="ProfileDocument.id nếu uploaded, None nếu missing"
    )
    document_file_path: Optional[str] = Field(
        default=None,
        description="S3 file_path nếu uploaded (FE basename extract)"
    )
    status: Literal["missing", "uploaded", "verified", "rejected"] = Field(
        ...,
        description="Document upload status"
    )
    verification_status: Optional[str] = Field(
        default=None,
        description="priority_object_evidence[sub_code].status (pending/verified/rejected)"
    )

    model_config = ConfigDict(extra="forbid")


class AdmissionProfileUpdate(BaseModel):
    """
    Schema for updating AdmissionProfile (only allowed when status = 'draft').

    Security:
    - All text fields sanitized via field validators
    - citizen_id format validated (12 digits)
    - Optimistic locking via version field (required)
    - Array size limits: family_info max 10, academic_history max 20
    """
    version: int = Field(
        ...,
        ge=1,
        description="Current version (for optimistic locking, must match DB)"
    )
    
    # Personal Info Fields
    full_name: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(
        None,
        # MIRROR CHÍNH XÁC VIETNAM_PHONE_REGEX (phone_helpers.py) để chặn số
        # 04x/06x/01x ngay ở 422 thay vì lọt xuống service rồi 400.
        # ⚠ Dùng [0-9] ASCII, KHÔNG \d: Pydantic \d khớp cả Unicode digit
        # (full-width ０-９) → '090１２３４５６７' lọt schema nhưng service reject
        # → vẫn "422-miss → 400". Đầu số hợp lệ: 03/05/07/08/09/02 (gồm cố định
        # 02x — KHÔNG mobile-only, khớp validate_vietnam_phone).
        pattern=r"^0(3|5|7|8|9|2)[0-9]{8,9}$",
        description="Số điện thoại Việt Nam hợp lệ (VD: 0901234567)"
    )
    email: Optional[EmailStr] = Field(None, max_length=255)
    dob: Optional[date] = Field(None, description="Date of birth")
    gender: Optional[str] = Field(None, max_length=50)
    
    citizen_id: Optional[str] = Field(
        None,
        pattern=r"^\d{12}$",
        description="CCCD/CMND number (12 digits)"
    )
    social_insurance_number: Optional[str] = Field(None, max_length=50)
    
    # Location Fields
    nationality: Optional[str] = Field(None, max_length=100)
    ethnicity: Optional[str] = Field(None, max_length=100)
    religion: Optional[str] = Field(None, max_length=100)
    disability_type: Optional[str] = Field(None, max_length=100)
    permanent_province: Optional[str] = Field(None, max_length=100)
    permanent_district: Optional[str] = Field(None, max_length=100)
    permanent_ward: Optional[str] = Field(None, max_length=100)
    permanent_residential_group: Optional[str] = Field(
        None, max_length=150,
        description="Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố — community sub-unit, free-text"
    )
    permanent_street_address: Optional[str] = Field(
        None, max_length=255,
        description="Số nhà, tên đường — street address line, free-text"
    )
    place_of_birth: Optional[str] = Field(None, max_length=255)
    native_place: Optional[str] = Field(None, max_length=255)
    
    # Political Info Dates
    union_entry_date: Optional[datetime] = Field(None, description="Union entry date")
    party_entry_date: Optional[datetime] = Field(None, description="Party entry date (probationary)")
    party_official_entry_date: Optional[datetime] = Field(None, description="Party entry date (official)")
    
    # JSONB Arrays
    family_info: Optional[List[FamilyMemberSchema]] = Field(
        None,
        max_length=10,
        description="Array of family members (max 10)"
    )
    academic_history: Optional[List[AcademicRecordSchema]] = Field(
        None,
        max_length=20,
        description="Array of academic records (schools attended, max 20)"
    )

    # Phase 6: Admission Scores
    admission_scores: Optional[AdmissionScoreSchema] = Field(
        None,
        description="Admission scores (GPA or subject scores) for dynamic scoring"
    )

    # =========================================================================
    # Q9 #07 Priority bonus fields
    # PR1 phase1_08b (legacy): high_school_id, high_school_kv_resolved,
    #   area_resolution_reason — DROPPED in phase1_09 v1.3
    # PR5 phase1_09 (current): cultural_education_level + vocational_qualification
    #   + permanent_commune_code + area_resolution_basis (kept)
    # =========================================================================
    cultural_education_level: Optional[str] = Field(
        None,
        pattern=r"^(completed_thcs|graduated_thcs|completed_thpt|graduated_thpt|graduated_gdtx)$",
        description=(
            "Trình độ văn hóa: completed_thcs | graduated_thcs | "
            "completed_thpt | graduated_thpt | graduated_gdtx. Nullable cho "
            "draft; required tại submit T1."
        ),
    )
    vocational_qualification: Optional[str] = Field(
        None,
        pattern=r"^(none|so_cap|trung_cap|cao_dang)$",
        description=(
            "Trình độ chuyên môn: none | so_cap | trung_cap | cao_dang. "
            "DB default 'none' nếu omitted (NOT NULL constraint)."
        ),
    )
    permanent_commune_code: Optional[str] = Field(
        None, max_length=20,
        description="BNV commune code — BACKUP KV cho 4 special cases + commune_fallback"
    )
    area_resolution_basis: Optional[str] = Field(
        None,
        pattern=r"^(high_school|permanent_address_special|manual_override)$",
        description="How KV was resolved (enum — mirror of CHECK constraint)"
    )
    priority_object_codes: Optional[List[PrioritySubCode]] = Field(
        None,
        max_length=20,
        description=(
            "UT đối tượng codes thí sinh khai (vd: ['04','06']). "
            "M1 review-2 fix: per-item regex ``^[0-9]{2}$`` mirrors phase1_08b "
            "CHECK so garbage codes (vd: 'INVALID_99') fail at 422 instead of "
            "silently scoring 0đ at T6."
        ),
    )
    priority_object_evidence: Optional[
        Dict[PrioritySubCode, PriorityObjectEvidenceEntry]
    ] = Field(
        None,
        description=(
            "Evidence dict keyed by sub_code → typed entry. "
            "M2 review-2 fix: strict nested shape (status enum + optional "
            "document_id / verified_by / verified_at / reject_reason) "
            "catches typos at boundary instead of letting them pass through "
            "to the engine as silently-unverified."
        ),
    )

    # Field validators to convert empty strings to None (for pattern fields)
    @field_validator(
        'phone', 'citizen_id', 'area_resolution_basis',
        'permanent_commune_code', 'cultural_education_level', 'vocational_qualification',
        mode='before',
    )
    @classmethod
    def empty_str_to_none(cls, v):
        """Convert empty strings to None to bypass pattern validation."""
        if v == "" or v is None:
            return None
        return v

    @field_validator('email', 'full_name', 'gender', 'social_insurance_number',
                     'nationality', 'ethnicity', 'religion', 'disability_type',
                     'permanent_province', 'permanent_district', 'permanent_ward',
                     'permanent_residential_group', 'permanent_street_address',
                     'place_of_birth', 'native_place', mode='before')
    @classmethod
    def empty_str_to_none_text(cls, v):
        """Convert empty strings to None for text fields."""
        if v == "" or v is None:
            return None
        return v

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    # Cross-field date invariants — delegate to standalone utility so
    # service-layer partial-update flows (apply_minor_correction,
    # update_profile candidate-state checks) share the exact same rules.
    # See feedback memory ``partial-update-loses-cross-field-invariants``.
    from pydantic import model_validator

    @model_validator(mode='after')
    def validate_logical_dates(self) -> 'AdmissionProfileUpdate':
        """Schema-level entry point — runs on the partial payload only.

        IMPORTANT: this catches violations within the payload itself, but
        does NOT catch a partial update that conflicts with values
        already in the database. Callers doing partial updates must
        build a candidate state (DB + payload) and call
        ``validate_logical_dates`` from
        ``app.services.admission_invariants`` directly.
        """
        from app.services.admission_invariants import validate_logical_dates
        validate_logical_dates(self.model_dump())
        return self

    @model_validator(mode='after')
    def validate_priority_basis_invariants(self) -> 'AdmissionProfileUpdate':
        """H1 cross-field invariants for area_resolution_basis (v1.3 phase1_09).

        Each basis value implies a specific supporting field must be set:
        * ``permanent_address_special`` → permanent_commune_code (4 cases TT)
        * ``manual_override`` → manual reason goes vào priority_resolution_snapshot
          at engine time (no payload field — admin/officer fills via separate endpoint)
        * ``high_school`` → academic_history với THPT/TC entries (multi-school rule)
          Validated by service-layer after lookup vào academic_history.

        v1.3 changes: 'high_school' basis no longer references single field;
        candidate khai trường qua academic_history JSONB. area_resolution_reason
        column DROPPED — canonical reason lives in priority_resolution_snapshot.

        IMPORTANT caveat: validator runs on PAYLOAD ONLY. Service-layer check
        in ``update_profile`` handles cross-field with DB-persisted state.
        """
        basis = self.area_resolution_basis
        if basis is None:
            return self  # not touching basis → invariant doesn't apply

        if basis == "permanent_address_special":
            if not self.permanent_commune_code:
                raise ValueError(
                    "area_resolution_basis='permanent_address_special' yêu cầu "
                    "permanent_commune_code (4 trường hợp đặc biệt TT 05/2021)."
                )
        # 'high_school' + 'manual_override' validation moved to service-layer
        # (need academic_history context not available in pure schema validator)

        return self


# ==============================================================================
# APPLIED RULES SCHEMA (Ticket #1)
# ==============================================================================

# Ticket #4: Default Upload Configuration (Shared Constant)
DEFAULT_UPLOAD_CONFIG = {
    "allowed_types": ["application/pdf", "image/jpeg", "image/png", "image/jpg"],
    "max_file_size": 10 * 1024 * 1024,  # 10MB
    "allowed_extensions": ["pdf", "jpg", "jpeg", "png"]
}

class DocumentConfigSnapshotSchema(BaseModel):
    """Snapshot of document configuration."""
    requires_upload: Optional[bool] = None
    submission_format: Optional[str] = None
    is_mandatory: Optional[bool] = None
    label: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class UploadConfigSchema(BaseModel):
    """
    Upload configuration (Ticket #4).
    Controls frontend file validation rules.
    """
    allowed_types: List[str]
    max_file_size: int
    allowed_extensions: List[str]

    model_config = ConfigDict(extra="ignore")


class AppliedRulesSchema(BaseModel):
    """
    Schema for applied_rules snapshot (Ticket #1).
    BE-FE Contract:
    - Must handle LEGACY data (defaults required for new fields).
    - Must correspond to Zod schema strictly.
    """
    # Group 1: Basic Criteria
    min_gpa: Optional[float] = None
    min_score: Optional[float] = None

    # Group 2: Scoring Configuration
    subject_selection_mode: Optional[Literal["fixed", "best_n", "any_n"]] = "fixed"
    scoring_method: Optional[Literal["sum", "average", "weighted"]] = "sum"
    required_subject_count: Optional[int] = None
    min_subject_score: Optional[float] = None
    max_possible_score: Optional[float] = None

    # Group 3: Subject Validation
    allowed_subject_codes: List[str] = []
    subject_groups: List[Dict[str, Any]] = []

    # Group 4: Method Metadata
    admission_method: Optional[str] = None
    admission_method_id: Optional[int] = None
    # Ticket #3: Explicit method type
    # Legacy data fallback: None (Frontend handles nullable)
    method_type: Optional[Literal["gpa_only", "subject_based", "combined"]] = None

    # Group 5: Document Requirements
    mandatory_docs: List[str] = []
    doc_configs: Dict[str, DocumentConfigSnapshotSchema] = {}
    
    # Ticket #4: Upload Config
    # CRITICAL: Must provide default for legacy JSONB data that lacks this field.
    # Frontend Zod requires this field (non-optional).
    upload_config: UploadConfigSchema = Field(
        default_factory=lambda: UploadConfigSchema(**DEFAULT_UPLOAD_CONFIG)
    )

    # Group 6: Metadata
    snapshot_source: Optional[str] = None
    admission_path_id: Optional[int] = None
    academic_info_id: Optional[int] = None

    # PR #6 — submit-gate snapshot. schema_version distinguishes pre-PR
    # rows (backfilled to 1) from post-PR rows (2+). allow_unverified_submission
    # freezes the path-level toggle at the time of profile creation so
    # later admin changes don't retroactively re-score in-flight profiles.
    schema_version: Optional[int] = None
    allow_unverified_submission: Optional[bool] = None

    # E2E F1+F5 fix 2026-05-16 — 9 keys snapshot từ JSONB nhưng trước đây
    # bị model_config extra="ignore" strip im lặng (memory pattern
    # `service-explicit-dict-field-drop-pattern`). Cần expose qua API
    # response cho:
    # - FE AddChoiceDialog: derive round_id từ applied_rules khi profile
    #   chưa có NV (E2E #6 root cause)
    # - FE display: round_code, application_fee cho card hiển thị
    # - FE engine config: subject_weights cho scoring detail
    admission_round_id: Optional[int] = None  # Phase 2 v8.2 PR-2B snapshot
    round_code: Optional[str] = None
    application_fee: Optional[float] = None
    requires_application_fee: Optional[bool] = None
    fee_status: Optional[str] = None  # exempt/paid/pending/etc
    # Snapshot do record_application_fee_payment ghi (admission_service.py).
    # Khai tuong minh de extra="ignore" khong strip - panel "da thu" cua FE doc
    # bien lai + thoi diem thu tu day. (recorded_by la id int.)
    fee_paid_at: Optional[str] = None
    fee_payment_data: Optional[Dict[str, Any]] = None
    method_quota: Optional[int] = None
    applicable_to: Optional[Any] = None  # JSONB free-form (eligibility expr)
    subject_weights: Optional[Dict[str, float]] = None
    bonus_rule_override: Optional[Dict[str, Any]] = None  # JSONB nested rule

    model_config = ConfigDict(extra="ignore")


class AdmissionProfileResponse(BaseModel):
    """
    Schema for AdmissionProfile response (GET, CREATE, UPDATE).

    Includes all fields + relationships (lead, student).
    
    Phase 7: Frontend Thin Client Compliance
    - permissions: dict of action permissions (computed from Casbin + status)
    - eligibility_status: computed eligibility state
    - validation_errors: list of validation issues
    - available_actions: list of allowed workflow actions
    - completion_percent: profile completion percentage
    """
    id: int
    lead_id: int
    status: str
    version: int
    academic_year: int  # ✅ NEW: Academic year (e.g., 2025, 2026)

    # phase3_01 (#184 Wave 3 PR-3A) P-UI-02 v0.6 — multi-NV gate.
    # false = legacy single-NV ProfileSubjectScore flow; true = Phase 3
    # AdmissionProfileChoice + ProfileChoiceScore engine flow. FE Step 5
    # "Nguyện vọng" hiển thị có điều kiện theo flag này (dynamic
    # visibleSteps array per P-UI-01).
    uses_choice_engine: bool = False

    # Phase 3 multi-NV choices array. Empty cho legacy profile
    # (uses_choice_engine=False). GET endpoints (single/list) eager-load
    # via AdmissionRepository._choices_eager_load_options() chain.
    # Mutation endpoints (POST/PATCH/approve/reject/withdraw/...) trả
    # empty list — caller refetch detail sau mutation nếu cần choices.
    # Lazy-load safety enforced by _safely_handle_unloaded_choices()
    # below (set_committed_value cho relation chưa load → tránh
    # MissingGreenlet trong async context).
    choices: List[AdmissionProfileChoiceResponse] = Field(default_factory=list)

    # ✅ Ticket #1: Use strict schema
    applied_rules: AppliedRulesSchema

    created_at: datetime
    updated_at: datetime
    
    # Personal Info Fields
    full_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    citizen_id: Optional[str] = None
    citizen_id_masked: Optional[str] = Field(
        None,
        description="Masked citizen ID for display (e.g., ********1234)"
    )
    social_insurance_number: Optional[str] = None
    
    # Location Fields
    nationality: Optional[str] = None
    ethnicity: Optional[str] = None
    religion: Optional[str] = None
    disability_type: Optional[str] = None
    permanent_province: Optional[str] = None
    permanent_district: Optional[str] = None
    permanent_ward: Optional[str] = None
    permanent_residential_group: Optional[str] = None
    permanent_street_address: Optional[str] = None
    place_of_birth: Optional[str] = None
    native_place: Optional[str] = None

    # =========================================================================
    # Q9 #07 Priority bonus fields (READ side) — v1.3 phase1_09
    # =========================================================================
    cultural_education_level: Optional[str] = None
    vocational_qualification: Optional[str] = None
    permanent_commune_code: Optional[str] = None
    area_resolution_basis: Optional[str] = None
    priority_object_codes: list[str] = Field(default_factory=list)
    priority_object_evidence: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Q9 #07 Phase E.4 (Option A) — denormalized projection for workbench UI.
    # Populated by admission_service._populate_response_fields as a TRANSIENT
    # attribute on the ORM instance. JSONB column `priority_object_evidence`
    # NEVER receives denormalized data — avoids SQLAlchemy dirty-flag persist
    # cascade.
    # FE pattern: prefer `priority_object_evidence_display ?? priority_object_evidence`.
    priority_object_evidence_display: Optional[
        Dict[str, PriorityObjectEvidenceDisplayEntry]
    ] = Field(default=None)
    # Q9 #07 Phase E.4 — codes có UT ghi nhận nhưng officer chưa scan file.
    # FE dùng để render inline warning ở §3 UT card. KHÔNG ảnh hưởng
    # eligibility_status — officer có quyền verify "Hồ sơ giấy" và submit.
    # Decision #2: warning UX only, NOT eligibility gate.
    missing_priority_evidence_codes: list[str] = Field(default_factory=list)
    # Q9 #07 Phase E.4 G0a — Server-computed Priority section rows for
    # DocumentsTab. FE DocumentsTab consume directly thay vì raw query.
    priority_evidence_documents: list[PriorityEvidenceDocumentItem] = Field(
        default_factory=list
    )
    priority_resolution_snapshot: Dict[str, Any] = Field(default_factory=dict)
    # Q9 #07 Phase E.4 — workbench audit timeline.
    # Last 20 priority_audit_log entries DESC (KV override + UT verify/reject
    # + admin bulk-fill). Empty list khi profile chưa có intervention nào.
    # Populated by admission_service._populate_response_fields.
    priority_audit_log: list[PriorityAuditEntry] = Field(default_factory=list)

    # Scores (Dynamic Calculation)
    admission_scores: Optional[AdmissionScoreSchema] = None
    total_score: Optional[float] = None
    average_score: Optional[float] = None
    
    # Political Dates
    union_entry_date: Optional[datetime] = None
    party_entry_date: Optional[datetime] = None
    party_official_entry_date: Optional[datetime] = None

    # ✅ FIX #6: Audit trail fields (approve/reject tracking)
    approved_at: Optional[datetime] = None
    approved_by_id: Optional[int] = None
    approval_notes: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by_id: Optional[int] = None
    rejection_reason: Optional[str] = None

    # ✅ Resubmit audit fields
    resubmitted_at: Optional[datetime] = None
    resubmitted_by_id: Optional[int] = None
    resubmit_notes: Optional[str] = None

    # ✅ Revision request audit fields
    revision_requested_at: Optional[datetime] = None
    revision_requested_by_id: Optional[int] = None
    revision_reason: Optional[str] = None

    # ✅ Override audit fields
    overridden_at: Optional[datetime] = None
    overridden_by_id: Optional[int] = None
    override_reason: Optional[str] = None

    # ✅ Drop-out tracking
    is_dropped: Optional[bool] = None
    dropped_at: Optional[datetime] = None
    dropped_by_id: Optional[int] = None
    dropped_reason: Optional[str] = None

    # ✅ Confirmation tracking
    confirmed_by_id: Optional[int] = None

    # Claim/assignment fields
    assigned_reviewer_id: Optional[int] = None
    assigned_reviewer_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    assigned_officer_name: Optional[str] = None

    # ✅ Ticket #2: Qualification Status
    # Computed by backend: True if all academic criteria met
    is_qualified: Optional[bool] = None

    # JSONB Fields — DB enforces NOT NULL DEFAULT '[]' after migration
    # `nn20260419001`. Validator below stays as belt-and-suspenders for
    # any cached payload / downgrade path that still produces None.
    # See project_admissions_list_null_list_fields for original 2026-04-18
    # incident.
    family_info: List[FamilyMemberSchema] = Field(default_factory=list)
    academic_history: List[AcademicRecordSchema] = Field(default_factory=list)

    @field_validator("family_info", "academic_history", mode="before")
    @classmethod
    def _coerce_null_list_jsonb_to_empty(cls, value):
        """Convert DB NULL into an empty list before Pydantic type-check.

        Runs in `mode='before'` so the raw `None` from SQLAlchemy never
        hits Pydantic's `List[...]` validator (which would raise
        `list_type`). If the column was accidentally set to a non-list
        value by some unusual path, we still raise below.
        """
        if value is None:
            return []
        return value

    # Nested relationships (using forward refs for circular import avoidance)
    lead: Optional["LeadShallowForAdmission"] = None
    student: Optional["StudentShallowForAdmission"] = None

    # Denormalized fields for list display (avoids nested relationship loading issues)
    program_name: Optional[str] = Field(
        None,
        description="Program name from lead.offering.program (denormalized for list view)"
    )

    # =========================================================================
    # Học phí HK1 (Admission List v2) — denormalized aggregate cho cột danh sách.
    # Set transient ở admission_repository.get_filtered_with_count (scalar
    # subquery, coalesce→0). Decimal → Pydantic v2 serialize JSON string; FE
    # normalize string→number ở API client listAdmissions (list không .parse()).
    # `tuition_hk1_status` do BE tính (_hk1_status) — FE chỉ map màu (thin-client).
    # =========================================================================
    tuition_paid_hk1: Optional[Decimal] = Field(
        None, description="Σ học phí HK1 đã đóng (fee tuition semester_no=1 non-cancelled)"
    )
    tuition_remaining_hk1: Optional[Decimal] = Field(
        None, description="Σ học phí HK1 còn lại (final − paid − waived)"
    )
    tuition_overdue_hk1: bool = Field(
        default=False, description="Có hóa đơn HK1 quá hạn chưa thanh toán đủ"
    )
    tuition_hk1_status: Optional[str] = Field(
        None, description="Trạng thái HK1: paid|partial|unpaid|overdue|none (BE emit, FE map màu)"
    )

    # =========================================================================
    # Phase 7: Frontend Thin Client Compliance Fields
    # =========================================================================
    
    # Permission flags (computed from Casbin + status + user context)
    # Keys: edit, save, submit, approve, reject, enroll, delete
    permissions: Dict[str, bool] = Field(
        default_factory=dict,
        description="Permission flags computed from Casbin policy and status"
    )
    
    # Eligibility status (computed by backend service)
    eligibility_status: Literal["eligible", "ineligible", "pending"] = Field(
        default="pending",
        description="Backend-computed eligibility based on applied_rules"
    )

    # F7: True when reviewer is about to act on a profile that bypassed
    # eligibility (allow_unverified_submission=true + ineligible + still
    # in a reviewable state). FE renders an orange warning banner +
    # confirmation dialog in front of the Approve button so admin doesn't
    # silently approve a profile with missing required data.
    bypass_warning: bool = Field(
        default=False,
        description="True if profile bypassed eligibility check via allow_unverified_submission flag"
    )

    # P0-1 fix 2026-05-22 — BE-aggregated mode flag thay thế FE `user.role`
    # string check ở PriorityTab (vi phạm Thin Client RULE 2 frontend/CLAUDE.md).
    # FE đọc thẳng field này để pass xuống PriorityOverrideDialog.mode →
    # render đúng UX copy/severity theo role. Server-derived, drift-free khi
    # Casbin policy thay đổi (vd accountant diamond-inherit manager).
    #
    # Officer mode KHÔNG phải "none" — vẫn render dialog read-only + secondary
    # CTA "Đề nghị quản lý ấn định KV" khi requires_manual_override.
    override_priority_kv_mode: Literal["admin", "manager", "officer", "none"] = Field(
        default="none",
        description="Mode flag cho PriorityOverrideDialog (admin/manager/officer/none). Server-derived, không check role.role ở FE.",
    )
    
    # Validation errors (reasons why profile is not eligible)
    validation_errors: List[str] = Field(
        default_factory=list,
        description="List of validation issues (e.g., 'CCCD required', 'GPA below threshold')"
    )
    
    # Available workflow actions
    available_actions: List[str] = Field(
        default_factory=list,
        description="List of currently available actions (e.g., ['save', 'submit'])"
    )

    # Per-profile effective allowlist for the post-approval correction
    # dialog. Resolved server-side from
    # SAFE_MINOR_CORRECTION_FIELDS ∩ admission_path.minor_correction_allowed_fields,
    # so FE renders only the fields admin enabled for this profile's path
    # without needing to fetch path config separately.
    minor_correction_fields: List[str] = Field(
        default_factory=list,
        description=(
            "Effective per-profile allowlist for minor correction. "
            "FE renders dialog rows from this list."
        )
    )
    
    # Profile completion percentage (0-100)
    completion_percent: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Profile completion percentage (computed by backend)"
    )
    
    # Validation summary (grouped errors for UX)
    validation_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Grouped validation errors: {gpa: {has_error, label, count}, documents: {...}, personal: {...}}"
    )

    # Grouped validation errors (categorized display)
    grouped_validation_errors: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Validation errors grouped by category: {personal_info: {category, errors, count}, documents: {...}, scores: {...}, required_data: {...}}"
    )

    # Draft còn thiếu dữ liệu bắt buộc (quá trình học tập / thông tin gia đình)
    # vốn chặn submit nhưng không nằm trong validation_errors → FE dùng cờ này để
    # disable nút Nộp + hiện lý do rõ ràng. Bypass-independent: cờ phản ánh submit
    # gate VÔ ĐIỀU KIỆN (allow_unverified_submission chỉ nới kiểm tra tài liệu).
    submit_blocked_by_data: Optional[bool] = Field(
        default=False,
        description="Draft blocked from submit by missing required data (family/academic). Bypass-independent: mirrors the unconditional submit gate; allow_unverified_submission only relaxes document verification, never these two groups."
    )

    # Executive summary for dashboard overview
    executive_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description="High-level status summary: {overall_status, completion_percent, step_summary, critical_blockers, warnings, next_action, can_submit}"
    )

    # Step status for sidebar (Architecture Compliant - Backend computes)
    step_status: Optional[Dict[int, str]] = Field(
        default=None,
        description="Step status map: {1: 'error', 2: 'warning', 3: 'success', ...}"
    )
    
    # Documents checklist for frontend display. Items follow
    # DocumentItemSchema — including the 5 per-document permission flags
    # the FE uses to gate Upload/Verify/Reject/Reset/Paper-submit buttons.
    documents_checklist: List[DocumentItemSchema] = Field(
        default_factory=list,
        description=(
            "Required-document items enriched with backend-computed display "
            "fields (is_mandatory, requires_upload, submission_format, "
            "rejection_reason) and permission flags (can_upload, can_verify, "
            "can_reject, can_reset, can_mark_paper_submitted)."
        ),
    )
    
    # ✅ Ticket #3.1: Document Status Summary (Computed by Backend)
    # Replaces frontend calculation logic for Thin Client compliance
    document_stats: Optional[Dict[str, int]] = Field(
        None,
        description="Document stats: {submitted_count, verified_count, mandatory_count, missing_count}"
    )

    # Snapshot Score (for Best N Highlighting)
    snapshot_score: Optional[Dict[str, Any]] = Field(
        None,
        description="Detailed score snapshot containing selected_subjects, etc."
    )

    # =========================================================================
    # Ticket #5: Score Status (Thin Client Compliance)
    # Backend computes pass/fail status, Frontend ONLY renders
    # =========================================================================
    score_snapshot_status: Optional[Dict[str, Any]] = Field(
        None,
        description="Backend-computed score pass/fail status: {total_status, subject_statuses: {code: status}}"
    )

    # =========================================================================
    # Fast-track prepay/giữ chỗ — nợ giấy tờ contract (C1)
    # =========================================================================
    # Persisted snapshot captured at staff submit-with-debt. Shape:
    # {codes, reason, by_user_id, at}. None = no debt ever recorded.
    document_debt: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Snapshot of nợ giấy tờ captured at submit-with-debt: "
            "{codes, reason, by_user_id, at}. None when no debt recorded."
        ),
    )
    # COMPUTED (transient): the snapshot's codes that are STILL missing now.
    # Self-resolves to [] once the officer uploads the owed docs — this is
    # what the FE badge counts (NOT document_debt.codes which is frozen).
    outstanding_debt_codes: List[str] = Field(
        default_factory=list,
        description=(
            "Document codes from document_debt that are still missing now "
            "(document_debt.codes ∩ currently-missing docs). Empty when the "
            "debt has been fully resolved."
        ),
    )
    # Mandatory document codes currently missing (truly-missing, excluding
    # uploaded-pending-verify). FE lists these in the submit-with-debt dialog.
    missing_doc_codes: List[str] = Field(
        default_factory=list,
        description=(
            "Mandatory document codes currently missing (excludes "
            "uploaded-but-pending-verify). Drives the submit-with-debt dialog."
        ),
    )
    # COMPUTED flag — true only when a staff actor could submit this draft
    # with a document debt: draft + staff + no non-document errors + at least
    # one missing doc + not a multi-NV-without-choice. FE gates the "Nộp kèm
    # nợ giấy tờ" button on this.
    can_submit_with_document_debt: bool = Field(
        default=False,
        description=(
            "True when the acting staff user may submit this draft with a "
            "document debt (eligible apart from missing docs)."
        ),
    )
    # COMPUTED (transient): true only when a rejected/withdrawn profile still
    # holds collected (unrefunded) tuition (SUM(fee.paid_amount) > 0). A prepaid
    # hold-spot fee survives reject/withdraw and is NOT auto-refunded → the FE
    # shows a "cần hoàn tiền" warning. False for every non-terminal status (no
    # DB hit). Self-resolves to False once the money is refunded (refund
    # decrements paid_amount).
    has_unrefunded_payment: bool = Field(
        default=False,
        description=(
            "True when a rejected/withdrawn profile still holds collected, "
            "not-yet-refunded tuition (SUM(fee.paid_amount) > 0). Drives the "
            "'cần hoàn tiền' warning banner."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _safely_handle_unloaded_choices(cls, data: Any) -> Any:
        """Skip lazy-load của ``choices`` relation khi serialize từ ORM.

        Mutation endpoints (POST/PATCH/approve/reject/withdraw/...) trả
        AdmissionProfile sau khi flush nhưng KHÔNG eager-load
        ``choices``. Pydantic ``from_attributes=True`` sẽ getattr
        choices → trigger lazy-load → ``MissingGreenlet`` trong async
        context (Pydantic không thể await).

        Fix: dùng SQLAlchemy ``set_committed_value`` để mark relation
        "loaded" với empty list cho instances không qua eager-load
        chain. GET endpoints (đã eager-load) skip nhánh này — ``choices``
        đã ở ``state.unloaded`` không nữa.

        Anti-pattern check: KHÔNG mutate user-data; chỉ inject empty
        list cho relation collection (đúng default semantics khi
        không có choices). Caller mutation endpoints không kỳ vọng
        receive choices trong response.
        """
        if isinstance(data, dict):
            return data
        try:
            from sqlalchemy import inspect as sa_inspect
            from sqlalchemy.orm.attributes import set_committed_value

            state = sa_inspect(data, raiseerr=False)
            if state is not None and "choices" in state.unloaded:
                set_committed_value(data, "choices", [])
        except Exception:
            # Defensive: nếu data không phải ORM (vd unit-test mock),
            # để Pydantic xử lý tự nhiên.
            pass
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def primary_choice_display(self) -> Optional[str]:
        """Resolved display name of the primary nguyện vọng — the SINGLE BE source
        so the FE header doesn't heuristically pick between ``choices[0]`` and the
        legacy ``program_name``.

        - Choice-engine profile: the lowest-``display_order`` choice's program name
          (falls back to its path name when the program label is blank).
        - Legacy single-NV profile (``uses_choice_engine=False``): ``program_name``.
        - Choice-engine profile with an EMPTY ``choices`` genuinely has no nguyện
          vọng yet → ``None`` (so the FE shows "Chưa chọn nguyện vọng" rather than a
          stale lead/offering value). Returns ``None`` when nothing is available.
        """
        if self.choices:
            first = min(self.choices, key=lambda c: c.display_order)
            name = (first.display_program_name or "").strip()
            if name:
                return name
            return (first.display_path_name or "").strip() or None
        if not self.uses_choice_engine and self.program_name:
            return self.program_name.strip() or None
        return None

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


class LeadShallowForAdmission(BaseModel):
    """Minimal Lead info for AdmissionProfileResponse."""
    id: int
    full_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    unit_id: Optional[int] = None
    assigned_officer_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class StudentShallowForAdmission(BaseModel):
    """Minimal Student info for AdmissionProfileResponse."""
    id: int
    student_code: str
    enrollment_date: datetime

    model_config = ConfigDict(from_attributes=True)


# Update forward refs
AdmissionProfileResponse.model_rebuild()


class AdmissionsPage(BaseModel):
    """Paginated admissions response with metadata."""
    total_count: int
    page: int
    page_size: int
    profiles: List[AdmissionProfileResponse]


class PendingDiplomaItem(BaseModel):
    """PR #13.7 — một hồ sơ còn "nợ bằng" (Giấy CN tốt nghiệp tạm thời)."""
    profile_id: int
    candidate_name: Optional[str] = None
    phone: Optional[str] = None
    status: str
    supplement_due_date: Optional[date] = None
    assigned_officer_name: Optional[str] = None


class PendingDiplomaResponse(BaseModel):
    """PR #13.7 — danh sách hồ sơ nợ bằng, IDOR-scoped theo người gọi."""
    total_count: int
    items: List[PendingDiplomaItem]


# ==============================================================================
# BULK ACTION SCHEMAS
# ==============================================================================

# ------------------------------------------------------------------------------
# ADM-026 review (Nit): the (bypass_quota, bypass_reason) pair previously
# carried three verbatim copies of the cross-field validator across
# BulkApproveItem / ApproveRequest / FinalizeRequest. Extract into a single
# mixin so the contract — "bypass requires a reason ≥20 chars" — has one
# definition. ``model_validator(mode="after")`` defined on a base class
# still fires on subclasses, so each schema picks the rule up by
# inheritance and the audit log evidence-string format stays identical.
# Admin-only enforcement still lives in the request-entry dependency
# (``require_admin_for_quota_bypass`` in ``deps.py``) plus the service-side
# defense-in-depth check inside ``_assert_quota_or_bypass``.
# ------------------------------------------------------------------------------


class _QuotaBypassMixin(BaseModel):
    """Shared (bypass_quota, bypass_reason) pair + cross-field validator."""

    bypass_quota: bool = Field(
        False,
        description="ADM-026: Override annual_admission_quota cap (admin only). Requires bypass_reason.",
    )
    bypass_reason: Optional[str] = Field(
        None,
        max_length=1000,
        description="ADM-026: Required when bypass_quota=true. Min 20 chars. Audit log evidence.",
    )

    @model_validator(mode="after")
    def _validate_bypass_pair(self):
        if self.bypass_quota:
            reason = (self.bypass_reason or "").strip()
            if len(reason) < 20:
                raise ValueError(
                    "bypass_reason is required and must be at least 20 characters when bypass_quota=true"
                )
        return self


class BulkApproveItem(_QuotaBypassMixin):
    """Single item in a bulk approve request."""
    profile_id: int = Field(..., description="Admission profile ID")
    version: int = Field(..., ge=1, description="Current profile version for optimistic locking")
    # ADM-026: per-item quota bypass. Admin-only enforced at request entry
    # (``require_admin_for_quota_bypass`` in ``deps.py``); service-side check
    # in ``_assert_quota_or_bypass`` is defense-in-depth.


class BulkApproveRequest(BaseModel):
    """Request schema for bulk approve action."""
    items: List[BulkApproveItem] = Field(..., min_length=1, max_length=100, description="List of profiles to approve with their versions")
    notes: Optional[str] = Field(None, max_length=1000, description="Optional approval notes")


class BulkRejectItem(BaseModel):
    """Single item in a bulk reject request."""
    profile_id: int = Field(..., description="Admission profile ID")
    version: int = Field(..., ge=1, description="Current profile version for optimistic locking")


class BulkRejectRequest(BaseModel):
    """Request schema for bulk reject action."""
    items: List[BulkRejectItem] = Field(..., min_length=1, max_length=100, description="List of profiles to reject with their versions")
    reason: str = Field(..., min_length=10, max_length=1000, description="Rejection reason (required)")


class BulkAssignRequest(BaseModel):
    """Request schema for bulk assign to officer action."""
    profile_ids: List[int] = Field(..., min_length=1, max_length=100, description="List of profile IDs to assign")
    officer_id: int = Field(..., description="ID of the officer to assign profiles to")


class BulkActionResponse(BaseModel):
    """Response schema for bulk actions."""
    success_count: int = Field(..., description="Number of successfully processed profiles")
    failed_count: int = Field(..., description="Number of failed profiles")
    failed_ids: List[int] = Field(default_factory=list, description="IDs of profiles that failed")
    errors: Optional[Dict[int, str]] = Field(None, description="Error messages per failed profile ID")
    message: str = Field(..., description="Summary message")


class AdmissionSubmitRequest(BaseModel):
    """Request body for ``POST /api/admissions/{id}/submit`` (fast-track C1).

    The endpoint historically took no body. The two optional fields enable
    the staff-only "Nộp kèm nợ giấy tờ" flow: when a profile is eligible in
    every respect except missing mandatory documents, an officer/manager/
    admin may acknowledge the missing docs and supply a reason; the service
    then transitions the profile to ``submitted`` and records a
    ``document_debt`` snapshot.

    Defaults (``acknowledge_missing_docs=False``, ``document_debt_reason=
    None``) reproduce the original no-body behaviour exactly, so existing
    callers (including the magic-link candidate path) are unaffected. The
    service enforces the staff-only gate + reason requirement; this schema
    only carries the inputs.
    """

    acknowledge_missing_docs: bool = Field(
        default=False,
        description=(
            "Staff acknowledges submitting with mandatory documents still "
            "missing (nợ giấy tờ). Ignored unless the actor is staff and "
            "the only outstanding errors are missing documents."
        ),
    )
    document_debt_reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description=(
            "Required when acknowledge_missing_docs=True — officer's reason "
            "for allowing the document debt (e.g. 'HS xin cấp lại học bạ, "
            "hẹn nộp 30/06')."
        ),
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionSubmitResponse(BaseModel):
    """
    Schema for submit endpoint response.

    ✅ CRITICAL FIX #1: Updated to match state machine flow
    - draft → submitted (validation pass)
    - draft → draft (validation fail - user fixes errors)

    Success (200):
    - status: "submitted" (wait for Manager approval)
    - message: Success message
    - validation_errors: null

    Validation Failed (200):
    - status: "draft" (user needs to fix errors)
    - message: null
    - validation_errors: List of error messages
    """
    status: Optional[Literal["draft", "submitted"]] = None  # ✅ FIX: Match state machine
    message: Optional[str] = None
    validation_errors: Optional[List[str]] = None  # ✅ FIX: Renamed from "errors"

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )


class EnrollStudentResponse(BaseModel):
    """
    Schema for enroll endpoint response (201 Created).

    Returns newly created student information.
    """
    student_id: int = Field(..., description="Student ID")
    student_code: str = Field(..., description="Generated student code (SV + YYYY + 0000)")
    enrollment_date: datetime = Field(..., description="Enrollment date (UTC)")

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


# ==============================================================================
# STUDENT SCHEMAS (for responses)
# ==============================================================================

class StudentDocumentResponse(BaseModel):
    """Schema for StudentDocument response."""
    id: int
    student_id: int
    doc_type: str
    file_path: str
    is_verified: bool
    reviewer_note: Optional[str] = None
    uploaded_at: datetime
    verified_at: Optional[datetime] = None

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


class DocumentUploadResponse(BaseModel):
    """Schema for document upload response."""
    code: str = Field(..., description="Document code (e.g., HOC_BA)")
    label: str = Field(..., description="Human-readable name")
    is_mandatory: bool = Field(default=True)
    status: Literal["missing", "uploaded", "verified", "rejected", "paper_submitted"] = Field(
        default="uploaded",
        description="Upload status"
    )
    file_path: Optional[str] = Field(
        None,
        description="File path where document is stored"
    )
    uploaded_at: Optional[str] = Field(
        None,
        description="Upload timestamp (ISO format)"
    )
    # ✅ FIX Finding 2.3
    verified_format: Optional[str] = Field(
        None,
        description="Verified format (original/certified_copy/photo)"
    )

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


class DocumentSubmissionRequest(BaseModel):
    """
    Schema for document submission (upload or paper receipt).
    User/Officer declares what type of document is being submitted.
    """
    actual_submission_format: Literal["original", "certified_copy", "photo"] = Field(
        ...,
        description="Type of physical document being submitted/uploaded"
    )
    # PR #13 — chỉ áp cho giấy TN THPT (bang_tot_nghiep_thpt); bỏ qua doc khác.
    graduation_proof_kind: Optional[
        Literal["official_diploma", "provisional_cert"]
    ] = Field(None, description="Loại giấy tốt nghiệp THPT (PR#13)")
    supplement_due_date: Optional[date] = Field(
        None, description="Hạn bổ sung bằng khi provisional_cert (PR#13)"
    )

    @model_validator(mode="after")
    def _check_provisional_due(self):
        if (
            self.graduation_proof_kind == "provisional_cert"
            and self.supplement_due_date is None
        ):
            raise ValueError(
                "supplement_due_date bắt buộc khi provisional_cert"
            )
        return self

    model_config = ConfigDict(str_strip_whitespace=True)


class GraduationProofUpdateRequest(BaseModel):
    """PR #13 — cập nhật loại giấy tốt nghiệp (vd provisional→official)."""
    kind: Literal["official_diploma", "provisional_cert"] = Field(
        ..., description="Loại giấy tốt nghiệp mới"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentFormatVerifyRequest(BaseModel):
    """
    Schema for verifying document format (Officer action).
    Finding 2.3: Officer confirms if document is Original/Copy.
    """
    format: Literal["original", "certified_copy", "photo"] = Field(
        ...,
        description="Physical format of the document"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentRejectRequest(BaseModel):
    """Schema for reject document request."""
    reason: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Rejection reason (required)"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class StudentResponse(BaseModel):
    """Schema for Student response."""
    id: int
    admission_profile_id: int
    student_code: str
    enrollment_date: datetime
    created_at: datetime

    # Nested relationships
    documents: List[StudentDocumentResponse] = []

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True
    )


# ==============================================================================
# STATE TRANSITION SCHEMAS (State Machine)
# ==============================================================================

class ApproveRequest(_QuotaBypassMixin):
    """
    Schema for approve action (Manager/Admin).

    ✅ CRITICAL FIX #4: Made version REQUIRED for optimistic locking
    Without version check: 2 managers can approve/reject same profile simultaneously
    With version check: Second request fails with 409 Conflict

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → APPROVED
    - Requires Manager or Admin role
    - Optional approval notes
    - REQUIRED version for optimistic locking (CRITICAL FIX #4)

    ADM-026: bypass_quota / bypass_reason inherited from _QuotaBypassMixin.
    Admin-only enforced at request entry (``require_admin_for_quota_bypass``
    in ``deps.py``); service ``_assert_quota_or_bypass`` is defense-in-depth.
    """
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional approval notes/comments"
    )
    version: int = Field(  # ✅ CRITICAL FIX #4: Now REQUIRED (was Optional)
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class RejectRequest(BaseModel):
    """
    Schema for reject action (Manager/Admin).

    ✅ CRITICAL FIX #4: Made version REQUIRED for optimistic locking

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1:
    - Transition: SUBMITTED/RESUBMITTED → REJECTED
    - Requires Manager or Admin role
    - Reason is MANDATORY (min 10 chars)
    - REQUIRED version for optimistic locking (CRITICAL FIX #4)
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Rejection reason (min 10 chars, required)"
    )
    version: int = Field(  # ✅ CRITICAL FIX #4: Now REQUIRED (was Optional)
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class RevisionRequest(BaseModel):
    """
    Schema for revision request action (Manager/Admin).

    Transition: SUBMITTED/RESUBMITTED -> REVISION_REQUESTED
    Requires Manager or Admin role.
    Reason is MANDATORY (min 10 chars).
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Revision reason/instructions (min 10 chars, required)"
    )
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class ResubmitRequest(BaseModel):
    """
    Schema for resubmit action (Officer).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2:
    - Transition: REJECTED → RESUBMITTED
    - Requires Officer or higher role
    - Optional notes about what was fixed
    """
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking"
    )
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional notes about what was fixed/updated"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class ConfirmRequest(BaseModel):
    """
    Schema for confirm action (Applicant/User).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.3:
    - Transition: APPROVED → CONFIRMED
    - SELF check required (lead.user_id == current_user.id)
    - Admin can also confirm
    """
    # No fields required - simple confirmation
    pass

    model_config = ConfigDict(str_strip_whitespace=True)


class WithdrawRequest(BaseModel):
    """
    Schema for withdrawal action.

    Transitions allowed from: DRAFT, SUBMITTED, REJECTED, RESUBMITTED
    Target state: WITHDRAWN (terminal)

    Lead pipeline sync: lead moves to sts08 (Từ chối tư vấn) per
    lead_admission_sync mapping. Service layer handles the sync.

    **Validation:**
    - reason: required, 5-1000 chars, HTML-escaped
    - version: required for optimistic locking
    """
    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Withdrawal reason (required)",
    )
    version: int = Field(
        ...,
        description="Profile version for optimistic locking",
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS prevention: escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class CancelWithdrawalRequest(BaseModel):
    """Schema for the admin "cancel withdrawal" action (PR-B).

    Reverts a ``withdrawal_pending`` profile back to ``draft`` when the refund
    was rejected, so the profile is not stuck awaiting a refund that will never
    complete. Admin-only (router gate). No optimistic-lock version: this is a
    rare recovery action on a profile that is, by definition, not being edited.
    """
    reason: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Reason for cancelling the withdrawal (required)",
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS prevention: escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class OverrideRequest(BaseModel):
    """
    Schema for override action (Admin only).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: APPROVED → OVERRIDDEN
    - Admin only
    - Reason MANDATORY (audit requirement)
    - Full audit logging required
    - REQUIRED version for optimistic locking (ADM-015)
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Override reason (min 10 chars, required for audit)"
    )
    bypass_rules: List[str] = Field(
        default_factory=list,
        description="List of rules bypassed (e.g., ['min_gpa', 'missing_documents'])"
    )
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class FinalizeRequest(_QuotaBypassMixin):
    """
    Schema for finalize action (Admin only).

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.4:
    - Transition: OVERRIDDEN/CONFIRMED → ENROLLED
    - Admin only
    - Creates Student record
    - REQUIRED version for optimistic locking (ADM-015)

    ADM-026: bypass_quota / bypass_reason inherited from _QuotaBypassMixin.
    """
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking (prevents race conditions)"
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class DropStudentRequest(BaseModel):
    """
    Schema for marking an enrolled student as dropped out (Manager/Admin).

    Side-channel: status stays "enrolled", sets is_dropped=True.
    Reason is MANDATORY (min 10 chars).
    """
    reason: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Drop-out reason (min 10 chars, required)"
    )
    version: int = Field(
        ...,
        ge=1,
        description="REQUIRED: Current profile version for optimistic locking"
    )

    @field_validator('reason')
    @classmethod
    def sanitize_reason(cls, v: str) -> str:
        """XSS Prevention: Escape HTML entities."""
        return html.escape(v.strip())

    model_config = ConfigDict(str_strip_whitespace=True)


class ClaimRequest(BaseModel):
    """
    Schema for Claiming a profile.
    Only version is needed for optimistic locking.
    """
    version: int = Field(..., description="Optimistic locking version")


# StringConstraints applies strip_whitespace BEFORE checking min/max
# length, so a payload like "          a" (9 spaces + 1 char, length 10)
# fails the min=10 check after stripping. Defends against accidental
# zero-effort reasons that bypass min_length when validated via
# Field(min_length=...).
TrimmedReason = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=10, max_length=1000),
]


class MinorCorrectionRequest(BaseModel):
    """Request schema for ``POST /admissions/{id}/minor-correction``.

    Three required fields:
    - ``version`` for optimistic locking (matches the version-on-state
      pattern used by approve/reject/etc., raises 409 on mismatch).
    - ``reason`` whose effective length is checked AFTER strip; an
      operator must supply real justification per audit policy.
    - ``changes`` is a dict of ``{field_key: new_value}``. Field-level
      type validation runs server-side via the FIELD_ADAPTERS map in
      ``admission_correction_helpers.py``; we keep the schema as
      ``dict[str, Any]`` here so unknown / hard-deny keys surface in
      the service-side check rather than failing Pydantic with a
      cryptic union error.
    """

    version: int = Field(
        ...,
        ge=1,
        description="Current profile version for optimistic locking"
    )
    reason: TrimmedReason = Field(
        ...,
        description=(
            "Why this correction is being made. Stored on the audit row. "
            "Min 10 characters AFTER trim — pure-whitespace inputs reject."
        ),
    )
    changes: Dict[str, Any] = Field(
        ...,
        description=(
            "Map of {field_key: new_value}. Field validation happens "
            "server-side after status / IDOR / allowlist gates."
        ),
    )

    @field_validator("changes")
    @classmethod
    def changes_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if not v:
            raise ValueError("changes must contain at least one field")
        return v


# ==============================================================================
# EXPORT ALL
# ==============================================================================

# ==============================================================================
# CONFIRMATION TOKEN SCHEMAS (Magic Link)
# ==============================================================================


class ConfirmTokenVerifyRequest(BaseModel):
    """
    Request body for token-based confirmation.
    
    Security:
    - Pattern validation for exactly 4 digits
    - Used with magic link token for CCCD verification
    """
    last_digits_citizen_id: str = Field(
        ...,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="Last 4 digits of CCCD/CMND"
    )
    
    model_config = ConfigDict(str_strip_whitespace=True)


class ConfirmTokenResponse(BaseModel):
    """Response after successful token-based confirmation."""
    message: str
    profile_id: int
    status: str
    confirmed_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


def _mask_display_name(name: str) -> str:
    """Mask a display name for the PUBLIC confirm-info endpoint so the full
    name (PII) is not exposed before CCCD verification — the token sits in the
    URL and anyone with the link can hit this endpoint. Keeps the first
    character of each word and replaces the rest with a fixed mask (does not
    leak the exact length)."""
    parts = (name or "").split()
    out = [p if len(p) <= 1 else p[0] + "•••" for p in parts]
    return " ".join(out) if out else (name or "")


class ConfirmTokenInfoResponse(BaseModel):
    """
    Info about token (for frontend to show confirmation form).
    
    Used by GET /confirm/{token} to display:
    - Lead name ("Xin chào, [Tên]...")
    - Token status (valid, expired, locked)
    - Attempts remaining
    """
    valid: bool
    expired: bool
    locked: bool
    already_used: bool
    attempts_remaining: int
    profile_name: str = Field(
        description=(
            "Lead's full_name MASKED (first letter of each word). The full "
            "name is only revealed after CCCD verification via "
            "POST /confirm/{token} — the token is public (in the URL)."
        )
    )
    expires_at: Optional[datetime] = None

    @field_validator("profile_name")
    @classmethod
    def _mask_name(cls, v: str) -> str:
        # PR1 Commit 7: never expose the full name from this public,
        # pre-verification endpoint.
        return _mask_display_name(v)
    
    model_config = ConfigDict(from_attributes=True)


class SendMagicLinkRequest(BaseModel):
    """W2-1 fix Wave 7 (2026-05-16) — Request body cho generate-side
    magic-link cho 3 non-confirm actions.

    Officer/manager/admin chọn action; BE validate state precondition +
    overwrite existing token row với action_type new. UX mirror
    /send-confirmation nhưng explicit action param.
    """
    action: Literal["submit", "resubmit", "withdraw"] = Field(
        ...,
        description=(
            "Action type magic-link sẽ enable cho candidate self-service. "
            "Confirm dùng /send-confirmation endpoint riêng (legacy path)."
        ),
    )
    model_config = ConfigDict(str_strip_whitespace=True)


class SendMagicLinkResponse(BaseModel):
    """Response after generating magic-link cho non-confirm action.

    Mirror SendConfirmationResponse shape — FE dialog copy URL pattern
    reused (SendConfirmationButton component). Officer chia sẻ URL
    manual qua Zalo/SMS tới candidate.
    """
    message: str
    action: Literal["submit", "resubmit", "withdraw"]
    token_expires_at: datetime
    sent_to_email: Optional[str] = Field(
        None,
        description="Lead email (informational — KHÔNG auto-email cho Wave 7 MVP)",
    )
    phone: Optional[str] = Field(
        None,
        description="Lead phone (informational — officer manual share)",
    )
    token_value: Optional[str] = Field(
        None,
        description="Token value cho copy thủ công nếu cần",
    )
    magic_link_url: Optional[str] = Field(
        None,
        description=(
            "Full magic-link URL (FRONTEND_URL + /magic-link/{action}/{token}). "
            "FE landing pages tại PR #280 đã ship — candidate click link → "
            "nhập CCCD → BE consume + apply action atomic."
        ),
    )


class SendConfirmationResponse(BaseModel):
    """Response after sending confirmation link."""
    message: str
    token_expires_at: datetime
    sent_to_email: Optional[str] = None
    # Canonical field: lead's phone number. The API does NOT send SMS today —
    # this is just data the officer can use to reach out. See
    # project_send_confirmation_ops_gaps for rationale on the rename.
    phone: Optional[str] = Field(
        None,
        description="Lead's phone number (informational — system does not send SMS)",
    )
    token_value: Optional[str] = Field(
        None,
        description="Token value for admin/officer to share confirmation link manually",
    )
    confirm_url: Optional[str] = Field(
        None,
        description=(
            "Full confirmation URL (FRONTEND_URL + /confirm/{token}). "
            "Prefer this over composing the link manually from `token_value`."
        ),
    )


class AdmissionStatusCounts(BaseModel):
    """Status counts for tab badges. From GET /admissions/status-counts."""
    counts: Dict[str, int]
    total: int


class AdmissionStats(BaseModel):
    """Aggregate statistics. From GET /admissions/stats."""
    total_profiles: int = 0
    draft_count: int = 0
    submitted_count: int = 0
    approved_count: int = 0
    enrolled_count: int = 0
    rejected_count: int = 0
    dropped_count: int = 0
    withdrawn_count: int = 0
    withdrawal_pending_count: int = 0
    conversion_rate: float = 0.0
    avg_completion: float = 0.0


# =============================================================================
# Phase 3 PR-3C Sub-3 — Choice-engine endpoint schemas
# =============================================================================


class _PerChoiceDecision(BaseModel):
    """Per-choice decision row inside `AdmissionPublishResultResponse`."""

    choice_id: int
    display_order: int
    decision: Literal["pending", "admitted", "waitlisted", "rejected", "skip"]
    reasons: List[str] = Field(default_factory=list)
    score: Optional[float] = None


class AdmissionPublishResultResponse(BaseModel):
    """T6 publish-result endpoint response — wraps `CascadeResult`.

    Returned by `POST /api/v2/admissions/{id}/publish-result` after the
    choice-engine cascade evaluates all profile.choices in display_order
    and transitions profile.status to admitted/rejected.
    """

    profile_id: int
    final_status: Literal["admitted", "rejected", "waitlisted"]
    admitted_choice_id: Optional[int] = None
    admitted_display_order: Optional[int] = None
    per_choice_decisions: List[_PerChoiceDecision] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AdmissionWaitlistPromoteRequest(BaseModel):
    """T10 waitlist-promote endpoint request body.

    DRIFT-01: Sub-3.4 route shipped là profile-scoped (Casbin canonical
    `/api/v2/admissions/{profile_id}/waitlist-promote`), NOT choice-scoped
    admin namespace per stale Plan v0.7 line 437. `choice_id` moves from
    URL param vào request body — service verifies ownership.

    `reason` optional cho audit context (transition() reason kwarg passes
    into status_history.transition_reason).
    """

    choice_id: int = Field(..., gt=0, description="ID nguyện vọng promote từ waitlist")
    reason: Optional[str] = Field(
        None,
        min_length=10,
        max_length=500,
        description="Optional audit reason (status_history.transition_reason)",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionWaitlistPromoteResponse(BaseModel):
    """T10 waitlist-promote endpoint response.

    Returned by `POST /api/v2/admissions/{profile_id}/waitlist-promote`
    after admin promotes a waitlisted choice → admitted.
    """

    choice_id: int
    decision: Literal["admitted"] = "admitted"
    profile_id: int
    profile_status: Literal["admitted"] = "admitted"


class AdmissionWaitlistRejectRequest(BaseModel):
    """T11 waitlist-reject endpoint request body (Wave 5 ship 2026-05-16).

    Manager/admin manually finalize candidate dự bị → trượt khi đợt
    closes + slot không mở. Mirror semantic của AdmissionWaitlistPromote
    nhưng `reason` REQUIRED (negative decision needs audit context per
    memory `phase3-pr-3d-b-backlog` "DELETE audit + reason").
    """

    choice_id: int = Field(..., gt=0, description="ID nguyện vọng reject từ waitlist")
    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Lý do reject (audit) — required min 10 chars",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionWaitlistRejectResponse(BaseModel):
    """T11 waitlist-reject endpoint response.

    Returned by `POST /api/v2/admissions/{profile_id}/waitlist-reject`
    after admin/manager finalizes a waitlisted choice → rejected.
    """

    choice_id: int
    decision: Literal["rejected"] = "rejected"
    profile_id: int
    # P1 fix 2026-05-22: trước đây có dòng duplicate `profile_status: Literal["admitted"]`
    # ngay sau dòng "rejected" → Python class body lấy cái cuối thành Literal["admitted"].
    # Service trả "rejected" → Pydantic ValidationError → 500 SAU db.commit() → mutation
    # thành công ở DB nhưng client thấy lỗi. Verified bằng runtime probe trong container.
    profile_status: Literal["rejected"] = "rejected"


class AdmissionAdminRollbackRequest(BaseModel):
    """T17 admin-rollback endpoint request body.

    Reason is mandatory + min 10 chars for audit trail. The reason flows
    into `AdmissionProfileStatusHistory.transition_reason` + dispatch
    payload of `ADMISSION_ROLLED_BACK`.
    """

    reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Mandatory rollback reason (audit log + dispatch payload)",
    )

    model_config = ConfigDict(str_strip_whitespace=True)


class AdmissionAdminRollbackResponse(BaseModel):
    """T17 admin-rollback endpoint response."""

    profile_id: int
    status: Literal["draft"] = "draft"
    rolled_back_from: str  # The status the profile was in BEFORE rollback
    already_at_target: bool = False  # W9-J.7.idem 2026-05-16: True when no-op (profile already draft)


# =============================================================================
# Q9 #07 Phase D — Live KV preview (draft state, no snapshot save)
# =============================================================================


class PreviewPriorityKvRequest(BaseModel):
    """Optional form overrides for live KV+UT preview. NULL fields fall back to profile current state.

    Used by candidate FE PriorityTab + AcademicHistoryTab + UtEvidenceCard
    to compute both KV (khu vực) + UT (đối tượng) potential bonus real-time
    as user edits form, BEFORE submit (T1) freezes snapshot.

    All fields optional — endpoint can be called with empty body to
    resolve from profile state-as-is.
    """

    cultural_education_level: Optional[str] = Field(None)
    vocational_qualification: Optional[str] = Field(None)
    area_resolution_basis: Optional[str] = Field(None)
    permanent_commune_code: Optional[str] = Field(None, max_length=20)
    academic_history: Optional[List[AcademicRecordSchema]] = Field(None)
    # Phase E wireframe — UT live preview support
    priority_object_codes: Optional[List[str]] = Field(
        None,
        description="UT sub_codes (vd ['04', '06']) overrided cho preview. Engine returns MAX bonus assuming all verified."
    )

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")


class PreviewPriorityKvResponse(BaseModel):
    """Engine resolve_kv_for_profile() + UT potential bonus result for FE preview.

    Mirror of internal engine return tuple `(kv, meta)` + extends với UT
    potential bonus (Phase E wireframe). KV is None when engine cannot
    resolve. `requires_manual_override=True` signals officer/admin must intervene.

    UT semantics for preview:
    - `object_bonus_potential` = MAX rate across submitted codes assuming ALL verified
    - `object_bonus_verified`  = MAX rate restricted to codes có status='verified'
      (= what engine T6 cascade actually counts). Pending evidence excluded.
    - Candidate UI shows "potential" với badge ⏳ if pending; officer flow
      verifies → moves to verified bucket. Mỗi diện hiển thị individual status.
    """

    # --- KV (existing Phase D) ---
    kv_resolved: Optional[str] = Field(None, description="KV1 | KV2-NT | KV2 | KV3, or None")
    pathway: Optional[str] = Field(None)
    rule_applied: Optional[str] = Field(None)
    requires_manual_override: bool = Field(False)
    reason: Optional[str] = Field(None)
    breakdown: Optional[dict] = Field(None)
    # Wire contract: Decimal → string by default trên Pydantic v2 json mode
    # (jsonable_encoder).  FE expects number (Zod z.number() + .toFixed()).
    # Schema field types là `float` để Pydantic auto-coerce Decimal → float
    # serialize as JSON number. BE engine vẫn dùng Decimal internal — chỉ
    # response shape thay đổi.
    area_bonus: Optional[float] = Field(None, description="KV bonus điểm (rate * 1.0)")

    # --- UT (Phase E wireframe extension) ---
    object_bonus_potential: Optional[float] = Field(
        None,
        description="MAX UT bonus assuming all submitted codes verified — preview only"
    )
    object_bonus_verified: Optional[float] = Field(
        None,
        description="MAX UT bonus restricted to verified codes — engine T6 actual"
    )
    ut_breakdown: Optional[dict] = Field(
        None,
        description="{ codes_submitted: [...], applied_code_potential: '04', applied_rate_potential: 1.00, verified_codes: ['04'], applied_code_verified: '04', applied_rate_verified: 1.00 }"
    )

    # --- Combined total ---
    total_bonus_potential: Optional[float] = Field(
        None,
        description="area_bonus + object_bonus_potential — candidate-facing total"
    )

    # Q9 #07 Phase E.4 — law citation cho FE hiển thị trong EngineResultCard.
    # Resolve qua services.priority_service.resolve_law_citation(rule_applied).
    # None khi rule_applied không match map (vd ambiguous_requires_manual).
    rule_law_citation: Optional[str] = Field(
        None,
        description=(
            "Citation pháp lý (vd 'TT 05/2021 Phụ lục 01 Mục 5.b') resolved "
            "từ rule_applied. FE EngineResultCard hiển thị để officer scan/trust."
        )
    )

    # Code review 2026-05-22 — path_bonus_rule denorm trong preview để FE
    # hiển thị cap consistent giữa draft preview và frozen snapshot. Trước
    # đây UX inconsistency: draft show "+3.50đ", sau submit cap về "+2.50đ".
    # Shape match snapshot.path_bonus_rule (priority_service.py:856).
    path_bonus_rule: Optional[dict] = Field(
        None,
        description=(
            "Path's bonus cap rule {'max_total_bonus': float|None}. FE PrioritySummaryPanel "
            "đọc để hiển thị cap badge + applied_bonus = min(total, cap) trong draft."
        )
    )

    model_config = ConfigDict(from_attributes=True)


class PriorityObjectCatalogItem(BaseModel):
    """One UT (đối tượng ưu tiên) code from `priority_object_config` table.

    Returned by `GET /api/v2/admissions/priority-objects/catalog?academic_year=`
    — candidate-facing catalog cho UT picker trong PriorityTab.

    Mirrors PriorityObjectConfigResponse shape (admin CRUD endpoint) but
    excludes admin-only metadata (created_at/updated_at).
    """

    group_code: str = Field(..., description="UT1 | UT2 | UT3+")
    sub_code: str = Field(..., description="2-digit numeric, vd '01'..'07'")
    description: str = Field(..., description="VD 'Anh hùng LLVTND, Anh hùng lao động'")
    # Wire contract: float (not Decimal) — Pydantic auto-coerce DB Decimal
    # → float for JSON number output. FE Zod expects z.number(). See
    # PreviewPriorityKvResponse note above for rationale.
    bonus_points: float = Field(..., description="Bonus rate cho diện này (vd 2.00 cho UT01)")
    evidence_doc_type: Optional[str] = Field(None, description="Gợi ý loại minh chứng (vd 'Quyết định phong tặng')")

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# Q9 #07 Phase E.2 + E.4 commit 7 — Manual KV override
# (admin/manager write-path; officer hard-denied per nghiệp vụ #10)
# =============================================================================


class OverridePriorityKvRequest(BaseModel):
    """Admin/manager override KV manually trên profile.

    Phase E.4 commit 7 hardening: officer KHÔNG được override KV. Casbin
    migration q9_07_e4f đã remove role:officer policy row; service-layer
    raises BusinessRuleViolation cho actor.role=="officer".

    Service-layer (priority_override_service.override_kv) enforces:
    * Optimistic-lock via ``version`` body field (memory
      `version-guard-before-state-machine` — version guard runs FIRST,
      before status whitelist).
    * Role gate: officer DENIED unconditionally; manager + admin allowed.
    * Status whitelist:
        - admin: any state (UI shows button; dialog handles post-publish ack)
        - manager: submitted/reviewing/revision_requested + draft (engine
          signal required, service verifies live recompute)
        - withdrawn/dropped/rejected hard-deny (all roles)
        - post-publish states require admin + ``acknowledge_post_publish=True``
    * Reason 20-500 char text (mandatory; persisted in
      ``profile.priority_resolution_snapshot.manual_override_reason``
      + ``priority_audit_log.new_value.reason``).
    * INSERT ``priority_audit_log`` row (action_type='kv_manual_override').
    * Bump ``profile.version`` after mutation.

    Snapshot keys written (overwritten on each override per Decision D1):
    * ``manual_override_by`` — actor.id
    * ``manual_override_at`` — ISO timestamp
    * ``manual_override_reason`` — user-supplied
    * ``evidence_file_id`` — optional FK soft reference
    * ``frozen_at`` / ``frozen_at_status='manual_override'`` /
      ``resolved_by``  — refreshed each override.

    Chain-of-override history queryable via composite index
    ``idx_priority_audit_log_profile_action_time`` on
    ``(profile_id, action_type, created_at DESC)``.
    """

    version: int = Field(
        ...,
        description="Client-known profile.version for optimistic lock. "
        "409 ConflictError if mismatch with DB state.",
        ge=0,
    )
    kv_resolved: Literal["KV1", "KV2-NT", "KV2", "KV3"] = Field(
        ...,
        description="New KV code to assign manually.",
    )
    reason: str = Field(
        ...,
        min_length=20,
        max_length=500,
        description="Justification 20-500 char. Persisted to snapshot + audit log.",
    )
    evidence_file_id: Optional[int] = Field(
        None,
        description="Optional FK to supporting document (soft reference, no FK constraint).",
    )
    acknowledge_post_publish: bool = Field(
        False,
        description="Admin-only escape hatch for post-publish profile (enrolled/approved/confirmed/...). "
        "Officer always refused for those states.",
    )

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# =============================================================================
# Q9 #07 Phase E.3 — UT evidence verify/reject (officer write-path)
# =============================================================================


class VerifyObjectEvidenceRequest(BaseModel):
    """Officer verifies one UT evidence (Phase E.3).

    Marks ``priority_object_evidence[sub_code]`` as ``status='verified'``
    + optional ``document_id`` reference. Per Decision D3 — candidate
    uploads via DocumentsTab; officer picks document tại verify time.

    Snapshot ``ut_verified_bucket`` recomputes after each verify (engine
    T6 actual rate freeze: MAX bonus_points across verified codes).
    """

    version: int = Field(
        ...,
        description="Client-known profile.version for optimistic lock.",
        ge=0,
    )
    document_id: Optional[int] = Field(
        None,
        description="Optional FK soft reference to supporting document.",
    )
    # Phase E.4 hotfix 3 (smoke 2026-05-21): post-publish guard. Officer/
    # manager refused outright (403) on approved/confirmed/enrolled/
    # result_published/admitted/waitlisted. Admin must opt in with this
    # flag — mirrors KV override OverridePriorityKvRequest.
    acknowledge_post_publish: bool = Field(
        default=False,
        description=(
            "Admin-only escape hatch for verifying UT on a profile already "
            "in a post-publish state. Officer/manager refused regardless. "
            "Audit log records the flag."
        ),
    )

    model_config = ConfigDict(extra="forbid")


class RejectObjectEvidenceRequest(BaseModel):
    """Officer rejects one UT evidence với reason (Phase E.3).

    Marks ``priority_object_evidence[sub_code]`` as ``status='rejected'``
    + ``reject_reason``. If rejected code was the applied verified code,
    ``ut_verified_bucket`` recomputes to next-highest verified or null.
    """

    version: int = Field(
        ...,
        description="Client-known profile.version for optimistic lock.",
        ge=0,
    )
    reject_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Reason for rejection (10-500 chars).",
    )
    # Phase E.4 hotfix 3 — same post-publish gate as verify above.
    acknowledge_post_publish: bool = Field(
        default=False,
        description=(
            "Admin-only escape hatch for rejecting UT on a profile already "
            "in a post-publish state. Officer/manager refused regardless. "
            "Audit log records the flag."
        ),
    )

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class UntickPriorityEvidenceRequest(BaseModel):
    """Officer unticks UT code + cascade hard delete evidence (Phase E.4 G1).

    Decision #4 UI guard: FE shows confirm dialog BEFORE call. Service-layer
    assumes caller already confirmed (no double-prompt). Hard delete cascades:
    JSONB cleanup + DELETE profile_document row + INSERT priority_audit_log
    + S3 file unlink post-commit (ADM-007 finalize callback).

    Soft delete (30d retention) defer Phase E.5 nếu officer report mất giấy.
    """

    version: int = Field(
        ...,
        description="Client-known profile.version for optimistic lock.",
        ge=0,
    )

    model_config = ConfigDict(extra="forbid")


__all__ = [
    # Nested schemas
    "FamilyMemberSchema",
    "AcademicRecordSchema",
    "AdmissionScoreSchema",
    "DocumentItemSchema",
    # AdmissionProfile schemas
    "AdmissionProfileCreate",
    "AdmissionProfileUpdate",
    "AdmissionProfileResponse",
    "AdmissionSubmitResponse",
    "EnrollStudentResponse",
    # State transition schemas
    "ClaimRequest",  # ✅ Added
    "DocumentFormatVerifyRequest",  # ✅ Added
    "ApproveRequest",
    "RejectRequest",
    "RevisionRequest",
    "ResubmitRequest",
    "DropStudentRequest",
    "ConfirmRequest",
    "OverrideRequest",
    "WithdrawRequest",
    "FinalizeRequest",
    # Student schemas
    "StudentDocumentResponse",
    "StudentResponse",
    "DocumentUploadResponse",
    # Confirmation token schemas (Magic Link)
    "ConfirmTokenVerifyRequest",
    "ConfirmTokenResponse",
    "ConfirmTokenInfoResponse",
    "SendConfirmationResponse",
    "SendMagicLinkRequest",
    "SendMagicLinkResponse",
    # Aggregate schemas
    "AdmissionStatusCounts",
    "AdmissionStats",
    # Phase 3 PR-3C Sub-3 — choice-engine endpoints
    "AdmissionPublishResultResponse",
    "AdmissionWaitlistPromoteRequest",
    "AdmissionWaitlistPromoteResponse",
    "AdmissionWaitlistRejectRequest",
    "AdmissionWaitlistRejectResponse",
    "AdmissionAdminRollbackRequest",
    "AdmissionAdminRollbackResponse",
    # Q9 #07 Phase D — Live KV preview
    "PreviewPriorityKvRequest",
    "PreviewPriorityKvResponse",
    "PriorityObjectCatalogItem",
    # Q9 #07 Phase E.2 — Manual KV override
    "OverridePriorityKvRequest",
    # Q9 #07 Phase E.3 — UT evidence verify/reject
    "VerifyObjectEvidenceRequest",
    "RejectObjectEvidenceRequest",
    # Q9 #07 Phase E.4 — Priority evidence schemas (PR-1 + PR-2)
    "PriorityObjectEvidenceDisplayEntry",
    "PriorityEvidenceDocumentItem",
    "UntickPriorityEvidenceRequest",
]
