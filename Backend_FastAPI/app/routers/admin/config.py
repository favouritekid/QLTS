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

from typing import List

import structlog
from fastapi import (
    APIRouter,
    Depends,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core import deps
from app.services import config_service

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - Config"])

# Permission dependency
PermissionDep = Depends(deps.check_permission)


# ============================================================================
# ASSIGNMENT CONFIG MANAGEMENT
# ============================================================================


@router.get(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
)
async def get_assignment_config_route(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy cấu hình phân chia của một đơn vị."""
    params = await config_service.get_assignment_config(db, unit_id)
    return {"params": params}


@router.put(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
)
async def update_assignment_config_route(
    unit_id: int,
    config_in: schemas.AssignmentConfig,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật cấu hình phân chia của một đơn vị."""
    updated_model = await config_service.update_assignment_config(
        db, unit_id, config_in.params
    )
    # Trả về schema Pydantic dựa trên model đã cập nhật từ DB
    return schemas.AssignmentConfig(params=updated_model.params)


# ============================================================================
# SKILL RULES MANAGEMENT
# ============================================================================


@router.get(
    "/skill-rules",
    response_model=List[schemas.SkillRule],
)
async def get_all_skill_rules_route(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy tất cả các quy tắc kỹ năng."""
    return await config_service.get_all_skill_rules(db)


@router.post(
    "/skill-rules",
    response_model=schemas.SkillRule,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_skill_rule_route(
    rule_in: schemas.SkillRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một quy tắc kỹ năng mới."""
    return await config_service.create_skill_rule(db, rule_in)


@router.delete(
    "/skill-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_skill_rule_route(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một quy tắc kỹ năng."""
    await config_service.delete_skill_rule(db, rule_id)
    return None


# ============================================================================
# OFFERING DISTRIBUTION STATS
# ============================================================================


@router.get("/distribution/{offering_id}/stats")
async def get_distribution_stats(
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


@router.get(
    "/distribution-rules",
    response_model=List[schemas.DistributionRuleResponse],
)
async def list_distribution_rules(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) List all distribution rules.

    Returns all distribution rules ordered by priority (highest first).
    """
    rules = await config_service.get_all_distribution_rules(db)

    # Enrich with offering and unit names
    response = []
    for rule in rules:
        # Load relationships if not already loaded
        await db.refresh(rule, ["offering", "unit"])

        response.append(schemas.DistributionRuleResponse(
            id=rule.id,
            offering_id=rule.offering_id,
            unit_id=rule.unit_id,
            weight=rule.weight,
            priority=rule.priority,
            is_active=rule.is_active,
            offering_name=rule.offering.name if rule.offering else None,
            unit_name=rule.unit.name if rule.unit else None,
        ))

    return response


@router.post(
    "/distribution-rules",
    response_model=schemas.DistributionRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_distribution_rule(
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
    rule = await config_service.create_distribution_rule(db, rule_in)

    # Load relationships for response
    await db.refresh(rule, ["offering", "unit"])

    return schemas.DistributionRuleResponse(
        id=rule.id,
        offering_id=rule.offering_id,
        unit_id=rule.unit_id,
        weight=rule.weight,
        priority=rule.priority,
        is_active=rule.is_active,
        offering_name=rule.offering.name if rule.offering else None,
        unit_name=rule.unit.name if rule.unit else None,
    )


@router.put(
    "/distribution-rules/{rule_id}",
    response_model=schemas.DistributionRuleResponse,
)
async def update_distribution_rule(
    rule_id: int,
    rule_in: schemas.DistributionRuleUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Update a distribution rule.

    Only provided fields will be updated (partial update).

    **Example:**
    ```json
    {
        "is_active": false
    }
    ```
    """
    rule = await config_service.update_distribution_rule(db, rule_id, rule_in)

    # Load relationships for response
    await db.refresh(rule, ["offering", "unit"])

    return schemas.DistributionRuleResponse(
        id=rule.id,
        offering_id=rule.offering_id,
        unit_id=rule.unit_id,
        weight=rule.weight,
        priority=rule.priority,
        is_active=rule.is_active,
        offering_name=rule.offering.name if rule.offering else None,
        unit_name=rule.unit.name if rule.unit else None,
    )


@router.delete(
    "/distribution-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_distribution_rule(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Delete a distribution rule."""
    await config_service.delete_distribution_rule(db, rule_id)
    return None
