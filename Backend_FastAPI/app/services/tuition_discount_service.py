# app/services/tuition_discount_service.py
"""
Service layer for TuitionDiscountPolicy - Quản lý chính sách ưu đãi học phí.

Cung cấp các chức năng:
- CRUD operations cho chính sách ưu đãi
- Tính toán ưu đãi cho sinh viên dựa trên các điều kiện
"""
from datetime import date
from decimal import Decimal
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TuitionDiscountPolicy, DiscountTypeEnum, User
from app.schemas.tuition_discount_policy import (
    TuitionDiscountPolicyCreate,
    TuitionDiscountPolicyUpdate,
    DiscountType,
)

log = structlog.get_logger(__name__)


# =============================================================================
# CRUD OPERATIONS
# =============================================================================

async def get_all_policies(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
    is_active: Optional[bool] = None,
    include_expired: bool = False,
) -> Tuple[List[TuitionDiscountPolicy], int]:
    """
    Lấy danh sách chính sách ưu đãi với phân trang và lọc.

    Args:
        db: Database session
        skip: Số bản ghi bỏ qua (offset)
        limit: Số bản ghi tối đa
        is_active: Lọc theo trạng thái (None = tất cả)
        include_expired: Bao gồm chính sách hết hạn

    Returns:
        Tuple[List[TuitionDiscountPolicy], int]: Danh sách và tổng số
    """
    # Build base query
    query = select(TuitionDiscountPolicy)
    count_query = select(func.count(TuitionDiscountPolicy.id))

    # Filter by active status
    if is_active is not None:
        query = query.where(TuitionDiscountPolicy.is_active == is_active)
        count_query = count_query.where(TuitionDiscountPolicy.is_active == is_active)

    # Filter expired policies
    if not include_expired:
        today = date.today()
        query = query.where(
            or_(
                TuitionDiscountPolicy.valid_to.is_(None),
                TuitionDiscountPolicy.valid_to >= today
            )
        )
        count_query = count_query.where(
            or_(
                TuitionDiscountPolicy.valid_to.is_(None),
                TuitionDiscountPolicy.valid_to >= today
            )
        )

    # Order by priority (desc), then by created_at (desc)
    query = query.order_by(
        TuitionDiscountPolicy.priority.desc(),
        TuitionDiscountPolicy.created_at.desc()
    )

    # Pagination
    query = query.offset(skip).limit(limit)

    # Execute queries
    result = await db.execute(query)
    policies = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    return list(policies), total


async def get_policy_by_id(
    db: AsyncSession,
    policy_id: int
) -> Optional[TuitionDiscountPolicy]:
    """Lấy chính sách theo ID"""
    result = await db.execute(
        select(TuitionDiscountPolicy).where(TuitionDiscountPolicy.id == policy_id)
    )
    return result.scalar_one_or_none()


async def get_policy_by_code(
    db: AsyncSession,
    code: str
) -> Optional[TuitionDiscountPolicy]:
    """Lấy chính sách theo mã"""
    result = await db.execute(
        select(TuitionDiscountPolicy).where(
            TuitionDiscountPolicy.code == code.upper()
        )
    )
    return result.scalar_one_or_none()


async def create_policy(
    db: AsyncSession,
    policy_data: TuitionDiscountPolicyCreate,
    created_by_user_id: Optional[int] = None
) -> Tuple[TuitionDiscountPolicy, Callable]:
    """
    Tạo chính sách ưu đãi mới.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        policy_data: Dữ liệu chính sách
        created_by_user_id: ID user tạo

    Returns:
        Tuple of (policy, post_commit_callback)

    Raises:
        ValueError: Nếu mã đã tồn tại
    """
    # Check duplicate code
    existing = await get_policy_by_code(db, policy_data.code)
    if existing:
        raise ValueError(f"Mã chính sách '{policy_data.code}' đã tồn tại")

    # Map discount_type string to enum VALUE (lowercase for PostgreSQL)
    discount_type_value = "amount"
    if policy_data.discount_type == DiscountType.PERCENTAGE:
        discount_type_value = "percentage"

    # Create new policy
    db_policy = TuitionDiscountPolicy(
        code=policy_data.code.upper(),
        name=policy_data.name,
        description=policy_data.description,
        discount_type=discount_type_value,  # Use string value directly
        discount_value=policy_data.discount_value,
        valid_from=policy_data.valid_from,
        valid_to=policy_data.valid_to,
        applicable_scope=policy_data.applicable_scope or {},
        target_criteria=policy_data.target_criteria or {},
        is_stackable=policy_data.is_stackable,
        priority=policy_data.priority,
        max_usage=policy_data.max_usage,
        is_active=policy_data.is_active,
        created_by_user_id=created_by_user_id,
        updated_by_user_id=created_by_user_id,
    )

    db.add(db_policy)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(db_policy)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Created tuition discount policy",
            policy_id=db_policy.id,
            code=db_policy.code,
            created_by=created_by_user_id
        )

    return db_policy, _post_commit


async def update_policy(
    db: AsyncSession,
    policy_id: int,
    policy_data: TuitionDiscountPolicyUpdate,
    updated_by_user_id: Optional[int] = None
) -> Tuple[Optional[TuitionDiscountPolicy], Optional[Callable]]:
    """
    Cập nhật chính sách ưu đãi.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        policy_id: ID chính sách cần cập nhật
        policy_data: Dữ liệu cập nhật
        updated_by_user_id: ID user cập nhật

    Returns:
        Tuple of (policy_or_None, post_commit_callback_or_None)
    """
    db_policy = await get_policy_by_id(db, policy_id)
    if not db_policy:
        return None, None

    # Update fields if provided
    update_data = policy_data.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        if field == "discount_type" and value:
            # Map to lowercase string value for PostgreSQL enum
            if value == DiscountType.PERCENTAGE or value == "percentage":
                value = "percentage"
            else:
                value = "amount"
        setattr(db_policy, field, value)

    db_policy.updated_by_user_id = updated_by_user_id

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(db_policy)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Updated tuition discount policy",
            policy_id=policy_id,
            updated_by=updated_by_user_id
        )

    return db_policy, _post_commit


async def delete_policy(
    db: AsyncSession,
    policy_id: int,
    hard_delete: bool = False
) -> Tuple[bool, Optional[Callable]]:
    """
    Xóa chính sách ưu đãi.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        policy_id: ID chính sách
        hard_delete: True = xóa vĩnh viễn, False = soft delete

    Returns:
        Tuple of (success, post_commit_callback_or_None)
    """
    db_policy = await get_policy_by_id(db, policy_id)
    if not db_policy:
        return False, None

    if hard_delete:
        await db.delete(db_policy)
        delete_type = "hard"
    else:
        db_policy.is_active = False
        delete_type = "soft"

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        if delete_type == "hard":
            log.info("Hard deleted tuition discount policy", policy_id=policy_id)
        else:
            log.info("Soft deleted tuition discount policy", policy_id=policy_id)

    return True, _post_commit


# =============================================================================
# DISCOUNT CALCULATION
# =============================================================================

async def get_applicable_policies(
    db: AsyncSession,
    *,
    major_program_id: Optional[int] = None,
    major_program_code: Optional[str] = None,
    is_heavy_program: bool = False,
    degree_level: Optional[str] = None,
    offering_id: Optional[int] = None,
    student_priority_type: Optional[str] = None,
    student_region: Optional[str] = None,
) -> List[TuitionDiscountPolicy]:
    """
    Lấy danh sách chính sách ưu đãi áp dụng được.

    Lọc dựa trên:
    - Thời gian hiệu lực
    - Phạm vi chương trình (applicable_scope)
    - Điều kiện đối tượng (target_criteria)
    - Còn quota sử dụng
    """
    today = date.today()

    # Base query: active, within validity, has quota
    query = select(TuitionDiscountPolicy).where(
        TuitionDiscountPolicy.is_active == True,
        or_(
            TuitionDiscountPolicy.valid_from.is_(None),
            TuitionDiscountPolicy.valid_from <= today
        ),
        or_(
            TuitionDiscountPolicy.valid_to.is_(None),
            TuitionDiscountPolicy.valid_to >= today
        ),
        or_(
            TuitionDiscountPolicy.max_usage.is_(None),
            TuitionDiscountPolicy.current_usage < TuitionDiscountPolicy.max_usage
        )
    ).order_by(TuitionDiscountPolicy.priority.desc())

    result = await db.execute(query)
    all_policies = result.scalars().all()

    # Filter by scope and criteria (JSON filtering done in Python for flexibility)
    applicable = []

    for policy in all_policies:
        scope = policy.applicable_scope or {}
        criteria = policy.target_criteria or {}

        # Check applicable_scope
        if not _matches_scope(
            scope,
            major_program_id=major_program_id,
            major_program_code=major_program_code,
            is_heavy_program=is_heavy_program,
            degree_level=degree_level,
            offering_id=offering_id,
        ):
            continue

        # Check target_criteria
        if not _matches_criteria(
            criteria,
            priority_type=student_priority_type,
            region=student_region,
        ):
            continue

        applicable.append(policy)

    return applicable


def _matches_scope(
    scope: dict,
    *,
    major_program_id: Optional[int] = None,
    major_program_code: Optional[str] = None,
    is_heavy_program: bool = False,
    degree_level: Optional[str] = None,
    offering_id: Optional[int] = None,
) -> bool:
    """Kiểm tra phạm vi áp dụng"""
    # If all_programs is True, apply to all
    if scope.get("all_programs", False):
        return True

    # Check is_heavy_only
    if scope.get("is_heavy_only", False):
        if not is_heavy_program:
            return False
        return True  # Heavy program matches

    # Check degree_levels
    degree_levels = scope.get("degree_levels", [])
    if degree_levels and degree_level:
        if degree_level not in degree_levels:
            return False

    # Check major_program_ids
    program_ids = scope.get("major_program_ids", [])
    if program_ids and major_program_id:
        if major_program_id not in program_ids:
            return False

    # Check major_program_codes
    program_codes = scope.get("major_program_codes", [])
    if program_codes and major_program_code:
        if major_program_code not in program_codes:
            return False

    # Check offering_ids
    offering_ids = scope.get("offering_ids", [])
    if offering_ids and offering_id:
        if offering_id not in offering_ids:
            return False

    # If no specific filter, it matches
    return True


def _matches_criteria(
    criteria: dict,
    *,
    priority_type: Optional[str] = None,
    region: Optional[str] = None,
    gpa: Optional[float] = None,
) -> bool:
    """Kiểm tra điều kiện đối tượng"""
    # If no criteria specified, apply to all
    if not criteria:
        return True

    # Check priority_types
    priority_types = criteria.get("priority_types", [])
    if priority_types:
        if not priority_type or priority_type not in priority_types:
            return False

    # Check regions
    regions = criteria.get("regions", [])
    if regions:
        if not region or region not in regions:
            return False

    # Check min_gpa
    min_gpa = criteria.get("min_gpa")
    if min_gpa is not None:
        if gpa is None or gpa < min_gpa:
            return False

    return True


def calculate_discount(
    tuition_fee: Decimal,
    policies: List[TuitionDiscountPolicy]
) -> Tuple[Decimal, List[dict]]:
    """
    Tính toán tổng ưu đãi từ danh sách chính sách.

    Args:
        tuition_fee: Học phí gốc
        policies: Danh sách chính sách đã lọc (sắp xếp theo priority)

    Returns:
        Tuple[Decimal, List[dict]]: (Tổng tiền giảm, Chi tiết các ưu đãi áp dụng)
    """
    total_discount = Decimal("0")
    applied = []

    for policy in policies:
        # Calculate discount amount
        if policy.discount_type == DiscountTypeEnum.PERCENTAGE:
            discount_amount = tuition_fee * policy.discount_value / 100
        else:
            discount_amount = policy.discount_value

        # Cap discount at tuition fee
        if total_discount + discount_amount > tuition_fee:
            discount_amount = tuition_fee - total_discount

        if discount_amount > 0:
            total_discount += discount_amount
            applied.append({
                "policy_id": policy.id,
                "policy_code": policy.code,
                "policy_name": policy.name,
                "discount_type": policy.discount_type.value,
                "discount_value": policy.discount_value,
                "discount_amount": discount_amount,
            })

        # If not stackable, stop after first applied
        if not policy.is_stackable:
            break

        # If total discount equals tuition, stop
        if total_discount >= tuition_fee:
            break

    return total_discount, applied
