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

from app.core.deps import (
    get_current_active_user,
    get_criteria_access,
    get_config_filter,
    get_admission_config_repo,
    verify_criteria_visibility,
    require_admin_or_manager,
)
from app.models.admission_config.criteria import AdmissionCriteria
from app.database import get_db
from app.schemas.organization import ConfigDegreeLevel
from app.models import User
from app.repositories.admission_config_repository import AdmissionConfigRepository
from app.services.admission_scoring_service import AdmissionScoringService
from app.services.admission_config_service import AdmissionConfigService
from app.services import config_service
from app.schemas.admission_config import (
    SubjectResponse,
    SubjectListResponse,
    SubjectCreate,
    SubjectUpdate,
    SubjectGroupResponse,
    SubjectInGroupResponse,
    SubjectGroupListResponse,
    SubjectGroupCreate,
    SubjectGroupUpdate,
    AdmissionMethodResponse,
    AdmissionMethodListResponse,
    AdmissionMethodCreate,
    AdmissionMethodUpdate,
    AdmissionCriteriaResponse,
    AdmissionCriteriaListResponse,
    AdmissionCriteriaCreate,
    AdmissionCriteriaUpdate,
    ScoringPreviewRequest,
    ScoringPreviewResponse,
    SharedDocumentGroupResponse,
    SharedDocumentGroupUpdate,
    DocumentGroupItemResponse,
)

router = APIRouter(prefix="/admission-config", tags=["Admission Config"])


# =============================================================================
# DEGREE LEVELS (Public read-only - accessible to all authenticated staff)
# =============================================================================

@router.get("/degree-levels", response_model=list[ConfigDegreeLevel])
async def list_degree_levels(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Get degree levels. Accessible to all authenticated staff (not admin-only).
    Used by admission filters dropdown.
    """
    return await config_service.get_degree_levels(db, active_only)


# =============================================================================
# SUBJECTS
# =============================================================================

@router.get("/subjects", response_model=SubjectListResponse)
async def get_subjects(
    active_only: bool = Depends(get_config_filter),
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
):
    """Get all subjects."""
    subjects = await repo.get_subjects(active_only=active_only)
    
    return SubjectListResponse(
        subjects=[SubjectResponse.model_validate(s) for s in subjects],
        total=len(subjects)
    )


@router.get("/subjects/{code}", response_model=SubjectResponse)
async def get_subject_by_code(
    code: str,
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
    # current_user unused
):
    """Get subject by code."""
    subject = await repo.get_subject_by_code(code)
    
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject '{code}' not found"
        )
    
    return SubjectResponse.model_validate(subject)


# =============================================================================
# SUBJECT CRUD (Admin Only)
# =============================================================================

@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED)
async def create_subject(
    data: SubjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Create new subject. Requires: Admin or Manager role."""
    service = AdmissionConfigService(db)
    subject, callback = await service.create_subject(data, current_user)
    await db.commit()
    await callback()
    return SubjectResponse.model_validate(subject)


@router.put("/subjects/{subject_id}", response_model=SubjectResponse)
async def update_subject(
    subject_id: int,
    data: SubjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Update existing subject. Requires: Admin or Manager role."""
    repo = AdmissionConfigRepository(db)
    subject = await repo.get_subject_by_id(subject_id)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject with ID {subject_id} not found"
        )
    
    service = AdmissionConfigService(db)
    updated, callback = await service.update_subject(subject, data, current_user)
    await db.commit()
    await callback()
    return SubjectResponse.model_validate(updated)


@router.delete("/subjects/{subject_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject(
    subject_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Delete subject. Requires: Admin or Manager role."""
    service = AdmissionConfigService(db)
    _, callback = await service.delete_subject(subject_id, current_user)
    await db.commit()
    await callback()
    return None


# =============================================================================
# SUBJECT GROUPS
# =============================================================================

@router.get("/subject-groups", response_model=SubjectGroupListResponse)
async def get_subject_groups(
    active_only: bool = Depends(get_config_filter),
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
):
    """Get all subject groups with their subjects."""
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
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
):
    """Get subject group by code with subjects."""
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
# SUBJECT GROUP CRUD (Admin Only)
# =============================================================================

def _build_subject_group_response(group) -> SubjectGroupResponse:
    """Helper to build SubjectGroupResponse from ORM model."""
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


@router.post("/subject-groups", response_model=SubjectGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_subject_group(
    data: SubjectGroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Create new subject group. Requires: Admin or Manager role."""
    service = AdmissionConfigService(db)
    group, callback = await service.create_subject_group(data, current_user)
    await db.commit()
    await callback()
    
    # Reload with subjects for response
    repo = AdmissionConfigRepository(db)
    group = await repo.get_subject_group_by_id(group.id, with_subjects=True)
    return _build_subject_group_response(group)


@router.put("/subject-groups/{group_id}", response_model=SubjectGroupResponse)
async def update_subject_group(
    group_id: int,
    data: SubjectGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Update existing subject group. Requires: Admin or Manager role."""
    repo = AdmissionConfigRepository(db)
    group = await repo.get_subject_group_by_id(group_id, with_subjects=True)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subject group with ID {group_id} not found"
        )
    
    service = AdmissionConfigService(db)
    updated, callback = await service.update_subject_group(group, data, current_user)
    await db.commit()
    await callback()
    
    # Reload with subjects
    updated = await repo.get_subject_group_by_id(group_id, with_subjects=True)
    return _build_subject_group_response(updated)


@router.delete("/subject-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subject_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Delete subject group. Requires: Admin or Manager role."""
    service = AdmissionConfigService(db)
    _, callback = await service.delete_subject_group(group_id, current_user)
    await db.commit()
    await callback()
    return None


# =============================================================================
# ADMISSION METHODS
# =============================================================================

@router.get("/methods", response_model=AdmissionMethodListResponse)
async def get_admission_methods(
    active_only: bool = Depends(get_config_filter),
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
):
    """Get all admission methods."""
    methods = await repo.get_admission_methods(active_only=active_only)
    
    return AdmissionMethodListResponse(
        methods=[AdmissionMethodResponse.model_validate(m) for m in methods],
        total=len(methods)
    )


@router.get("/methods/{code}", response_model=AdmissionMethodResponse)
async def get_method_by_code(
    code: str,
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
    # current_user unused
):
    """Get admission method by code."""
    method = await repo.get_method_by_code(code)
    
    if not method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Method '{code}' not found"
        )
    
    return AdmissionMethodResponse.model_validate(method)


# =============================================================================
# ADMISSION METHOD CRUD (Admin Only)
# =============================================================================

@router.post("/methods", response_model=AdmissionMethodResponse, status_code=status.HTTP_201_CREATED)
async def create_method(
    data: AdmissionMethodCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Create new admission method.
    
    Requires: Admin or Manager role.
    """
    service = AdmissionConfigService(db)
    method, callback = await service.create_method(data, current_user)
    await db.commit()
    await callback()
    
    return AdmissionMethodResponse.model_validate(method)


@router.put("/methods/{method_id}", response_model=AdmissionMethodResponse)
async def update_method(
    method_id: int,
    data: AdmissionMethodUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Update existing admission method.
    
    Requires: Admin or Manager role.
    """
    repo = AdmissionConfigRepository(db)
    method = await repo.get_method_by_id(method_id)
    if not method:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Method with ID {method_id} not found"
        )
    
    service = AdmissionConfigService(db)
    updated, callback = await service.update_method(method, data, current_user)
    await db.commit()
    await callback()
    
    return AdmissionMethodResponse.model_validate(updated)


@router.delete("/methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_method(
    method_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Delete admission method.
    
    Requires: Admin or Manager role.
    """
    service = AdmissionConfigService(db)
    _, callback = await service.delete_method(method_id, current_user)
    await db.commit()
    await callback()
    return None


# =============================================================================
# ADMISSION CRITERIA
# =============================================================================

@router.get("/criteria", response_model=AdmissionCriteriaListResponse)
async def get_all_criteria(
    method_code: Optional[str] = None,
    active_only: bool = Depends(get_config_filter),
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
):
    """Get all admission criteria, optionally filtered by method."""
    
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
    # ✅ FIX: Use Dependency Injection for Authz (Repo + Logic)
    # This automatically handles fetching AND 404/403 (IDOR protection)
    criteria: AdmissionCriteria = Depends(get_criteria_access),
):
    """
    Get single criteria by code.
    
    Security:
    - Public: Can only view ACTIVE criteria (enforced by Dependency)
    - Admin: Can view INACTIVE (draft) criteria (enforced by Dependency)
    """
    # Criteria is already fetched and authorized by dependency
    c = criteria
    
    # Reload with full groups (Dependency uses 'with_groups' by default but let's be safe)
    # Actually dependency returns model directly. If we need more data we might need to lazy load or fetch again?
    # The dependency loaded "with_groups" so we are good.

    
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
# ADMISSION CRITERIA CRUD
# =============================================================================

@router.post("/criteria", response_model=AdmissionCriteriaResponse, status_code=201)
async def create_criteria(
    data: AdmissionCriteriaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Create new admission criteria.
    
    Requires: Admin or Manager role.
    """
    service = AdmissionConfigService(db)
    criteria, callback = await service.create_criteria(data, current_user)
    await db.commit()
    await callback()
    
    # Reload with relationships
    repo = AdmissionConfigRepository(db)
    criteria = await repo.get_criteria_by_id(criteria.id, load_level="with_groups")
    
    allowed_groups = [m.subject_group.code for m in criteria.subject_group_mappings]
    
    return AdmissionCriteriaResponse(
        id=criteria.id,
        code=criteria.code,
        name=criteria.name,
        method_code=criteria.method.code if criteria.method else None,
        method_name=criteria.method.name if criteria.method else None,
        min_gpa=criteria.min_gpa,
        min_score=criteria.min_score,
        required_subject_count=criteria.required_subject_count,
        subject_selection_mode=criteria.subject_selection_mode,
        scoring_method=criteria.scoring_method,
        max_possible_score=criteria.max_possible_score,
        min_subject_score=criteria.min_subject_score,
        conditions=criteria.conditions,
        is_active=criteria.is_active,
        allowed_subject_groups=allowed_groups,
    )


@router.put("/criteria/{criteria_id}", response_model=AdmissionCriteriaResponse)
async def update_criteria(
    criteria_id: int,
    data: AdmissionCriteriaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Update existing admission criteria.
    
    Requires: Admin or Manager role.
    """
    repo = AdmissionConfigRepository(db)
    criteria = await repo.get_criteria_by_id(criteria_id, load_level="with_groups")
    
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Criteria with ID {criteria_id} not found"
        )
    
    service = AdmissionConfigService(db)
    criteria, callback = await service.update_criteria(criteria, data, current_user)
    await db.commit()
    await callback()
    
    # Reload with relationships
    criteria = await repo.get_criteria_by_id(criteria.id, load_level="with_groups")
    allowed_groups = [m.subject_group.code for m in criteria.subject_group_mappings]
    
    return AdmissionCriteriaResponse(
        id=criteria.id,
        code=criteria.code,
        name=criteria.name,
        method_code=criteria.method.code if criteria.method else None,
        method_name=criteria.method.name if criteria.method else None,
        min_gpa=criteria.min_gpa,
        min_score=criteria.min_score,
        required_subject_count=criteria.required_subject_count,
        subject_selection_mode=criteria.subject_selection_mode,
        scoring_method=criteria.scoring_method,
        max_possible_score=criteria.max_possible_score,
        min_subject_score=criteria.min_subject_score,
        conditions=criteria.conditions,
        is_active=criteria.is_active,
        allowed_subject_groups=allowed_groups,
    )


@router.delete("/criteria/{criteria_id}", status_code=204)
async def delete_criteria(
    criteria_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Delete admission criteria.
    
    Requires: Admin or Manager role.
    """
    repo = AdmissionConfigRepository(db)
    criteria = await repo.get_criteria_by_id(criteria_id, load_level="light")
    
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Criteria with ID {criteria_id} not found"
        )
    
    service = AdmissionConfigService(db)
    success, callback = await service.delete_criteria(criteria, current_user)
    await db.commit()
    await callback()
    
    return None


# =============================================================================
# SCORING PREVIEW
# =============================================================================

@router.post("/scoring/preview", response_model=ScoringPreviewResponse)
async def preview_scoring(
    request: ScoringPreviewRequest,
    repo: AdmissionConfigRepository = Depends(get_admission_config_repo),
    current_user: User = Depends(get_current_active_user),
):
    """
    Preview admission scoring without saving.
    
    Use this to test score calculation before profile submission.
    Returns pass/fail, scores, and transparency metadata.
    """
    
    # Get criteria (need full depth for scoring)
    # ✅ FIX: Manual check because input is in Body (can't use Path dependency)
    criteria = await repo.get_criteria_by_code(
        request.criteria_code,
        load_level="full"
    )
    
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Criteria '{request.criteria_code}' not found"
        )

    # ✅ Phase 6.5: Use shared helper for visibility check (AUTHORIZATION_GUIDELINES compliant)
    verify_criteria_visibility(criteria, current_user, request.criteria_code)
    
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


# =============================================================================
# SHARED DOCUMENT GROUPS (Phase 1)
# =============================================================================

def _build_doc_group_response(group) -> Optional[SharedDocumentGroupResponse]:
    if not group:
        return None
        
    items = []
    # Sort items by display_order
    # Note: selectinload already orders by display_order if defined in relationship, 
    # but we double check sort here just in case.
    sorted_items = sorted(group.items, key=lambda x: x.display_order)
    
    for item in sorted_items:
        items.append(DocumentGroupItemResponse(
            id=item.id,
            document_type_id=item.document_type_id,
            document_type_name=item.document_type.name, # Eager loaded
            is_mandatory=item.is_mandatory,
            requires_upload=item.requires_upload,
            submission_format=item.submission_format,
            display_order=item.display_order,
        ))
        
    return SharedDocumentGroupResponse(
        id=group.id,
        offering_type_id=group.offering_type_id,
        code=group.code,
        name=group.name,
        items=items
    )


@router.get("/document-groups/shared/{offering_type_id}", response_model=Optional[SharedDocumentGroupResponse])
async def get_shared_document_group(
    offering_type_id: int,
    db: AsyncSession = Depends(get_db),
    # Read access allowed for all
):
    """
    Get shared document group configuration for an Offering Type.
    """
    service = AdmissionConfigService(db)
    group = await service.get_shared_document_group(offering_type_id)
    
    if not group:
        return None
        
    return _build_doc_group_response(group)


@router.put("/document-groups/shared/{offering_type_id}", response_model=SharedDocumentGroupResponse)
async def upsert_shared_document_group(
    offering_type_id: int,
    data: SharedDocumentGroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """
    Create or Update shared document group configuration.
    Requires: Admin or Manager role.
    """
    service = AdmissionConfigService(db)
    group, callback = await service.upsert_shared_document_group(offering_type_id, data, current_user)
    await db.commit()
    await callback()
    
    return _build_doc_group_response(group)

