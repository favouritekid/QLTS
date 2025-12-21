# app/routers/admin/config.py
"""
Configuration Management Admin Router

Handles all system configuration operations including:
- Assignment Config (lead distribution settings per unit)
- Skill Rules (skill-based assignment rules)

PHASE 2B: Extracted from monolithic admin.py
Dependencies: config_service (from PHASE 1)

Complexity: LOW (simple CRUD operations)
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

from typing import List

import structlog
from fastapi import (
    APIRouter,
    Depends,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core import deps
from app.core.constants import UserRole
from app.services import config_service

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - Config"])

# Permission dependency
PermissionDep = Depends(deps.check_permission)


# ============================================================================
# ASSIGNMENT CONFIG MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
)
async def get_assignment_config_route(
    request: Request,
    unit: models.OrganizationUnit = Depends(deps.get_organizational_unit_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin/Manager) Get assignment config for an organizational unit.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to managed units
    - ✓ IDOR Protection: Enabled

    **Access Levels:**
    - **Admin**: Can access all units
    - **Manager**: Can only access units they manage
    """
    params = await config_service.get_assignment_config(db, unit.id)
    return {"params": params}


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
)
async def update_assignment_config_route(
    request: Request,
    config_in: schemas.AssignmentConfig,
    unit: models.OrganizationUnit = Depends(deps.get_organizational_unit_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin/Manager) Update assignment config for an organizational unit.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to managed units
    - ✓ IDOR Protection: Enabled

    **Access Levels:**
    - **Admin**: Can update all units
    - **Manager**: Can only update units they manage

    **Business Rules:**
    - Assignment config controls officer distribution settings per unit
    - Changes affect future lead assignments only (not existing assignments)
    """
    updated_model, post_commit = await config_service.update_assignment_config(
        db, unit.id, config_in.params
    )
    await db.commit()
    await post_commit()
    # Trả về schema Pydantic dựa trên model đã cập nhật từ DB
    return schemas.AssignmentConfig(params=updated_model.params)


# ============================================================================
# SKILL RULES MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/skill-rules",
    response_model=List[schemas.SkillRule],
)
async def get_all_skill_rules_route(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy tất cả các quy tắc kỹ năng."""
    return await config_service.get_all_skill_rules(db)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/skill-rules",
    response_model=schemas.SkillRule,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_skill_rule_route(
    request: Request,
    rule_in: schemas.SkillRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một quy tắc kỹ năng mới."""
    rule, callback = await config_service.create_skill_rule(db, rule_in)
    await db.commit()
    await callback()
    return rule


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/skill-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill_rule_route(
    request: Request,
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xoá một quy tắc kỹ năng."""
    _, callback = await config_service.delete_skill_rule(db, rule_id)
    await db.commit()
    await callback()
    return None


# ============================================================================
# OFFERING DISTRIBUTION STATS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get("/distribution/{offering_id}/stats")
async def get_distribution_stats(
    request: Request,
    offering_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Get distribution statistics for a Program Offering.

    Shows current round-robin cursor position, active distribution configs,
    and which unit will receive the next lead for this offering.

    **Returns:**
    ```json
    {
        "offering_id": 5,
        "cursor_value": 42,
        "configs": [
            {
                "unit_id": 10,
                "unit_name": "Phòng Tuyển Sinh A",
                "weight": 3,
                "priority": 1,
                "slots_in_cycle": 3
            },
            {
                "unit_id": 20,
                "unit_name": "Phòng Tuyển Sinh B",
                "weight": 1,
                "priority": 1,
                "slots_in_cycle": 1
            }
        ],
        "total_slots": 4,
        "next_unit_id": 10
    }
    ```

    **Use Cases:**
    - Monitor distribution fairness
    - Debug distribution issues
    - Analytics and reporting
    - Reset cursor if needed (separate endpoint)
    """
    from app.services import distribution_service

    stats = await distribution_service.get_distribution_stats(db, offering_id)
    return stats


# ============================================================================
# DISTRIBUTION RULES MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/distribution-rules",
    response_model=List[schemas.DistributionRuleResponse],
)
async def list_distribution_rules(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin/Manager) List distribution rules.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - Admin: Returns all distribution rules
    - Manager: Returns only rules in managed units

    Returns distribution rules ordered by priority (highest first).
    """
    # Admin gets all rules
    if current_admin.role == UserRole.ADMIN:
        return await config_service.get_all_distribution_rules(db)

    # Manager gets rules in their managed units only
    managed_units = await deps.get_user_managed_units(db, current_admin.id)
    return await config_service.get_distribution_rules_by_units(db, managed_units)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/distribution-rules",
    response_model=schemas.DistributionRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution_rule(
    request: Request,
    rule_in: schemas.DistributionRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Create a new distribution rule.

    **Validation:**
    - offering_id must exist
    - unit_id must exist
    - Duplicate (offering_id + unit_id) is not allowed

    **Example:**
    ```json
    {
        "offering_id": 5,
        "unit_id": 10,
        "weight": 3,
        "priority": 1,
        "is_active": true
    }
    ```
    """
    return await config_service.create_distribution_rule(db, rule_in)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/distribution-rules/{rule_id}",
    response_model=schemas.DistributionRuleResponse,
)
async def update_distribution_rule(
    request: Request,
    rule_in: schemas.DistributionRuleUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    rule: models.OfferingDistributionConfig = deps.DistributionRuleAccessDep,
):
    """
    (Admin/Manager) Update a distribution rule.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to managed units
    - ✓ IDOR Protection: Enabled

    Only provided fields will be updated (partial update).

    **Example:**
    ```json
    {
        "is_active": false
    }
    ```
    """
    return await config_service.update_distribution_rule(db, rule.id, rule_in)


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/distribution-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Deleted successfully"},
        403: {"description": "Forbidden - IDOR or insufficient permission"},
        404: {"description": "Not found"},
        400: {"description": "Cannot delete - rule is active or in use"}
    }
)
async def delete_distribution_rule(
    request: Request,  # Required for rate limiter
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    rule: models.OfferingDistributionConfig = deps.DistributionRuleAccessDep,
):
    """
    (Admin/Manager) Delete a distribution rule.

    **Security:**
    - ✓ Role: Admin or Manager (Casbin)
    - ✓ Ownership: Manager limited to managed units
    - ✓ IDOR Protection: Enabled

    **Business Rules:**
    - Cannot delete active rules (is_active=True)
    - Cannot delete rules currently in use by leads
    """
    await config_service.delete_distribution_rule(db, rule.id)
    return None


# ============================================================================
# DEGREE LEVELS MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/degree-levels",
    response_model=List[schemas.ConfigDegreeLevel],
)
async def list_degree_levels(
    request: Request,
    active_only: bool = True,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) List all degree levels.

    Args:
        active_only: If True, return only active degree levels
    """
    return await config_service.get_degree_levels(db, active_only)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/degree-levels",
    response_model=schemas.ConfigDegreeLevel,
    status_code=status.HTTP_201_CREATED,
)
async def create_degree_level(
    request: Request,
    level_in: schemas.ConfigDegreeLevelCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Create a new degree level."""
    level, callback = await config_service.create_degree_level(db, level_in)
    await db.commit()
    await callback()
    return level


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/degree-levels/{level_id}",
    response_model=schemas.ConfigDegreeLevel,
)
async def update_degree_level(
    request: Request,
    level_id: int,
    level_in: schemas.ConfigDegreeLevelUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Update a degree level."""
    level, callback = await config_service.update_degree_level(db, level_id, level_in)
    await db.commit()
    await callback()
    return level


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/degree-levels/{level_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_degree_level(
    request: Request,
    level_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Delete a degree level (soft delete)."""
    _, callback = await config_service.delete_degree_level(db, level_id)
    await db.commit()
    await callback()
    return None


# ============================================================================
# OFFERING TYPES MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/offering-types",
    response_model=List[schemas.ConfigOfferingType],
)
async def list_offering_types(
    request: Request,
    active_only: bool = True,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) List all offering types.

    Args:
        active_only: If True, return only active offering types
    """
    return await config_service.get_offering_types(db, active_only)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/offering-types",
    response_model=schemas.ConfigOfferingType,
    status_code=status.HTTP_201_CREATED,
)
async def create_offering_type(
    request: Request,
    type_in: schemas.ConfigOfferingTypeCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Create a new offering type."""
    offering_type, callback = await config_service.create_offering_type(db, type_in)
    await db.commit()
    await callback()
    return offering_type


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/offering-types/{type_id}",
    response_model=schemas.ConfigOfferingType,
)
async def update_offering_type(
    request: Request,
    type_id: int,
    type_in: schemas.ConfigOfferingTypeUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Update an offering type."""
    offering_type, callback = await config_service.update_offering_type(db, type_id, type_in)
    await db.commit()
    await callback()
    return offering_type


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/offering-types/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_offering_type(
    request: Request,
    type_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Delete an offering type (soft delete)."""
    _, callback = await config_service.delete_offering_type(db, type_id)
    await db.commit()
    await callback()
    return None


# ============================================================================
# DOCUMENT TYPES MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/document-types",
    response_model=List[schemas.ConfigDocumentType],
)
async def list_document_types(
    request: Request,
    active_only: bool = True,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) List all document types.

    Args:
        active_only: If True, return only active document types
    """
    return await config_service.get_document_types(db, active_only)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/document-types",
    response_model=schemas.ConfigDocumentType,
    status_code=status.HTTP_201_CREATED,
)
async def create_document_type(
    request: Request,
    type_in: schemas.ConfigDocumentTypeCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Create a new document type."""
    doc_type, callback = await config_service.create_document_type(db, type_in)
    await db.commit()
    await callback()
    return doc_type


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/document-types/{type_id}",
    response_model=schemas.ConfigDocumentType,
)
async def update_document_type(
    request: Request,
    type_id: int,
    type_in: schemas.ConfigDocumentTypeUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Update a document type."""
    doc_type, callback = await config_service.update_document_type(db, type_id, type_in)
    await db.commit()
    await callback()
    return doc_type


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/document-types/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document_type(
    request: Request,
    type_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Delete a document type (soft delete)."""
    _, callback = await config_service.delete_document_type(db, type_id)
    await db.commit()
    await callback()
    return None