# app/routers/admin/tuition_discount.py
"""
Tuition Discount Policy Admin Router

Quản lý chính sách ưu đãi học phí:
- CRUD operations cho chính sách
- Tính toán ưu đãi cho sinh viên
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core.deps import CasbinAuth  # Phase 2.2
from app.services import tuition_discount_service

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - Tuition Discount Policy"])



# =============================================================================
# CRUD ENDPOINTS
# =============================================================================

@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/tuition-discount-policies",
    response_model=schemas.TuitionDiscountPolicyListResponse,
    summary="Lấy danh sách chính sách ưu đãi",
)
async def list_policies(
    request: Request,
    page: int = Query(1, ge=1, description="Trang hiện tại"),
    page_size: int = Query(20, ge=1, le=100, description="Số item mỗi trang"),
    is_active: Optional[bool] = Query(None, description="Lọc theo trạng thái"),
    include_expired: bool = Query(False, description="Bao gồm chính sách hết hạn"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Lấy danh sách chính sách ưu đãi học phí với phân trang.

    - **page**: Trang hiện tại (bắt đầu từ 1)
    - **page_size**: Số chính sách mỗi trang
    - **is_active**: Lọc theo trạng thái hoạt động
    - **include_expired**: Bao gồm cả chính sách đã hết hạn
    """
    skip = (page - 1) * page_size

    policies, total = await tuition_discount_service.get_all_policies(
        db,
        skip=skip,
        limit=page_size,
        is_active=is_active,
        include_expired=include_expired,
    )

    # Add computed fields
    policy_responses = []
    for policy in policies:
        policy_dict = {
            **policy.__dict__,
            "is_expired": policy.is_expired,
            "is_within_validity": policy.is_within_validity,
            "has_quota_remaining": policy.has_quota_remaining,
        }
        policy_responses.append(schemas.TuitionDiscountPolicy.model_validate(policy_dict))

    total_pages = (total + page_size - 1) // page_size

    return schemas.TuitionDiscountPolicyListResponse(
        items=policy_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/tuition-discount-policies/{policy_id}",
    response_model=schemas.TuitionDiscountPolicy,
    summary="Lấy chi tiết chính sách ưu đãi",
)
async def get_policy(
    request: Request,
    policy_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Lấy chi tiết một chính sách ưu đãi theo ID."""
    policy = await tuition_discount_service.get_policy_by_id(db, policy_id)
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chính sách với ID {policy_id}"
        )

    # Add computed fields
    policy_dict = {
        **policy.__dict__,
        "is_expired": policy.is_expired,
        "is_within_validity": policy.is_within_validity,
        "has_quota_remaining": policy.has_quota_remaining,
    }
    return schemas.TuitionDiscountPolicy.model_validate(policy_dict)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/tuition-discount-policies",
    response_model=schemas.TuitionDiscountPolicy,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo chính sách ưu đãi mới",
)
async def create_policy(
    request: Request,
    policy_data: schemas.TuitionDiscountPolicyCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Tạo chính sách ưu đãi học phí mới.

    **Ví dụ request body:**
    ```json
    {
        "code": "EARLY_BIRD_2025",
        "name": "Ưu đãi đăng ký sớm 2025",
        "description": "Giảm 15% học phí cho thí sinh đăng ký trước 31/03/2025",
        "discount_type": "percentage",
        "discount_value": 15,
        "valid_from": "2025-01-01",
        "valid_to": "2025-03-31",
        "applicable_scope": {"all_programs": true},
        "target_criteria": {},
        "is_stackable": false,
        "priority": 10
    }
    ```
    """
    try:
        policy, callback = await tuition_discount_service.create_policy(
            db,
            policy_data,
            created_by_user_id=current_user.id
        )
        await db.commit()
        await callback()

        policy_dict = {
            **policy.__dict__,
            "is_expired": policy.is_expired,
            "is_within_validity": policy.is_within_validity,
            "has_quota_remaining": policy.has_quota_remaining,
        }
        return schemas.TuitionDiscountPolicy.model_validate(policy_dict)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/tuition-discount-policies/{policy_id}",
    response_model=schemas.TuitionDiscountPolicy,
    summary="Cập nhật chính sách ưu đãi",
)
async def update_policy(
    request: Request,
    policy_id: int,
    policy_data: schemas.TuitionDiscountPolicyUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Cập nhật thông tin chính sách ưu đãi."""
    policy, callback = await tuition_discount_service.update_policy(
        db,
        policy_id,
        policy_data,
        updated_by_user_id=current_user.id
    )

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chính sách với ID {policy_id}"
        )

    await db.commit()
    await callback()

    policy_dict = {
        **policy.__dict__,
        "is_expired": policy.is_expired,
        "is_within_validity": policy.is_within_validity,
        "has_quota_remaining": policy.has_quota_remaining,
    }
    return schemas.TuitionDiscountPolicy.model_validate(policy_dict)


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/tuition-discount-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa chính sách ưu đãi",
)
async def delete_policy(
    request: Request,
    policy_id: int,
    hard_delete: bool = Query(False, description="Xóa vĩnh viễn (mặc định: soft delete)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Xóa chính sách ưu đãi.

    - **hard_delete=false** (mặc định): Soft delete - đánh dấu is_active=false
    - **hard_delete=true**: Xóa vĩnh viễn khỏi database
    """
    success, callback = await tuition_discount_service.delete_policy(
        db, policy_id, hard_delete=hard_delete
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy chính sách với ID {policy_id}"
        )

    await db.commit()
    await callback()


# =============================================================================
# DISCOUNT CALCULATION ENDPOINT
# =============================================================================

@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/tuition-discount-policies/calculate",
    response_model=schemas.DiscountCalculationResponse,
    summary="Tính toán ưu đãi học phí",
)
async def calculate_discount(
    request: Request,  # Required for rate limiter
    body: schemas.DiscountCalculationRequest,  # Renamed from 'request' to avoid conflict
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Tính toán ưu đãi học phí cho sinh viên dựa trên các điều kiện.

    **Ví dụ request body:**
    ```json
    {
        "tuition_fee": 15000000,
        "major_program_id": 1,
        "is_heavy_program": false,
        "student_priority_type": "con_thuong_binh"
    }
    ```

    **Response:**
    ```json
    {
        "original_tuition": 15000000,
        "total_discount": 2250000,
        "final_tuition": 12750000,
        "applied_policies": [
            {
                "policy_id": 1,
                "policy_code": "EARLY_BIRD_2025",
                "policy_name": "Ưu đãi đăng ký sớm 2025",
                "discount_type": "percentage",
                "discount_value": 15,
                "discount_amount": 2250000
            }
        ]
    }
    ```
    """
    # Get applicable policies
    policies = await tuition_discount_service.get_applicable_policies(
        db,
        major_program_id=body.major_program_id,  # Changed from request. to body.
        major_program_code=body.major_program_code,  # Changed from request. to body.
        is_heavy_program=body.is_heavy_program,  # Changed from request. to body.
        offering_id=body.offering_id,  # Changed from request. to body.
        student_priority_type=body.student_priority_type,  # Changed from request. to body.
        student_region=body.student_region,  # Changed from request. to body.
    )

    # Calculate discount
    total_discount, applied = tuition_discount_service.calculate_discount(
        body.tuition_fee,  # Changed from request. to body.
        policies
    )

    return schemas.DiscountCalculationResponse(
        original_tuition=body.tuition_fee,  # Changed from request. to body.
        total_discount=total_discount,
        final_tuition=body.tuition_fee - total_discount,  # Changed from request. to body.
        applied_policies=[
            schemas.AppliedDiscount(**p) for p in applied
        ]
    )