# app/routers/profile.py
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError  # <-- BỔ SUNG TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, services
from ..core import deps
from ..services import activity_service

router = APIRouter(tags=["Profile"])
PermissionDep = Depends(deps.check_permission)


@router.get("", response_model=schemas.User)
async def read_current_user_profile(
    current_user: models.User = PermissionDep,  # <-- THAY ĐỔI
):
    """
    Lấy thông tin profile của chính người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền GET /api/profile)
    """
    return current_user


# === HÀM ĐÃ ĐƯỢỢC CẬP NHẬT ===
@router.put("", response_model=schemas.User)
async def update_current_user_profile(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
):
    """
    Cập nhật thông tin profile cho người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền PUT /api/profile)
    """
    update_dict = {}
    if full_name is not None and full_name.strip():
        update_dict["full_name"] = full_name.strip()
    if phone_number is not None and phone_number.strip():
        update_dict["phone_number"] = phone_number.strip()

    # --- SỬA LỖI LOGIC TẠI ĐÂY ---
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)

            # Chỉ kiểm tra DB nếu email thực sự thay đổi
            if valid_email != current_user.email:
                existing_user = await services.user_service.get_user_by_email(
                    db, valid_email
                )
                if existing_user:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email already registered by another user",
                    )
                update_dict["email"] = valid_email
        except ValidationError as e:
            error_detail = e.errors()[0].get("msg", "Invalid email format")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid email format: {cleaned_email}. Error: {error_detail}",
            )
    # --- KẾT THÚC SỬA LỖI ---

    # Track changes for activity log
    changes = {}
    if update_dict:
        for key, new_value in update_dict.items():
            old_value = getattr(current_user, key, None)
            if old_value != new_value:
                changes[key] = {"old": str(old_value), "new": str(new_value)}

    update_data = schemas.UserUpdate(**update_dict)

    updated_user = await services.user_service.update_profile(
        db, db_user=current_user, user_in=update_data, avatar_file=avatar
    )

    # Log activity
    await activity_service.log_activity_from_request(
        db=db,
        request=request,
        action="update_profile",
        resource_type="user",
        actor_id=current_user.id,
        target_user_id=current_user.id,
        resource_id=current_user.id,
        description=f"User updated their own profile: {current_user.username}",
        changes=changes if changes else None,
    )

    return updated_user
