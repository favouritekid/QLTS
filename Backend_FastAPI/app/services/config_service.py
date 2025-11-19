# app/services/config_service.py
import json  # 👈 *** ADD IMPORT ***
from typing import Any, List

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas

# 👈 *** ADD REDIS IMPORTS ***
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..services.pipeline_service import invalidate_pipeline_cache
from ..utils.exceptions import ResourceNotFoundError

log = structlog.get_logger(__name__)

# === ⭐️ CONFIGURATION CACHE SETTINGS ⭐️ ===
CONFIG_CACHE_TTL_SECONDS = 3600  # Cache config for 1 hour


async def get_assignment_config(db: AsyncSession, unit_id: int) -> dict:
    """
    Lấy cấu hình phân chia của một đơn vị.
    ✅ FIXED: Uses Redis Cache-Aside pattern.
    """
    cache_key = f"config:assignment:{unit_id}"
    log.debug(
        "Fetching assignment config", unit_id=unit_id, cache_key=cache_key
    )  # THÊM await

    # 1. Try cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            log.debug("Cache hit for assignment config", unit_id=unit_id)  # THÊM await
            return json.loads(cached_data)
    except Exception as e_redis_get:
        # Log error but proceed to DB query (fail-open)
        log.error(  # THÊM await
            "Failed to get assignment config from cache",
            unit_id=unit_id,
            error=str(e_redis_get),
        )

    log.debug(
        "Cache miss for assignment config, querying DB", unit_id=unit_id
    )  # THÊM await
    # 2. Cache Miss: Query DB
    config = await db.scalar(
        select(models.OfficerAssignmentConfig).where(
            models.OfficerAssignmentConfig.unit_id == unit_id
        )
    )

    # === TÁCH KIỂM TRA ===
    if not config:
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found."
        )

    # Kiểm tra params (cột JSON có thể cần truy cập)
    config_params = config.params

    if not config_params:  # Nếu params là None hoặc {}
        raise ResourceNotFoundError(
            detail=f"Assignment config for unit {unit_id} not found or has no params."
        )
    # === KẾT THÚC TÁCH ===

    # 3. Store in cache
    try:
        await safe_redis_set(
            cache_key, json.dumps(config_params), ex=CONFIG_CACHE_TTL_SECONDS
        )
        log.debug(  # THÊM await
            "Stored assignment config in cache",
            unit_id=unit_id,
            ttl=CONFIG_CACHE_TTL_SECONDS,
        )
    except Exception as e_redis_set:
        log.error(  # THÊM await
            "Failed to set assignment config in cache",
            unit_id=unit_id,
            error=str(e_redis_set),
        )

    return config_params


async def update_assignment_config(
    db: AsyncSession, unit_id: int, params: Any
) -> models.OfficerAssignmentConfig:
    """
    Cập nhật cấu hình phân chia của một đơn vị.
    Sử dụng commit/rollback tường minh.
    """
    cache_key = f"config:assignment:{unit_id}"
    try:
        # Logic tìm hoặc tạo config
        config = await db.scalar(
            select(models.OfficerAssignmentConfig)
            .where(models.OfficerAssignmentConfig.unit_id == unit_id)
            .with_for_update()  # Lock the row
        )

        if not config:
            unit = await db.get(models.OrganizationUnit, unit_id)
            if not unit:
                raise ResourceNotFoundError(
                    detail=f"Organization Unit with id {unit_id} not found."
                )
            config = models.OfficerAssignmentConfig(unit_id=unit_id, params=params)
            log.info("Creating new assignment config", unit_id=unit_id)
        else:
            config.params = params
            log.info("Updating existing assignment config", unit_id=unit_id)

        db.add(config)

        # === THAY ĐỔI CHÍNH ===
        # 1. Commit thay đổi vào DB
        await db.commit()
        # 2. Refresh để load lại cột 'params' sau khi commit
        # (Chỉ định rõ 'params' để đảm bảo nó được load)
        await db.refresh(config, attribute_names=["params"])

        config_to_return = config
        # === KẾT THÚC THAY ĐỔI ===

        # --- Invalidate Cache SAU KHI DB commit thành công ---
        try:
            deleted_count = await safe_redis_delete(cache_key)
            if deleted_count > 0:
                log.info("Invalidated assignment config cache", unit_id=unit_id)
            else:
                log.debug("No assignment config cache to invalidate", unit_id=unit_id)
        except Exception as e_redis_del:
            log.error(
                "Failed to invalidate assignment config cache after update",
                unit_id=unit_id,
                error=str(e_redis_del),
            )

        return config_to_return

    except Exception as e:
        await db.rollback()  # Rollback nếu có lỗi TRƯỚC KHI commit
        log.error(
            "Failed to update assignment config",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e  # Ném lại lỗi (ví dụ: ResourceNotFoundError)


# --- Skill Rules (Consider caching if needed) ---


async def get_all_skill_rules(db: AsyncSession) -> List[models.SkillRequirementRule]:
    # NOTE: Caching this might be complex due to potential updates.
    # If this list is large and frequently accessed, consider Redis caching
    # with appropriate invalidation when rules are created/deleted.
    # For now, let's keep it simple.
    result = await db.execute(select(models.SkillRequirementRule))
    return result.scalars().all()


async def create_skill_rule(
    db: AsyncSession, rule_in: schemas.SkillRuleCreate
) -> models.SkillRequirementRule:
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = models.SkillRequirementRule(**rule_in.model_dump())
        db.add(db_rule)
        await db.commit()
        await db.refresh(db_rule)

        await invalidate_pipeline_cache()
        log.info("Skill rule created, relevant cache invalidated", rule_id=db_rule.id)

        return db_rule
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create skill rule",
            rule=rule_in.model_dump_json(),
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_skill_rule(db: AsyncSession, rule_id: int):
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        db_rule = await db.get(models.SkillRequirementRule, rule_id)
        if not db_rule:
            raise ResourceNotFoundError(
                detail=f"Skill rule with id {rule_id} not found."
            )
        await db.delete(db_rule)
        await db.commit()

        await invalidate_pipeline_cache()
        log.info("Skill rule deleted, relevant cache invalidated", rule_id=rule_id)

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete skill rule", rule_id=rule_id, error=str(e), exc_info=True
        )
        raise e


# =============================================================================
# DEGREE LEVEL CONFIGURATION
# =============================================================================

async def get_degree_levels(
    db: AsyncSession,
    active_only: bool = True
) -> List[models.ConfigDegreeLevel]:
    """
    Get all degree levels, ordered by display_order.

    Args:
        db: Database session
        active_only: If True, only return active levels

    Returns:
        List of ConfigDegreeLevel models
    """
    query = select(models.ConfigDegreeLevel)

    if active_only:
        query = query.where(models.ConfigDegreeLevel.is_active == True)

    query = query.order_by(models.ConfigDegreeLevel.display_order)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_degree_level_by_id(
    db: AsyncSession,
    level_id: int
) -> models.ConfigDegreeLevel:
    """Get a degree level by ID."""
    result = await db.execute(
        select(models.ConfigDegreeLevel).where(models.ConfigDegreeLevel.id == level_id)
    )
    level = result.scalar_one_or_none()

    if not level:
        raise ResourceNotFoundError(detail=f"Degree level with ID {level_id} not found")

    return level


async def create_degree_level(
    db: AsyncSession,
    level_in: schemas.ConfigDegreeLevelCreate
) -> models.ConfigDegreeLevel:
    """
    Create a new degree level.

    Validates:
    - Code uniqueness
    - Name uniqueness
    """
    from ..utils.exceptions import BadRequest

    # Check for duplicate code
    existing_code = await db.execute(
        select(models.ConfigDegreeLevel).where(
            models.ConfigDegreeLevel.code == level_in.code
        )
    )
    if existing_code.scalar_one_or_none():
        raise BadRequest(detail=f"Degree level with code '{level_in.code}' already exists")

    # Check for duplicate name
    existing_name = await db.execute(
        select(models.ConfigDegreeLevel).where(
            models.ConfigDegreeLevel.name == level_in.name
        )
    )
    if existing_name.scalar_one_or_none():
        raise BadRequest(detail=f"Degree level with name '{level_in.name}' already exists")

    # Create new level
    db_level = models.ConfigDegreeLevel(**level_in.model_dump())
    db.add(db_level)
    await db.commit()
    await db.refresh(db_level)

    log.info("Degree level created", level_id=db_level.id, code=db_level.code)
    return db_level


async def update_degree_level(
    db: AsyncSession,
    level_id: int,
    level_in: schemas.ConfigDegreeLevelUpdate
) -> models.ConfigDegreeLevel:
    """Update a degree level."""
    from ..utils.exceptions import BadRequest

    db_level = await get_degree_level_by_id(db, level_id)

    update_data = level_in.model_dump(exclude_unset=True)

    # Validate uniqueness if code is being updated
    if "code" in update_data and update_data["code"] != db_level.code:
        existing_code = await db.execute(
            select(models.ConfigDegreeLevel).where(
                models.ConfigDegreeLevel.code == update_data["code"],
                models.ConfigDegreeLevel.id != level_id
            )
        )
        if existing_code.scalar_one_or_none():
            raise BadRequest(detail=f"Degree level with code '{update_data['code']}' already exists")

    # Validate uniqueness if name is being updated
    if "name" in update_data and update_data["name"] != db_level.name:
        existing_name = await db.execute(
            select(models.ConfigDegreeLevel).where(
                models.ConfigDegreeLevel.name == update_data["name"],
                models.ConfigDegreeLevel.id != level_id
            )
        )
        if existing_name.scalar_one_or_none():
            raise BadRequest(detail=f"Degree level with name '{update_data['name']}' already exists")

    # Apply updates
    for field, value in update_data.items():
        setattr(db_level, field, value)

    await db.commit()
    await db.refresh(db_level)

    log.info("Degree level updated", level_id=level_id)
    return db_level


async def delete_degree_level(
    db: AsyncSession,
    level_id: int,
    soft_delete: bool = True
) -> None:
    """
    Delete a degree level.

    Args:
        db: Database session
        level_id: ID of the level to delete
        soft_delete: If True, set is_active=False; if False, hard delete

    Raises:
        ResourceNotFoundError: If level doesn't exist
        BadRequest: If level is being used by MajorPrograms
    """
    from ..utils.exceptions import BadRequest

    db_level = await get_degree_level_by_id(db, level_id)

    # Check if any MajorProgram is using this degree level
    programs_using = await db.execute(
        select(models.MajorProgram).where(
            models.MajorProgram.degree_level == db_level.name
        ).limit(1)
    )
    if programs_using.scalar_one_or_none():
        raise BadRequest(
            detail=f"Cannot delete degree level '{db_level.name}' - it is being used by one or more programs"
        )

    if soft_delete:
        db_level.is_active = False
        await db.commit()
        log.info("Degree level soft deleted", level_id=level_id)
    else:
        await db.delete(db_level)
        await db.commit()
        log.info("Degree level hard deleted", level_id=level_id)


# =============================================================================
# OFFERING TYPE CONFIGURATION
# =============================================================================

async def get_offering_types(
    db: AsyncSession,
    active_only: bool = True
) -> List[models.ConfigOfferingType]:
    """
    Get all offering types, ordered by display_order.

    Args:
        db: Database session
        active_only: If True, only return active types

    Returns:
        List of ConfigOfferingType models
    """
    query = select(models.ConfigOfferingType)

    if active_only:
        query = query.where(models.ConfigOfferingType.is_active == True)

    query = query.order_by(models.ConfigOfferingType.display_order)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_offering_type_by_id(
    db: AsyncSession,
    type_id: int
) -> models.ConfigOfferingType:
    """Get an offering type by ID."""
    result = await db.execute(
        select(models.ConfigOfferingType).where(models.ConfigOfferingType.id == type_id)
    )
    offering_type = result.scalar_one_or_none()

    if not offering_type:
        raise ResourceNotFoundError(detail=f"Offering type with ID {type_id} not found")

    return offering_type


async def create_offering_type(
    db: AsyncSession,
    type_in: schemas.ConfigOfferingTypeCreate
) -> models.ConfigOfferingType:
    """
    Create a new offering type.

    Validates:
    - Code uniqueness
    - Name uniqueness
    """
    from ..utils.exceptions import BadRequest

    # Check for duplicate code
    existing_code = await db.execute(
        select(models.ConfigOfferingType).where(
            models.ConfigOfferingType.code == type_in.code
        )
    )
    if existing_code.scalar_one_or_none():
        raise BadRequest(detail=f"Offering type with code '{type_in.code}' already exists")

    # Check for duplicate name
    existing_name = await db.execute(
        select(models.ConfigOfferingType).where(
            models.ConfigOfferingType.name == type_in.name
        )
    )
    if existing_name.scalar_one_or_none():
        raise BadRequest(detail=f"Offering type with name '{type_in.name}' already exists")

    # Create new type
    db_type = models.ConfigOfferingType(**type_in.model_dump())
    db.add(db_type)
    await db.commit()
    await db.refresh(db_type)

    log.info("Offering type created", type_id=db_type.id, code=db_type.code)
    return db_type


async def update_offering_type(
    db: AsyncSession,
    type_id: int,
    type_in: schemas.ConfigOfferingTypeUpdate
) -> models.ConfigOfferingType:
    """Update an offering type."""
    from ..utils.exceptions import BadRequest

    db_type = await get_offering_type_by_id(db, type_id)

    update_data = type_in.model_dump(exclude_unset=True)

    # Validate uniqueness if code is being updated
    if "code" in update_data and update_data["code"] != db_type.code:
        existing_code = await db.execute(
            select(models.ConfigOfferingType).where(
                models.ConfigOfferingType.code == update_data["code"],
                models.ConfigOfferingType.id != type_id
            )
        )
        if existing_code.scalar_one_or_none():
            raise BadRequest(detail=f"Offering type with code '{update_data['code']}' already exists")

    # Validate uniqueness if name is being updated
    if "name" in update_data and update_data["name"] != db_type.name:
        existing_name = await db.execute(
            select(models.ConfigOfferingType).where(
                models.ConfigOfferingType.name == update_data["name"],
                models.ConfigOfferingType.id != type_id
            )
        )
        if existing_name.scalar_one_or_none():
            raise BadRequest(detail=f"Offering type with name '{update_data['name']}' already exists")

        # ✅ FIX: Cascade update to ProgramOffering when name changes
        # Without this, ProgramOfferings would keep the old name and become inconsistent
        old_name = db_type.name
        new_name = update_data["name"]

        log.info(
            "Cascading offering type name update to ProgramOfferings",
            old_name=old_name,
            new_name=new_name
        )

        # Update all ProgramOfferings that use the old name
        result = await db.execute(
            select(models.ProgramOffering).where(
                models.ProgramOffering.offering_type == old_name
            )
        )
        affected_offerings = result.scalars().all()

        for offering in affected_offerings:
            offering.offering_type = new_name

        log.info(
            "Updated offering type references",
            old_name=old_name,
            new_name=new_name,
            affected_count=len(affected_offerings)
        )

    # Apply updates
    for field, value in update_data.items():
        setattr(db_type, field, value)

    await db.commit()
    await db.refresh(db_type)

    log.info("Offering type updated", type_id=type_id)
    return db_type


async def delete_offering_type(
    db: AsyncSession,
    type_id: int,
    soft_delete: bool = True
) -> None:
    """
    Delete an offering type.

    Args:
        db: Database session
        type_id: ID of the type to delete
        soft_delete: If True, set is_active=False; if False, hard delete

    Raises:
        ResourceNotFoundError: If type doesn't exist
        BadRequest: If type is being used by ProgramOfferings
    """
    from ..utils.exceptions import BadRequest

    db_type = await get_offering_type_by_id(db, type_id)

    # Check if any ProgramOffering is using this offering type
    offerings_using = await db.execute(
        select(models.ProgramOffering).where(
            models.ProgramOffering.offering_type == db_type.name
        ).limit(1)
    )
    if offerings_using.scalar_one_or_none():
        raise BadRequest(
            detail=f"Cannot delete offering type '{db_type.name}' - it is being used by one or more program offerings"
        )

    if soft_delete:
        db_type.is_active = False
        await db.commit()
        log.info("Offering type soft deleted", type_id=type_id)
    else:
        await db.delete(db_type)
        await db.commit()
        log.info("Offering type hard deleted", type_id=type_id)


# =============================================================================
# DOCUMENT TYPE CONFIGURATION
# =============================================================================

async def get_document_types(
    db: AsyncSession,
    active_only: bool = True
) -> List[models.ConfigDocumentType]:
    """
    Get all document types, ordered by display_order.

    Args:
        db: Database session
        active_only: If True, return only active document types

    Returns:
        List of ConfigDocumentType models
    """
    query = select(models.ConfigDocumentType)

    if active_only:
        query = query.where(models.ConfigDocumentType.is_active == True)

    query = query.order_by(
        models.ConfigDocumentType.display_order,
        models.ConfigDocumentType.name
    )

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_document_type_by_id(
    db: AsyncSession,
    type_id: int
) -> models.ConfigDocumentType:
    """Get a document type by ID."""
    result = await db.execute(
        select(models.ConfigDocumentType).where(models.ConfigDocumentType.id == type_id)
    )
    document_type = result.scalar_one_or_none()

    if not document_type:
        raise ResourceNotFoundError(detail=f"Document type with ID {type_id} not found")

    return document_type


async def create_document_type(
    db: AsyncSession,
    type_in: schemas.ConfigDocumentTypeCreate
) -> models.ConfigDocumentType:
    """
    Create a new document type.

    Args:
        db: Database session
        type_in: Document type creation data

    Returns:
        Created ConfigDocumentType model

    Raises:
        DuplicateResourceError: If code or name already exists
    """
    # Check unique code
    existing = await db.execute(
        select(models.ConfigDocumentType).where(
            models.ConfigDocumentType.code == type_in.code.lower()
        )
    )
    if existing.scalar_one_or_none():
        raise DuplicateResourceError(
            detail=f"Document type with code '{type_in.code}' already exists"
        )

    # Check unique name
    existing = await db.execute(
        select(models.ConfigDocumentType).where(
            models.ConfigDocumentType.name == type_in.name
        )
    )
    if existing.scalar_one_or_none():
        raise DuplicateResourceError(
            detail=f"Document type with name '{type_in.name}' already exists"
        )

    db_type = models.ConfigDocumentType(
        code=type_in.code.lower(),
        name=type_in.name,
        description=type_in.description,
        display_order=type_in.display_order,
        is_active=type_in.is_active
    )
    db.add(db_type)
    await db.commit()
    await db.refresh(db_type)

    log.info("Document type created", type_id=db_type.id, code=db_type.code)
    return db_type


async def update_document_type(
    db: AsyncSession,
    type_id: int,
    type_in: schemas.ConfigDocumentTypeUpdate
) -> models.ConfigDocumentType:
    """Update a document type."""
    from ..utils.exceptions import BadRequest

    db_type = await get_document_type_by_id(db, type_id)

    update_data = type_in.model_dump(exclude_unset=True)

    # Validate uniqueness if code is being updated
    if "code" in update_data and update_data["code"] != db_type.code:
        existing = await db.execute(
            select(models.ConfigDocumentType).where(
                models.ConfigDocumentType.code == update_data["code"].lower(),
                models.ConfigDocumentType.id != type_id
            )
        )
        if existing.scalar_one_or_none():
            raise BadRequest(
                detail=f"Document type with code '{update_data['code']}' already exists"
            )
        update_data["code"] = update_data["code"].lower()

    # Validate uniqueness if name is being updated
    if "name" in update_data and update_data["name"] != db_type.name:
        existing = await db.execute(
            select(models.ConfigDocumentType).where(
                models.ConfigDocumentType.name == update_data["name"],
                models.ConfigDocumentType.id != type_id
            )
        )
        if existing.scalar_one_or_none():
            raise BadRequest(
                detail=f"Document type with name '{update_data['name']}' already exists"
            )

    for key, value in update_data.items():
        setattr(db_type, key, value)

    await db.commit()
    await db.refresh(db_type)

    log.info("Document type updated", type_id=type_id)
    return db_type


async def delete_document_type(
    db: AsyncSession,
    type_id: int,
    soft_delete: bool = True
) -> None:
    """
    Delete a document type.

    Args:
        db: Database session
        type_id: ID of the document type
        soft_delete: If True, set is_active=False; otherwise hard delete

    Raises:
        ResourceNotFoundError: If type doesn't exist
    """
    db_type = await get_document_type_by_id(db, type_id)

    if soft_delete:
        db_type.is_active = False
        await db.commit()
        log.info("Document type soft deleted", type_id=type_id)
    else:
        await db.delete(db_type)
        await db.commit()
        log.info("Document type hard deleted", type_id=type_id)


# ============================================================================
# DISTRIBUTION RULES MANAGEMENT
# ============================================================================


async def get_all_distribution_rules(db: AsyncSession) -> List[models.OfferingDistributionConfig]:
    """
    Get all distribution rules with offering and unit names.

    Returns:
        List of OfferingDistributionConfig models
    """
    result = await db.execute(
        select(models.OfferingDistributionConfig)
        .order_by(
            models.OfferingDistributionConfig.priority.asc(),  # Lower number = higher priority
            models.OfferingDistributionConfig.id
        )
    )
    return result.scalars().all()


async def get_distribution_rule_by_id(
    db: AsyncSession,
    rule_id: int
) -> models.OfferingDistributionConfig:
    """
    Get a distribution rule by ID.

    Args:
        db: Database session
        rule_id: ID of the rule

    Returns:
        OfferingDistributionConfig model

    Raises:
        ResourceNotFoundError: If rule doesn't exist
    """
    rule = await db.get(models.OfferingDistributionConfig, rule_id)
    if not rule:
        raise ResourceNotFoundError(
            detail=f"Distribution rule with id {rule_id} not found"
        )
    return rule


async def create_distribution_rule(
    db: AsyncSession,
    rule_in: schemas.DistributionRuleCreate
) -> models.OfferingDistributionConfig:
    """
    Create a new distribution rule.

    Args:
        db: Database session
        rule_in: Distribution rule creation data

    Returns:
        Created DistributionRule model

    Raises:
        BadRequest: If offering_id or unit_id doesn't exist
    """
    from ..utils.exceptions import BadRequest

    # Validate offering exists
    offering = await db.get(models.ProgramOffering, rule_in.offering_id)
    if not offering:
        raise BadRequest(
            detail=f"Program offering with id {rule_in.offering_id} not found"
        )

    # Validate unit exists
    unit = await db.get(models.OrganizationUnit, rule_in.unit_id)
    if not unit:
        raise BadRequest(
            detail=f"Organization unit with id {rule_in.unit_id} not found"
        )

    # Check for duplicate (same offering + unit)
    existing = await db.execute(
        select(models.OfferingDistributionConfig).where(
            models.OfferingDistributionConfig.offering_id == rule_in.offering_id,
            models.OfferingDistributionConfig.unit_id == rule_in.unit_id
        )
    )
    if existing.scalar_one_or_none():
        raise BadRequest(
            detail=f"Distribution rule for offering {rule_in.offering_id} and unit {rule_in.unit_id} already exists"
        )

    # Create rule
    db_rule = models.OfferingDistributionConfig(**rule_in.model_dump())
    db.add(db_rule)
    await db.commit()
    await db.refresh(db_rule)

    log.info(
        "Distribution rule created",
        rule_id=db_rule.id,
        offering_id=db_rule.offering_id,
        unit_id=db_rule.unit_id
    )
    return db_rule


async def update_distribution_rule(
    db: AsyncSession,
    rule_id: int,
    rule_in: schemas.DistributionRuleUpdate
) -> models.OfferingDistributionConfig:
    """
    Update a distribution rule.

    Args:
        db: Database session
        rule_id: ID of the rule to update
        rule_in: Update data

    Returns:
        Updated DistributionRule model

    Raises:
        ResourceNotFoundError: If rule doesn't exist
    """
    db_rule = await get_distribution_rule_by_id(db, rule_id)

    # Update only provided fields
    update_data = rule_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_rule, field, value)

    await db.commit()
    await db.refresh(db_rule)

    log.info("Distribution rule updated", rule_id=rule_id)
    return db_rule


async def delete_distribution_rule(
    db: AsyncSession,
    rule_id: int
) -> None:
    """
    Delete a distribution rule.

    Args:
        db: Database session
        rule_id: ID of the rule to delete

    Raises:
        ResourceNotFoundError: If rule doesn't exist
    """
    db_rule = await get_distribution_rule_by_id(db, rule_id)

    await db.delete(db_rule)
    await db.commit()

    log.info("Distribution rule deleted", rule_id=rule_id)
