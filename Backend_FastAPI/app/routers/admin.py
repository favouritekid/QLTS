# app/routers/admin.py
import io
from typing import List, Optional

import casbin
import pandas as pd
import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import EmailStr  # <-- BỔ SUNG TypeAdapter, ValidationError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

from .. import database, models, schemas, services
from ..celery_utils import process_automatic_lead_assignment_task
from ..core import deps
from ..schemas.permissions import PolicyCreate, RoleAssignment
from ..services import (
    config_service,
    lead_service,
    organization_service,
    pipeline_service,
)
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)
router = APIRouter(tags=["Admin"])

# --- ĐỊNH NGHĨA DEPENDENCY MỚI ---
PermissionDep = Depends(deps.check_permission)
LeadAccessDep = Depends(deps.get_lead_for_user)


# ===============================================================
# POLICY MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/policies",
    response_model=List[List[str]],  # Casbin trả về List[List[str]]
    tags=["Admin - Permissions"],
)
async def get_all_policies(
    request: Request, current_admin: models.User = PermissionDep
):
    """(Admin only) Lấy tất cả các chính sách (policies) hiện có."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    # SỬA: Bỏ await vì get_policy() không phải là async
    policies = enforcer.get_policy()
    return policies


@router.post(
    "/policies",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
async def add_new_policy(
    policy_in: PolicyCreate,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thêm một chính sách (quyền) mới."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not added:
        raise DuplicateResourceError("Policy already exists.")

    # Chính xác: Không cần save_policy()

    return {"detail": "Policy added successfully."}


@router.delete(
    "/policies",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def delete_policy(
    policy_in: PolicyCreate,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một chính sách (quyền) cụ thể."""
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_policy(
        policy_in.subject, policy_in.object, policy_in.action
    )
    if not removed:
        raise ResourceNotFoundError("Policy not found or could not be removed.")

    # Chính xác: Không cần save_policy()

    return {"detail": "Policy removed successfully."}


@router.post(
    "/assign-role",
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Permissions"],
)
async def assign_role_to_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Gán một vai trò cho người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    added = await enforcer.add_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not added:
        raise DuplicateResourceError("User already has this role.")

    # SỬA: Xóa dòng save_policy()
    # await enforcer.save_policy() # AsyncAdapter tự lưu

    return {"detail": "Role assigned."}


@router.delete(
    "/assign-role",
    status_code=status.HTTP_200_OK,
    tags=["Admin - Permissions"],
)
async def remove_role_from_user(
    assignment: RoleAssignment,
    request: Request,
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa (thu hồi) vai trò của người dùng."""
    # SỬA: Type hint thành AsyncEnforcer
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer

    removed = await enforcer.remove_grouping_policy(
        f"user:{assignment.user_id}", assignment.role
    )
    if not removed:
        raise ResourceNotFoundError(
            "Role assignment not found or could not be removed."
        )

    # SỬA: Xóa dòng save_policy()
    # await enforcer.save_policy() # AsyncAdapter tự lưu

    return {"detail": "Role removed from user."}


# ===============================================================
# USER MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/users",
    response_model=schemas.User,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - User Management"],
)
async def create_new_user(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form("user"),
    status: str = Form("active"),
    avatar: Optional[UploadFile] = File(None),
):
    """(Admin only) Tạo một người dùng mới, có hỗ trợ upload avatar."""
    user_in = schemas.AdminUserCreate(
        username=username,
        email=email,
        password=password,
        confirm_password=password,
        full_name=full_name,
        role=role,
        status=status,
    )

    if await services.user_service.get_user_by_username(db, user_in.username):
        raise DuplicateResourceError(detail="Username already exists")
    if await services.user_service.get_user_by_email(db, user_in.email):
        raise DuplicateResourceError(detail="Email already exists")

    # Truyền avatar vào hàm service
    created_user = await services.user_service.create_user_by_admin(
        db, user_in, avatar_file=avatar
    )

    # ✅ FIX: Automatically add Casbin grouping policy to map user to their role
    try:
        enforcer = request.app.state.enforcer
        if enforcer:
            role_name = f"role:{created_user.role}"
            user_subject = f"user:{created_user.id}"
            await enforcer.add_grouping_policy(user_subject, role_name)
            log.info(
                "Casbin grouping policy added for admin-created user",
                user_id=created_user.id,
                role=created_user.role,
            )
    except Exception as e:
        log.error(
            "Failed to add Casbin grouping policy for admin-created user",
            user_id=created_user.id,
            error=str(e),
        )
        # Don't fail user creation if Casbin update fails

    return created_user


@router.get(
    "/users", response_model=schemas.UsersPage, tags=["Admin - User Management"]
)
async def get_all_users(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """(Admin only) Lấy danh sách tất cả người dùng với phân trang, filter, search."""
    skip = (page - 1) * page_size
    query_params = dict(request.query_params)
    total, users = await services.user_service.get_users(
        db, params=query_params, skip=skip, limit=page_size
    )
    return {"total_count": total, "users": users}


@router.get(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def get_user_details(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy thông tin chi tiết của một người dùng."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    return db_user


@router.put(
    "/users/{user_id}", response_model=schemas.User, tags=["Admin - User Management"]
)
async def update_existing_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),  # <-- Sửa lại thành Optional[str]
    phone_number: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
    skills: Optional[str] = Form(None),  # Nhận JSON string từ form-data
    max_capacity: Optional[int] = Form(None),
):
    """(Admin only) Cập nhật người dùng, có hỗ trợ upload avatar."""
    db_user = await services.user_service.get_user_by_id(db, user_id)
    if not db_user:
        raise ResourceNotFoundError(detail="User not found")

    # Xây dựng dict chỉ chứa các trường hợp lệ được cung cấp
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()
    if role is not None and role.strip():
        update_dict["role"] = role.strip()
    if status is not None and status.strip():
        update_dict["status"] = status.strip()
    if max_capacity is not None and max_capacity >= 0:
        update_dict["max_capacity"] = max_capacity
    if skills is not None:
        try:
            # Chuyển đổi chuỗi JSON 'skills' từ Form thành đối tượng Python (list)
            import json

            update_dict["skills"] = json.loads(skills)
            if not isinstance(update_dict["skills"], list):
                raise ValueError("Skills must be a JSON list of strings")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f'Invalid format for skills. Must be a JSON string of a list (e.g., \'["skill1", "skill2"]\'): {e}',
            )
    # Chỉ xử lý email nếu được cung cấp và không rỗng
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)
            
            # ✅ SỬA: Thêm kiểm tra DB (giống hệt logic của profile.py)
            if valid_email != db_user.email:
                existing_user = await services.user_service.get_user_by_email(db, valid_email)
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
            update_dict["email"] = valid_email
            
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid email format: {cleaned_email}. Error: {error_detail}",
            )
        # (Thêm HTTPException nếu raise từ logic check DB)
        except HTTPException as e: 
            raise e

    # Tạo schema UserUpdate CHỈ với các dữ liệu đã được xác thực
    user_in = schemas.UserUpdate(**update_dict)

    # Truyền avatar vào hàm service
    return await services.user_service.update_user(
        db, db_user, user_in, avatar_file=avatar
    )


# === KẾT THÚC HÀM CẬP NHẬT ===
@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def delete_existing_user(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một người dùng."""
    if user_id == current_admin.id:
        raise PermissionDeniedError(detail="Admin cannot delete themselves")

    # Bỏ kiểm tra 'is None' vì service đã ném 404
    await services.user_service.delete_user(db, user_id)
    return None


@router.post(
    "/users/{user_id}/set-password",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - User Management"],
)
async def admin_set_user_password(
    user_id: int,
    password_data: schemas.AdminSetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Admin đặt lại mật khẩu cho người dùng."""
    await services.user_service.set_password_by_admin(
        db, user_id, password_data.new_password
    )
    return None


@router.post(
    "/users/bulk-action",
    status_code=status.HTTP_200_OK,
    tags=["Admin - User Management"],
)
async def bulk_user_action(
    action_data: schemas.BulkActionSchema,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Thực hiện hành động hàng loạt (xóa, đổi trạng thái) trên nhiều người dùng."""
    message = await services.user_service.perform_bulk_action(
        db,
        action=action_data.action,
        user_ids=action_data.user_ids,
        admin_user=current_admin,
        new_status=action_data.status,
    )
    return {"detail": message}


# ===============================================================
# ORGANIZATION & MAJOR MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/organization-units",
    response_model=schemas.OrganizationUnit,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_organization_unit(
    unit_in: schemas.OrganizationUnitCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một đơn vị tổ chức mới."""
    return await organization_service.create_organization_unit(db, unit_in)


@router.get(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def get_organization_unit_details(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một đơn vị tổ chức."""
    return await organization_service.get_organization_unit_by_id(db, unit_id)


@router.put(
    "/organization-units/{unit_id}",
    response_model=schemas.OrganizationUnit,
    tags=["Admin - Organization"],
)
async def update_existing_organization_unit(
    unit_id: int,
    unit_in: schemas.OrganizationUnitUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một đơn vị tổ chức."""
    return await organization_service.update_organization_unit(db, unit_id, unit_in)


@router.delete(
    "/organization-units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_organization_unit(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một đơn vị tổ chức."""
    await organization_service.delete_organization_unit(db, unit_id)
    return None


@router.post(
    "/majors",
    response_model=schemas.Major,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Organization"],
)
async def create_new_major(
    major_in: schemas.MajorCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một ngành học mới."""
    return await organization_service.create_major(db, major_in)


@router.get(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def get_major_details(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một ngành học."""
    return await organization_service.get_major_by_id(db, major_id)


@router.put(
    "/majors/{major_id}", response_model=schemas.Major, tags=["Admin - Organization"]
)
async def update_existing_major(
    major_id: int,
    major_in: schemas.MajorUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một ngành học."""
    return await organization_service.update_major(db, major_id, major_in)


@router.delete(
    "/majors/{major_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Organization"],
)
async def delete_existing_major(
    major_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một ngành học."""
    await organization_service.delete_major(db, major_id)
    return None


# ===============================================================
# CONFIG MANAGEMENT ROUTES
# ===============================================================


@router.get(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def get_assignment_config_route(
    unit_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy cấu hình phân chia của một đơn vị."""
    params = await config_service.get_assignment_config(db, unit_id)
    return {"params": params}


@router.put(
    "/assignment-config/{unit_id}",
    response_model=schemas.AssignmentConfig,
    tags=["Admin - Config"],
)
async def update_assignment_config_route(
    unit_id: int,
    config_in: schemas.AssignmentConfig,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật cấu hình phân chia của một đơn vị."""
    updated_model = await config_service.update_assignment_config(
        db, unit_id, config_in.params
    )
    # Trả về schema Pydantic dựa trên model đã cập nhật từ DB
    return schemas.AssignmentConfig(params=updated_model.params)


@router.get(
    "/skill-rules", response_model=List[schemas.SkillRule], tags=["Admin - Config"]
)
async def get_all_skill_rules_route(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy tất cả các quy tắc kỹ năng."""
    return await config_service.get_all_skill_rules(db)


@router.post(
    "/skill-rules",
    response_model=schemas.SkillRule,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Config"],
)
async def create_new_skill_rule_route(
    rule_in: schemas.SkillRuleCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một quy tắc kỹ năng mới."""
    return await config_service.create_skill_rule(db, rule_in)


@router.delete(
    "/skill-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Config"],
)
async def delete_skill_rule_route(
    rule_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một quy tắc kỹ năng."""
    await config_service.delete_skill_rule(db, rule_id)
    return None


# ===============================================================
# PIPELINE MANAGEMENT ROUTES (MỚI)
# ===============================================================


@router.get(
    "/pipeline-stages",
    response_model=List[schemas.PipelineStage],
    tags=["Admin - Pipeline Management"],
)
async def get_all_pipeline_stages_list(
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Giai đoạn (Stages) trong Pipeline."""
    # Gọi service function đã có (trả về List[dict] từ cache/DB)
    # Pydantic sẽ tự động chuyển đổi List[dict] -> List[schemas.PipelineStage]
    stages_data = await pipeline_service.get_all_pipeline_stages(db)
    return stages_data


@router.post(
    "/pipeline-stages",
    response_model=schemas.PipelineStage,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_pipeline_stage(
    stage_in: schemas.PipelineStageCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Giai đoạn (Stage) mới trong Pipeline."""
    return await pipeline_service.create_pipeline_stage(db, stage_in)


@router.get(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def get_pipeline_stage_details(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Giai đoạn (Stage)."""
    return await pipeline_service.get_pipeline_stage(db, stage_id)


@router.put(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_pipeline_stage(
    stage_id: str,
    stage_in: schemas.PipelineStageUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Giai đoạn (Stage)."""
    return await pipeline_service.update_pipeline_stage(db, stage_id, stage_in)


@router.delete(
    "/pipeline-stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_pipeline_stage(
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Giai đoạn (Stage). (Chỉ thành công nếu không có Status nào liên kết)"""
    await pipeline_service.delete_pipeline_stage(db, stage_id)
    return None


@router.post(
    "/consultation-statuses",
    response_model=schemas.ConsultationStatus,
    status_code=status.HTTP_201_CREATED,
    tags=["Admin - Pipeline Management"],
)
async def create_new_consultation_status(
    status_in: schemas.ConsultationStatusCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Trạng thái tư vấn (Status) mới."""
    return await pipeline_service.create_consultation_status(db, status_in)


@router.get(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def get_consultation_status_details(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Trạng thái tư vấn (Status)."""
    return await pipeline_service.get_consultation_status(db, status_id)


@router.put(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
    tags=["Admin - Pipeline Management"],
)
async def update_existing_consultation_status(
    status_id: str,
    status_in: schemas.ConsultationStatusUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Trạng thái tư vấn (Status)."""
    return await pipeline_service.update_consultation_status(db, status_id, status_in)


@router.delete(
    "/consultation-statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Admin - Pipeline Management"],
)
async def delete_existing_consultation_status(
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xóa một Trạng thái tư vấn (Status). (Chỉ thành công nếu không có Lead nào sử dụng)"""
    await pipeline_service.delete_consultation_status(db, status_id)
    return None


# ===============================================================
# LEAD MANAGEMENT ROUTES
# ===============================================================


@router.post(
    "/leads/{lead_id}/revert-status",
    response_model=schemas.Lead,
    tags=["Admin - Lead Management"],  # Thêm tag mới hoặc dùng tag cũ
    summary="Admin reverts the last status change of a Lead",
)
async def admin_revert_lead_status(
    lead: models.Lead = LeadAccessDep,  # <-- THAY ĐỔI (Đã bao gồm check admin)
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI (Check Casbin)
    reason: Optional[str] = Body(
        None, embed=True, description="Reason for reverting the status"
    ),
    db: AsyncSession = Depends(database.get_db),
):
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của một Lead.
    """
    try:
        # Dependency 'LeadAccessDep' đã kiểm tra quyền admin/manager
        updated_lead = await lead_service.revert_last_status(
            db=db, lead_id=lead.id, admin_user=current_user, reason=reason
        )
        return updated_lead
    except (BadRequest, ResourceNotFoundError) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.error(
            "Error reverting lead status via API",
            lead_id=lead.id,
            admin_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revert lead status.",
        )


@router.post(
    "/leads/bulk-assign",
    status_code=status.HTTP_202_ACCEPTED,  # Trả về 202 vì task chạy nền
    tags=["Admin - Lead Management"],
    summary="Trigger automatic assignment for multiple leads",
)
async def bulk_assign_leads(
    assignment_data: schemas.BulkAssignLeadsSchema,  # Sử dụng schema mới
    current_admin: models.User = PermissionDep,  # Yêu cầu quyền admin (qua Casbin)
):
    """
    (Admin only) Kích hoạt tác vụ phân công tự động cho một danh sách các Lead ID.
    Các tác vụ sẽ được xử lý dưới nền bởi Celery worker.
    """
    lead_ids = assignment_data.lead_ids
    dispatched_count = 0
    failed_ids = []

    log.info(
        "Received bulk assign request",
        admin_id=current_admin.id,
        lead_count=len(lead_ids),
    )

    for lead_id in lead_ids:
        try:
            # Gọi task Celery cho từng lead_id
            process_automatic_lead_assignment_task.delay(lead_id)
            dispatched_count += 1
            log.debug("Dispatched assignment task", lead_id=lead_id)
        except Exception as e:
            failed_ids.append(lead_id)
            log.error(
                "Failed to dispatch assignment task for lead",
                lead_id=lead_id,
                error=str(e),
                exc_info=True,  # Log traceback nếu có lỗi khi gọi .delay()
            )

    success_rate = (dispatched_count / len(lead_ids)) * 100 if lead_ids else 100
    message = f"Successfully dispatched {dispatched_count}/{len(lead_ids)} ({success_rate:.1f}%) assignment tasks."

    if failed_ids:
        log.warning(
            "Some tasks failed to dispatch",
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
        )
        message += f" Failed to dispatch for {len(failed_ids)} leads."
        # Bạn có thể cân nhắc trả về status code khác nếu có lỗi, ví dụ 207 Multi-Status
        # Hoặc vẫn trả về 202 nhưng kèm thông tin lỗi chi tiết hơn trong body
        # return {"detail": message, "failed_ids": failed_ids}

    log.info(
        "Finished processing bulk assign request",
        dispatched=dispatched_count,
        failed=len(failed_ids),
    )
    return {"detail": message}


@router.post(
    "/leads/import",
    response_model=schemas.LeadImportResult,  # Sử dụng schema kết quả mới
    status_code=status.HTTP_200_OK,  # Trả về 200 OK (hoặc 207 Multi-Status nếu muốn chi tiết hơn)
    tags=["Admin - Lead Management"],
    summary="Import leads from a CSV or Excel file",
)
async def import_leads_from_file(
    file: UploadFile = File(
        ..., description="CSV or Excel file containing lead data (.csv, .xlsx)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """
    (Admin only) Import leads từ file CSV hoặc Excel.
    File cần có các cột: 'full_name', 'email', 'phone', 'source', 'unit_id', 'major_id' (tùy chọn).
    Endpoint sẽ tạo leads trong DB nhưng **không** tự động phân công.
    Trả về kết quả import bao gồm ID các lead đã tạo và danh sách lỗi.
    """
    log.info(
        "Received lead import request",
        admin_id=current_admin.id,
        filename=file.filename,
    )

    # --- 1. Kiểm tra loại file ---
    file_extension = ""
    if file.filename:
        file_extension = file.filename.rsplit(".", 1)[-1].lower()

    if file_extension not in ["csv", "xlsx"]:
        log.warning(
            "Import failed: Invalid file extension",
            filename=file.filename,
            ext=file_extension,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only .csv and .xlsx files are supported.",
        )

    # --- 2. Đọc nội dung file vào DataFrame ---
    try:
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file uploaded."
            )

        if file_extension == "csv":
            # Dùng io.BytesIO để pandas đọc từ bytes
            df = pd.read_csv(io.BytesIO(content))
        else:  # xlsx
            df = pd.read_excel(io.BytesIO(content), engine="openpyxl")

        log.info(f"Successfully read {len(df)} rows from {file_extension} file.")

    except HTTPException as e:
        raise e  # Ném lại lỗi 400
    except Exception as e:
        log.error(
            "Failed to read or parse file content",
            filename=file.filename,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read or parse the file. Ensure it is a valid {file_extension} file. Error: {e}",
        )
    finally:
        await file.close()  # Luôn đóng file

    # --- 3. Xử lý dữ liệu và Tạo Leads ---
    required_columns = {"full_name", "email", "phone", "source", "unit_id"}
    # optional_columns = {"major_id"}  # Các cột tùy chọn
    # Chuẩn hóa tên cột (viết thường, bỏ dấu cách)
    df.columns = df.columns.str.lower().str.strip().str.replace(" ", "_")

    # Kiểm tra các cột bắt buộc
    missing_cols = required_columns - set(df.columns)
    if missing_cols:
        log.warning(
            "Import failed: Missing required columns", missing=list(missing_cols)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File is missing required columns: {', '.join(missing_cols)}",
        )

    leads_to_insert = []
    errors: List[schemas.LeadImportError] = []
    processed_row_count = 0
    initial_status_id = settings.DEFAULT_INITIAL_LEAD_STATUS_ID  # Lấy status mặc định

    # Lấy stage_id tương ứng với initial_status_id (cần cho bulk insert)
    initial_status_obj = await db.get(models.ConsultationStatus, initial_status_id)
    initial_stage_id = initial_status_obj.stage_id if initial_status_obj else None
    if not initial_stage_id:
        log.error(
            f"FATAL: Initial status {initial_status_id} not found in DB. Cannot determine initial stage."
        )
        raise HTTPException(
            status_code=500,
            detail="System configuration error: Initial lead status not found.",
        )

    # Lấy danh sách email đã tồn tại để kiểm tra trùng lặp hiệu quả hơn
    existing_emails_in_db = set()
    async for email_tuple in await db.stream(select(models.Lead.email)):
        existing_emails_in_db.add(email_tuple[0])
    emails_in_current_file = set()

    # Lặp qua từng dòng trong DataFrame
    for index, row in df.iterrows():
        processed_row_count += 1
        row_number = index + 2
        row_data = row.to_dict()
        cleaned_data = {}  # Dữ liệu đã được ép kiểu
        validation_errors_for_row = []  # Lỗi ép kiểu

        # --- ✅ BẮT ĐẦU SỬA LỖI ÉP KIỂU ---

        # 1. Ép kiểu các trường bắt buộc
        try:
            # Dùng str() và strip() cho các trường text
            cleaned_data["full_name"] = str(row_data.get("full_name", "")).strip()
            cleaned_data["email"] = str(row_data.get("email", "")).strip()
            # Xử lý đặc biệt cho 'phone': luôn chuyển sang string, bỏ ".0" nếu là float
            phone_val = row_data.get("phone")
            cleaned_data["phone"] = (
                str(phone_val).split(".")[0] if pd.notna(phone_val) else ""
            )

            cleaned_data["source"] = str(row_data.get("source", "")).strip()

            # Xử lý 'unit_id': ép sang int
            unit_id_val = row_data.get("unit_id")
            if pd.notna(unit_id_val):
                cleaned_data["unit_id"] = int(float(unit_id_val))
            else:
                # Nếu unit_id là bắt buộc, Pydantic sẽ bắt lỗi 'missing' sau
                cleaned_data["unit_id"] = None

        except (ValueError, TypeError, Exception) as e:
            # Lỗi cơ bản khi ép kiểu (ví dụ: unit_id là "abc")
            validation_errors_for_row.append(f"Type conversion error: {e}")

        # 2. Ép kiểu trường tùy chọn 'major_id'
        major_id_val = row_data.get("major_id")
        if pd.notna(major_id_val):
            try:
                cleaned_data["major_id"] = int(float(major_id_val))
            except (ValueError, TypeError):
                validation_errors_for_row.append(
                    "Invalid format for 'major_id', expected a number."
                )
        else:
            cleaned_data["major_id"] = None

        # --- KẾT THÚC SỬA LỖI ÉP KIỂU ---

        # 3. Validate bằng Pydantic
        try:
            # Nếu đã có lỗi ép kiểu, ném lỗi luôn để vào khối except
            if validation_errors_for_row:
                raise ValueError(", ".join(validation_errors_for_row))

            lead_in = schemas.LeadCreate(**cleaned_data)

            # Kiểm tra trùng lặp email
            if (
                lead_in.email in existing_emails_in_db
                or lead_in.email in emails_in_current_file
            ):
                raise ValueError(
                    f"Email '{lead_in.email}' already exists in the database or this file."
                )

            emails_in_current_file.add(lead_in.email)

            # Chuẩn bị dict để bulk insert (Nếu mọi thứ OK)
            lead_dict = lead_in.model_dump()
            lead_dict["status"] = initial_status_id
            lead_dict["consultation_status_id"] = initial_status_id
            lead_dict["pipeline_stage_id"] = initial_stage_id
            lead_dict["assigned_officer_id"] = None
            lead_dict["assigned_at"] = None

            leads_to_insert.append(lead_dict)

        except (ValueError, TypeError) as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Data validation failed: {e}",  # Lỗi Pydantic hoặc lỗi ép kiểu/trùng lặp
                    row_data=row_data,
                )
            )
        except Exception as e:
            errors.append(
                schemas.LeadImportError(
                    row_number=row_number,
                    error_message=f"Unexpected error processing row: {e}",
                    row_data=row_data,
                )
            )

    # --- 4. Thực hiện Bulk Insert ---
    created_lead_ids: List[int] = []
    batch_size = 100  # Commit mỗi 100 lead

    if leads_to_insert:
        try:
            for i in range(0, len(leads_to_insert), batch_size):
                batch = leads_to_insert[i : i + batch_size]
                
                async with db.begin_nested(): # Bắt đầu 1 transaction con
                    # 1. Insert batch
                    await db.execute(pg_insert(models.Lead), batch)
                    
                    # 2. Lấy ID của batch vừa insert
                    inserted_emails = [ld["email"] for ld in batch]
                    query = select(models.Lead.id).where(models.Lead.email.in_(inserted_emails))
                    result = await db.execute(query)
                    batch_ids = result.scalars().all()
                    created_lead_ids.extend(batch_ids)
                
                # 3. Commit transaction con (db.begin_nested() tự commit)
                log.info(f"Committed batch {i // batch_size + 1}, {len(batch_ids)} leads inserted.")

            # Commit transaction chính (nếu có)
            await db.commit()
            log.info(f"Successfully bulk inserted {len(created_lead_ids)} leads in total.")

        except Exception as e:
            await db.rollback() # Rollback transaction chính nếu có lỗi
            log.error(
                "Bulk lead insertion failed during batch, rolling back.", error=str(e), exc_info=True
            )
            # Ghi nhận lỗi
            errors.append(
                schemas.LeadImportError(
                    row_number=-1,
                    error_message=f"Database bulk insert error (batch failed): {e}",
                    row_data={},
                )
            )
            created_lead_ids = []  # Reset ID vì đã rollback

    # --- 5. Trả về kết quả ---
    result = schemas.LeadImportResult(
        total_rows_processed=processed_row_count,
        successful_imports=len(created_lead_ids),
        failed_imports=len(errors),
        created_lead_ids=created_lead_ids,
        errors=errors,
    )

    result_summary = result.model_dump(exclude={"errors"})
    if errors:
        log.warning("Lead import process finished with errors", result=result_summary)
    else:
        log.info("Lead import process finished successfully", result=result_summary)

    return result
