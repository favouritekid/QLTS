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
# ✅ REMOVED (Priority 2): import asyncio (no longer needed - using redis_distributed_lock)
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, List, Optional, Tuple  # ✅ ADD Callable, Tuple for transaction pattern

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from .. import models, schemas
from ..config import settings
from ..database import safe_redis_delete, safe_redis_get, safe_redis_set, redis_distributed_lock
from ..repositories import OrganizationRepository
from ..socket_manager import emit_to_all
from ..core.constants import UserRole
from ..utils.exceptions import BadRequest, DuplicateResourceError, ForbiddenError, ResourceNotFoundError

log = structlog.get_logger(__name__)


# =============================================================================
# BUSINESS LOGIC CONSTANTS
# =============================================================================

# Unit types that are allowed to manage academic programs (major/degree)
# Only academic units (Khoa, Bộ môn, Trung tâm) can have major programs
ALLOWED_ACADEMIC_UNIT_TYPES = {
    schemas.OrganizationUnitType.KHOA.value,        # "Khoa"
    schemas.OrganizationUnitType.BO_MON.value,      # "Bộ môn"
    schemas.OrganizationUnitType.TRUNG_TAM.value,   # "Trung tâm"
}


# =============================================================================
# HELPER FUNCTIONS (Module Level - exportable)
# =============================================================================

def create_recursive_unit_loader(depth: int):
    """
    Create recursive loader for organization units with programs.
    
    ✅ SPRINT 4 HOTFIX: Moved to module level for OrganizationRepository import.
    
    Args:
        depth: Maximum depth for recursive loading
        
    Returns:
        SQLAlchemy selectinload option for recursive children loading
    """
    if depth <= 0:
        return selectinload(models.OrganizationUnit.major_programs).selectinload(
            models.MajorProgram.offerings
        ).selectinload(
            models.ProgramOffering.academic_info_history
        ).selectinload(
            models.OfferingAcademicInfo.semester_tuitions
        )  # Base case: just load programs

    return selectinload(models.OrganizationUnit.children).options(
        selectinload(models.OrganizationUnit.major_programs).selectinload(
            models.MajorProgram.offerings
        ).selectinload(
            models.ProgramOffering.academic_info_history
        ).selectinload(
            models.OfferingAcademicInfo.semester_tuitions
        ),
        create_recursive_unit_loader(depth - 1)
    )


# =============================================================================
# JSON ENCODER FOR DECIMAL
# =============================================================================

class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts Decimal to float and datetime to ISO format."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# Cache configuration
ORG_UNITS_CACHE_KEY = "org:all_units_tree"
ORG_TREE_AGG_CACHE_KEY = "org:tree_with_aggregation"  # Cache key for aggregation tree
CACHE_TTL = settings.CONFIG_CACHE_TTL_SECONDS
# ✅ REMOVED (Priority 2 - Deep Dive Audit): asyncio.Lock() replaced with redis_distributed_lock
# OLD: _org_cache_lock = asyncio.Lock()  # Only works within ONE process!
# NEW: Using redis_distributed_lock() for multi-worker support


# =============================================================================
# CACHE INVALIDATION & NOTIFICATIONS
# =============================================================================

async def invalidate_org_cache():
    """Invalidate all organization tree caches."""
    try:
        # Invalidate both basic tree and aggregation caches
        await safe_redis_delete(ORG_UNITS_CACHE_KEY)
        await safe_redis_delete(ORG_TREE_AGG_CACHE_KEY)
        log.info("Organization caches invalidated", keys=[ORG_UNITS_CACHE_KEY, ORG_TREE_AGG_CACHE_KEY])
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
                "timestamp": datetime.now(timezone.utc).isoformat()
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
# ACCESS CONTROL HELPERS (IDOR PROTECTION)
# =============================================================================

async def _check_unit_access(
    db: AsyncSession,
    unit_id: int,
    current_user: models.User,
    allow_read_only: bool = False
) -> models.OrganizationUnit:
    """
    INTERNAL: Rigorous unit-level access check (IDOR protection).
    
    Ensures that current_user has permission to view/modify the unit_id.
    Standardized across all service operations.
    """
    from app.core import deps
    return await deps.get_organizational_unit_for_user(
        unit_id=unit_id,
        db=db,
        current_user=current_user,
        allow_read_only=allow_read_only
    )


async def _get_managed_unit_ids(db: AsyncSession, user_id: int) -> List[int]:
    """Get list of unit IDs that a user manages (via UserRepository)."""
    from ..repositories import UserRepository

    repo = UserRepository(db)
    return await repo.get_managed_unit_ids(user_id)


def _filter_tree_by_managed_units(
    tree: List[dict], managed_ids: set
) -> List[dict]:
    """
    Filter organization tree to only show units managed by the user.

    Walks the tree and extracts subtrees rooted at managed units.
    Descendants of managed units are included automatically (nested structure).

    Args:
        tree: List of root-level org unit dicts with nested 'children'
        managed_ids: Set of unit IDs the Manager directly manages

    Returns:
        Filtered list of org unit dicts
    """
    result = []
    for node in tree:
        if node.get("id") in managed_ids:
            # Include this node with all its children (user manages it)
            result.append(node)
        else:
            # Recurse into children to find managed units deeper in tree
            children = node.get("children", [])
            if children:
                filtered = _filter_tree_by_managed_units(children, managed_ids)
                result.extend(filtered)
    return result


# =============================================================================
# ORGANIZATION UNIT SERVICES
# =============================================================================

async def check_duplicate_unit_name(
    db: AsyncSession,
    name: str,
    parent_id: Optional[int],
    exclude_unit_id: Optional[int] = None
) -> None:
    """
    Check for duplicate unit name within the same parent.

    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    
    IMPORTANT: Only checks active units (is_active=True) to avoid
    the "Zombie Data Problem" where soft-deleted units prevent
    creating new units with the same name.
    """
    repo = OrganizationRepository(db)
    existing = await repo.check_duplicate_name(name, parent_id, exclude_unit_id)

    if existing:
        parent_name = "cấp gốc" if parent_id is None else f"đơn vị cha #{parent_id}"
        raise DuplicateResourceError(
            detail=f"Đã tồn tại đơn vị '{name}' trong {parent_name}"
        )


async def _get_user_counts_by_unit(db: AsyncSession) -> dict:
    """
    Get user counts grouped by unit_id.
    
    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.

    Returns:
        Dict mapping unit_id -> user_count
    """
    repo = OrganizationRepository(db)
    return await repo.get_user_counts_by_unit()


def _add_user_counts_to_tree(units_data: List[dict], user_counts: dict) -> List[dict]:
    """
    Recursively add user_count to each unit in the tree.
    Parent units show aggregated counts from all descendants.

    Args:
        units_data: List of unit dicts (tree structure)
        user_counts: Dict mapping unit_id -> direct user_count

    Returns:
        Updated units_data with aggregated user_count field
    """
    def calculate_total_users(unit: dict) -> int:
        """Calculate total users for a unit including all descendants."""
        direct_count = user_counts.get(unit["id"], 0)
        children_count = 0
        if unit.get("children"):
            for child in unit["children"]:
                children_count += calculate_total_users(child)
        total = direct_count + children_count
        unit["user_count"] = total
        return total

    for unit in units_data:
        calculate_total_users(unit)
    return units_data


async def get_all_organization_units(
    db: AsyncSession,
    current_user=None,
) -> List[dict]:
    """
    Get all organization units as a tree structure with caching support.

    Args:
        db: Database session
        current_user: If provided, filters tree by user's role/managed units (M12 fix)

    Returns:
        List of root organization units with nested children, major_programs, and user_count
    """
    log.debug("Fetching all organization units", cache_key=ORG_UNITS_CACHE_KEY)

    # Try cache first
    try:
        cached_data = await safe_redis_get(ORG_UNITS_CACHE_KEY)
        if cached_data:
            log.debug("Cache hit for organization units")
            units_data = json.loads(cached_data)
            # ✅ M12 FIX: Filter by role after cache read
            return await _apply_unit_scoping(db, units_data, current_user)
    except Exception as e:
        log.error("Failed to get from cache", error=str(e))

    log.debug("Cache miss, acquiring distributed lock...")

    # ✅ PRIORITY 2 FIX (Deep Dive Audit): Use Redis distributed lock
    # Replaces asyncio.Lock() to support multi-worker deployments (uvicorn --workers, K8s, Docker)
    async with redis_distributed_lock("org_cache_rebuild", timeout=30):
        # Double-check cache after acquiring lock
        try:
            cached_data = await safe_redis_get(ORG_UNITS_CACHE_KEY)
            if cached_data:
                log.debug("Cache hit after lock")
                units_data = json.loads(cached_data)
                return await _apply_unit_scoping(db, units_data, current_user)
        except Exception:
            pass

        log.debug("Querying database for organization tree")

        # ✅ SPRINT 4 HOTFIX: Use module-level create_recursive_unit_loader
        # (moved to module level for OrganizationRepository import)

        # ✅ SPRINT 3 REFACTORED: Use Repository for tree loading
        repo = OrganizationRepository(db)
        root_units = await repo.get_tree_with_programs(depth=9)

        # Get user counts per unit
        user_counts = await _get_user_counts_by_unit(db)
        log.debug("Got user counts for units", total_units_with_users=len(user_counts))

        # Serialize to JSON using Pydantic schemas
        try:
            units_data = [
                schemas.OrganizationUnit.model_validate(unit, from_attributes=True).model_dump()
                for unit in root_units
            ]
        except Exception as e:
            log.error("Failed to serialize organization tree", error=str(e), exc_info=True)
            raise

        # Add user counts to each unit in the tree
        units_data = _add_user_counts_to_tree(units_data, user_counts)

        # Cache the result (full tree, filtering happens per-request)
        try:
            await safe_redis_set(
                ORG_UNITS_CACHE_KEY,
                json.dumps(units_data, cls=DecimalEncoder),
                ex=CACHE_TTL
            )
            log.debug("Cached organization tree", ttl=CACHE_TTL)
        except Exception as e:
            log.error("Failed to cache organization tree", error=str(e))

        # ✅ M12 FIX: Filter by role before returning
        return await _apply_unit_scoping(db, units_data, current_user)


async def _apply_unit_scoping(
    db: AsyncSession, units_data: List[dict], current_user=None
) -> List[dict]:
    """
    Filter organization tree by user's role and managed units (M12 fix).

    - Admin: full access (no filtering)
    - Manager: only managed units and their subtrees
    - Officer: only their own unit subtree
    - Other: no filtering (Casbin handles endpoint access)
    """
    if current_user is None:
        return units_data

    role = getattr(current_user, "role", None)

    if role == UserRole.ADMIN:
        return units_data

    if role == UserRole.MANAGER:
        managed_ids = await _get_managed_unit_ids(db, current_user.id)
        if not managed_ids:
            return []
        filtered = _filter_tree_by_managed_units(units_data, set(managed_ids))
        log.debug(
            "Filtered org tree for Manager",
            user_id=current_user.id,
            managed_ids=managed_ids,
            result_count=len(filtered),
        )
        return filtered

    if role == UserRole.OFFICER:
        unit_id = getattr(current_user, "unit_id", None)
        if not unit_id:
            return []
        filtered = _filter_tree_by_managed_units(units_data, {unit_id})
        return filtered

    # Other roles: return full tree (Casbin controls endpoint access)
    return units_data


async def _get_allowed_unit_ids_for_user(
    db: AsyncSession, current_user
) -> Optional[set]:
    """
    Get set of unit IDs the user is allowed to see (including descendants).

    Returns:
        None = full access (Admin or no user context)
        set() = no access
        set({1,2,3}) = restricted to these unit IDs
    """
    if current_user is None:
        return None

    role = getattr(current_user, "role", None)
    if role == UserRole.ADMIN:
        return None

    repo = OrganizationRepository(db)

    if role == UserRole.MANAGER:
        managed_ids = await _get_managed_unit_ids(db, current_user.id)
        if not managed_ids:
            return set()
        allowed = set()
        for mid in managed_ids:
            descendants = await repo.get_descendant_unit_ids(mid)
            allowed.update(descendants)
        return allowed

    if role == UserRole.OFFICER:
        unit_id = getattr(current_user, "unit_id", None)
        if unit_id:
            descendants = await repo.get_descendant_unit_ids(unit_id)
            return set(descendants)
        return set()

    return None  # Other roles: no filtering (Casbin controls endpoint access)


async def get_organization_unit_by_id(
    db: AsyncSession,
    unit_id: int
) -> models.OrganizationUnit:
    """
    Get organization unit by ID with all relationships loaded.
    
    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    """
    repo = OrganizationRepository(db)
    unit = await repo.get_by_id_full(unit_id)
    
    if not unit:
        raise ResourceNotFoundError(
            detail=f"Organization Unit with id {unit_id} not found."
        )
    return unit


async def create_organization_unit(
    db: AsyncSession,
    unit_in: schemas.OrganizationUnitCreate,
    current_user: models.User
) -> Tuple[models.OrganizationUnit, Callable]:
    """
    Create a new organization unit.

    ✅ IDOR: Verify parent unit access.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (organization_unit, post_commit_callback)
    """
    try:
        # ✅ IDOR: If parent is specified, must have access to it
        if unit_in.parent_id:
            await _check_unit_access(db, unit_in.parent_id, current_user)

        # Check duplicate name
        await check_duplicate_unit_name(db, unit_in.name, unit_in.parent_id)

        # Verify parent exists if specified
        if unit_in.parent_id:
            repo = OrganizationRepository(db)
            parent_unit = await repo.get_by_id(unit_in.parent_id)
            if not parent_unit:
                raise ResourceNotFoundError(
                    detail=f"Parent unit with id {unit_in.parent_id} not found."
                )

        db_unit = models.OrganizationUnit(**unit_in.model_dump())
        db.add(db_unit)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_unit)

        # Get full unit with relationships
        result_unit = await get_organization_unit_by_id(db, db_unit.id)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="create",
                resource_type="organization",
                resource_id=db_unit.id,
                resource_name=db_unit.name
            )

        return result_unit, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create organization unit", error=str(e), exc_info=True)
        raise


async def check_circular_dependency(
    db: AsyncSession,
    unit_id: int,
    new_parent_id: int
) -> None:
    """
    Check if setting new_parent_id as parent of unit_id would create a circular dependency.

    Algorithm: Use Recursive CTE to fetch entire ancestor chain from new_parent_id in ONE query.
    If unit_id appears in the ancestor chain, setting this relationship would create a cycle.

    Performance: O(1) query instead of O(depth) queries.

    Args:
        db: Database session
        unit_id: ID of the unit being updated
        new_parent_id: ID of the proposed new parent

    Raises:
        DuplicateResourceError: If circular dependency detected
    """
    if new_parent_id is None:
        return  # No parent = no cycle possible

    if unit_id == new_parent_id:
        raise DuplicateResourceError(
            detail="Một đơn vị không thể là đơn vị cha của chính nó."
        )

    # ✅ SPRINT 3 REFACTORED: Use Repository for cycle detection
    repo = OrganizationRepository(db)
    found_cycle = await repo.check_cycle_in_hierarchy(unit_id, new_parent_id)

    if found_cycle:
        raise DuplicateResourceError(
            detail="Không thể tạo mối quan hệ vòng lặp trong cây đơn vị. "
                   "Đơn vị cha được chọn là con/cháu của đơn vị hiện tại."
        )


async def update_organization_unit(
    db: AsyncSession,
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    current_user: models.User
) -> Tuple[models.OrganizationUnit, Callable]:
    """
    Update an organization unit.

    ✅ IDOR: Verify access to target unit and new parent.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (organization_unit, post_commit_callback)
    """
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        
        # ✅ IDOR: Must have access to target unit
        await _check_unit_access(db, unit_id, current_user)

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
                # ✅ IDOR: Must have access to new parent
                await _check_unit_access(db, new_parent_id, current_user)

                # Check for circular dependency (includes self-parent check)
                await check_circular_dependency(db, unit_id, new_parent_id)

                # Verify parent exists
                repo = OrganizationRepository(db)
                parent_unit = await repo.get_by_id(new_parent_id)
                if not parent_unit:
                    raise ResourceNotFoundError(
                        detail=f"Parent unit with id {new_parent_id} not found."
                    )

        # Apply updates
        for key, value in update_data.items():
            setattr(db_unit, key, value)

        db.add(db_unit)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # Get full unit with relationships
        result_unit = await get_organization_unit_by_id(db, unit_id)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="update",
                resource_type="organization",
                resource_id=db_unit.id,
                resource_name=db_unit.name
            )

        return result_unit, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to update organization unit", error=str(e), exc_info=True)
        raise


async def delete_organization_unit(
    db: AsyncSession, 
    unit_id: int,
    current_user: models.User
) -> Tuple[None, Callable]:
    """
    Soft delete an organization unit.

    ✅ IDOR: Verify access to target unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Sets is_active=False to preserve historical data.
    Prevents deletion if unit has active children or programs.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        db_unit = await get_organization_unit_by_id(db, unit_id)
        unit_name = db_unit.name

        # ✅ IDOR: Must have access to target unit
        await _check_unit_access(db, unit_id, current_user)

        # ✅ SPRINT 3 REFACTORED: Use Repository for validation checks
        repo = OrganizationRepository(db)
        
        # Check counts via repository
        active_children_count = await repo.count_active_children(unit_id)
        active_programs_count = await repo.count_active_programs(unit_id)
        assigned_users_count = await repo.count_assigned_users(unit_id)

        # Build error message based on what's blocking deletion
        blocking_reasons = []
        if active_children_count > 0:
            blocking_reasons.append(f"{active_children_count} đơn vị con đang hoạt động")
        if active_programs_count > 0:
            blocking_reasons.append(f"{active_programs_count} chương trình đào tạo đang hoạt động")
        if assigned_users_count > 0:
            blocking_reasons.append(f"{assigned_users_count} người dùng đang thuộc đơn vị này")

        if blocking_reasons:
            reasons_str = ", ".join(blocking_reasons)
            raise DuplicateResourceError(
                detail=f"Không thể xóa đơn vị '{unit_name}': {reasons_str}. "
                       "Vui lòng chuyển hoặc xóa các mục này trước khi xóa đơn vị."
            )

        # Soft delete
        db_unit.is_active = False
        db.add(db_unit)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Organization unit soft-deleted", unit_id=unit_id, unit_name=unit_name)
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="delete",
                resource_type="organization",
                resource_id=unit_id,
                resource_name=unit_name
            )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to delete organization unit", error=str(e), exc_info=True)
        raise


# =============================================================================
# MAJOR PROGRAM (LEVEL 1) SERVICES
# =============================================================================

async def get_major_program_by_id(
    db: AsyncSession,
    program_id: int
) -> models.MajorProgram:
    """
    Get major program by ID with all offerings and academic info loaded.
    
    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    """
    repo = OrganizationRepository(db)
    program = await repo.get_major_program_by_id_full(program_id)
    
    if not program:
        raise ResourceNotFoundError(
            detail=f"MajorProgram with id {program_id} not found."
        )
    return program


async def create_major_program(
    db: AsyncSession,
    program_in: schemas.MajorProgramCreate,
    current_user: models.User
) -> Tuple[models.MajorProgram, Callable]:
    """
    Create a new major program.

    ✅ IDOR: Verify access to unit_id.

    ✅ SPRINT 3 REFACTORED: Uses OrganizationRepository for duplicate check.
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (major_program, post_commit_callback)
    """
    try:
        # ✅ IDOR: Must have access to unit_id
        await _check_unit_access(db, program_in.unit_id, current_user)

        repo = OrganizationRepository(db)
        
        # Check duplicate code via repository
        existing = await repo.check_duplicate_program_code(program_in.code)
        if existing:
            raise DuplicateResourceError(
                detail=f"Major program with code '{program_in.code}' already exists."
            )

        # Verify unit exists
        unit = await repo.get_by_id(program_in.unit_id)
        if not unit:
            raise ResourceNotFoundError(
                detail=f"Organization unit with id {program_in.unit_id} not found."
            )

        # Validate unit type - only academic units can manage major programs
        if unit.type not in ALLOWED_ACADEMIC_UNIT_TYPES:
            allowed_types_str = ", ".join(ALLOWED_ACADEMIC_UNIT_TYPES)
            raise DuplicateResourceError(
                detail=f"Đơn vị loại '{unit.type}' không được phép quản lý chương trình đào tạo. "
                       f"Chỉ các đơn vị sau mới có thể quản lý ngành học: {allowed_types_str}"
            )

        db_program = models.MajorProgram(**program_in.model_dump())
        db.add(db_program)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_program)

        # Get full program with relationships
        result_program = await get_major_program_by_id(db, db_program.id)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Major program created", program_id=db_program.id, code=db_program.code)
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="create",
                resource_type="program",
                resource_id=db_program.id,
                resource_name=db_program.name
            )

        return result_program, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create major program", error=str(e), exc_info=True)
        raise


async def update_major_program(
    db: AsyncSession,
    program_id: int,
    program_in: schemas.MajorProgramUpdate,
    current_user: models.User
) -> Tuple[models.MajorProgram, Callable]:
    """
    Update a major program. Note: code cannot be updated.

    ✅ IDOR: Verify access to program's unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (major_program, post_commit_callback)
    """
    try:
        db_program = await get_major_program_by_id(db, program_id)
        
        # ✅ IDOR: Must have access to unit managing this program
        await _check_unit_access(db, db_program.unit_id, current_user)

        update_data = program_in.model_dump(exclude_unset=True)

        # Code cannot be updated (business rule)
        if "code" in update_data:
            del update_data["code"]
            log.warning("Attempted to update program code (not allowed)", program_id=program_id)

        # Apply updates
        for key, value in update_data.items():
            setattr(db_program, key, value)

        db.add(db_program)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # Get full program with relationships
        result_program = await get_major_program_by_id(db, program_id)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Major program updated", program_id=program_id)
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="update",
                resource_type="program",
                resource_id=db_program.id,
                resource_name=db_program.name
            )

        return result_program, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to update major program", error=str(e), exc_info=True)
        raise


async def delete_major_program(
    db: AsyncSession, 
    program_id: int,
    current_user: models.User
) -> Tuple[None, Callable]:
    """
    Soft delete a Major Program and CASCADE soft delete to all its Program Offerings.

    ✅ IDOR: Verify access to program's unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Performance Optimized: Uses Bulk Update instead of Loop.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        # 1. Kiểm tra tồn tại (để lấy tên log và confirm ID hợp lệ)
        db_program = await get_major_program_by_id(db, program_id)
        
        # ✅ IDOR: Must have access to unit managing this program
        await _check_unit_access(db, db_program.unit_id, current_user)

        program_name = db_program.name
        program_code = db_program.code

        # 2. Thực hiện Soft Delete (Set is_active = False)

        # 2a. Xóa mềm Ngành học (Level 1)
        db_program.is_active = False
        db.add(db_program)

        # 2b. ✅ CASCADE: Xóa mềm hàng loạt Loại hình con (Level 2)
        # Sử dụng Bulk Update để tối ưu hiệu năng (1 Query duy nhất)
        stmt_offerings = (
            update(models.ProgramOffering)
            .where(models.ProgramOffering.program_id == program_id)
            .values(is_active=False)
            .execution_options(synchronize_session=False) # Bỏ qua sync session để nhanh hơn
        )
        await db.execute(stmt_offerings)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Major program deleted", program_id=program_id, name=program_name)
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="delete",
                resource_type="program",
                resource_id=program_id,
                resource_name=program_name
            )
            
        return None, _post_commit


    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to delete major program", error=str(e), exc_info=True)
        raise


# =============================================================================
# PROGRAM OFFERING (LEVEL 2) SERVICES
# =============================================================================

async def get_program_offering_by_id(
    db: AsyncSession,
    offering_id: int
) -> models.ProgramOffering:
    """
    Get program offering by ID with academic info loaded.
    
    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    """
    repo = OrganizationRepository(db)
    offering = await repo.get_offering_by_id_full(offering_id)
    
    if not offering:
        raise ResourceNotFoundError(
            detail=f"ProgramOffering with id {offering_id} not found."
        )
    return offering


async def create_program_offering(
    db: AsyncSession,
    offering_in: schemas.ProgramOfferingCreate,
    current_user: models.User
) -> Tuple[models.ProgramOffering, Callable]:
    """
    Create a new program offering.

    ✅ IDOR: Verify access to program's unit.

    ✅ SPRINT 3 REFACTORED: Uses OrganizationRepository for duplicate check.
    
    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (program_offering, post_commit_callback)
    """
    try:
        repo = OrganizationRepository(db)
        
        # Verify program exists
        program = await repo.get_major_program_by_id_full(offering_in.program_id)
        if not program:
            raise ResourceNotFoundError(
                detail=f"Major program with id {offering_in.program_id} not found."
            )

        # ✅ IDOR: Must have access to unit managing this program
        await _check_unit_access(db, program.unit_id, current_user)

        # Check duplicate (program_id, offering_type) via repository
        existing = await repo.check_duplicate_offering(
            offering_in.program_id, 
            offering_in.offering_type
        )
        if existing:
            raise DuplicateResourceError(
                detail=f"Offering '{offering_in.offering_type}' already exists for this program."
            )

        db_offering = models.ProgramOffering(**offering_in.model_dump())
        db.add(db_offering)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_offering)

        # Get full offering with relationships
        result_offering = await get_program_offering_by_id(db, db_offering.id)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
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

        return result_offering, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create program offering", error=str(e), exc_info=True)
        raise


async def update_program_offering(
    db: AsyncSession,
    offering_id: int,
    offering_in: schemas.ProgramOfferingUpdate,
    current_user: models.User
) -> Tuple[models.ProgramOffering, Callable]:
    """
    Update a program offering.

    ✅ IDOR: Verify access to program's unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (program_offering, post_commit_callback)
    """
    try:
        db_offering = await get_program_offering_by_id(db, offering_id)
        
        # ✅ IDOR: Must have access to unit managing this program
        program = await get_major_program_by_id(db, db_offering.program_id)
        await _check_unit_access(db, program.unit_id, current_user)

        update_data = offering_in.model_dump(exclude_unset=True)

        # ✅ SPRINT 3 REFACTORED: Use Repository for duplicate check
        if "offering_type" in update_data and update_data["offering_type"] != db_offering.offering_type:
            repo = OrganizationRepository(db)
            existing = await repo.check_duplicate_offering(
                db_offering.program_id,
                update_data["offering_type"],
                exclude_id=offering_id
            )
            if existing:
                raise DuplicateResourceError(
                    detail=f"Offering '{update_data['offering_type']}' already exists for this program."
                )

        # Apply updates
        for key, value in update_data.items():
            setattr(db_offering, key, value)

        db.add(db_offering)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # Get full offering with relationships
        result_offering = await get_program_offering_by_id(db, offering_id)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Program offering updated", offering_id=offering_id)
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="update",
                resource_type="offering",
                resource_id=db_offering.id,
                resource_name=db_offering.offering_type
            )

        return result_offering, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to update program offering", error=str(e), exc_info=True)
        raise


async def delete_program_offering(
    db: AsyncSession, 
    offering_id: int,
    current_user: models.User
) -> Tuple[None, Callable]:
    """
    Soft delete a program offering.

    ✅ IDOR: Verify access to program's unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Cascade will also delete associated academic info records.

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        db_offering = await get_program_offering_by_id(db, offering_id)
        
        # ✅ IDOR: Must have access to unit managing this program
        program = await get_major_program_by_id(db, db_offering.program_id)
        await _check_unit_access(db, program.unit_id, current_user)

        offering_name = db_offering.offering_type

        # Soft delete
        db_offering.is_active = False
        db.add(db_offering)

        # ✅ CASCADE: Soft delete related academic info
        stmt_academic = (
            update(models.OfferingAcademicInfo)
            .where(models.OfferingAcademicInfo.offering_id == offering_id)
            .values(is_deleted=True, updated_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False)
        )
        await db.execute(stmt_academic)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info("Program offering soft-deleted", offering_id=offering_id, offering_name=offering_name)
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="delete",
                resource_type="offering",
                resource_id=offering_id,
                resource_name=offering_name
            )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
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
    repo = OrganizationRepository(db)
    academic_info = await repo.get_academic_info_by_id(academic_info_id)
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
    """
    Get academic info for a specific offering and year.
    
    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    """
    repo = OrganizationRepository(db)
    return await repo.get_academic_info_by_offering_and_year(offering_id, academic_year)


async def get_current_academic_info(
    db: AsyncSession,
    offering_id: int
) -> Optional[models.OfferingAcademicInfo]:
    """
    Get current year's published academic info for an offering.
    
    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    """
    repo = OrganizationRepository(db)
    current_year = datetime.now(timezone.utc).year
    return await repo.get_current_academic_info(offering_id, current_year)


async def get_academic_info_history(
    db: AsyncSession,
    offering_id: int,
    published_only: bool = False
) -> List[models.OfferingAcademicInfo]:
    """
    Get all academic info history for an offering, ordered by year (newest first).

    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    
    Args:
        db: Database session
        offering_id: ID of the program offering
        published_only: If True, only return published academic info

    Returns:
        List of academic info records ordered by academic_year descending
    """
    repo = OrganizationRepository(db)
    return await repo.get_academic_info_history(offering_id, published_only)


async def _validate_discount_policy_ids(
    db: AsyncSession, policy_ids: Optional[List[int]]
) -> None:
    """Chặn gắn chính sách ưu đãi KHÔNG tồn tại / đã ngừng hoạt động cho ngành.

    ``applied_discount_policy_ids`` là NGUỒN quyết định "ngành này được giảm
    theo chính sách nào" (``fee_pricing`` chỉ áp chính sách được gắn tường minh
    ở đây, không tự suy diễn). Cột là JSONB không có ràng buộc khoá ngoại, nên
    một id gõ nhầm hoặc một chính sách đã tắt nằm im trong cấu hình mà không ai
    biết: lúc tính phí, engine lặng lẽ bỏ qua và kế toán thấy "đã bật ưu đãi mà
    không giảm đồng nào". Bắt tại chỗ CẤU HÌNH thì người sửa được ngay.

    Chính sách CHƯA tới hạn / ĐÃ hết hạn vẫn cho gắn (chuẩn bị cho đợt sau, hoặc
    giữ lại lịch sử) — hiệu lực theo ngày do engine xét tại thời điểm tính phí.
    """
    if not policy_ids:
        return

    unique = list(dict.fromkeys(policy_ids))
    if len(unique) != len(policy_ids):
        raise BadRequest(
            detail="Danh sách chính sách ưu đãi có id trùng lặp."
        )

    rows = (
        await db.execute(
            select(models.TuitionDiscountPolicy).where(
                models.TuitionDiscountPolicy.id.in_(unique)
            )
        )
    ).scalars().all()
    found = {p.id: p for p in rows}

    missing = [pid for pid in unique if pid not in found]
    if missing:
        raise BadRequest(
            detail="Chính sách ưu đãi không tồn tại: "
                   + ", ".join(str(pid) for pid in missing)
        )

    inactive = [found[pid] for pid in unique if not found[pid].is_active]
    if inactive:
        raise BadRequest(
            detail="Chính sách ưu đãi đã ngừng hoạt động, không gắn được cho "
                   "ngành: " + ", ".join(f"{p.name} (id {p.id})" for p in inactive)
        )


async def create_academic_info(
    db: AsyncSession,
    academic_info_in: schemas.OfferingAcademicInfoCreate,
    current_user: models.User,
    created_by_user_id: Optional[int] = None
) -> Tuple[models.OfferingAcademicInfo, Callable]:
    """
    Create new academic info for an offering.

    ✅ IDOR: Verify access to offering's unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Returns:
        Tuple of (academic_info, post_commit_callback)
    """
    try:
        # Verify offering exists
        repo = OrganizationRepository(db)
        offering = await repo.get_offering_by_id_full(academic_info_in.offering_id)
        if not offering:
            raise ResourceNotFoundError(
                detail=f"Program offering with id {academic_info_in.offering_id} not found."
            )

        # ✅ IDOR: Must have access to unit managing this offering
        program = await get_major_program_by_id(db, offering.program_id)
        await _check_unit_access(db, program.unit_id, current_user)

        # Check duplicate (offering_id, academic_year)
        existing = await get_academic_info_by_offering_and_year(
            db, academic_info_in.offering_id, academic_info_in.academic_year
        )
        if existing:
            raise DuplicateResourceError(
                detail=f"Academic info for offering {academic_info_in.offering_id} "
                       f"and year {academic_info_in.academic_year} already exists."
            )

        await _validate_discount_policy_ids(
            db, academic_info_in.applied_discount_policy_ids
        )

        db_academic_info = models.OfferingAcademicInfo(
            **academic_info_in.model_dump(),
            created_by_user_id=created_by_user_id
        )
        db.add(db_academic_info)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_academic_info)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Academic info created",
                academic_info_id=db_academic_info.id,
                offering_id=academic_info_in.offering_id,
                academic_year=academic_info_in.academic_year
            )
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="create",
                resource_type="academic_info",
                resource_id=db_academic_info.id,
                resource_name=f"Năm {academic_info_in.academic_year}"
            )

        return db_academic_info, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to create academic info", error=str(e), exc_info=True)
        raise


async def update_academic_info(
    db: AsyncSession,
    academic_info_id: int,
    academic_info_in: schemas.OfferingAcademicInfoUpdate,
    current_user: models.User,
    updated_by_user_id: Optional[int] = None
) -> Tuple[models.OfferingAcademicInfo, Callable]:
    """
    Update existing academic info.

    ✅ IDOR: Verify access to offering's unit.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Blocks editing of tuition fees for past academic years
    to prevent financial history rewriting (immutable financial data).

    Returns:
        Tuple of (academic_info, post_commit_callback)
    """
    try:
        db_academic_info = await get_academic_info_by_id(db, academic_info_id)
        
        # ✅ IDOR: Must have access to unit managing this offering
        offering = await get_program_offering_by_id(db, db_academic_info.offering_id)
        program = await get_major_program_by_id(db, offering.program_id)
        await _check_unit_access(db, program.unit_id, current_user)

        update_data = academic_info_in.model_dump(exclude_unset=True)

        # ✅ FIX: Prevent editing financial data for past academic years
        current_year = datetime.now(timezone.utc).year
        if db_academic_info.academic_year < current_year:
            # Check if trying to modify tuition fee
            if "tuition_fee_per_year" in update_data:
                old_fee = db_academic_info.tuition_fee_per_year
                new_fee = update_data["tuition_fee_per_year"]
                if old_fee != new_fee:
                    raise BadRequest(
                        detail=f"Không thể thay đổi học phí của năm học {db_academic_info.academic_year} "
                               f"(năm trong quá khứ). Dữ liệu tài chính lịch sử phải bất biến (immutable) "
                               f"để đảm bảo tính toàn vẹn của báo cáo tài chính."
                    )

        if "applied_discount_policy_ids" in update_data:
            await _validate_discount_policy_ids(
                db, update_data["applied_discount_policy_ids"]
            )

        # Apply updates
        for key, value in update_data.items():
            setattr(db_academic_info, key, value)

        if updated_by_user_id:
            db_academic_info.updated_by_user_id = updated_by_user_id

        db.add(db_academic_info)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_academic_info)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Academic info updated",
                academic_info_id=academic_info_id,
                offering_id=db_academic_info.offering_id,
                academic_year=db_academic_info.academic_year
            )
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="update",
                resource_type="academic_info",
                resource_id=academic_info_id,
                resource_name=f"Năm {db_academic_info.academic_year}"
            )

        return db_academic_info, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to update academic info", error=str(e), exc_info=True)
        raise


async def delete_academic_info(
    db: AsyncSession, 
    academic_info_id: int,
    current_user: models.User
) -> Tuple[None, Callable]:
    """
    Soft delete academic info.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    CRITICAL: This is a SOFT DELETE, not hard delete. Academic info contains
    financial data (tuition fees) and historical enrollment data that must be
    preserved for:
    - Financial reporting and audits
    - Historical statistics and analytics
    - Lead references and student records
    - Compliance and legal requirements

    NEVER hard delete academic info - use is_deleted flag instead.

    Blocks deletion of past academic year data to prevent
    historical data loss (immutable financial history).

    Returns:
        Tuple of (None, post_commit_callback)
    """
    try:
        db_academic_info = await get_academic_info_by_id(db, academic_info_id)
        
        # ✅ IDOR: Must have access to unit managing this offering
        offering = await get_program_offering_by_id(db, db_academic_info.offering_id)
        program = await get_major_program_by_id(db, offering.program_id)
        await _check_unit_access(db, program.unit_id, current_user)

        offering_id = db_academic_info.offering_id
        academic_year = db_academic_info.academic_year

        # ✅ FIX: Prevent deletion of past academic year data
        current_year = datetime.now(timezone.utc).year
        if academic_year < current_year:
            raise BadRequest(
                detail=f"Không thể xóa dữ liệu tuyển sinh của năm học {academic_year} "
                       f"(năm trong quá khứ). Dữ liệu lịch sử phải được bảo toàn "
                       f"để đảm bảo tính toàn vẹn của báo cáo tài chính và thống kê."
            )

        # Soft delete - set flag instead of removing from database
        db_academic_info.is_deleted = True
        db_academic_info.updated_at = datetime.now(timezone.utc)  # ✅ FIX: Explicitly update timestamp

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Academic info soft deleted (is_deleted=True)",
                academic_info_id=academic_info_id,
                offering_id=offering_id,
                academic_year=academic_year
            )
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="delete",
                resource_type="academic_info",
                resource_id=academic_info_id,
                resource_name=f"Năm {academic_year}"
            )

        return None, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to delete academic info", error=str(e), exc_info=True)
        raise


async def restore_academic_info(
    db: AsyncSession, 
    academic_info_id: int,
    current_user: models.User
) -> Tuple[models.OfferingAcademicInfo, Callable]:
    """
    Restore a soft-deleted academic info record.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Sets is_deleted back to False, allowing the record to be visible and editable again.
    This is useful when a user accidentally deletes a record.

    Returns:
        Tuple of (academic_info, post_commit_callback)
    """
    try:
        db_academic_info = await get_academic_info_by_id(db, academic_info_id)
        
        # ✅ IDOR: Must have access to unit managing this offering
        offering = await get_program_offering_by_id(db, db_academic_info.offering_id)
        program = await get_major_program_by_id(db, offering.program_id)
        await _check_unit_access(db, program.unit_id, current_user)

        offering_id = db_academic_info.offering_id
        academic_year = db_academic_info.academic_year

        if not db_academic_info.is_deleted:
            raise BadRequest(
                detail=f"Bản ghi năm học {academic_year} không bị xóa, không cần khôi phục."
            )

        # Restore - set flag back to False
        db_academic_info.is_deleted = False
        db_academic_info.updated_at = datetime.now(timezone.utc)

        # ✅ TRANSACTION FIX: Flush instead of commit
        await db.flush()
        await db.refresh(db_academic_info)

        # ✅ Create post-commit callback
        async def _post_commit():
            """Execute after router commits the transaction."""
            log.info(
                "Academic info restored (is_deleted=False)",
                academic_info_id=academic_info_id,
                offering_id=offering_id,
                academic_year=academic_year
            )
            await invalidate_org_cache()
            await emit_organization_updated(
                operation="update",
                resource_type="academic_info",
                resource_id=academic_info_id,
                resource_name=f"Năm {academic_year}"
            )

        return db_academic_info, _post_commit

    except Exception as e:
        # ✅ Router will handle rollback
        log.error("Failed to restore academic info", error=str(e), exc_info=True)
        raise


# =============================================================================
# TREE AGGREGATION WITH 3-TIER SUPPORT
# =============================================================================

async def get_organization_tree_with_aggregation(
    db: AsyncSession,
    academic_year: Optional[int] = None,
    include_inactive: bool = False,
    current_user=None,
) -> List[schemas.OrganizationTreeNodeWithAggregation]:
    """
    Get organization tree with aggregated statistics for 3-tier architecture.

    ✅ PERFORMANCE: Uses Redis caching to avoid expensive aggregation computation.

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
        academic_year = datetime.now(timezone.utc).year

    # ✅ PERFORMANCE FIX: Use Redis cache for aggregation results
    cache_key = f"{ORG_TREE_AGG_CACHE_KEY}:{academic_year}:{include_inactive}"

    # Try cache first
    try:
        cached_data = await safe_redis_get(cache_key)
        if cached_data:
            log.debug("Cache hit for organization tree aggregation", cache_key=cache_key)
            cached_list = json.loads(cached_data)
            # Convert back to Pydantic models
            return [
                schemas.OrganizationTreeNodeWithAggregation.model_validate(item)
                for item in cached_list
            ]
    except Exception as e:
        log.error("Failed to get aggregation from cache", error=str(e))

    log.info(
        "Building organization tree with aggregation (3-tier)",
        academic_year=academic_year,
        include_inactive=include_inactive
    )

    # ✅ FIX: Performance optimization - only load academic info for the specified year
    # Instead of loading ALL academic_info_history (which could be 30,000+ records),
    # we query only the academic info for the specified year separately.

    # ✅ SPRINT 3 REFACTORED: Use Repository for data access
    repo = OrganizationRepository(db)
    
    # Step 1: Query all units with programs and offerings (without academic info history)
    all_units = await repo.get_tree_for_aggregation(include_inactive)

    # Step 2: Query academic info for ONLY the specified year
    all_academic_info = await repo.get_academic_info_for_year(academic_year)

    # PR 7: HK1 semester tuition lookup for KPI metrics
    hk1_by_info_id = await repo.get_hk1_tuition_by_academic_info_id(academic_year)

    # Build lookup dict: offering_id -> academic_info
    academic_info_by_offering = {
        info.offering_id: info for info in all_academic_info
    }

    def _resolve_tuition(academic_info) -> Optional[Decimal]:
        """HK1 with fallback to legacy annual."""
        if academic_info is None:
            return None
        return hk1_by_info_id.get(academic_info.id) or academic_info.tuition_fee_per_year

    # Build tree with aggregation. Each call returns
    # (node, tuition_sum, tuition_count, tuition_min, tuition_max)
    # so parent nodes compute true subtree averages.
    def build_node_with_aggregation(
        unit: models.OrganizationUnit
    ) -> tuple:
        """Recursively build node with aggregated statistics."""

        majors_with_stats = []
        direct_total_quota = 0
        direct_tuition_sum = Decimal("0")
        direct_tuition_count = 0
        direct_tuition_values: list = []

        for program in unit.major_programs:
            if not program.is_active and not include_inactive:
                continue

            for offering in program.offerings:
                if not offering.is_active and not include_inactive:
                    continue

                academic_info = academic_info_by_offering.get(offering.id)
                resolved = _resolve_tuition(academic_info)

                major_stats = schemas.MajorWithStats(
                    id=program.id,
                    name=program.name,
                    code=program.code,
                    degree_level=program.degree_level,
                    total_admission_quota=academic_info.annual_admission_quota if academic_info else None,
                    tuition_fee=resolved,
                )
                majors_with_stats.append(major_stats)

                if academic_info:
                    if academic_info.annual_admission_quota:
                        direct_total_quota += academic_info.annual_admission_quota
                    if resolved:
                        direct_tuition_sum += resolved
                        direct_tuition_count += 1
                        direct_tuition_values.append(resolved)

        # Recursively build children
        children_results = []
        for child_unit in all_units:
            if child_unit.parent_id == unit.id:
                if not include_inactive and not child_unit.is_active:
                    continue
                children_results.append(build_node_with_aggregation(child_unit))

        # Aggregate across subtree
        total_majors = len(majors_with_stats)
        total_quota = direct_total_quota
        subtree_sum = direct_tuition_sum
        subtree_count = direct_tuition_count
        all_values = direct_tuition_values.copy()

        children_nodes = []
        for child_node, c_sum, c_count, c_min, c_max in children_results:
            children_nodes.append(child_node)
            total_majors += child_node.stats.total_majors
            if child_node.stats.total_admission_quota:
                total_quota += child_node.stats.total_admission_quota
            subtree_sum += c_sum
            subtree_count += c_count
            if c_min is not None:
                all_values.append(c_min)
            if c_max is not None and c_max != c_min:
                all_values.append(c_max)

        avg_tuition = (subtree_sum / subtree_count) if subtree_count > 0 else None
        min_tuition = min(all_values) if all_values else None
        max_tuition = max(all_values) if all_values else None

        stats = schemas.UnitAggregatedStats(
            total_majors=total_majors,
            direct_majors=len(majors_with_stats),
            total_admission_quota=total_quota if total_quota > 0 else None,
            avg_tuition_fee=avg_tuition,
            min_tuition_fee=min_tuition,
            max_tuition_fee=max_tuition,
        )

        node = schemas.OrganizationTreeNodeWithAggregation(
            id=unit.id,
            name=unit.name,
            type=unit.type,
            description=unit.description,
            parent_id=unit.parent_id,
            is_active=unit.is_active,
            majors=majors_with_stats,
            stats=stats,
            children=children_nodes,
        )
        return node, subtree_sum, subtree_count, min_tuition, max_tuition

    # Build root nodes
    root_nodes = []
    for unit in all_units:
        if unit.parent_id is None:
            if not include_inactive and not unit.is_active:
                continue
            root_node, _, _, _, _ = build_node_with_aggregation(unit)
            root_nodes.append(root_node)

    log.info(
        "Organization tree built successfully",
        root_nodes_count=len(root_nodes),
        total_units=len(all_units),
        academic_year=academic_year
    )

    # ✅ PERFORMANCE FIX: Cache the result
    try:
        cache_data = [node.model_dump() for node in root_nodes]
        await safe_redis_set(
            cache_key,
            json.dumps(cache_data, cls=DecimalEncoder),
            ex=CACHE_TTL
        )
        log.debug("Cached organization tree aggregation", cache_key=cache_key, ttl=CACHE_TTL)
    except Exception as e:
        log.error("Failed to cache organization tree aggregation", error=str(e))

    # ✅ M12 FIX: Filter aggregation tree by user's managed units
    if current_user is not None:
        role = getattr(current_user, "role", None)
        if role == UserRole.MANAGER:
            managed_ids = set(await _get_managed_unit_ids(db, current_user.id))
            root_nodes = _filter_agg_tree_by_managed_units(root_nodes, managed_ids)
        elif role == UserRole.OFFICER:
            unit_id = getattr(current_user, "unit_id", None)
            if unit_id:
                root_nodes = _filter_agg_tree_by_managed_units(root_nodes, {unit_id})
            else:
                root_nodes = []

    return root_nodes


def _filter_agg_tree_by_managed_units(
    nodes: List[schemas.OrganizationTreeNodeWithAggregation],
    managed_ids: set,
) -> List[schemas.OrganizationTreeNodeWithAggregation]:
    """Filter aggregation tree (Pydantic models) to only show managed unit subtrees."""
    result = []
    for node in nodes:
        if node.id in managed_ids:
            result.append(node)
        elif node.children:
            filtered = _filter_agg_tree_by_managed_units(node.children, managed_ids)
            result.extend(filtered)
    return result


# =============================================================================
# HELPER: Get programs by unit tree (for search/filtering)
# =============================================================================

async def get_programs_by_unit_tree(
    db: AsyncSession,
    unit_id: Optional[int] = None,
    search_term: Optional[str] = None,
    current_user=None,
) -> List[models.MajorProgram]:
    """
    Get all programs belonging to a unit and all its descendants.
    If unit_id is None, returns ALL programs (flat list).

    ✅ SPRINT 3 REFACTORED: Now uses OrganizationRepository for data access.
    ✅ M12 FIX: Filters by Manager's managed units.
    """
    repo = OrganizationRepository(db)

    # ✅ M12 FIX: Determine allowed unit IDs based on role
    allowed_unit_ids = None
    if current_user is not None:
        role = getattr(current_user, "role", None)
        if role == UserRole.MANAGER:
            managed_ids = await _get_managed_unit_ids(db, current_user.id)
            if not managed_ids:
                return []
            # Expand managed IDs to include all descendants
            allowed_unit_ids = set()
            for mid in managed_ids:
                descendant_ids = await repo.get_descendant_unit_ids(mid)
                allowed_unit_ids.update(descendant_ids)
        elif role == UserRole.OFFICER:
            own_unit = getattr(current_user, "unit_id", None)
            if own_unit:
                allowed_unit_ids = set(await repo.get_descendant_unit_ids(own_unit))
            else:
                return []

    # If unit_id specified, validate it's in allowed scope
    if unit_id:
        if allowed_unit_ids is not None and unit_id not in allowed_unit_ids:
            return []  # Unit not in scope - return empty (not 404 to avoid enumeration)
        all_related_unit_ids = await repo.get_descendant_unit_ids(unit_id)
        return await repo.search_programs_in_hierarchy(
            unit_ids=all_related_unit_ids,
            search_term=search_term,
            limit=20
        )

    # No unit specified
    if allowed_unit_ids is not None:
        # Manager/Officer: filter to their allowed units
        return await repo.search_programs_in_hierarchy(
            unit_ids=list(allowed_unit_ids),
            search_term=search_term,
            limit=20
        )

    # Admin or no user context: return all
    return await repo.get_all_major_programs(search_term=search_term)


# =============================================================================
# PROGRAM OFFERINGS (Flat List for Dropdowns)
# =============================================================================

async def get_all_program_offerings(
    db: AsyncSession,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 1000,
    current_user=None,
) -> List[models.ProgramOffering]:
    """
    Get all program offerings as flat list for dropdowns.

    Uses OrganizationRepository with eager loading for program name display.

    NOTE: No unit-based RBAC filtering here. This endpoint serves dropdown
    selections (e.g., LeadDialog, LeadFilterBar) where all authenticated users
    need to see all active programs. Officers in administrative units (e.g.,
    Phòng Tuyển sinh) must be able to select any program when managing leads.
    Casbin enforces endpoint-level access at the router layer.

    Args:
        db: Database session
        is_active: Filter by active status (None = all)
        skip: Offset for pagination
        limit: Maximum results
        current_user: If provided, used for Casbin auth (handled by router)

    Returns:
        List of ProgramOffering with program loaded
    """
    repo = OrganizationRepository(db)
    offerings = await repo.get_all_offerings(
        is_active=is_active,
        skip=skip,
        limit=limit
    )

    return offerings


async def get_all_academic_infos(
    db: AsyncSession,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 1000,
    current_user=None,
) -> List[schemas.OfferingAcademicInfo]:
    repo = OrganizationRepository(db)
    # Receive list of tuples (model, path_count)
    results = await repo.get_all_academic_infos(
        is_active=is_active,
        skip=skip,
        limit=limit
    )

    # ✅ M12 FIX: Filter by allowed unit IDs
    allowed_unit_ids = await _get_allowed_unit_ids_for_user(db, current_user)
    if allowed_unit_ids is not None:
        # Pre-fetch offering_id → unit_id mapping via program chain
        offering_query = (
            select(models.ProgramOffering.id)
            .join(
                models.MajorProgram,
                models.ProgramOffering.program_id == models.MajorProgram.id,
            )
            .where(models.MajorProgram.unit_id.in_(allowed_unit_ids))
        )
        result = await db.execute(offering_query)
        allowed_offering_ids = set(result.scalars().all())
        results = [
            (info, count) for info, count in results
            if info.offering_id in allowed_offering_ids
        ]

    response = []
    for info_model, path_count in results:
        # Map to Pydantic
        item = schemas.OfferingAcademicInfo.model_validate(info_model)

        # Populate computed fields
        item.path_count = path_count

        if path_count > 0:
            item.admission_status = schemas.AdmissionStatus.CONFIGURED
        elif (item.annual_admission_quota or 0) > 0:
            item.admission_status = schemas.AdmissionStatus.READY
        else:
            item.admission_status = schemas.AdmissionStatus.NOT_ELIGIBLE

        response.append(item)

    return response


# =============================================================================
# OfferingSemesterTuition CRUD — PR 2 (ADR-002)
# =============================================================================

async def _resolve_academic_info_for_semester_tuition(
    db: AsyncSession,
    academic_info_id: int,
    current_user: models.User,
) -> models.OfferingAcademicInfo:
    """Load academic info + verify IDOR access + reject soft-deleted.

    Shared by all semester tuition CRUD. Returns 404 for soft-deleted
    parents so that callers cannot accidentally edit semester tuition on
    an academic info that the admin has "deleted" (soft). Consistent
    with the plan's "404 if not found/soft-deleted" rule.
    """
    db_info = await get_academic_info_by_id(db, academic_info_id)
    if db_info.is_deleted:
        raise ResourceNotFoundError(
            "Thông tin tuyển sinh đã bị xóa. Vui lòng khôi phục trước "
            "khi chỉnh sửa học phí học kỳ."
        )
    offering = await get_program_offering_by_id(db, db_info.offering_id)
    program = await get_major_program_by_id(db, offering.program_id)
    await _check_unit_access(db, program.unit_id, current_user)
    return db_info


def _check_semester_tuition_immutability(
    db_info: models.OfferingAcademicInfo,
) -> None:
    """Block semester tuition edits for past academic years."""
    current_year = datetime.now(timezone.utc).year
    if db_info.academic_year < current_year:
        raise BadRequest(
            detail=f"Không thể thay đổi học phí học kỳ của năm học "
                   f"{db_info.academic_year} (năm trong quá khứ). Dữ liệu "
                   f"tài chính lịch sử phải bất biến để đảm bảo tính toàn "
                   f"vẹn của báo cáo tài chính."
        )


async def _invalidate_semester_tuition_dependents(
    academic_info_id: int,
    academic_year: int,
    operation: str,
    semester_info: str = "",
) -> None:
    """Post-commit: invalidate caches + emit Socket.IO event.

    This is the ADR-002 Decision 4 hook point. PR 2 does cache
    invalidation + Socket.IO only. PR 3 will extend this to trigger
    discount recalculation on FeeAppliedDiscount rows.
    """
    await invalidate_org_cache()
    await emit_organization_updated(
        operation=operation,
        resource_type="semester_tuition",
        resource_id=academic_info_id,
        resource_name=f"Năm {academic_year} — {semester_info}",
    )


async def list_semester_tuitions(
    db: AsyncSession,
    academic_info_id: int,
    current_user: models.User,
) -> List[models.OfferingSemesterTuition]:
    """List all semester tuition rows for an academic info, ordered by semester_no.

    Uses the shared IDOR + soft-delete check so that the list endpoint
    is consistent with the write endpoints.
    """
    await _resolve_academic_info_for_semester_tuition(
        db, academic_info_id, current_user
    )
    result = await db.execute(
        select(models.OfferingSemesterTuition)
        .where(models.OfferingSemesterTuition.academic_info_id == academic_info_id)
        .order_by(models.OfferingSemesterTuition.semester_no)
    )
    return list(result.scalars().all())


async def create_semester_tuition(
    db: AsyncSession,
    academic_info_id: int,
    data: schemas.SemesterTuitionCreate,
    current_user: models.User,
) -> Tuple[models.OfferingSemesterTuition, Callable]:
    """Create a single semester tuition row."""
    db_info = await _resolve_academic_info_for_semester_tuition(
        db, academic_info_id, current_user
    )
    _check_semester_tuition_immutability(db_info)

    existing = await db.execute(
        select(models.OfferingSemesterTuition)
        .where(
            models.OfferingSemesterTuition.academic_info_id == academic_info_id,
            models.OfferingSemesterTuition.semester_no == data.semester_no,
        )
    )
    if existing.scalar_one_or_none():
        raise DuplicateResourceError(
            f"Học phí HK{data.semester_no} đã tồn tại cho năm học "
            f"{db_info.academic_year}"
        )

    row = models.OfferingSemesterTuition(
        academic_info_id=academic_info_id,
        semester_no=data.semester_no,
        amount=data.amount,
        notes=data.notes,
        created_by_user_id=current_user.id,
        updated_by_user_id=current_user.id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    _year = db_info.academic_year

    async def _post_commit():
        log.info("semester_tuition_created",
                 academic_info_id=academic_info_id,
                 semester_no=data.semester_no,
                 amount=str(data.amount))
        await _invalidate_semester_tuition_dependents(
            academic_info_id, _year, "create",
            f"HK{data.semester_no}",
        )

    return row, _post_commit


async def update_semester_tuition(
    db: AsyncSession,
    semester_tuition_id: int,
    data: schemas.SemesterTuitionUpdate,
    current_user: models.User,
) -> Tuple[models.OfferingSemesterTuition, Callable]:
    """Update a single semester tuition row."""
    result = await db.execute(
        select(models.OfferingSemesterTuition)
        .where(models.OfferingSemesterTuition.id == semester_tuition_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ResourceNotFoundError("Không tìm thấy bản ghi học phí học kỳ")

    db_info = await _resolve_academic_info_for_semester_tuition(
        db, row.academic_info_id, current_user
    )
    _check_semester_tuition_immutability(db_info)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(row, key, value)
    row.updated_by_user_id = current_user.id

    await db.flush()
    await db.refresh(row)

    # PR 3: recalculate affected tuition fees (pre-commit)
    from app.services.fee_calculation_service import (
        recalculate_fees_for_semester_tuition_change,
    )
    recalc_count = await recalculate_fees_for_semester_tuition_change(
        db, row.academic_info_id
    )

    _year = db_info.academic_year
    _sem = row.semester_no

    async def _post_commit():
        log.info("semester_tuition_updated",
                 semester_tuition_id=semester_tuition_id,
                 semester_no=_sem,
                 fees_recalculated=recalc_count)
        await _invalidate_semester_tuition_dependents(
            row.academic_info_id, _year, "update", f"HK{_sem}",
        )

    return row, _post_commit


async def delete_semester_tuition(
    db: AsyncSession,
    semester_tuition_id: int,
    current_user: models.User,
) -> Tuple[None, Callable]:
    """Delete a single semester tuition row (hard delete — catalog row, not financial)."""
    result = await db.execute(
        select(models.OfferingSemesterTuition)
        .where(models.OfferingSemesterTuition.id == semester_tuition_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ResourceNotFoundError("Không tìm thấy bản ghi học phí học kỳ")

    db_info = await _resolve_academic_info_for_semester_tuition(
        db, row.academic_info_id, current_user
    )
    _check_semester_tuition_immutability(db_info)

    _year = db_info.academic_year
    _sem = row.semester_no
    _info_id = row.academic_info_id

    await db.delete(row)
    await db.flush()

    async def _post_commit():
        log.info("semester_tuition_deleted",
                 academic_info_id=_info_id,
                 semester_no=_sem)
        await _invalidate_semester_tuition_dependents(
            _info_id, _year, "delete", f"HK{_sem}",
        )

    return None, _post_commit


async def bulk_upsert_semester_tuitions(
    db: AsyncSession,
    academic_info_id: int,
    data: schemas.SemesterTuitionBulkUpsert,
    current_user: models.User,
) -> Tuple[List[models.OfferingSemesterTuition], Callable]:
    """Replace-all semester tuition rows for an academic info.

    Empty items list = clear all rows (fall back to legacy tuition_fee_per_year).
    Non-empty list = upsert matching semester_no, delete rows not in the list.
    """
    db_info = await _resolve_academic_info_for_semester_tuition(
        db, academic_info_id, current_user
    )
    _check_semester_tuition_immutability(db_info)

    existing_result = await db.execute(
        select(models.OfferingSemesterTuition)
        .where(models.OfferingSemesterTuition.academic_info_id == academic_info_id)
    )
    existing_rows = {row.semester_no: row for row in existing_result.scalars().all()}

    incoming_semesters = {item.semester_no for item in data.items}

    # Delete rows not in the incoming list
    for sem_no, row in existing_rows.items():
        if sem_no not in incoming_semesters:
            await db.delete(row)

    # Upsert: update existing or create new
    for item in data.items:
        if item.semester_no in existing_rows:
            row = existing_rows[item.semester_no]
            row.amount = item.amount
            row.notes = item.notes
            row.updated_by_user_id = current_user.id
        else:
            row = models.OfferingSemesterTuition(
                academic_info_id=academic_info_id,
                semester_no=item.semester_no,
                amount=item.amount,
                notes=item.notes,
                created_by_user_id=current_user.id,
                updated_by_user_id=current_user.id,
            )
            db.add(row)

    await db.flush()

    # PR 3 (ADR-002 Decision 4): recalculate affected tuition fees
    # pre-commit so the new amounts are part of the same transaction.
    from app.services.fee_calculation_service import (
        recalculate_fees_for_semester_tuition_change,
    )
    recalc_count = await recalculate_fees_for_semester_tuition_change(
        db, academic_info_id
    )

    # Re-query for the final ordered list
    final_result = await db.execute(
        select(models.OfferingSemesterTuition)
        .where(models.OfferingSemesterTuition.academic_info_id == academic_info_id)
        .order_by(models.OfferingSemesterTuition.semester_no)
    )
    final_rows = list(final_result.scalars().all())

    _year = db_info.academic_year
    _count = len(final_rows)

    async def _post_commit():
        log.info("semester_tuitions_bulk_upserted",
                 academic_info_id=academic_info_id,
                 count=_count,
                 fees_recalculated=recalc_count)
        await _invalidate_semester_tuition_dependents(
            academic_info_id, _year, "bulk_upsert",
            f"{_count} học kỳ",
        )

    return final_rows, _post_commit

