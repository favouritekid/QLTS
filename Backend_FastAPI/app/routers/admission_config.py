# app/routers/admission_config.py
"""
Admission Config Router.

Endpoints for admission configuration data.
Read-only access to subjects, groups, methods, criteria.
Scoring preview endpoint for testing.
"""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import User
from app.repositories.admission_config_repository import AdmissionConfigRepository
from app.services.admission_scoring_service import AdmissionScoringService
from app.schemas.admission_config import (
    SubjectResponse,
    SubjectListResponse,
    SubjectGroupResponse,
    SubjectInGroupResponse,
    SubjectGroupListResponse,
    AdmissionMethodResponse,
    AdmissionMethodListResponse,
    AdmissionCriteriaResponse,
    AdmissionCriteriaListResponse,
    ScoringPreviewRequest,
    ScoringPreviewResponse,
)

router = APIRouter(prefix="/admission-config", tags=["Admission Config"])


# =============================================================================
# SUBJECTS
# =============================================================================

@router.get("/subjects", response_model=SubjectListResponse)
async def get_subjects(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get all subjects."""
    repo = AdmissionConfigRepository(db)
    subjects = await repo.get_subjects(active_only=active_only)
    
    return SubjectListResponse(
        subjects=[SubjectResponse.model_validate(s) for s in subjects],
        total=len(subjects)
    )


@router.get("/subjects/{code}", response_model=SubjectResponse)
async def get_subject_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get subject by code."""
    repo = AdmissionConfigRepository(db)
    subject = await repo.get_subject_by_code(code)
    
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject '{code}' not found"
        )
    
    return SubjectResponse.model_validate(subject)


# =============================================================================
# SUBJECT GROUPS
# =============================================================================

@router.get("/subject-groups", response_model=SubjectGroupListResponse)
async def get_subject_groups(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get all subject groups with their subjects."""
    repo = AdmissionConfigRepository(db)
    groups = await repo.get_subject_groups(with_subjects=True, active_only=active_only)
    
    response_groups = []
    for group in groups:
        subjects = []
        for mapping in sorted(group.subject_mappings, key=lambda m: m.position):
            subjects.append(SubjectInGroupResponse(
                code=mapping.subject.code,
                name_vi=mapping.subject.name_vi,
                position=mapping.position,
            ))
        
        response_groups.append(SubjectGroupResponse(
            id=group.id,
            code=group.code,
            name=group.name,
            display_order=group.display_order,
            is_active=group.is_active,
            subjects=subjects,
        ))
    
    return SubjectGroupListResponse(
        groups=response_groups,
        total=len(response_groups)
    )


@router.get("/subject-groups/{code}", response_model=SubjectGroupResponse)
async def get_subject_group_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get subject group by code with subjects."""
    repo = AdmissionConfigRepository(db)
    group = await repo.get_subject_group_by_code(code, with_subjects=True)
    
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject group '{code}' not found"
        )
    
    subjects = []
    for mapping in sorted(group.subject_mappings, key=lambda m: m.position):
        subjects.append(SubjectInGroupResponse(
            code=mapping.subject.code,
            name_vi=mapping.subject.name_vi,
            position=mapping.position,
        ))
    
    return SubjectGroupResponse(
        id=group.id,
        code=group.code,
        name=group.name,
        display_order=group.display_order,
        is_active=group.is_active,
        subjects=subjects,
    )


# =============================================================================
# ADMISSION METHODS
# =============================================================================

@router.get("/methods", response_model=AdmissionMethodListResponse)
async def get_admission_methods(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get all admission methods."""
    repo = AdmissionConfigRepository(db)
    methods = await repo.get_admission_methods(active_only=active_only)
    
    return AdmissionMethodListResponse(
        methods=[AdmissionMethodResponse.model_validate(m) for m in methods],
        total=len(methods)
    )


@router.get("/methods/{code}", response_model=AdmissionMethodResponse)
async def get_method_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get admission method by code."""
    repo = AdmissionConfigRepository(db)
    method = await repo.get_method_by_code(code)
    
    if not method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Method '{code}' not found"
        )
    
    return AdmissionMethodResponse.model_validate(method)


# =============================================================================
# ADMISSION CRITERIA
# =============================================================================

@router.get("/criteria", response_model=AdmissionCriteriaListResponse)
async def get_all_criteria(
    method_code: Optional[str] = None,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get all admission criteria, optionally filtered by method."""
    repo = AdmissionConfigRepository(db)
    
    if method_code:
        criteria_list = await repo.get_criteria_by_method(
            method_code=method_code,
            active_only=active_only,
            load_level="with_groups"
        )
    else:
        criteria_list = await repo.get_all_criteria(
            active_only=active_only,
            load_level="light"
        )
    
    response_criteria = []
    for c in criteria_list:
        # Get allowed subject groups
        allowed_groups = []
        if hasattr(c, 'subject_group_mappings'):
            allowed_groups = [m.subject_group.code for m in c.subject_group_mappings]
        
        response_criteria.append(AdmissionCriteriaResponse(
            id=c.id,
            code=c.code,
            name=c.name,
            method_code=c.method.code if c.method else None,
            method_name=c.method.name if c.method else None,
            min_gpa=c.min_gpa,
            min_score=c.min_score,
            required_subject_count=c.required_subject_count,
            subject_selection_mode=c.subject_selection_mode,
            scoring_method=c.scoring_method,
            max_possible_score=c.max_possible_score,
            min_subject_score=c.min_subject_score,
            conditions=c.conditions,
            is_active=c.is_active,
            allowed_subject_groups=allowed_groups,
        ))
    
    return AdmissionCriteriaListResponse(
        criteria=response_criteria,
        total=len(response_criteria)
    )


@router.get("/criteria/{code}", response_model=AdmissionCriteriaResponse)
async def get_criteria_by_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Get single criteria by code."""
    repo = AdmissionConfigRepository(db)
    c = await repo.get_criteria_by_code(code, load_level="with_groups")
    
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Criteria '{code}' not found"
        )
    
    allowed_groups = [m.subject_group.code for m in c.subject_group_mappings]
    
    return AdmissionCriteriaResponse(
        id=c.id,
        code=c.code,
        name=c.name,
        method_code=c.method.code if c.method else None,
        method_name=c.method.name if c.method else None,
        min_gpa=c.min_gpa,
        min_score=c.min_score,
        required_subject_count=c.required_subject_count,
        subject_selection_mode=c.subject_selection_mode,
        scoring_method=c.scoring_method,
        max_possible_score=c.max_possible_score,
        min_subject_score=c.min_subject_score,
        conditions=c.conditions,
        is_active=c.is_active,
        allowed_subject_groups=allowed_groups,
    )


# =============================================================================
# SCORING PREVIEW
# =============================================================================

@router.post("/scoring/preview", response_model=ScoringPreviewResponse)
async def preview_scoring(
    request: ScoringPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Preview admission scoring without saving.
    
    Use this to test score calculation before profile submission.
    Returns pass/fail, scores, and transparency metadata.
    """
    repo = AdmissionConfigRepository(db)
    
    # Get criteria (need full depth for scoring)
    criteria = await repo.get_criteria_by_code(
        request.criteria_code,
        load_level="full"
    )
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Criteria '{request.criteria_code}' not found"
        )
    
    # Get subject group (optional)
    subject_group = None
    if request.subject_group_code:
        subject_group = await repo.get_subject_group_by_code(
            request.subject_group_code,
            with_subjects=True
        )
        if not subject_group:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subject group '{request.subject_group_code}' not found"
            )
    
    # ✅ REFACTORED: Delegate subject resolution to Service (not router)
    resolution = AdmissionScoringService.resolve_allowed_subjects(
        criteria=criteria,
        subject_group=subject_group,
    )
    
    # Convert scores to Decimal
    subject_scores = {
        code: Decimal(str(score))
        for code, score in request.subject_scores.items()
    }
    
    # Calculate score
    result = AdmissionScoringService.calculate_score(
        criteria=criteria,
        subject_scores=subject_scores,
        allowed_subjects=resolution.allowed_subjects,
    )
    
    # Generate snapshot with policy version
    snapshot = AdmissionScoringService.generate_snapshot(
        criteria=criteria,
        subject_group=subject_group,
        allowed_subjects=resolution.allowed_subjects,
        input_scores=subject_scores,
        score_result=result,
        policy_version="2025.1",  # TODO: Get from criteria or config
    )
    
    return ScoringPreviewResponse(
        # Profile status
        status=result.status.value,
        passed=result.passed,
        final_score=float(result.final_score) if result.final_score else None,  # None if INVALID
        # Details
        selected_subjects=result.selected_subjects,
        subject_scores={k: float(v) for k, v in result.subject_scores.items()},
        input_subject_count=result.input_subject_count,
        used_subject_count=result.used_subject_count,
        ignored_subjects=result.ignored_subjects,
        # Rule info
        criteria_code=result.criteria_code,
        selection_mode=result.selection_mode,
        scoring_method=result.scoring_method,
        required_count=result.required_count,
        min_score_threshold=float(result.min_score_threshold) if result.min_score_threshold else None,
        min_subject_score_threshold=float(result.min_subject_score_threshold) if result.min_subject_score_threshold else None,
        # Validation
        failure_reasons=result.failure_reasons,
        disqualification_codes=result.disqualification_codes,
        snapshot=snapshot,
    )

