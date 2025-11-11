# app/services/organization_service.py
import asyncio  # ✅ 1. Thêm import
import json  # ✅ 2. Thêm import
from datetime import datetime
from typing import List, Optional

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas

# ✅ 3. Thêm import
from ..config import settings
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set
from ..socket_manager import emit_to_all
from ..utils.exceptions import DuplicateResourceError, ResourceNotFoundError

log = structlog.get_logger(__name__)

# --- ✅ 4. Định nghĩa Cache Key, TTL, và Lock ---
ORG_UNITS_CACHE_KEY = "org:all_units_tree"
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS  # Lấy từ config (ví dụ: 3600s)
_org_cache_lock = asyncio.Lock()
# ----------------------------------------------


# --- ✅ 5. Tạo hàm Invalidate Cache ---
async def invalidate_org_cache():
    """Xóa cache của cây tổ chức (Organization Tree)."""
    try:
        await safe_redis_delete(ORG_UNITS_CACHE_KEY)
        log.info(
            "Organization cache invalidated successfully.", key=ORG_UNITS_CACHE_KEY
        )
    except Exception as e:
        log.error("Failed to invalidate organization cache", error=str(e))


# --- ✅ Emit Organization Updated via Socket.IO ---
async def emit_organization_updated(
    operation: str,
    resource_type: str,  # "organization" hoặc "major"
    resource_id: int,
    resource_name: str = None
):
    """
    Phát sóng sự kiện cập nhật organization qua Socket.IO.

    Args:
        operation: "create", "update", hoặc "delete"
        resource_type: "organization" hoặc "major"
        resource_id: ID của resource
        resource_name: Tên của resource (optional)
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
        log.error("Failed to emit organization update", exc_info=True, error=str(e))


# --- ✅ Check Duplicate Unit Name ---
async def check_duplicate_unit_name(
    db: AsyncSession,
    name: str,
    parent_id: Optional[int],
    exclude_unit_id: Optional[int] = None
) -> None:
    """
    Kiểm tra xem đã có đơn vị cùng tên trong cùng parent_id chưa.

    Args:
        db: Database session
        name: Tên đơn vị cần kiểm tra
        parent_id: ID của đơn vị cha (None nếu là root)
        exclude_unit_id: ID của đơn vị cần loại trừ (dùng cho update)

    Raises:
        DuplicateResourceError: Nếu đã tồn tại đơn vị cùng tên
    """
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


# --- ✅ 6. Cập nhật hàm `get_all_organization_units` ---
async def get_all_organization_units(db: AsyncSession) -> List[dict]:
    """Lấy danh sách tất cả các đơn vị, hỗ trợ cache và chống cache stampede."""
    log.debug("Fetching all organization units", cache_key=ORG_UNITS_CACHE_KEY)

    # 1. Thử cache trước
    try:
        cached_data = await safe_redis_get(ORG_UNITS_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for organization units")
            return json.loads(cached_data)
    except Exception as e_redis_get:
        log.error("Failed to get organization units from cache", error=str(e_redis_get))

    log.debug("Cache miss for organization units, acquiring lock...")

    # 2. Cache Miss -> Lấy Lock
    async with _org_cache_lock:
        # 2a. Kiểm tra lại cache (phòng trường hợp request khác đã refresh)
        try:
            cached_data_after_lock = await safe_redis_get(ORG_UNITS_CACHE_KEY)
            if cached_data_after_lock:
                log.debug("Cache hit (after lock) for organization units")
                return json.loads(cached_data_after_lock)
        except Exception:
            pass  # Bỏ qua, chúng ta sẽ query lại

        log.debug("Cache miss (after lock), querying DB")

        # 3. Query DB - ✅ PHASE 2: Only fetch active units (soft delete support)
        query = (
            select(models.OrganizationUnit)
            .where(models.OrganizationUnit.is_active == True)  # Only active units
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
        all_units_models = result.scalars().unique().all()

        # 4. Serialize (Chuyển đổi models sang Pydantic rồi sang dict để cache)
        # Bước này rất quan trọng để xử lý các object lồng nhau
        try:
            schemas_list = [
                schemas.OrganizationUnit.model_validate(unit)
                for unit in all_units_models
            ]
            units_data = [s.model_dump() for s in schemas_list]
        except Exception as e_serialize:
            log.error(
                "Failed to serialize organization units for cache",
                error=str(e_serialize),
            )
            # Trả về dữ liệu thô (không cache) nếu lỗi
            return all_units_models

        # 5. Lưu vào cache
        try:
            await safe_redis_set(
                ORG_UNITS_CACHE_KEY, json.dumps(units_data), ex=CACHE_TTL
            )
            log.debug("Stored organization units in cache", ttl=CACHE_TTL)
        except Exception as e_redis_set:
            log.error(
                "Failed to set organization units in cache", error=str(e_redis_set)
            )

        return units_data


# --- Các hàm Read-only khác (giữ nguyên) ---


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


# --- ✅ 7. Cập nhật các hàm GHI (Write) để invalidate cache ---


async def create_organization_unit(
    db: AsyncSession, unit_in: schemas.OrganizationUnitCreate
) -> models.OrganizationUnit:
    try:
        # Check duplicate name
        await check_duplicate_unit_name(db, unit_in.name, unit_in.parent_id)

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

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # 🆕 THÊM EMIT
        await emit_organization_updated(
            operation="create",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

        # Tải lại đầy đủ relations trước khi trả về
        return await get_organization_unit_by_id(db, db_unit.id)
    except Exception as e:
        await db.rollback()
        log.error(
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

        # Check duplicate name if name or parent_id is being changed
        new_name = update_data.get("name", db_unit.name)
        new_parent_id = update_data.get("parent_id", db_unit.parent_id)
        if "name" in update_data or "parent_id" in update_data:
            await check_duplicate_unit_name(
                db, new_name, new_parent_id, exclude_unit_id=unit_id
            )

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

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # 🆕 THÊM EMIT
        await emit_organization_updated(
            operation="update",
            resource_type="organization",
            resource_id=db_unit.id,
            resource_name=db_unit.name
        )

        # Tải lại đầy đủ relations
        return await get_organization_unit_by_id(db, unit_id)
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def delete_organization_unit(db: AsyncSession, unit_id: int):
    """
    ✅ PHASE 2: Soft delete organization unit.

    Sets is_active=false instead of physical deletion to preserve historical data.
    Prevents deletion if unit has active children or majors.
    """
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        unit_name = db_unit.name  # Lưu tên trước khi "xóa"

        # Check for active children (only block if children are active)
        active_children_query = select(models.OrganizationUnit).where(
            models.OrganizationUnit.parent_id == unit_id,
            models.OrganizationUnit.is_active == True
        )
        active_children_result = await db.execute(active_children_query)
        active_children = active_children_result.scalars().all()

        # Check for active majors
        active_majors_query = select(models.Major).where(
            models.Major.unit_id == unit_id,
            models.Major.is_active == True
        )
        active_majors_result = await db.execute(active_majors_query)
        active_majors = active_majors_result.scalars().all()

        if active_children or active_majors:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains active child units or majors."
            )

        # ✅ SOFT DELETE: Set is_active=false instead of physical delete
        db_unit.is_active = False
        db.add(db_unit)
        await db.commit()

        log.info(
            "Organization unit soft-deleted successfully",
            unit_id=unit_id,
            unit_name=unit_name
        )

        await invalidate_org_cache()  # <-- HỦY CACHE

        # 🆕 EMIT
        await emit_organization_updated(
            operation="delete",
            resource_type="organization",
            resource_id=unit_id,
            resource_name=unit_name
        )

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete organization unit",
            unit_id=unit_id,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Major Services (Các hàm này cũng nên HỦY CACHE TỔ CHỨC) ---


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

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE (vì Major là con của Unit)

        # 🆕 THÊM EMIT
        await emit_organization_updated(
            operation="create",
            resource_type="major",
            resource_id=db_major.id,
            resource_name=db_major.name
        )

        return db_major
    except Exception as e:
        await db.rollback()
        log.error(
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

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # 🆕 THÊM EMIT
        await emit_organization_updated(
            operation="update",
            resource_type="major",
            resource_id=db_major.id,
            resource_name=db_major.name
        )

        return db_major
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


async def delete_major(db: AsyncSession, major_id: int):
    """
    ✅ PHASE 2: Soft delete major.

    Sets is_active=false instead of physical deletion to preserve historical data.
    This ensures major academic info history remains queryable.
    """
    try:
        db_major = await get_major_by_id(db, major_id)
        major_name = db_major.name  # Lưu tên trước khi "xóa"

        # ✅ SOFT DELETE: Set is_active=false instead of physical delete
        db_major.is_active = False
        db.add(db_major)
        await db.commit()

        log.info(
            "Major soft-deleted successfully",
            major_id=major_id,
            major_name=major_name
        )

        await invalidate_org_cache()  # <-- HỦY CACHE

        # 🆕 EMIT
        await emit_organization_updated(
            operation="delete",
            resource_type="major",
            resource_id=major_id,
            resource_name=major_name
        )

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete major", major_id=major_id, error=str(e), exc_info=True
        )
        raise e


# --- (Hàm `get_majors_by_unit_tree` giữ nguyên vì nó không dùng cache) ---
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

    # ✅ PHASE 2: Only fetch active majors (soft delete support)
    query = select(models.Major).filter(
        models.Major.unit_id.in_(all_related_unit_ids),
        models.Major.is_active == True  # Only active majors
    )
    if search_term:
        # 1. Làm sạch và tạo pattern an toàn
        safe_pattern = f"%{search_term.strip()}%"

        # 2. Truyền TOÀN BỘ pattern như một tham số
        # SQLAlchemy sẽ tự động escape nó
        query = query.filter(models.Major.name.ilike(safe_pattern))

    majors_result = await db.execute(query.order_by(models.Major.name).limit(20))
    return majors_result.scalars().all()


# =============================================================================
# ✅ PHASE 2: MAJOR ACADEMIC INFO SERVICES (Year-Versioned Data)
# =============================================================================

async def get_academic_info_by_major_and_year(
    db: AsyncSession,
    major_id: int,
    academic_year: int
) -> Optional[models.MajorAcademicInfo]:
    """
    Get academic info for a specific major and academic year.

    Args:
        db: Database session
        major_id: ID of the major
        academic_year: Academic year (e.g., 2024)

    Returns:
        MajorAcademicInfo object or None if not found
    """
    query = select(models.MajorAcademicInfo).where(
        models.MajorAcademicInfo.major_id == major_id,
        models.MajorAcademicInfo.academic_year == academic_year
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_academic_info_history(
    db: AsyncSession,
    major_id: int,
    published_only: bool = False
) -> List[models.MajorAcademicInfo]:
    """
    Get all academic info history for a major, ordered by year descending.

    Args:
        db: Database session
        major_id: ID of the major
        published_only: If True, only return published info

    Returns:
        List of MajorAcademicInfo objects
    """
    query = (
        select(models.MajorAcademicInfo)
        .where(models.MajorAcademicInfo.major_id == major_id)
        .order_by(models.MajorAcademicInfo.academic_year.desc())
    )

    if published_only:
        query = query.where(models.MajorAcademicInfo.is_published == True)

    result = await db.execute(query)
    return result.scalars().all()


async def create_academic_info(
    db: AsyncSession,
    academic_info_in: schemas.MajorAcademicInfoCreate,
    created_by_user_id: Optional[int] = None
) -> models.MajorAcademicInfo:
    """
    Create new academic info for a major and year.

    Args:
        db: Database session
        academic_info_in: Academic info data
        created_by_user_id: ID of user creating the info

    Returns:
        Created MajorAcademicInfo object

    Raises:
        ResourceNotFoundError: If major doesn't exist
        DuplicateResourceError: If academic info already exists for this major/year
    """
    try:
        # Verify major exists
        major = await get_major_by_id(db, academic_info_in.major_id)

        # Check for existing info for this major/year
        existing = await get_academic_info_by_major_and_year(
            db, academic_info_in.major_id, academic_info_in.academic_year
        )
        if existing:
            raise DuplicateResourceError(
                detail=f"Academic info for major {academic_info_in.major_id} "
                       f"and year {academic_info_in.academic_year} already exists."
            )

        # Create new academic info
        db_academic_info = models.MajorAcademicInfo(
            **academic_info_in.model_dump(),
            created_by_user_id=created_by_user_id
        )
        db.add(db_academic_info)
        await db.commit()
        await db.refresh(db_academic_info)

        log.info(
            "Major academic info created successfully",
            major_id=academic_info_in.major_id,
            academic_year=academic_info_in.academic_year,
            created_by=created_by_user_id
        )

        await invalidate_org_cache()  # Invalidate cache (majors include academic info)

        return db_academic_info

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to create major academic info",
            major_id=academic_info_in.major_id,
            year=academic_info_in.academic_year,
            error=str(e),
            exc_info=True
        )
        raise e


async def update_academic_info(
    db: AsyncSession,
    academic_info_id: int,
    academic_info_in: schemas.MajorAcademicInfoUpdate
) -> models.MajorAcademicInfo:
    """
    Update existing academic info.

    Args:
        db: Database session
        academic_info_id: ID of academic info to update
        academic_info_in: Updated data

    Returns:
        Updated MajorAcademicInfo object

    Raises:
        ResourceNotFoundError: If academic info doesn't exist
    """
    try:
        db_academic_info = await db.get(models.MajorAcademicInfo, academic_info_id)
        if not db_academic_info:
            raise ResourceNotFoundError(
                detail=f"Academic info with id {academic_info_id} not found."
            )

        update_data = academic_info_in.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(db_academic_info, key, value)

        db.add(db_academic_info)
        await db.commit()
        await db.refresh(db_academic_info)

        log.info(
            "Major academic info updated successfully",
            academic_info_id=academic_info_id,
            major_id=db_academic_info.major_id,
            academic_year=db_academic_info.academic_year
        )

        await invalidate_org_cache()

        return db_academic_info

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to update major academic info",
            academic_info_id=academic_info_id,
            error=str(e),
            exc_info=True
        )
        raise e


async def delete_academic_info(db: AsyncSession, academic_info_id: int):
    """
    Delete academic info.

    This is a hard delete since academic info is versioned per year.
    If you need to preserve history, consider marking as unpublished instead.

    Args:
        db: Database session
        academic_info_id: ID of academic info to delete

    Raises:
        ResourceNotFoundError: If academic info doesn't exist
    """
    try:
        db_academic_info = await db.get(models.MajorAcademicInfo, academic_info_id)
        if not db_academic_info:
            raise ResourceNotFoundError(
                detail=f"Academic info with id {academic_info_id} not found."
            )

        major_id = db_academic_info.major_id
        academic_year = db_academic_info.academic_year

        await db.delete(db_academic_info)
        await db.commit()

        log.info(
            "Major academic info deleted successfully",
            academic_info_id=academic_info_id,
            major_id=major_id,
            academic_year=academic_year
        )

        await invalidate_org_cache()

    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to delete major academic info",
            academic_info_id=academic_info_id,
            error=str(e),
            exc_info=True
        )
        raise e


# =============================================================================
# ✅ PHASE 4: TREE WITH AGGREGATION FUNCTIONS
# =============================================================================

async def get_organization_tree_with_aggregation(
    db: AsyncSession,
    academic_year: Optional[int] = None,
    include_inactive: bool = False
) -> List[schemas.OrganizationTreeNodeWithAggregation]:
    """
    Lấy cây tổ chức với thông tin ngành học và dữ liệu tổng hợp.

    Args:
        db: Database session
        academic_year: Năm học cần lấy thông tin (mặc định là năm hiện tại)
        include_inactive: Có bao gồm các đơn vị không hoạt động không

    Returns:
        List of root organization units with aggregated data
    """
    from decimal import Decimal

    # 1. Xác định năm học
    if academic_year is None:
        academic_year = datetime.now().year

    log.info(
        "Building organization tree with aggregation",
        academic_year=academic_year,
        include_inactive=include_inactive
    )

    # 2. Query tất cả units với majors và academic info
    query = (
        select(models.OrganizationUnit)
        .options(
            selectinload(models.OrganizationUnit.majors).selectinload(
                models.Major.academic_info_history
            ),
            selectinload(models.OrganizationUnit.children)
        )
        .order_by(models.OrganizationUnit.name)
    )

    if not include_inactive:
        query = query.where(models.OrganizationUnit.is_active == True)

    result = await db.execute(query)
    all_units = result.scalars().unique().all()

    # 3. Tạo map để dễ tìm kiếm
    units_map = {unit.id: unit for unit in all_units}

    # 4. Build tree với aggregation
    def build_node_with_aggregation(unit: models.OrganizationUnit) -> schemas.OrganizationTreeNodeWithAggregation:
        """Build a tree node with aggregated statistics"""

        # Lấy majors của unit này với academic info
        majors_with_stats = []
        direct_total_quota = 0
        tuition_fees = []

        for major in unit.majors:
            if not major.is_active:
                continue

            # Tìm academic info cho năm học này
            academic_info = None
            for info in major.academic_info_history:
                if info.academic_year == academic_year and info.is_published:
                    academic_info = info
                    break

            # Build MajorWithStats
            major_stats = schemas.MajorWithStats(
                id=major.id,
                name=major.name,
                code=major.code,
                total_admission_quota=academic_info.annual_admission_quota if academic_info else None,
                tuition_fee=academic_info.tuition_fee_per_year if academic_info else None
            )
            majors_with_stats.append(major_stats)

            # Collect stats for aggregation
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

        # Aggregate statistics from children
        total_majors = len(majors_with_stats)
        total_quota = direct_total_quota
        all_tuition_fees = tuition_fees.copy()

        for child in children_nodes:
            total_majors += child.stats.total_majors
            if child.stats.total_admission_quota:
                total_quota += child.stats.total_admission_quota
            # Collect tuition fees from children for avg/min/max calculation
            if child.stats.min_tuition_fee:
                all_tuition_fees.append(child.stats.min_tuition_fee)
            if child.stats.max_tuition_fee:
                all_tuition_fees.append(child.stats.max_tuition_fee)

        # Calculate aggregated tuition fee stats
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
        node = schemas.OrganizationTreeNodeWithAggregation(
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

        return node

    # 5. Build root nodes (units without parent)
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
        total_units=len(all_units)
    )

    return root_nodes
