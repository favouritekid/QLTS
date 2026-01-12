# app/schemas/admission_config.py
"""
Admission Config Schemas.

Pydantic schemas for API responses.
"""

from decimal import Decimal
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


# =============================================================================
# SUBJECT SCHEMAS
# =============================================================================

class SubjectResponse(BaseModel):
    """Subject response schema."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name_vi: str
    display_order: int
    is_active: bool


class SubjectListResponse(BaseModel):
    """List of subjects."""
    subjects: list[SubjectResponse]
    total: int


# =============================================================================
# SUBJECT GROUP SCHEMAS
# =============================================================================

class SubjectInGroupResponse(BaseModel):
    """Subject within a group."""
    model_config = ConfigDict(from_attributes=True)
    
    code: str
    name_vi: str
    position: int


class SubjectGroupResponse(BaseModel):
    """Subject group response schema."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    display_order: int
    is_active: bool
    subjects: list[SubjectInGroupResponse] = []


class SubjectGroupListResponse(BaseModel):
    """List of subject groups."""
    groups: list[SubjectGroupResponse]
    total: int


# =============================================================================
# ADMISSION METHOD SCHEMAS
# =============================================================================

class AdmissionMethodResponse(BaseModel):
    """Admission method response schema."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    description: Optional[str] = None
    requires_gpa: bool
    requires_subject_scores: bool
    display_order: int
    is_active: bool


class AdmissionMethodListResponse(BaseModel):
    """List of admission methods."""
    methods: list[AdmissionMethodResponse]
    total: int


# =============================================================================
# ADMISSION CRITERIA SCHEMAS
# =============================================================================

class AdmissionCriteriaResponse(BaseModel):
    """Admission criteria response schema."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    method_code: Optional[str] = None
    method_name: Optional[str] = None
    
    # Thresholds
    min_gpa: Optional[Decimal] = None
    min_score: Optional[Decimal] = None
    
    # Rule Engine config
    required_subject_count: Optional[int] = None
    subject_selection_mode: str = "fixed"
    scoring_method: str = "sum"
    max_possible_score: Optional[Decimal] = None
    min_subject_score: Optional[Decimal] = None
    
    # Meta
    conditions: Optional[str] = None
    is_active: bool = True
    
    # Related subject groups
    allowed_subject_groups: list[str] = []


class AdmissionCriteriaListResponse(BaseModel):
    """List of admission criteria."""
    criteria: list[AdmissionCriteriaResponse]
    total: int


class AdmissionCriteriaCreate(BaseModel):
    """Request schema for creating admission criteria."""
    method_code: str  # Lookup by code instead of ID
    code: str
    name: str
    
    # Thresholds (at least one required)
    min_gpa: Optional[Decimal] = None
    min_score: Optional[Decimal] = None
    
    # Rule Engine config
    required_subject_count: Optional[int] = None
    subject_selection_mode: Optional[str] = "fixed"
    scoring_method: Optional[str] = "sum"
    max_possible_score: Optional[Decimal] = None
    min_subject_score: Optional[Decimal] = None
    
    # Meta
    conditions: Optional[str] = None
    is_active: Optional[bool] = False  # Draft by default
    policy_version: Optional[str] = "2025.1"
    
    # Subject groups to link
    subject_group_ids: Optional[list[int]] = None


class AdmissionCriteriaUpdate(BaseModel):
    """Request schema for updating admission criteria."""
    name: Optional[str] = None
    
    # Thresholds
    min_gpa: Optional[Decimal] = None
    min_score: Optional[Decimal] = None
    
    # Rule Engine config
    required_subject_count: Optional[int] = None
    subject_selection_mode: Optional[str] = None
    scoring_method: Optional[str] = None
    max_possible_score: Optional[Decimal] = None
    min_subject_score: Optional[Decimal] = None
    
    # Meta
    conditions: Optional[str] = None
    is_active: Optional[bool] = None
    policy_version: Optional[str] = None
    
    # Subject groups (replace all)
    subject_group_ids: Optional[list[int]] = None


# =============================================================================
# SCORING PREVIEW SCHEMAS
# =============================================================================

class ScoringPreviewRequest(BaseModel):
    """Request for scoring preview."""
    criteria_code: str
    subject_group_code: Optional[str] = None
    subject_scores: dict[str, float]  # code -> score


class ScoringPreviewResponse(BaseModel):
    """Response from scoring preview."""
    # Profile status (VALID / INVALID)
    status: str = "valid"  # valid | invalid
    passed: bool
    
    # CRITICAL: None if profile is INVALID
    final_score: Optional[float] = None
    
    # Details
    selected_subjects: list[str]
    subject_scores: dict[str, float]
    
    # Transparency metadata (for UX)
    input_subject_count: int = 0
    used_subject_count: int = 0
    ignored_subjects: list[str] = []
    
    # Rule info
    criteria_code: str
    selection_mode: str
    scoring_method: str
    required_count: Optional[int] = None
    
    # Thresholds
    min_score_threshold: Optional[float] = None
    min_subject_score_threshold: Optional[float] = None
    
    # Validation failures
    failure_reasons: list[str] = []
    disqualification_codes: list[str] = []  # Standardized codes
    
    # Snapshot (for reference)
    snapshot: Optional[dict] = None

