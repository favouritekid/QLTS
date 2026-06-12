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
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Path as PathParam
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.constants import UserRole
from app.core.deps import (
    get_current_active_user,
    get_optional_profile_cultural_for_audience,
    check_permission,
    require_admin,
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
    AdmissionAudience,
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

    if hasattr(criteria, "subject_group_mappings") and criteria.subject_group_mappings:
        for mapping in criteria.subject_group_mappings:
            if mapping.subject_group:
                subject_groups.append(
                    SubjectGroupNested(
                        id=mapping.subject_group.id,
                        code=mapping.subject_group.code,
                        name=mapping.subject_group.name,
                    )
                )

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


async def build_path_response(
    path: models.AdmissionPath,
    service: AdmissionPathService,
    current_user: models.User,
    *,
    include_validation_errors: bool = False,
) -> AdmissionPathResponse:
    """Build AdmissionPathResponse with role-aware control fields.

    ADM-021: the FE reads ``available_actions`` / ``can_*`` directly, so
    these fields must mirror route/service authorization gates.
    """
    response = AdmissionPathResponse.model_validate(path)
    response.criteria = build_criteria_nested(path)
    # Round contract hardening (plan v4 Section D — Finding #3): populate
    # flat round metadata from the eager-loaded ``admission_round``
    # relationship. ``__dict__.get`` avoids triggering a lazy load
    # (MissingGreenlet in async context) when a query didn't eager-load the
    # relationship — the flat fields then stay None (schema default).
    _round = path.__dict__.get("admission_round")
    if _round is not None:
        response.round_code = _round.round_code
        response.round_name = _round.round_name
        response.round_start_date = _round.start_date
        response.round_end_date = _round.end_date
        response.round_archived_at = _round.archived_at
        response.round_is_active = _round.is_active
        response.round_allow_multi_nv = _round.allow_multi_nv
    # Trình độ + tên ngành (FE phân biệt CĐ/TC trong dropdown nguyện vọng).
    # ``__dict__.get`` tránh lazy load (MissingGreenlet) khi chain chưa eager-load
    # — flat field stay None. degree_level là column trên MajorProgram nên load
    # cùng ``program`` (không trigger lazy thêm).
    _ai = path.__dict__.get("academic_info")
    _offering = _ai.__dict__.get("offering") if _ai is not None else None
    _program = _offering.__dict__.get("program") if _offering is not None else None
    if _program is not None:
        response.degree_level = getattr(_program, "degree_level", None)
        response.major_name = getattr(_program, "name", None)
    response.available_actions = service.compute_available_actions(path, current_user)
    response.can_edit = service.compute_can_edit(path, current_user)
    response.can_activate = await service.compute_can_activate(path, current_user)
    response.can_edit_governance = service.compute_can_edit_governance(
        path, current_user
    )
    if include_validation_errors:
        _, errors = await service.validate_activation(path)
        response.validation_errors = errors
    return response


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
    "/years", response_model=AcademicYearListResponse, summary="Get all academic years"
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
    return AcademicYearListResponse(years=years, current_year=current_year)


@router.get(
    "/coverage-matrix",
    response_model=CoverageMatrixResponse,
    summary="Get coverage matrix for paths",
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
    summary="Get active paths for an offering (public)",
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
    service = AdmissionPathService(db)
    items = []
    for path in paths:
        items.append(await build_path_response(path, service, current_user))

    return AdmissionPathListResponse(total=len(items), items=items)


@router.get(
    "/paths/{path_id}/subject-group-configs",
    summary="Get subject-group configs of a path (multi-NV AddChoiceDialog)",
)
async def list_path_subject_group_configs(
    path_id: int = PathParam(..., description="Admission path ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """List subject-group configs (tổ hợp môn) thuộc 1 path.

    Phase 3 multi-NV AddChoiceDialog: candidate/officer chọn tổ hợp sau
    khi pick path → fetch list configs → render dropdown 6 sg_config.
    Eager-load subject_group + items + subject so FE render đầy đủ tên +
    môn cho user choice.

    Mirror admin endpoint ``/api/v2/admin/admission-paths/{id}/
    subject-group-configs`` nhưng allow officer+ (non-admin) cho add-choice
    flow. Read-only — không mutation.
    """
    from app.repositories.path_subject_group_repository import (
        PathSubjectGroupRepository,
    )
    repo = PathSubjectGroupRepository(db)
    configs = await repo.list_configs_by_path_with_subjects(path_id)

    items = []
    for c in configs:
        sg = c.subject_group
        subjects = []
        if sg is not None and sg.subject_mappings:
            for mapping in sorted(
                sg.subject_mappings, key=lambda m: getattr(m, "position", 0) or 0
            ):
                s = mapping.subject
                if s is None:
                    continue
                subjects.append({
                    "subject_id": s.id,
                    "subject_code": s.code,
                    "subject_name": s.name_vi,
                    "max_score": float(s.max_score) if s.max_score is not None else 10.0,
                    "min_possible_score": (
                        float(s.min_possible_score)
                        if s.min_possible_score is not None
                        else 0.0
                    ),
                    "position": getattr(mapping, "position", 0) or 0,
                })
        items.append({
            "id": c.id,
            "admission_path_id": c.admission_path_id,
            "subject_group_id": c.subject_group_id,
            "subject_group_code": getattr(sg, "code", None) if sg else None,
            "subject_group_name": getattr(sg, "name", None) if sg else None,
            "min_score": float(c.min_score) if c.min_score is not None else None,
            "min_subject_score": (
                float(c.min_subject_score) if c.min_subject_score is not None else None
            ),
            "group_quota": c.group_quota,
            "subjects": subjects,
        })

    return {"total": len(items), "items": items}


@router.get(
    "/paths/by-round/{round_id}",
    response_model=AdmissionPathListResponse,
    summary="Get active paths in a round (multi-NV AddChoiceDialog)",
)
async def get_paths_by_round(
    round_id: int = PathParam(..., description="Admission round ID"),
    # IDOR-scoped: dependency đọc query ``profile_id`` + scope theo hồ sơ
    # officer được phép xem, trả cultural_education_level (hoặc None khi không
    # truyền / chưa khai). 404 fake nếu profile_id ngoài phạm vi.
    cultural: Optional[str] = Depends(get_optional_profile_cultural_for_audience),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """List ACTIVE admission paths trong 1 round.

    Phase 3 multi-NV AddChoiceDialog: officer+/manager+/admin chọn
    ngành+method để thêm NV mới trong cùng đợt đang xét.
    Cross-academic_info (different majors); FE filter thêm theo path đã
    có trong choices nếu cần.

    Security: authenticated user (Officer+). Magic-link candidate flow
    KHÔNG dùng endpoint này (no auth context); candidate-side AddChoice
    via `/api/v2/admissions/{id}/choices` POST direct. BE precheck
    (uses_choice_engine, allow_multi_nv, max_choices) áp dụng tại POST.
    """
    service = AdmissionPathService(db)
    paths, callback = await service.list_active_paths_by_round(
        round_id, cultural=cultural
    )
    # Read-only endpoint — KHÔNG cần db.commit() (nit fix #8)
    await callback()

    items = []
    for path in paths:
        items.append(await build_path_response(path, service, current_user))

    return AdmissionPathListResponse(total=len(items), items=items)


@router.get(
    "/paths", response_model=AdmissionPathListResponse, summary="List admission paths"
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
        items.append(await build_path_response(path, service, current_user))

    return AdmissionPathListResponse(total=len(items), items=items)


@router.post(
    "/paths",
    response_model=AdmissionPathResponse,
    status_code=201,
    summary="Create admission path",
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

    return await build_path_response(path, service, current_user)


@router.get(
    "/paths/{path_id}",
    response_model=AdmissionPathResponse,
    summary="Get admission path by ID",
)
async def get_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Get a single admission path by ID.

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)

    return await build_path_response(
        path,
        service,
        current_user,
        include_validation_errors=True,
    )


@router.put(
    "/paths/{path_id}",
    response_model=AdmissionPathResponse,
    summary="Update admission path",
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

    return await build_path_response(path, service, current_user)


@router.put(
    "/paths/{path_id}/criteria",
    response_model=AdmissionPathResponse,
    summary="Update admission criteria",
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

    return await build_path_response(path, service, current_user)


@router.put(
    "/paths/{path_id}/documents",
    response_model=ResolvedDocumentListResponse,
    summary="Update document requirements",
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
    resolved_docs, callback = await service.upsert_documents(
        path, documents, current_user
    )
    await db.commit()
    await callback()

    # Need offering_type_id for response
    offering_type_id = path.academic_info.offering.offering_type_id

    return ResolvedDocumentListResponse(
        path_id=path.id,
        offering_type_id=offering_type_id,
        admission_method_id=path.admission_method_id,
        documents=resolved_docs,
    )


# =============================================================================
# ACTIVATION ENDPOINTS
# =============================================================================


@router.post(
    "/paths/{path_id}/activate",
    response_model=AdmissionPathResponse,
    summary="Activate admission path (admin-only)",
)
async def activate_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),  # ADM-008: admin-only per Q3=a
):
    """
    Activate an admission path.

    **Authorization (ADM-008 / Q3=a):** Admin only. Manager can create/edit
    draft paths but cannot activate or deactivate — Admin "approves =
    activates". Manager attempting this route gets 403 from
    ``require_admin``.

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

    return await build_path_response(path, service, current_user)


@router.post(
    "/paths/{path_id}/deactivate",
    response_model=AdmissionPathResponse,
    summary="Deactivate admission path (admin-only)",
)
async def deactivate_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),  # ADM-008: admin-only per Q3=a
):
    """
    Deactivate an active admission path.

    **Authorization (ADM-008 / Q3=a):** Admin only. Symmetric to activate —
    once a path goes live, only Admin may take it back down.

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)
    path, callback = await service.deactivate_path(path, current_user)
    await db.commit()
    await callback()

    # Reload
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)

    return await build_path_response(path, service, current_user)


@router.post(
    "/paths/{path_id}/archive",
    response_model=AdmissionPathResponse,
    summary="Archive admission path (admin-only)",
)
async def archive_admission_path(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),  # ADM-008 admin-only
):
    """
    Archive (soft-delete) a ``draft`` or ``inactive`` admission path →
    ``archived``.

    **Authorization (ADM-008 / Q3=a):** Admin only — symmetric to
    activate/deactivate; service re-checks as defense-in-depth.

    Lets admin retire an unused draft/inactive path through the API instead
    of raw SQL. Active paths return 400 (deactivate first); already-archived
    return 400. Archived is terminal — ``_check_lifecycle_guard`` blocks
    edits and ``activate_path`` rejects re-activation.

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    service = AdmissionPathService(db)
    path, callback = await service.archive_path(path, current_user)
    await db.commit()
    await callback()

    # Reload
    path = await AdmissionPathRepository(db).get_by_id_with_relations(path.id)

    return await build_path_response(path, service, current_user)


# =============================================================================
# DOCUMENT RESOLUTION ENDPOINTS
# =============================================================================


@router.get(
    "/paths/{path_id}/documents",
    response_model=ResolvedDocumentListResponse,
    summary="Get resolved documents for path",
)
async def get_resolved_documents(
    audience: Optional[AdmissionAudience] = Query(
        None,
        description=(
            "Lọc bộ hồ sơ theo 1 diện thí sinh (POST_THPT, POST_THCS,...). "
            "Bỏ trống → trả TẤT CẢ lớp (NỀN + mọi audience) cho view admin "
            "(không co lại sau backfill audience)."
        ),
    ),
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get resolved document requirements for a path.

    3-tier override (path > method > shared). feat audience: trong tier shared,
    ``?audience=`` lọc lớp theo diện thí sinh; bỏ trống → ALL layers (round-6 G2:
    admin thấy đủ bộ, không co lại sau backfill audience).

    IDOR: Protected via get_admission_path_for_user dependency.
    """
    # Get offering_type_id from path
    offering_type_id = path.academic_info.offering.offering_type_id

    service = AdmissionPathService(db)
    if audience is None:
        documents, callback = await service.resolve_documents_for_path(
            path, offering_type_id, all_audiences=True
        )
    else:
        documents, callback = await service.resolve_documents_for_path(
            path, offering_type_id, audience_set={audience}
        )
    await db.commit()
    await callback()

    return ResolvedDocumentListResponse(
        path_id=path.id,
        offering_type_id=offering_type_id,
        admission_method_id=path.admission_method_id,
        documents=documents,
    )


@router.get(
    "/paths/{path_id}/validate-activation",
    response_model=ActivationValidationResponse,
    summary="Validate if path can be activated",
)
async def validate_path_activation(
    path: models.AdmissionPath = Depends(get_admission_path_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Check if a path can be activated.

    Returns:
        can_activate: bool
        validation_errors: List of reasons if blocked
    """
    service = AdmissionPathService(db)
    can_activate, errors = await service.validate_activation(path)
    if current_user.role != UserRole.ADMIN:
        can_activate = False
        errors = [
            "Chỉ admin được activate admission path.",
            *errors,
        ]

    return ActivationValidationResponse(
        can_activate=can_activate, validation_errors=errors
    )
