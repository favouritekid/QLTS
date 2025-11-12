# app/services/organization_service.py
"""
Organization Service - Refactored for 3-tier architecture.

Handles:
- OrganizationUnit CRUD
- MajorProgram (Level 1) CRUD
- ProgramOffering (Level 2) CRUD
- OfferingAcademicInfo (Level 3) CRUD
- Tree aggregation with nested statistics
"""
import asyncio
import json
from datetime import datetime
from typing import List, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
from ..config import settings
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..socket_manager import emit_to_all
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)

# Cache configuration
ORG_UNITS_CACHE_KEY = "org:all_units_tree"
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS
_org_cache_lock = asyncio.Lock()


# =============================================================================
# CACHE INVALIDATION & NOTIFICATIONS
# =============================================================================

async def invalidate_org_cache():
    """Invalidate organization tree cache."""
    try:
        await safe_redis_delete(ORG_UNITS_CACHE_KEY)
        log.info("Organization cache invalidated", key=ORG_UNITS_CACHE_KEY)
    except Exception as e:
        log.error("Failed to invalidate organization cache", error=str(e))


async def emit_organization_updated(
    operation: str,
    resource_type: str,
    resource_id: int,
    resource_name: str = None
):
    """
    Emit organization update event via Socket.IO.

    Args:
        operation: "create", "update", or "delete"
        resource_type: "organization", "program", "offering", or "academic_info"
        resource_id: ID of the resource
        resource_name: Name of the resource (optional)
    """
    try:
        await emit_to_all(
            "data_updated",
            {
                "resource_type": resource_type,
                "operation": operation,
                "resource_id": resource_id,
                "resource_name": resource_name,
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        log.info(
            "Emitted organization update",
            resource_type=resource_type,
            operation=operation,
            resource_id=resource_id
        )
    except Exception as e:
        log.error("Failed to emit organization update", error=str(e))


# =============================================================================
# ORGANIZATION UNIT SERVICES
# =============================================================================

async def check_duplicate_unit_name(
    db: AsyncSession,
    name: str,
    parent_id: Optional[int],
    exclude_unit_id: Optional[int] = None
) -> None:
    """Check for duplicate unit name within the same parent."""
    query = select(models.OrganizationUnit).where(
        models.OrganizationUnit.name == name.strip(),
        models.OrganizationUnit.parent_id == parent_id
    )

    if exclude_unit_id is not None:
        query = query.where(models.OrganizationUnit.id != exclude_unit_id)

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        parent_name = "cấp gốc" if parent_id is None else f"đơn vị cha #{parent_id}"
        raise DuplicateResourceError(
            detail=f"Đã tồn tại đơn vị '{name}' trong {parent_name}"
        )


async def get_all_organization_units(db: AsyncSession) -> List[dict]:
    """
    Get all organization units as a tree structure with caching support.

    Returns:
        List of root organization units with nested children and major_programs
    """
    log.debug("Fetching all organization units", cache_key=ORG_UNITS_CACHE_KEY)

    # Try cache first
    try:
        cached_data = await safe_redis_get(ORG_UNITS_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for organization units")
            return json.loads(cached_data)
    except Exception as e:
        log.error("Failed to get from cache", error=str(e))

    log.debug("Cache miss, acquiring lock...")

    # Cache miss - acquire lock and query database
    async with _org_cache_lock:
        # Double-check cache after acquiring lock
        try:
            cached_data = await safe_redis_get(ORG_UNITS_CACHE_KEY)
            if cached_data:
                log.debug("Cache hit after lock")
                return json.loads(cached_data)
        except Exception:
            pass

        log.debug("Querying database for organization tree")

        # Create recursive loader for 3-tier hierarchy
        # OrganizationUnit → MajorProgram → ProgramOffering → OfferingAcademicInfo
        def create_recursive_unit_loader(depth: int):
            """Create recursive loader for organization units"""
            if depth <= 0:
                return selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ).selectinload(
                    models.ProgramOffering.academic_info_history
                )

            return selectinload(models.OrganizationUnit.children).options(
                selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ).selectinload(
                    models.ProgramOffering.academic_info_history
                ),
                create_recursive_unit_loader(depth - 1)
            )

        # Query root units with full hierarchy (up to 9 levels deep)
        recursive_loader = create_recursive_unit_loader(depth=9)

        query = (
            select(models.OrganizationUnit)
            .where(
                models.OrganizationUnit.is_active == True,
                models.OrganizationUnit.parent_id == None  # Only root units
            )
            .options(
                selectinload(models.OrganizationUnit.major_programs).selectinload(
                    models.MajorProgram.offerings
                ).selectinload(
                    models.ProgramOffering.academic_info_history
                ),
                recursive_loader,
                selectinload(models.OrganizationUnit.parent)
            )
            .order_by(models.OrganizationUnit.name)
        )

        result = await db.execute(query)
        root_units = result.scalars().unique().all()

        # Serialize to JSON using Pydantic schemas
        try:
            units_data = [
                schemas.OrganizationUnit.model_validate(unit, from_attributes=True).model_dump()
                for unit in root_units
            ]
        except Exception as e:
            log.error("Failed to serialize organization tree", error=str(e), exc_info=True)
            raise

        # Cache the result
        try:
            await safe_redis_set(
                ORG_UNITS_CACHE_KEY,
                json.dumps(units_data),
                ex=CACHE_TTL
            )
            log.debug("Cached organization tree", ttl=CACHE_TTL)
        except Exception as e:
            log.error("Failed to cache organization tree", error=str(e))

        return units_data


async def get_organization_unit_by_id(
    db: AsyncSession,
    unit_id: int
) -> models.OrganizationUnit:
    """Get organization unit by ID with all relationships loaded."""
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.parent),
            selectinload(models.OrganizationUnit.children),
            selectinload(models.OrganizationUnit.major_programs).selectinload(
                models.MajorProgram.offerings
            ).selectinload(
                models.ProgramOffering.academic_info_history
            ),
        )
        .where(models.OrganizationUnit.id == unit_id)
    )
    result = await db.execute(query)
    unit = result.scalars().unique().one_or_none()

    if not unit:
        raise ResourceNotFoundError(
            detail=f"Organization Unit with id {unit_id} not found."
        )
    return unit


async def create_organization_unit(
    db: AsyncSession,
    unit_in: schemas.OrganizationUnitCreate
) -> models.OrganizationUnit:
    """Create a new organization unit."""
    try:
        # Check duplicate name
        await check_duplicate_unit_name(db, unit_in.name, unit_in.parent_id)

        # Verify parent exists if specified
        if unit_in.parent_id:
            parent_unit = await db.get(models.OrganizationUnit, unit_in.parent_id)
            if not parent_unit:
                raise ResourceNotFoundError(
                    detail=f"Parent unit with id {unit_in.parent_id} not found."
                )

        db_unit = models.OrganizationUnit(**unit_in.model_dump())
        db.add(db_unit)
        await db.commit()
        await db.refresh(db_unit)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="create",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

        return await get_organization_unit_by_id(db, db_unit.id)

    except Exception as e:
        await db.rollback()
        log.error("Failed to create organization unit", error=str(e), exc_info=True)
        raise


async def update_organization_unit(
    db: AsyncSession,
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate
) -> models.OrganizationUnit:
    """Update an organization unit."""
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        update_data = unit_in.model_dump(exclude_unset=True)

        # Check duplicate name if being changed
        new_name = update_data.get("name", db_unit.name)
        new_parent_id = update_data.get("parent_id", db_unit.parent_id)
        if "name" in update_data or "parent_id" in update_data:
            await check_duplicate_unit_name(
                db, new_name, new_parent_id, exclude_unit_id=unit_id
            )

        # Handle parent_id update
        if "parent_id" in update_data:
            new_parent_id = update_data["parent_id"]
            if new_parent_id is not None:
                if new_parent_id == unit_id:
                    raise DuplicateResourceError(
                        detail="A unit cannot be its own parent."
                    )
                parent_unit = await db.get(models.OrganizationUnit, new_parent_id)
                if not parent_unit:
                    raise ResourceNotFoundError(
                        detail=f"Parent unit with id {new_parent_id} not found."
                    )

        # Apply updates
        for key, value in update_data.items():
            setattr(db_unit, key, value)

        db.add(db_unit)
        await db.commit()

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="update",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

        return await get_organization_unit_by_id(db, unit_id)

    except Exception as e:
        await db.rollback()
        log.error("Failed to update organization unit", error=str(e), exc_info=True)
        raise


async def delete_organization_unit(db: AsyncSession, unit_id: int):
    """
    Soft delete an organization unit.

    Sets is_active=False to preserve historical data.
    Prevents deletion if unit has active children or programs.
    """
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        unit_name = db_unit.name

        # Check for active children
        active_children_query = select(models.OrganizationUnit).where(
            models.OrganizationUnit.parent_id == unit_id,
            models.OrganizationUnit.is_active == True
        )
        active_children_result = await db.execute(active_children_query)
        active_children = active_children_result.scalars().all()

        # Check for active major programs
        active_programs_query = select(models.MajorProgram).where(
            models.MajorProgram.unit_id == unit_id,
            models.MajorProgram.is_active == True
        )
        active_programs_result = await db.execute(active_programs_query)
        active_programs = active_programs_result.scalars().all()

        if active_children or active_programs:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains active child units or programs."
            )

        # Soft delete
        db_unit.is_active = False
        db.add(db_unit)
        await db.commit()

        log.info("Organization unit soft-deleted", unit_id=unit_id, unit_name=unit_name)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="delete",
            resource_type="organization",
            resource_id=unit_id,
            resource_name=unit_name
        )

    except Exception as e:
        await db.rollback()
        log.error("Failed to delete organization unit", error=str(e), exc_info=True)
        raise


# =============================================================================
# MAJOR PROGRAM (LEVEL 1) SERVICES
# =============================================================================

async def get_major_program_by_id(
    db: AsyncSession,
    program_id: int
) -> models.MajorProgram:
    """Get major program by ID with all offerings and academic info loaded."""
    query = (
        select(models.MajorProgram)
        .options(
            selectinload(models.MajorProgram.offerings).selectinload(
                models.ProgramOffering.academic_info_history
            ),
            selectinload(models.MajorProgram.unit)
        )
        .where(models.MajorProgram.id == program_id)
    )
    result = await db.execute(query)
    program = result.scalars().unique().one_or_none()

    if not program:
        raise ResourceNotFoundError(
            detail=f"MajorProgram with id {program_id} not found."
        )
    return program


async def create_major_program(
    db: AsyncSession,
    program_in: schemas.MajorProgramCreate
) -> models.MajorProgram:
    """Create a new major program."""
    try:
        # Check duplicate code
        existing_query = select(models.MajorProgram).where(
            models.MajorProgram.code == program_in.code
        )
        existing = await db.execute(existing_query)
        if existing.scalar_one_or_none():
            raise DuplicateResourceError(
                detail=f"Major program with code '{program_in.code}' already exists."
            )

        # Verify unit exists
        unit = await db.get(models.OrganizationUnit, program_in.unit_id)
        if not unit:
            raise ResourceNotFoundError(
                detail=f"Organization unit with id {program_in.unit_id} not found."
            )

        db_program = models.MajorProgram(**program_in.model_dump())
        db.add(db_program)
        await db.commit()
        await db.refresh(db_program)

        log.info("Major program created", program_id=db_program.id, code=db_program.code)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="create",
            resource_type="program",
            resource_id=db_program.id,
            resource_name=db_program.name
        )

        return await get_major_program_by_id(db, db_program.id)

    except Exception as e:
        await db.rollback()
        log.error("Failed to create major program", error=str(e), exc_info=True)
        raise


async def update_major_program(
    db: AsyncSession,
    program_id: int,
    program_in: schemas.MajorProgramUpdate
) -> models.MajorProgram:
    """Update a major program. Note: code cannot be updated."""
    try:
        db_program = await get_major_program_by_id(db, program_id)
        update_data = program_in.model_dump(exclude_unset=True)

        # Code cannot be updated (business rule)
        if "code" in update_data:
            del update_data["code"]
            log.warning("Attempted to update program code (not allowed)", program_id=program_id)

        # Apply updates
        for key, value in update_data.items():
            setattr(db_program, key, value)

        db.add(db_program)
        await db.commit()

        log.info("Major program updated", program_id=program_id)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="update",
            resource_type="program",
            resource_id=db_program.id,
            resource_name=db_program.name
        )

        return await get_major_program_by_id(db, program_id)

    except Exception as e:
        await db.rollback()
        log.error("Failed to update major program", error=str(e), exc_info=True)
        raise


async def delete_major_program(db: AsyncSession, program_id: int):
    """
    Soft delete a major program.

    Sets is_active=False. Cascade will soft-delete associated offerings.
    """
    try:
        db_program = await get_major_program_by_id(db, program_id)
        program_name = db_program.name

        # Soft delete
        db_program.is_active = False
        db.add(db_program)
        await db.commit()

        log.info("Major program soft-deleted", program_id=program_id, program_name=program_name)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="delete",
            resource_type="program",
            resource_id=program_id,
            resource_name=program_name
        )

    except Exception as e:
        await db.rollback()
        log.error("Failed to delete major program", error=str(e), exc_info=True)
        raise


# =============================================================================
# PROGRAM OFFERING (LEVEL 2) SERVICES
# =============================================================================

async def get_program_offering_by_id(
    db: AsyncSession,
    offering_id: int
) -> models.ProgramOffering:
    """Get program offering by ID with academic info loaded."""
    query = (
        select(models.ProgramOffering)
        .options(
            selectinload(models.ProgramOffering.academic_info_history),
            selectinload(models.ProgramOffering.program)
        )
        .where(models.ProgramOffering.id == offering_id)
    )
    result = await db.execute(query)
    offering = result.scalars().unique().one_or_none()

    if not offering:
        raise ResourceNotFoundError(
            detail=f"ProgramOffering with id {offering_id} not found."
        )
    return offering


async def create_program_offering(
    db: AsyncSession,
    offering_in: schemas.ProgramOfferingCreate
) -> models.ProgramOffering:
    """Create a new program offering."""
    try:
        # Verify program exists
        program = await db.get(models.MajorProgram, offering_in.program_id)
        if not program:
            raise ResourceNotFoundError(
                detail=f"Major program with id {offering_in.program_id} not found."
            )

        # Check duplicate (program_id, offering_type)
        existing_query = select(models.ProgramOffering).where(
            models.ProgramOffering.program_id == offering_in.program_id,
            models.ProgramOffering.offering_type == offering_in.offering_type
        )
        existing = await db.execute(existing_query)
        if existing.scalar_one_or_none():
            raise DuplicateResourceError(
                detail=f"Offering '{offering_in.offering_type}' already exists for this program."
            )

        db_offering = models.ProgramOffering(**offering_in.model_dump())
        db.add(db_offering)
        await db.commit()
        await db.refresh(db_offering)

        log.info(
            "Program offering created",
            offering_id=db_offering.id,
            program_id=offering_in.program_id,
            offering_type=offering_in.offering_type
        )

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="create",
            resource_type="offering",
            resource_id=db_offering.id,
            resource_name=db_offering.offering_type
        )

        return await get_program_offering_by_id(db, db_offering.id)

    except Exception as e:
        await db.rollback()
        log.error("Failed to create program offering", error=str(e), exc_info=True)
        raise


async def update_program_offering(
    db: AsyncSession,
    offering_id: int,
    offering_in: schemas.ProgramOfferingUpdate
) -> models.ProgramOffering:
    """Update a program offering."""
    try:
        db_offering = await get_program_offering_by_id(db, offering_id)
        update_data = offering_in.model_dump(exclude_unset=True)

        # Check duplicate if offering_type is being changed
        if "offering_type" in update_data and update_data["offering_type"] != db_offering.offering_type:
            existing_query = select(models.ProgramOffering).where(
                models.ProgramOffering.program_id == db_offering.program_id,
                models.ProgramOffering.offering_type == update_data["offering_type"]
            )
            existing = await db.execute(existing_query)
            if existing.scalar_one_or_none():
                raise DuplicateResourceError(
                    detail=f"Offering '{update_data['offering_type']}' already exists for this program."
                )

        # Apply updates
        for key, value in update_data.items():
            setattr(db_offering, key, value)

        db.add(db_offering)
        await db.commit()

        log.info("Program offering updated", offering_id=offering_id)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="update",
            resource_type="offering",
            resource_id=db_offering.id,
            resource_name=db_offering.offering_type
        )

        return await get_program_offering_by_id(db, offering_id)

    except Exception as e:
        await db.rollback()
        log.error("Failed to update program offering", error=str(e), exc_info=True)
        raise


async def delete_program_offering(db: AsyncSession, offering_id: int):
    """
    Soft delete a program offering.

    Cascade will also delete associated academic info records.
    """
    try:
        db_offering = await get_program_offering_by_id(db, offering_id)
        offering_name = db_offering.offering_type

        # Soft delete
        db_offering.is_active = False
        db.add(db_offering)
        await db.commit()

        log.info("Program offering soft-deleted", offering_id=offering_id, offering_name=offering_name)

        await invalidate_org_cache()
        await emit_organization_updated(
            operation="delete",
            resource_type="offering",
            resource_id=offering_id,
            resource_name=offering_name
        )

    except Exception as e:
        await db.rollback()
        log.error("Failed to delete program offering", error=str(e), exc_info=True)
        raise


# =============================================================================
# OFFERING ACADEMIC INFO (LEVEL 3) SERVICES
# =============================================================================

async def get_academic_info_by_id(
    db: AsyncSession,
    academic_info_id: int
) -> models.OfferingAcademicInfo:
    """Get academic info by ID."""
    academic_info = await db.get(models.OfferingAcademicInfo, academic_info_id)
    if not academic_info:
        raise ResourceNotFoundError(
            detail=f"Academic info with id {academic_info_id} not found."
        )
    return academic_info


async def get_academic_info_by_offering_and_year(
    db: AsyncSession,
    offering_id: int,
    academic_year: int
) -> Optional[models.OfferingAcademicInfo]:
    """Get academic info for a specific offering and year."""
    query = select(models.OfferingAcademicInfo).where(
        models.OfferingAcademicInfo.offering_id == offering_id,
        models.OfferingAcademicInfo.academic_year == academic_year
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_current_academic_info(
    db: AsyncSession,
    offering_id: int
) -> Optional[models.OfferingAcademicInfo]:
    """Get current year's published academic info for an offering."""
    current_year = datetime.now().year
    query = select(models.OfferingAcademicInfo).where(
        models.OfferingAcademicInfo.offering_id == offering_id,
        models.OfferingAcademicInfo.academic_year == current_year,
        models.OfferingAcademicInfo.is_published == True
    ).limit(1)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_academic_info_history(
    db: AsyncSession,
    offering_id: int,
    published_only: bool = False
) -> List[models.OfferingAcademicInfo]:
    """
    Get all academic info history for an offering, ordered by year (newest first).

    Args:
        db: Database session
        offering_id: ID of the program offering
        published_only: If True, only return published academic info

    Returns:
        List of academic info records ordered by academic_year descending
    """
    query = select(models.OfferingAcademicInfo).where(
        models.OfferingAcademicInfo.offering_id == offering_id
    )

    if published_only:
        query = query.where(models.OfferingAcademicInfo.is_published == True)

    query = query.order_by(models.OfferingAcademicInfo.academic_year.desc())

    result = await db.execute(query)
    return list(result.scalars().all())


async def create_academic_info(
    db: AsyncSession,
    academic_info_in: schemas.OfferingAcademicInfoCreate,
    created_by_user_id: Optional[int] = None
) -> models.OfferingAcademicInfo:
    """Create new academic info for an offering."""
    try:
        # Verify offering exists
        offering = await db.get(models.ProgramOffering, academic_info_in.offering_id)
        if not offering:
            raise ResourceNotFoundError(
                detail=f"Program offering with id {academic_info_in.offering_id} not found."
            )

        # Check duplicate (offering_id, academic_year)
        existing = await get_academic_info_by_offering_and_year(
            db, academic_info_in.offering_id, academic_info_in.academic_year
        )
        if existing:
            raise DuplicateResourceError(
                detail=f"Academic info for offering {academic_info_in.offering_id} "
                       f"and year {academic_info_in.academic_year} already exists."
            )

        db_academic_info = models.OfferingAcademicInfo(
            **academic_info_in.model_dump(),
            created_by_user_id=created_by_user_id
        )
        db.add(db_academic_info)
        await db.commit()
        await db.refresh(db_academic_info)

        log.info(
            "Academic info created",
            academic_info_id=db_academic_info.id,
            offering_id=academic_info_in.offering_id,
            academic_year=academic_info_in.academic_year
        )

        await invalidate_org_cache()

        return db_academic_info

    except Exception as e:
        await db.rollback()
        log.error("Failed to create academic info", error=str(e), exc_info=True)
        raise


async def update_academic_info(
    db: AsyncSession,
    academic_info_id: int,
    academic_info_in: schemas.OfferingAcademicInfoUpdate,
    updated_by_user_id: Optional[int] = None
) -> models.OfferingAcademicInfo:
    """Update existing academic info."""
    try:
        db_academic_info = await get_academic_info_by_id(db, academic_info_id)
        update_data = academic_info_in.model_dump(exclude_unset=True)

        # Apply updates
        for key, value in update_data.items():
            setattr(db_academic_info, key, value)

        if updated_by_user_id:
            db_academic_info.updated_by_user_id = updated_by_user_id

        db.add(db_academic_info)
        await db.commit()
        await db.refresh(db_academic_info)

        log.info(
            "Academic info updated",
            academic_info_id=academic_info_id,
            offering_id=db_academic_info.offering_id,
            academic_year=db_academic_info.academic_year
        )

        await invalidate_org_cache()

        return db_academic_info

    except Exception as e:
        await db.rollback()
        log.error("Failed to update academic info", error=str(e), exc_info=True)
        raise


async def delete_academic_info(db: AsyncSession, academic_info_id: int):
    """
    Delete academic info.

    This is a hard delete since academic info is versioned per year.
    """
    try:
        db_academic_info = await get_academic_info_by_id(db, academic_info_id)
        offering_id = db_academic_info.offering_id
        academic_year = db_academic_info.academic_year

        await db.delete(db_academic_info)
        await db.commit()

        log.info(
            "Academic info deleted",
            academic_info_id=academic_info_id,
            offering_id=offering_id,
            academic_year=academic_year
        )

        await invalidate_org_cache()

    except Exception as e:
        await db.rollback()
        log.error("Failed to delete academic info", error=str(e), exc_info=True)
        raise


# =============================================================================
# TREE AGGREGATION WITH 3-TIER SUPPORT
# =============================================================================

async def get_organization_tree_with_aggregation(
    db: AsyncSession,
    academic_year: Optional[int] = None,
    include_inactive: bool = False
) -> List[schemas.OrganizationTreeNodeWithAggregation]:
    """
    Get organization tree with aggregated statistics for 3-tier architecture.

    Args:
        db: Database session
        academic_year: Year for academic info (default: current year)
        include_inactive: Include inactive units/programs

    Returns:
        List of root organization units with nested statistics
    """
    from decimal import Decimal

    # Determine academic year
    if academic_year is None:
        academic_year = datetime.now().year

    log.info(
        "Building organization tree with aggregation (3-tier)",
        academic_year=academic_year,
        include_inactive=include_inactive
    )

    # Query all units with full 3-tier hierarchy loaded
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.major_programs).selectinload(
                models.MajorProgram.offerings
            ).selectinload(
                models.ProgramOffering.academic_info_history
            ),
            selectinload(models.OrganizationUnit.children)
        )
        .order_by(models.OrganizationUnit.name)
    )

    if not include_inactive:
        query = query.where(models.OrganizationUnit.is_active == True)

    result = await db.execute(query)
    all_units = result.scalars().unique().all()

    # Build tree with aggregation
    def build_node_with_aggregation(
        unit: models.OrganizationUnit
    ) -> schemas.OrganizationTreeNodeWithAggregation:
        """Recursively build node with aggregated statistics for 3-tier structure."""

        # Collect majors with stats from programs → offerings → academic info
        majors_with_stats = []
        direct_total_quota = 0
        tuition_fees = []

        for program in unit.major_programs:
            if not program.is_active and not include_inactive:
                continue

            # For each program, iterate through offerings to find academic info
            for offering in program.offerings:
                if not offering.is_active and not include_inactive:
                    continue

                # Find academic info for the specified year
                academic_info = None
                for info in offering.academic_info_history:
                    if info.academic_year == academic_year and info.is_published:
                        academic_info = info
                        break

                # Build MajorWithStats (represents program at offering level)
                major_stats = schemas.MajorWithStats(
                    id=program.id,
                    name=program.name,
                    code=program.code,
                    degree_level=program.degree_level,
                    total_admission_quota=academic_info.annual_admission_quota if academic_info else None,
                    tuition_fee=academic_info.tuition_fee_per_year if academic_info else None
                )
                majors_with_stats.append(major_stats)

                # Collect for aggregation
                if academic_info:
                    if academic_info.annual_admission_quota:
                        direct_total_quota += academic_info.annual_admission_quota
                    if academic_info.tuition_fee_per_year:
                        tuition_fees.append(academic_info.tuition_fee_per_year)

        # Recursively build children
        children_nodes = []
        for child_unit in all_units:
            if child_unit.parent_id == unit.id:
                if not include_inactive and not child_unit.is_active:
                    continue
                child_node = build_node_with_aggregation(child_unit)
                children_nodes.append(child_node)

        # Aggregate statistics from this unit and all descendants
        total_majors = len(majors_with_stats)
        total_quota = direct_total_quota
        all_tuition_fees = tuition_fees.copy()

        for child in children_nodes:
            total_majors += child.stats.total_majors
            if child.stats.total_admission_quota:
                total_quota += child.stats.total_admission_quota
            if child.stats.min_tuition_fee:
                all_tuition_fees.append(child.stats.min_tuition_fee)
            if child.stats.max_tuition_fee:
                all_tuition_fees.append(child.stats.max_tuition_fee)

        # Calculate tuition fee statistics
        avg_tuition = None
        min_tuition = None
        max_tuition = None
        if all_tuition_fees:
            avg_tuition = sum(all_tuition_fees) / len(all_tuition_fees)
            min_tuition = min(all_tuition_fees)
            max_tuition = max(all_tuition_fees)

        # Build aggregated stats
        stats = schemas.UnitAggregatedStats(
            total_majors=total_majors,
            direct_majors=len(majors_with_stats),
            total_admission_quota=total_quota if total_quota > 0 else None,
            avg_tuition_fee=avg_tuition,
            min_tuition_fee=min_tuition,
            max_tuition_fee=max_tuition
        )

        # Build node
        return schemas.OrganizationTreeNodeWithAggregation(
            id=unit.id,
            name=unit.name,
            type=unit.type,
            description=unit.description,
            parent_id=unit.parent_id,
            is_active=unit.is_active,
            majors=majors_with_stats,
            stats=stats,
            children=children_nodes
        )

    # Build root nodes
    root_nodes = []
    for unit in all_units:
        if unit.parent_id is None:
            if not include_inactive and not unit.is_active:
                continue
            root_node = build_node_with_aggregation(unit)
            root_nodes.append(root_node)

    log.info(
        "Organization tree built successfully",
        root_nodes_count=len(root_nodes),
        total_units=len(all_units),
        academic_year=academic_year
    )

    return root_nodes


# =============================================================================
# HELPER: Get programs by unit tree (for search/filtering)
# =============================================================================

async def get_programs_by_unit_tree(
    db: AsyncSession,
    unit_id: int,
    search_term: Optional[str] = None
) -> List[models.MajorProgram]:
    """Get all programs belonging to a unit and all its descendants."""
    if not unit_id:
        return []

    # Get all related unit IDs using recursive CTE
    sql = text(
        """
        WITH RECURSIVE unit_hierarchy AS (
           SELECT id FROM organization_unit WHERE id = :unit_id
           UNION ALL
           SELECT u.id FROM organization_unit u
           JOIN unit_hierarchy uh ON u.parent_id = uh.id
        )
        SELECT id FROM unit_hierarchy;
    """
    )
    result = await db.execute(sql, {"unit_id": unit_id})
    all_related_unit_ids = [row[0] for row in result]

    # Query programs in these units
    query = select(models.MajorProgram).filter(
        models.MajorProgram.unit_id.in_(all_related_unit_ids),
        models.MajorProgram.is_active == True
    )

    if search_term:
        safe_pattern = f"%{search_term.strip()}%"
        query = query.filter(models.MajorProgram.name.ilike(safe_pattern))

    programs_result = await db.execute(query.order_by(models.MajorProgram.name).limit(20))
    return programs_result.scalars().all()
