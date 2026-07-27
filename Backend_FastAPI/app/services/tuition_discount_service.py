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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TuitionDiscountPolicy, DiscountTypeEnum
from app.schemas.tuition_discount_policy import (
    TuitionDiscountPolicyCreate,
    TuitionDiscountPolicyUpdate,
    DiscountType,
)
from app.repositories import TuitionDiscountRepository
from app.utils.exceptions import BadRequest, DuplicateResourceError

log = structlog.get_logger(__name__)


def _get_repo(db: AsyncSession) -> TuitionDiscountRepository:
    """Helper to get repository instance. Uses local import to avoid circular dependency."""
    return TuitionDiscountRepository(db)


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
    """
    repo = _get_repo(db)
    total, policies = await repo.get_filtered(
        skip=skip,
        limit=limit,
        is_active=is_active,
        include_expired=include_expired
    )

    return policies, total


async def get_policy_by_id(
    db: AsyncSession,
    policy_id: int
) -> Optional[TuitionDiscountPolicy]:
    """Lấy chính sách theo ID"""
    return await _get_repo(db).get_by_id(policy_id)


async def get_policy_by_code(
    db: AsyncSession,
    code: str
) -> Optional[TuitionDiscountPolicy]:
    """Lấy chính sách theo mã"""
    return await _get_repo(db).get_by_code(code)


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
    repo = _get_repo(db)
    
    # Check duplicate code
    existing = await repo.get_by_code(policy_data.code)
    if existing:
        raise DuplicateResourceError(f"Mã chính sách '{policy_data.code}' đã tồn tại")

    # Validate JSON structures
    _validate_json_fields(policy_data.applicable_scope, policy_data.target_criteria)

    # Map discount_type string to enum VALUE for DB
    discount_type_value = "amount"
    if policy_data.discount_type == DiscountType.PERCENTAGE:
        discount_type_value = "percentage"

    # Prepare data
    policy_dict = policy_data.model_dump()
    policy_dict.update({
        "code": policy_data.code.upper(),
        "discount_type": discount_type_value,
        "created_by_user_id": created_by_user_id,
        "updated_by_user_id": created_by_user_id,
    })

    # Create new policy via repository.
    # 🔴 ``BaseRepository.create`` nhận DICT rồi tự dựng model (``self.model(**obj_in)``).
    # Bản cũ truyền sẵn một INSTANCE ⇒ ``TypeError: argument after ** must be a
    # mapping`` ⇒ MỌI lần tạo chính sách qua giao diện đều 500. Không test nào
    # chạm (test service mock repo nên chữ ký thật không được kiểm).
    db_policy = await repo.create(policy_dict)
    await db.flush()

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
    repo = _get_repo(db)
    db_policy = await repo.get_by_id(policy_id)
    if not db_policy:
        return None, None

    # Update fields if provided
    update_data = policy_data.model_dump(exclude_unset=True)

    # Validate JSON if provided
    if "applicable_scope" in update_data or "target_criteria" in update_data:
        _validate_json_fields(
            update_data.get("applicable_scope", db_policy.applicable_scope),
            update_data.get("target_criteria", db_policy.target_criteria)
        )

    if "discount_type" in update_data and update_data["discount_type"]:
        # Map to lowercase string value for PostgreSQL enum
        if update_data["discount_type"] in [DiscountType.PERCENTAGE, "percentage"]:
            update_data["discount_type"] = "percentage"
        else:
            update_data["discount_type"] = "amount"

    update_data["updated_by_user_id"] = updated_by_user_id

    # Update via repository. ``BaseRepository.update(db_obj, obj_in: dict)`` nhận
    # dict Ở VỊ TRÍ THỨ HAI — bản cũ bung thành kwargs ⇒ TypeError ⇒ mọi lần sửa
    # chính sách qua giao diện đều 500. Cùng một lớp lỗi với ``create`` bên trên.
    db_policy = await repo.update(db_policy, update_data)
    await db.flush()

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
    repo = _get_repo(db)
    db_policy = await repo.get_by_id(policy_id)
    if not db_policy:
        return False, None

    if hard_delete:
        await repo.delete(db_policy)
        delete_type = "hard"
    else:
        await repo.soft_delete(db_policy)
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
    student_gpa: Optional[float] = None,
) -> List[TuitionDiscountPolicy]:
    """
    Lấy danh sách chính sách ưu đãi áp dụng được.

    Lọc dựa trên:
    - Thời gian hiệu lực
    - Phạm vi chương trình (applicable_scope)
    - Điều kiện đối tượng (target_criteria)
    - Còn quota sử dụng
    """
    repo = _get_repo(db)
    all_policies = await repo.get_active_within_validity()
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
            gpa=student_gpa,
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


def _validate_json_fields(scope: Optional[dict], criteria: Optional[dict]):
    """
    Validate structure of JSON config fields using Pydantic schemas.
    Raises BadRequest if invalid.
    """
    from app.schemas.tuition_discount_policy import ApplicableScope, TargetCriteria
    from pydantic import ValidationError as PydanticValidationError

    if scope:
        try:
            ApplicableScope(**scope)
        except PydanticValidationError as e:
            log.warning("Invalid applicable_scope structure", error=str(e))
            raise BadRequest(detail=f"Cấu hình phạm vi áp dụng không hợp lệ: {str(e)}")

    if criteria:
        try:
            TargetCriteria(**criteria)
        except PydanticValidationError as e:
            log.warning("Invalid target_criteria structure", error=str(e))
            raise BadRequest(detail=f"Cấu hình điều kiện đối tượng không hợp lệ: {str(e)}")
