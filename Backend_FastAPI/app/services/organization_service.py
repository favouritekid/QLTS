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

        # 3. Query DB (Logic cũ)
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
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        unit_name = db_unit.name  # Lưu tên trước khi xóa

        if db_unit.children or db_unit.majors:
            raise DuplicateResourceError(
                detail="Cannot delete unit: It contains child units or majors."
            )
        await db.delete(db_unit)
        await db.commit()

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # 🆕 THÊM EMIT
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
    try:
        db_major = await get_major_by_id(db, major_id)
        major_name = db_major.name  # Lưu tên trước khi xóa

        await db.delete(db_major)
        await db.commit()

        await invalidate_org_cache()  # <-- THÊM HỦY CACHE

        # 🆕 THÊM EMIT
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

    query = select(models.Major).filter(models.Major.unit_id.in_(all_related_unit_ids))
    if search_term:
        # 1. Làm sạch và tạo pattern an toàn
        safe_pattern = f"%{search_term.strip()}%"

        # 2. Truyền TOÀN BỘ pattern như một tham số
        # SQLAlchemy sẽ tự động escape nó
        query = query.filter(models.Major.name.ilike(safe_pattern))

    majors_result = await db.execute(query.order_by(models.Major.name).limit(20))
    return majors_result.scalars().all()
