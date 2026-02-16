# app/services/config_service.py
"""
✅ PATTERN A COMPLIANT - Config Service

Refactored to use Repository pattern for all database queries.
"""
import json
from typing import Any, Callable, List, Tuple

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..repositories.config_repository import (
    AssignmentConfigRepository,
    DegreeLevelRepository,
    DistributionRuleRepository,
    DocumentTypeRepository,
    OfferingTypeRepository,
    SkillRuleRepository,
    SystemCategoryRepository
)
# ... (existing imports)
import io
import openpyxl

# ... (End of file, append new functions)

# =============================================================================
# SYSTEM CATEGORY CONFIGURATION
# =============================================================================

async def get_system_categories(
    db: AsyncSession,
    type: str,
    active_only: bool = True
) -> List[models.ConfigSystemCategory]:
    """Get system categories by type."""
    repo = SystemCategoryRepository(db)
    return await repo.get_by_type(type, active_only)

async def import_system_categories(
    db: AsyncSession,
    type_key: str,
    file_content: bytes
) -> dict:
    """
    Import system categories from Excel file.
    Expected format: Column A = Code, Column B = Name (optional)
    """
    repo = SystemCategoryRepository(db)
    try:
        wb = openpyxl.load_workbook(filename=io.BytesIO(file_content), data_only=True)
        ws = wb.active # Use active sheet
        
        created_count = 0
        updated_count = 0
        
        # Iterate rows starting from 2 (skip header)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or row[0] is None:
                continue
                
            code = str(row[0]).strip()
            # If name is missing, use code as name
            name = str(row[1]).strip() if len(row) > 1 and row[1] else code
            
            _, created = await repo.create_or_update(type_key, code, name)
            if created:
                created_count += 1
            else:
                updated_count += 1
                
        return {"created": created_count, "updated": updated_count}
        
    except Exception as e:
        log.error("Failed to import categories", error=str(e))
        raise BadRequest(detail=f"Import failed: {str(e)}")

from ..repositories.organization_repository import OrganizationRepository
from ..services.pipeline_service import invalidate_pipeline_cache
from ..utils.exceptions import BadRequest, DuplicateResourceError, ResourceNotFoundError

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
    )

    # 1. Try cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            log.debug("Cache hit for assignment config", unit_id=unit_id)
            return json.loads(cached_data)
    except Exception as e_redis_get:
        # Log error but proceed to DB query (fail-open)
        log.error(
            "Failed to get assignment config from cache",
            unit_id=unit_id,
            error=str(e_redis_get),
        )

    log.debug(
        "Cache miss for assignment config, querying DB", unit_id=unit_id
    )
    # 2. Cache Miss: Query DB via Repository
    repo = AssignmentConfigRepository(db)
    config = await repo.get_by_unit_id(unit_id)

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
        log.debug(
            "Stored assignment config in cache",
            unit_id=unit_id,
            ttl=CONFIG_CACHE_TTL_SECONDS,
        )
    except Exception as e_redis_set:
        log.error(
            "Failed to set assignment config in cache",
            unit_id=unit_id,
            error=str(e_redis_set),
        )

    return config_params


async def update_assignment_config(
    db: AsyncSession, unit_id: int, params: Any
) -> Tuple[models.OfficerAssignmentConfig, Callable]:
    """
    Cập nhật cấu hình phân chia của một đơn vị.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        unit_id: ID của organization unit
        params: Configuration parameters

    Returns:
        Tuple of (config, post_commit_callback)

    Raises:
        ResourceNotFoundError: If organization unit doesn't exist

    Example:
        config, post_commit = await update_assignment_config(db, unit_id, params)
        await db.commit()  # Router commits
        await post_commit()  # Execute post-commit actions
    """
    cache_key = f"config:assignment:{unit_id}"
    repo = AssignmentConfigRepository(db)
    org_repo = OrganizationRepository(db)

    # Check unit exists via OrganizationRepository
    unit = await org_repo.get_by_id(unit_id)
    if not unit:
        raise ResourceNotFoundError(detail=f"Organization unit {unit_id} not found")

    # 1. Validation: params must be a dict
    if not isinstance(params, dict):
        log.error("Invalid assignment config parameters type", unit_id=unit_id, type=type(params).__name__)
        raise BadRequest(detail="Assignment config parameters must be a JSON object (dictionary)")

    # 1.1 Deep Validation: check for negative numbers in numeric fields
    for key, value in params.items():
        if isinstance(value, (int, float)) and value < 0:
            raise BadRequest(detail=f"Configuration parameter '{key}' cannot be negative.")

    try:
        # Use row lock for update
        db_config = await repo.get_by_unit_id_for_update(unit_id)

        if not db_config:
            # Create new config via repository
            config = await repo.create({"unit_id": unit_id, "params": params})
            log.info("Creating new assignment config", unit_id=unit_id)
        else:
            # Update existing config via repository
            config = await repo.update(db_config, {"params": params})
            log.info("Updating existing assignment config", unit_id=unit_id)

        # ✅ TRANSACTION FIX: Flush instead of commit
        # Flush writes to DB and gets ID without committing transaction
        await db.flush()
        # Refresh to load 'params' column after flush
        await db.refresh(config, attribute_names=["params"])

        # ✅ Create post-commit callback for cache invalidation
        async def _post_commit():
            """Execute after router commits the transaction."""
            try:
                deleted_count = await safe_redis_delete(cache_key)
                if deleted_count > 0:
                    log.info("Invalidated assignment config cache", unit_id=unit_id)
                else:
                    log.debug("No assignment config cache to invalidate", unit_id=unit_id)
            except Exception as e_redis_del:
                log.error(
                    "Failed to invalidate cache after config update",
                    unit_id=unit_id,
                    error=str(e_redis_del),
                )

        return config, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to update assignment config",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise  # Re-raise exception (e.g., ResourceNotFoundError)


# --- Skill Rules (Consider caching if needed) ---


async def get_all_skill_rules(db: AsyncSession) -> List[models.SkillRequirementRule]:
    """Get all skill rules via Repository."""
    repo = SkillRuleRepository(db)
    return await repo.get_all_rules()


async def create_skill_rule(
    db: AsyncSession, rule_in: schemas.SkillRuleCreate
) -> Tuple[models.SkillRequirementRule, Callable]:
    """
    Create a skill rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule_in: Skill rule data

    Returns:
        Tuple of (skill_rule, post_commit_callback)
    """
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        repo = SkillRuleRepository(db)
        db_rule = await repo.create(rule_in.model_dump())

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_rule)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            await invalidate_pipeline_cache()
            log.info("Skill rule created, relevant cache invalidated", rule_id=db_rule.id)

        return db_rule, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to create skill rule",
            rule=rule_in.model_dump_json(),
            error=str(e),
            exc_info=True,
        )
        raise


async def delete_skill_rule(db: AsyncSession, rule_id: int) -> Tuple[None, Callable]:
    """
    Delete a skill rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule_id: ID of the rule to delete

    Returns:
        Tuple of (None, post_commit_callback)

    Raises:
        ResourceNotFoundError: If rule doesn't exist
    """
    # NOTE: If caching get_all_skill_rules, invalidate the cache here.
    try:
        repo = SkillRuleRepository(db)
        rule = await repo.get_by_id(rule_id)
        if not rule:
            raise ResourceNotFoundError(detail=f"Skill rule with id {rule_id} not found")
        await repo.delete(rule)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            await invalidate_pipeline_cache()
            log.info("Skill rule deleted, relevant cache invalidated", rule_id=rule_id)

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error(
            "Failed to delete skill rule", rule_id=rule_id, error=str(e), exc_info=True
        )
        raise


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
    repo = DegreeLevelRepository(db)
    return await repo.get_all_active(active_only)


async def get_programs_with_admissions(
    db: AsyncSession,
    current_user: "models.User" = None,
) -> list:
    """
    Get distinct MajorPrograms that have at least one admission profile.

    Used by admission list page filter dropdown.
    Only returns active programs linked to real admission data.

    IDOR:
    - Admin: all programs
    - Manager + Officer: programs within their unit
    """
    from sqlalchemy import select
    from ..core.constants import UserRole

    query = (
        select(models.MajorProgram)
        .join(
            models.ProgramOffering,
            models.ProgramOffering.program_id == models.MajorProgram.id,
        )
        .join(
            models.Lead,
            models.Lead.offering_id == models.ProgramOffering.id,
        )
        .join(
            models.AdmissionProfile,
            models.AdmissionProfile.lead_id == models.Lead.id,
        )
        .where(models.MajorProgram.is_active == True)
        .distinct()
        .order_by(models.MajorProgram.name)
    )

    if current_user:
        if current_user.role == UserRole.ADMIN:
            pass  # no filter
        else:
            # Manager + Officer: unit scope
            query = query.where(models.Lead.unit_id == current_user.unit_id)

    result = await db.execute(query)
    return list(result.scalars().all())


async def get_degree_level_by_id(
    db: AsyncSession,
    level_id: int
) -> models.ConfigDegreeLevel:
    """Get a degree level by ID via Repository."""
    repo = DegreeLevelRepository(db)
    level = await repo.get_by_id(level_id)

    if not level:
        raise ResourceNotFoundError(detail=f"Degree level with ID {level_id} not found")

    return level


async def create_degree_level(
    db: AsyncSession,
    level_in: schemas.ConfigDegreeLevelCreate
) -> Tuple[models.ConfigDegreeLevel, Callable]:
    """
    Create a new degree level.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Validates:
    - Code uniqueness
    - Name uniqueness

    Args:
        db: Database session
        level_in: Degree level data

    Returns:
        Tuple of (degree_level, post_commit_callback)

    Raises:
        BadRequest: If code or name already exists
    """
    repo = DegreeLevelRepository(db)
    
    # Check for duplicate code via Repository
    if await repo.check_code_exists(level_in.code):
        raise BadRequest(detail=f"Degree level with code '{level_in.code}' already exists")

    # Check for duplicate name via Repository
    if await repo.check_name_exists(level_in.name):
        raise BadRequest(detail=f"Degree level with name '{level_in.name}' already exists")

    # Create new level via Repository
    db_level = await repo.create(level_in.model_dump())

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Degree level created", level_id=db_level.id, code=db_level.code)

    return db_level, _post_commit


async def update_degree_level(
    db: AsyncSession,
    level_id: int,
    level_in: schemas.ConfigDegreeLevelUpdate
) -> Tuple[models.ConfigDegreeLevel, Callable]:
    """
    Update a degree level.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        level_id: ID of the degree level to update
        level_in: Update data

    Returns:
        Tuple of (degree_level, post_commit_callback)

    Raises:
        ResourceNotFoundError: If level doesn't exist
        BadRequest: If code or name already exists
    """
    repo = DegreeLevelRepository(db)
    db_level = await repo.get_by_id(level_id)
    
    if not db_level:
        raise ResourceNotFoundError(detail=f"Degree level with ID {level_id} not found")

    update_data = level_in.model_dump(exclude_unset=True)

    # Validate uniqueness if code is being updated via Repository
    if "code" in update_data and update_data["code"] != db_level.code:
        if await repo.check_code_exists(update_data["code"], exclude_id=level_id):
            raise BadRequest(detail=f"Degree level with code '{update_data['code']}' already exists")

    # Validate uniqueness if name is being updated via Repository
    if "name" in update_data and update_data["name"] != db_level.name:
        if await repo.check_name_exists(update_data["name"], exclude_id=level_id):
            raise BadRequest(detail=f"Degree level with name '{update_data['name']}' already exists")

        # ✅ Cascade update to MajorProgram when name changes
        old_name = db_level.name
        new_name = update_data["name"]
        
        affected_programs = await repo.get_programs_by_degree_name(old_name)
        for program in affected_programs:
            program.degree_level = new_name
            
        log.info(
            "Cascading degree level name update",
            old_name=old_name,
            new_name=new_name,
            affected_count=len(affected_programs)
        )

    # Update via Repository
    db_level = await repo.update(db_level, update_data)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Degree level updated", level_id=level_id)

    return db_level, _post_commit


async def delete_degree_level(
    db: AsyncSession,
    level_id: int,
    soft_delete: bool = True
) -> Tuple[None, Callable]:
    """
    Delete a degree level.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        level_id: ID of the level to delete
        soft_delete: If True, set is_active=False; if False, hard delete

    Returns:
        Tuple of (None, post_commit_callback)

    Raises:
        ResourceNotFoundError: If level doesn't exist
        BadRequest: If level is being used by MajorPrograms
    """
    repo = DegreeLevelRepository(db)
    db_level = await repo.get_by_id(level_id)
    
    if not db_level:
        raise ResourceNotFoundError(detail=f"Degree level with ID {level_id} not found")

    # Check if any MajorProgram is using this degree level via Repository
    if await repo.is_used_by_programs(db_level.name):
        raise BadRequest(
            detail=f"Cannot delete degree level '{db_level.name}' - it is being used by one or more programs"
        )

    # ✅ Perform delete/deactivate via Repository
    if soft_delete:
        db_level = await repo.soft_delete(db_level)
        delete_type = "soft"
    else:
        await repo.delete(db_level)
        delete_type = "hard"

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        if delete_type == "soft":
            log.info("Degree level soft deleted", level_id=level_id)
        else:
            log.info("Degree level hard deleted", level_id=level_id)

    return None, _post_commit


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
    repo = OfferingTypeRepository(db)
    return await repo.get_all_active(active_only)


async def get_offering_type_by_id(
    db: AsyncSession,
    type_id: int
) -> models.ConfigOfferingType:
    """Get an offering type by ID via Repository."""
    repo = OfferingTypeRepository(db)
    offering_type = await repo.get_by_id(type_id)

    if not offering_type:
        raise ResourceNotFoundError(detail=f"Offering type with ID {type_id} not found")

    return offering_type


async def create_offering_type(
    db: AsyncSession,
    type_in: schemas.ConfigOfferingTypeCreate
) -> Tuple[models.ConfigOfferingType, Callable]:
    """
    Create a new offering type via Repository.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    """
    repo = OfferingTypeRepository(db)
    
    # Check for duplicate code via Repository
    if await repo.check_code_exists(type_in.code):
        raise BadRequest(detail=f"Offering type with code '{type_in.code}' already exists")

    # Check for duplicate name via Repository
    if await repo.check_name_exists(type_in.name):
        raise BadRequest(detail=f"Offering type with name '{type_in.name}' already exists")

    # Create new type via Repository
    db_type = await repo.create(type_in.model_dump())

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Offering type created", type_id=db_type.id, code=db_type.code)

    return db_type, _post_commit


async def update_offering_type(
    db: AsyncSession,
    type_id: int,
    type_in: schemas.ConfigOfferingTypeUpdate
) -> Tuple[models.ConfigOfferingType, Callable]:
    """
    Update an offering type via Repository.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    """
    repo = OfferingTypeRepository(db)
    db_type = await repo.get_by_id(type_id)
    
    if not db_type:
        raise ResourceNotFoundError(detail=f"Offering type with ID {type_id} not found")

    update_data = type_in.model_dump(exclude_unset=True)

    # Validate uniqueness if code is being updated via Repository
    if "code" in update_data and update_data["code"] != db_type.code:
        if await repo.check_code_exists(update_data["code"], exclude_id=type_id):
            raise BadRequest(detail=f"Offering type with code '{update_data['code']}' already exists")

    # Validate uniqueness if name is being updated via Repository
    if "name" in update_data and update_data["name"] != db_type.name:
        if await repo.check_name_exists(update_data["name"], exclude_id=type_id):
            raise BadRequest(detail=f"Offering type with name '{update_data['name']}' already exists")

        # ✅ Cascade update to ProgramOffering when name changes via Repository
        old_name = db_type.name
        new_name = update_data["name"]
        
        affected_offerings = await repo.get_offerings_by_type_name(old_name)
        for offering in affected_offerings:
            offering.offering_type = new_name
        
        log.info(
            "Cascading offering type name update",
            old_name=old_name,
            new_name=new_name,
            affected_count=len(affected_offerings)
        )

    # Update via Repository
    db_type = await repo.update(db_type, update_data)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Offering type updated", type_id=type_id)

    return db_type, _post_commit


async def delete_offering_type(
    db: AsyncSession,
    type_id: int,
    soft_delete: bool = True
) -> Tuple[None, Callable]:
    """
    Delete an offering type via Repository.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    """
    repo = OfferingTypeRepository(db)
    db_type = await repo.get_by_id(type_id)
    
    if not db_type:
        raise ResourceNotFoundError(detail=f"Offering type with ID {type_id} not found")

    # Check if any ProgramOffering is using this offering type via Repository
    if await repo.is_used_by_offerings(db_type.name):
        raise BadRequest(
            detail=f"Cannot delete offering type '{db_type.name}' - it is being used by one or more program offerings"
        )

    # ✅ Perform delete/deactivate via Repository
    if soft_delete:
        db_type = await repo.soft_delete(db_type)
        delete_type = "soft"
    else:
        await repo.delete(db_type)
        delete_type = "hard"

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        if delete_type == "soft":
            log.info("Offering type soft deleted", type_id=type_id)
        else:
            log.info("Offering type hard deleted", type_id=type_id)

    return None, _post_commit


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
    repo = DocumentTypeRepository(db)
    return await repo.get_all_active(active_only)


async def get_document_type_by_id(
    db: AsyncSession,
    type_id: int
) -> models.ConfigDocumentType:
    """Get a document type by ID via Repository."""
    repo = DocumentTypeRepository(db)
    document_type = await repo.get_by_id(type_id)

    if not document_type:
        raise ResourceNotFoundError(detail=f"Document type with ID {type_id} not found")

    return document_type


async def create_document_type(
    db: AsyncSession,
    type_in: schemas.ConfigDocumentTypeCreate
) -> Tuple[models.ConfigDocumentType, Callable]:
    """
    Create a new document type via Repository.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    """
    repo = DocumentTypeRepository(db)
    
    # Check unique code via Repository
    if await repo.check_code_exists(type_in.code.lower()):
        raise DuplicateResourceError(
            detail=f"Document type with code '{type_in.code}' already exists"
        )

    # Check unique name via Repository
    if await repo.check_name_exists(type_in.name):
        raise DuplicateResourceError(
            detail=f"Document type with name '{type_in.name}' already exists"
        )

    # Create via Repository
    data = type_in.model_dump()
    data["code"] = data["code"].lower()
    db_type = await repo.create(data)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Document type created", type_id=db_type.id, code=db_type.code)

    return db_type, _post_commit


async def update_document_type(
    db: AsyncSession,
    type_id: int,
    type_in: schemas.ConfigDocumentTypeUpdate
) -> Tuple[models.ConfigDocumentType, Callable]:
    """
    Update a document type via Repository.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    """
    repo = DocumentTypeRepository(db)
    db_type = await repo.get_by_id(type_id)
    
    if not db_type:
        raise ResourceNotFoundError(detail=f"Document type with ID {type_id} not found")

    update_data = type_in.model_dump(exclude_unset=True)

    # Validate uniqueness if code is being updated via Repository
    if "code" in update_data and update_data["code"] != db_type.code:
        if await repo.check_code_exists(update_data["code"].lower(), exclude_id=type_id):
            raise BadRequest(
                detail=f"Document type with code '{update_data['code']}' already exists"
            )
        update_data["code"] = update_data["code"].lower()

    # Validate uniqueness if name is being updated via Repository
    if "name" in update_data and update_data["name"] != db_type.name:
        if await repo.check_name_exists(update_data["name"], exclude_id=type_id):
            raise BadRequest(
                detail=f"Document type with name '{update_data['name']}' already exists"
            )

    # Update via Repository
    old_code = db_type.code
    db_type = await repo.update(db_type, update_data)
    new_code = db_type.code

    # Note: Old cascade logic for ProgramOffering.admission_rules removed.
    # Documents are now managed via relational DocumentGroup tables.

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Document type updated", type_id=type_id)

    return db_type, _post_commit


async def delete_document_type(
    db: AsyncSession,
    type_id: int,
    soft_delete: bool = True
) -> Tuple[None, Callable]:
    """
    Delete a document type via Repository.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.
    """
    repo = DocumentTypeRepository(db)
    db_type = await repo.get_by_id(type_id)
    
    if not db_type:
        raise ResourceNotFoundError(detail=f"Document type with ID {type_id} not found")

    # ✅ Perform delete/deactivate via Repository
    if soft_delete:
        db_type = await repo.soft_delete(db_type)
        delete_type = "soft"
    else:
        await repo.delete(db_type)
        delete_type = "hard"

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        if delete_type == "soft":
            log.info("Document type soft deleted", type_id=type_id)
        else:
            log.info("Document type hard deleted", type_id=type_id)

    return None, _post_commit


# ============================================================================
# DISTRIBUTION RULES MANAGEMENT
# ============================================================================


def _build_distribution_rule_response(
    rule: models.OfferingDistributionConfig
) -> schemas.DistributionRuleResponse:
    """
    Helper to build DistributionRuleResponse from model.

    Constructs offering_name as: "{MajorProgram.name} - {offering_type}"
    """
    offering_name = None
    if rule.offering:
        program_name = rule.offering.program.name if rule.offering.program else "Unknown"
        offering_name = f"{program_name} - {rule.offering.offering_type}"

    return schemas.DistributionRuleResponse(
        id=rule.id,
        offering_id=rule.offering_id,
        unit_id=rule.unit_id,
        weight=rule.weight,
        priority=rule.priority,
        is_active=rule.is_active,
        offering_name=offering_name,
        unit_name=rule.unit.name if rule.unit else None,
    )


async def get_all_distribution_rules(db: AsyncSession) -> List[schemas.DistributionRuleResponse]:
    """
    Get all distribution rules with offering and unit names.

    Returns:
        List of DistributionRuleResponse schemas
    """
    repo = DistributionRuleRepository(db)
    rules = await repo.get_all_with_relations()

    return [_build_distribution_rule_response(rule) for rule in rules]


async def get_distribution_rules_by_units(
    db: AsyncSession,
    unit_ids: List[int]
) -> List[schemas.DistributionRuleResponse]:
    """
    Get distribution rules filtered by unit IDs (for manager ownership).

    This function is used to enforce IDOR protection by returning only
    distribution rules that belong to the specified organizational units.

    Args:
        db: Database session
        unit_ids: List of organization unit IDs to filter by

    Returns:
        List of DistributionRuleResponse schemas for rules in specified units
    """
    if not unit_ids:
        return []

    repo = DistributionRuleRepository(db)
    rules = await repo.get_by_units_with_relations(unit_ids)

    return [_build_distribution_rule_response(rule) for rule in rules]


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
    repo = DistributionRuleRepository(db)
    rule = await repo.get_by_id(rule_id)
    if not rule:
        raise ResourceNotFoundError(
            detail=f"Distribution rule with id {rule_id} not found"
        )
    return rule


async def create_distribution_rule(
    db: AsyncSession,
    rule_in: schemas.DistributionRuleCreate
) -> Tuple[schemas.DistributionRuleResponse, Callable]:
    """
    Create a new distribution rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule_in: Distribution rule creation data

    Returns:
        Tuple of (DistributionRuleResponse, post_commit_callback)

    Raises:
        BadRequest: If offering_id or unit_id doesn't exist
    """
    repo = DistributionRuleRepository(db)
    org_repo = OrganizationRepository(db)

    # Validate offering exists
    # Note: Using OrganizationRepository for Offering since it contains those models too
    # or we could use DegreeLevelRepository if it had general offering get
    offering = await org_repo.get_offering_by_id_full(rule_in.offering_id)
    if not offering:
        raise BadRequest(
            detail=f"Program offering with id {rule_in.offering_id} not found"
        )

    # Validate unit exists
    unit = await org_repo.get_by_id(rule_in.unit_id)
    if not unit:
        raise BadRequest(
            detail=f"Organization unit with id {rule_in.unit_id} not found"
        )

    # Check for duplicate via Repository
    if await repo.check_duplicate(rule_in.offering_id, rule_in.unit_id):
        raise BadRequest(
            detail=f"Distribution rule for offering {rule_in.offering_id} and unit {rule_in.unit_id} already exists"
        )

    # Create and fetch with relations via Repository
    db_rule = await repo.create_and_fetch(rule_in)

    response = _build_distribution_rule_response(db_rule)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Distribution rule created",
            rule_id=db_rule.id,
            offering_id=db_rule.offering_id,
            unit_id=db_rule.unit_id
        )

    return response, _post_commit


async def update_distribution_rule(
    db: AsyncSession,
    rule_id: int,
    rule_in: schemas.DistributionRuleUpdate
) -> Tuple[schemas.DistributionRuleResponse, Callable]:
    """
    Update a distribution rule.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        rule_id: ID of the rule to update
        rule_in: Update data

    Returns:
        Tuple of (DistributionRuleResponse, post_commit_callback)

    Raises:
        ResourceNotFoundError: If rule doesn't exist
    """
    repo = DistributionRuleRepository(db)
    db_rule = await repo.get_by_id(rule_id)
    if not db_rule:
        raise ResourceNotFoundError(detail=f"Distribution rule with id {rule_id} not found")

    # If updating offering or unit, check for duplicates
    update_data = rule_in.model_dump(exclude_unset=True)
    new_offering_id = update_data.get("offering_id", db_rule.offering_id)
    new_unit_id = update_data.get("unit_id", db_rule.unit_id)

    if new_offering_id != db_rule.offering_id or new_unit_id != db_rule.unit_id:
        if await repo.check_duplicate(new_offering_id, new_unit_id, exclude_id=rule_id):
            raise BadRequest(
                detail=f"Distribution rule for offering {new_offering_id} and unit {new_unit_id} already exists"
            )

    # Update via Repository
    db_rule = await repo.update_and_fetch(rule_id, rule_in)
    if not db_rule:
        raise ResourceNotFoundError(
            detail=f"Distribution rule with id {rule_id} not found"
        )

    response = _build_distribution_rule_response(db_rule)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info("Distribution rule updated", rule_id=rule_id)

    return response, _post_commit


async def delete_distribution_rule(
    db: AsyncSession,
    rule_id: int
) -> Tuple[None, Callable]:
    """
    Delete a distribution rule with business rule validation.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    **Business Rules:**
    - Cannot delete active rules (is_active=True)
    - Should check if rule is in use (future enhancement)

    Args:
        db: Database session
        rule_id: ID of the rule to delete

    Returns:
        Tuple of (None, post_commit_callback)

    Raises:
        ResourceNotFoundError: If rule doesn't exist
        BadRequest: If rule cannot be deleted (active or in use)
    """
    db_rule = await get_distribution_rule_by_id(db, rule_id)

    # Business Rule 1: Cannot delete active rules
    if db_rule.is_active:
        log.warning(
            "Attempt to delete active distribution rule blocked",
            rule_id=rule_id,
            is_active=db_rule.is_active
        )
        raise BadRequest(
            detail=f"Cannot delete active distribution rule. "
                   f"Please deactivate the rule first (set is_active=False)."
        )

    # Business Rule 2: Check if rule is in use by leads (future enhancement)
    # This would require querying leads table to see if any leads
    # were distributed using this rule

    # Store info for logging before deletion
    offering_id = db_rule.offering_id
    unit_id = db_rule.unit_id

    await db.delete(db_rule)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Distribution rule deleted",
            rule_id=rule_id,
            offering_id=offering_id,
            unit_id=unit_id
        )

    return None, _post_commit


# =============================================================================
# SUBJECT GROUP CONFIGURATION (Migrated to Relational SubjectGroup)
# =============================================================================

from app.models.admission_config import SubjectGroup, SubjectGroupSubject
from sqlalchemy.orm import selectinload


def _build_subject_group_response(group: SubjectGroup) -> dict:
    """Build a response dict from SubjectGroup with subjects array."""
    sorted_mappings = sorted(group.subject_mappings, key=lambda m: m.position)
    return {
        "id": group.id,
        "code": group.code,
        "name": group.name,
        "subjects": [m.subject.code for m in sorted_mappings],
        "display_order": group.display_order,
        "is_active": group.is_active,
    }


async def get_subject_groups(
    db: AsyncSession,
    active_only: bool = True
) -> List[dict]:
    """
    Get all subject groups for admission scoring.
    
    MIGRATED: Now uses relational SubjectGroup instead of ConfigSubjectGroup.
    
    Args:
        db: Database session
        active_only: If True, only return active groups
        
    Returns:
        List of subject group dicts with subjects array
    """
    from sqlalchemy import select
    
    query = (
        select(SubjectGroup)
        .options(
            selectinload(SubjectGroup.subject_mappings)
            .selectinload(SubjectGroupSubject.subject)
        )
    )
    
    if active_only:
        query = query.where(SubjectGroup.is_active == True)
    
    query = query.order_by(SubjectGroup.display_order)
    
    result = await db.execute(query)
    groups = result.scalars().all()
    
    return [_build_subject_group_response(group) for group in groups]



async def get_subject_group_by_code(
    db: AsyncSession,
    code: str
) -> dict | None:
    """
    Get a specific subject group by code.
    
    MIGRATED: Now uses relational SubjectGroup.
    
    Args:
        db: Database session
        code: Subject group code (e.g., 'A00', 'D01')
        
    Returns:
        Subject group dict with subjects array, or None if not found
    """
    from sqlalchemy import select
    
    query = (
        select(SubjectGroup)
        .options(
            selectinload(SubjectGroup.subject_mappings)
            .selectinload(SubjectGroupSubject.subject)
        )
        .where(SubjectGroup.code == code.upper())
        .where(SubjectGroup.is_active == True)
    )
    
    result = await db.execute(query)
    group = result.scalar_one_or_none()
    
    if group:
        return _build_subject_group_response(group)
    return None


async def get_subject_groups_by_codes(
    db: AsyncSession,
    codes: List[str]
) -> List[dict]:
    """
    Get multiple subject groups by their codes.
    Used to resolve subject_groups array in admission_criteria.
    
    MIGRATED: Now uses relational SubjectGroup.
    
    Args:
        db: Database session
        codes: List of codes (e.g., ['A00', 'D01', 'B00'])
        
    Returns:
        List of subject group dicts matching the codes
    """
    from sqlalchemy import select
    
    if not codes:
        return []
    
    upper_codes = [c.upper() for c in codes]
    
    query = (
        select(SubjectGroup)
        .options(
            selectinload(SubjectGroup.subject_mappings)
            .selectinload(SubjectGroupSubject.subject)
        )
        .where(SubjectGroup.code.in_(upper_codes))
        .where(SubjectGroup.is_active == True)
        .order_by(SubjectGroup.display_order)
    )
    
    result = await db.execute(query)
    groups = result.scalars().all()
    
    return [_build_subject_group_response(group) for group in groups]

