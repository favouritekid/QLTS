# app/routers/admission_paths.py
"""
Admission Paths Router.

REST API endpoints for AdmissionPath management.

MASTER_ARCHITECTURE.md Compliance:
- No business logic in router
- All deps via Depends()
- response_model on every endpoint
- db.commit() in router, not service
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, Query, Path as PathParam
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.constants import UserRole
from app.core.deps import (
    get_current_active_user,
    check_permission,
    require_admin_or_manager,
)
from app.schemas.admission_path import (
    AdmissionPathCreate,
    AdmissionPathUpdate,
    AdmissionCriteriaCreate,
    AdmissionPathDocumentUpsert,
    AdmissionPathResponse,
    AdmissionPathListResponse,
    AcademicYearListResponse,
    ResolvedDocumentListResponse,
    ActivationValidationResponse,
    AdmissionCriteriaNested,
    SubjectGroupNested,
    CoverageMatrixResponse,
)
from app.services.admission_path_service import AdmissionPathService
from app.repositories.admission_path_repository import AdmissionPathRepository
from app.utils.exceptions import ResourceNotFoundError

router = APIRouter(prefix="/admission-config", tags=["Admission Configuration"])


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def build_criteria_nested(path) -> AdmissionCriteriaNested | None:
    """
    Build AdmissionCriteriaNested from ORM model.
    
    Extracts subject_groups from the relation chain:
    AdmissionPath.criteria.subject_group_mappings[].subject_group
    """
    if not path.criteria:
        return None
    
    criteria = path.criteria
    subject_groups = []
    
    if hasattr(criteria, 'subject_group_mappings') and criteria.subject_group_mappings:
        for mapping in criteria.subject_group_mappings:
            if mapping.subject_group:
                subject_groups.append(SubjectGroupNested(
                    id=mapping.subject_group.id,
                    code=mapping.subject_group.code,
                    name=mapping.subject_group.name,
                ))
    
    return AdmissionCriteriaNested(
        id=criteria.id,
        code=criteria.code,
        name=criteria.name,
        min_gpa=criteria.min_gpa,
        min_score=criteria.min_score,
        min_subject_score=criteria.min_subject_score,
        max_possible_score=criteria.max_possible_score,
        conditions=criteria.conditions,
        required_subject_count=criteria.required_subject_count,
        subject_selection_mode=criteria.subject_selection_mode or "fixed",
        scoring_method=criteria.scoring_method or "sum",
        subject_groups=subject_groups,
    )


# =============================================================================
# IDOR DEPENDENCY (inline for now, can move to deps.py later)
# =============================================================================

async def get_admission_path_for_user(
    path_id: int = PathParam(..., description="Admission Path ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.AdmissionPath:
    """
    IDOR protection for AdmissionPath.
    
    Security:
    - Admin/Manager: Full access
    - Returns 404 for unauthorized (not 403) per AUTHORIZATION_GUIDELINES
    """
    repo = AdmissionPathRepository(db)
    path = await repo.get_by_id_with_relations(path_id)
    
    if not path:
        raise ResourceNotFoundError(f"Admission path {path_id} not found")
    
    # Admin/Manager have full access (for config console)
    if current_user.role in [UserRole.ADMIN, UserRole.MANAGER]:
        return path
    
    # For other roles, return 404 (IDOR protection)
    raise ResourceNotFoundError(f"Admission path {path_id} not found")


# =============================================================================
# ACADEMIC YEAR ENDPOINTS
# =============================================================================

@router.get(
    "/years",
    response_model=AcademicYearListResponse,
    summary="Get all academic years"
)
async def get_academic_years(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Get all distinct academic years from the system.
    
    Returns:
        List of years sorted DESC, plus current year
    """
    service = AdmissionPathService(db)
    years, callback = await service.get_distinct_years()
    await db.commit()
    await callback()
    
    current_year = datetime.now().year
    return AcademicYearListResponse(
        years=years,
        current_year=current_year
    )


@router.get(
    "/coverage-matrix",
    response_model=CoverageMatrixResponse,
    summary="Get coverage matrix for paths"
)
async def get_coverage_matrix(
    academic_info_id: int = Query(..., description="Academic Info ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(check_permission),
):
    """
    Get coverage matrix showing readiness status of all paths.
    
    Used by Config Console to audit path configuration before activation.
    
    Returns:
        Matrix with has_criteria, has_documents, has_quota, can_activate per path.
    """
    service = AdmissionPathService(db)
    result, callback = await service.get_coverage_matrix(academic_info_id)
    await db.commit()
    await callback()
    
    return result


# =============================================================================
# ADMISSION PATH CRUD ENDPOINTS
# =============================================================================

@router.get(
    "/paths/for-offering/{offering_id}",
    response_model=AdmissionPathListResponse,
    summary="Get active paths for an offering (public)"
)
async def get_paths_for_offering(
    offering_id: int = PathParam(..., description="Program Offering ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Get all ACTIVE admission paths for a ProgramOffering.
    
    Used by LeadApplicationForm to populate "Phương thức xét tuyển" dropdown.
    Returns paths with nested admission_method and criteria.
    
    Security: Requires authenticated user (Officer+)
    """
    repo = AdmissionPathRepository(db)
    paths = await repo.get_active_paths_by_offering_id(offering_id)
    
    # Build response with nested criteria (GAP-D fix for LeadApplicationForm)
    items = []
    for path in paths:
        response = AdmissionPathResponse.model_validate(path)
        response.criteria = build_criteria_nested(path)
        items.append(response)
    
    return AdmissionPathListResponse(total=len(items), items=items)

@router.get(
    "/paths",
    response_model=AdmissionPathListResponse,
    summary="List admission paths"
)
async def list_admission_paths(
    academic_info_id: int = Query(..., description="Filter by academic info ID"),
    status: str = Query(None, description="Filter by status"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(check_permission),
):
    """
    List all admission paths for a specific academic info (offering + year).
    
    Requires: Admin or Manager role (via Casbin)
    """
    service = AdmissionPathService(db)
    paths, callback = await service.list_paths_by_academic_info(academic_info_id)
    await db.commit()
    await callback()
    
    # Compute control fields for each path
    items = []
    for path in paths:
        response = AdmissionPathResponse.model_validate(path)
        response.criteria = build_criteria_nested(path)  # GAP-D fix
        response.available_actions = service.compute_available_actions(path)
        response.can_edit = service.compute_can_edit(path)
        response.can_activate = await service.compute_can_activate(path)
        items.append(response)
    
    return AdmissionPathListResponse(total=len(items), items=items)


@router.post(
    "/paths",
    response_model=AdmissionPathResponse,
    status_code=201,
    summary="Create admission path"
)
async def create_admission_path(
    data: AdmissionPathCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Create a new admission path (draft status).

    Requires: Admin or Manager role
    """
    service = AdmissionPathService(db)
    path, callback = await service.create_path(data, current_user)
    await db.commit()
    await callback()

    # Reload with relationships
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)

    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)  # Include criteria (will be None for new paths)
    response.available_actions = service.compute_available_actions(path)
    response.can_edit = service.compute_can_edit(path)
    response.can_activate = await service.compute_can_activate(path)

    return response


@router.get(
    "/paths/{path_id}",
    response_model=AdmissionPathResponse,
    summary="Get admission path by ID"
)
async def get_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get a single admission path by ID.

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)

    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)  # Include criteria with subject groups
    response.available_actions = service.compute_available_actions(path)
    response.can_edit = service.compute_can_edit(path)
    response.can_activate = await service.compute_can_activate(path)
    can_activate, errors = await service.validate_activation(path)
    response.validation_errors = errors

    return response


@router.put(
    "/paths/{path_id}",
    response_model=AdmissionPathResponse,
    summary="Update admission path"
)
async def update_admission_path(
    data: AdmissionPathUpdate,
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Update an admission path.

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)
    path, callback = await service.update_path(path, data, current_user)
    await db.commit()
    await callback()

    # Reload
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)

    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)  # Include criteria with subject groups
    response.available_actions = service.compute_available_actions(path)
    response.can_edit = service.compute_can_edit(path)
    response.can_activate = await service.compute_can_activate(path)

    return response


@router.put(
    "/paths/{path_id}/criteria",
    response_model=AdmissionPathResponse,
    summary="Update admission criteria"
)
async def update_admission_criteria(
    data: AdmissionCriteriaCreate,
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Update Admission Criteria (GPA, Scores, Subject Groups).
    """
    import structlog
    logger = structlog.get_logger()
    logger.info("Updating criteria", path_id=path.id, data=data.model_dump())

    service = AdmissionPathService(db)
    path, callback = await service.upsert_criteria(path, data, current_user)
    await db.commit()
    await callback()
    
    # Reload
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)
    
    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)
    response.available_actions = service.compute_available_actions(path)
    response.can_edit = service.compute_can_edit(path)
    response.can_activate = await service.compute_can_activate(path)
    
    return response


@router.put(
    "/paths/{path_id}/documents",
    response_model=ResolvedDocumentListResponse,
    summary="Update document requirements"
)
async def update_admission_documents(
    documents: List[AdmissionPathDocumentUpsert],
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Update Document Requirements (Checklist).
    
    Overrides default document group for this Method + Offering Type.
    """
    service = AdmissionPathService(db)
    resolved_docs, callback = await service.upsert_documents(path, documents, current_user)
    await db.commit()
    await callback()
    
    # Need offering_type_id for response
    offering_type_id = path.academic_info.offering.offering_type_id
    
    return ResolvedDocumentListResponse(
        path_id=path.id,
        offering_type_id=offering_type_id,
        admission_method_id=path.admission_method_id,
        documents=resolved_docs
    )


# =============================================================================
# ACTIVATION ENDPOINTS
# =============================================================================

@router.post(
    "/paths/{path_id}/activate",
    response_model=AdmissionPathResponse,
    summary="Activate admission path"
)
async def activate_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Activate an admission path.

    Validation:
    - Must have criteria
    - Must have document config
    - Must have quota > 0

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)
    path, callback = await service.activate_path(path, current_user)
    await db.commit()
    await callback()

    # Reload
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)

    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)  # Include criteria with subject groups
    response.available_actions = service.compute_available_actions(path)
    response.can_edit = service.compute_can_edit(path)
    response.can_activate = False  # Already activated

    return response


@router.post(
    "/paths/{path_id}/deactivate",
    response_model=AdmissionPathResponse,
    summary="Deactivate admission path"
)
async def deactivate_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Deactivate an active admission path.

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)
    path, callback = await service.deactivate_path(path, current_user)
    await db.commit()
    await callback()

    # Reload
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)

    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)  # Include criteria with subject groups
    response.available_actions = service.compute_available_actions(path)
    response.can_edit = service.compute_can_edit(path)
    response.can_activate = await service.compute_can_activate(path)

    return response


# =============================================================================
# DOCUMENT RESOLUTION ENDPOINTS
# =============================================================================

@router.get(
    "/paths/{path_id}/documents",
    response_model=ResolvedDocumentListResponse,
    summary="Get resolved documents for path"
)
async def get_resolved_documents(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get resolved document requirements for a path.

    Override Rule:
    - Shared docs (method_id = NULL) apply to all methods
    - Method-specific docs override shared

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    # Get offering_type_id from path
    offering_type_id = path.academic_info.offering.offering_type_id

    service = AdmissionPathService(db)
    documents, callback = await service.resolve_documents_for_path(path, offering_type_id)
    await db.commit()
    await callback()

    return ResolvedDocumentListResponse(
        path_id=path.id,
        offering_type_id=offering_type_id,
        admission_method_id=path.admission_method_id,
        documents=documents
    )


@router.get(
    "/paths/{path_id}/validate-activation",
    response_model=ActivationValidationResponse,
    summary="Validate if path can be activated"
)
async def validate_path_activation(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Check if a path can be activated.
    
    Returns:
        can_activate: bool
        validation_errors: List of reasons if blocked
    """
    service = AdmissionPathService(db)
    can_activate, errors = await service.validate_activation(path)
    
    return ActivationValidationResponse(
        can_activate=can_activate,
        validation_errors=errors
    )
