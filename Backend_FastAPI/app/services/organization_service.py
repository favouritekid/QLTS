# app/services/organization_service.py
from typing import List, Optional

import structlog  # <-- BỔ SUNG
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)  # <-- BỔ SUNG

# --- OrganizationUnit Services ---


async def get_all_organization_units(db: AsyncSession) -> List[models.OrganizationUnit]:
    """Lấy danh sách tất cả các đơn vị, tải háo hức các quan hệ."""
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.parent).options(
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.OrganizationUnit.children),
            selectinload(models.OrganizationUnit.majors),
        )
        .order_by(models.OrganizationUnit.name)
    )
    result = await db.execute(query)
    return result.scalars().unique().all()


async def get_organization_unit_by_id(
    db: AsyncSession, unit_id: int
) -> Optional[models.OrganizationUnit]:
    """Lấy chi tiết một đơn vị, tải háo hức các quan hệ."""
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.parent).options(
                selectinload(models.OrganizationUnit.children),
                selectinload(models.OrganizationUnit.majors),
            ),
            selectinload(models.OrganizationUnit.children),
            selectinload(models.OrganizationUnit.majors),
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
    db: AsyncSession, unit_in: schemas.OrganizationUnitCreate
) -> models.OrganizationUnit:
    try:
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
        # Tải lại đầy đủ relations trước khi trả về
        return await get_organization_unit_by_id(db, db_unit.id)
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create organization unit",
            unit_name=unit_in.name,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_organization_unit(
    db: AsyncSession, unit_id: int, unit_in: schemas.OrganizationUnitUpdate
) -> models.OrganizationUnit:
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        update_data = unit_in.model_dump(exclude_unset=True)

        if "parent_id" in update_data:
            new_parent_id = update_data["parent_id"]
            if new_parent_id is None:
                db_unit.parent_id = None
            else:
                if new_parent_id == unit_id:
                    raise DuplicateResourceError(
                        detail="A unit cannot be its own parent."
                    )
                parent_unit = await db.get(models.OrganizationUnit, new_parent_id)
                if not parent_unit:
                    raise ResourceNotFoundError(
                        detail=f"Parent unit with id {new_parent_id} not found."
                    )
                db_unit.parent_id = new_parent_id

        for key, value in update_data.items():
            if key != "parent_id":
                setattr(db_unit, key, value)

        db.add(db_unit)
        await db.commit()
        # Tải lại đầy đủ relations
        return await get_organization_unit_by_id(db, unit_id)
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_organization_unit(db: AsyncSession, unit_id: int):
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        if db_unit.children or db_unit.majors:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains child units or majors."
            )
        await db.delete(db_unit)
        await db.commit()
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to delete organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Major Services ---


async def get_major_by_id(db: AsyncSession, major_id: int) -> Optional[models.Major]:
    major = await db.get(models.Major, major_id)
    if not major:
        raise ResourceNotFoundError(detail=f"Major with id {major_id} not found.")
    return major


async def create_major(db: AsyncSession, major_in: schemas.MajorCreate) -> models.Major:
    try:
        existing_major_query = select(models.Major).where(
            models.Major.code == major_in.code
        )
        existing_major = await db.execute(existing_major_query)
        if existing_major.scalar_one_or_none():
            raise DuplicateResourceError(
                detail=f"Major with code '{major_in.code}' already exists."
            )

        db_major = models.Major(**major_in.model_dump())
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)
        return db_major
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create major",
            major_code=major_in.code,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_major(
    db: AsyncSession, major_id: int, major_in: schemas.MajorUpdate
) -> models.Major:
    try:
        db_major = await get_major_by_id(db, major_id)
        update_data = major_in.model_dump(exclude_unset=True)

        if "code" in update_data and update_data["code"] != db_major.code:
            existing_major_query = select(models.Major).where(
                models.Major.code == update_data["code"]
            )
            if (await db.execute(existing_major_query)).scalar_one_or_none():
                raise DuplicateResourceError(
                    detail=f"Major with code '{update_data['code']}' already exists."
                )

        for key, value in update_data.items():
            setattr(db_major, key, value)
        db.add(db_major)
        await db.commit()
        await db.refresh(db_major)
        return db_major
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


async def delete_major(db: AsyncSession, major_id: int):
    try:
        db_major = await get_major_by_id(db, major_id)
        await db.delete(db_major)
        await db.commit()
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to delete major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


async def get_majors_by_unit_tree(
    db: AsyncSession, unit_id: int, search_term: str = None
) -> List[models.Major]:
    """Lấy danh sách ngành học thuộc về một đơn vị và tất cả các đơn vị con cháu của nó."""
    if not unit_id:
        return []

    sql = text(
        """
        WITH RECURSIVE unit_hierarchy AS (
           SELECT id FROM organization_unit WHERE id = :unit_id
           UNION ALL
           SELECT u.id FROM organization_unit u JOIN unit_hierarchy uh ON u.parent_id = uh.id
        )
        SELECT id FROM unit_hierarchy;
    """
    )
    result = await db.execute(sql, {"unit_id": unit_id})
    all_related_unit_ids = [row[0] for row in result]

    query = select(models.Major).filter(models.Major.unit_id.in_(all_related_unit_ids))
    if search_term:
        # 1. Làm sạch và tạo pattern an toàn
        safe_pattern = f"%{search_term.strip()}%"

        # 2. Truyền TOÀN BỘ pattern như một tham số
        # SQLAlchemy sẽ tự động escape nó
        query = query.filter(models.Major.name.ilike(safe_pattern))

    majors_result = await db.execute(query.order_by(models.Major.name).limit(20))
    return majors_result.scalars().all()
