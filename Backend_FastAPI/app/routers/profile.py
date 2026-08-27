# app/routers/profile.py
import structlog
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import EmailStr, TypeAdapter, ValidationError  # <-- BỔ SUNG TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core.deps import CasbinAuth  # ✅ Phase 2.2: Use standard alias
from ..services import activity_service, user_service
from app.core.rate_limits import limiter, RateLimits

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Profile"])


# ✅ PHASE 1: Helper function for activity logging (replaces service-level log_activity_from_request)
async def log_profile_activity(
    db: AsyncSession,
    request: Request,
    action: str,
    resource_type: str,
    actor_id: Optional[int] = None,
    target_user_id: Optional[int] = None,
    resource_id: Optional[int] = None,
    description: Optional[str] = None,
    changes: Optional[dict] = None,
) -> models.UserActivityLog:
    """Trích IP/UA từ request rồi uỷ quyền cho ``activity_service``.

    Trả về **một** ``UserActivityLog``, KHÔNG phải tuple. Caller vẫn phải
    ``db.commit()`` — hàm này chỉ ``flush``.

    ⚠️ Đừng khôi phục kiểu ``Tuple[UserActivityLog, Callable]``. Contract một
    đối tượng là contract của ``activity_service.log_activity`` và đã có test
    service khoá nó; bọc lại thành tuple ở đây là dựng một callback no-op chỉ
    để chiều caller — hai nguồn chuẩn cho cùng một câu hỏi.
    """
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    return await activity_service.log_activity(
        db=db,
        action=action,
        resource_type=resource_type,
        actor_id=actor_id,
        target_user_id=target_user_id,
        resource_id=resource_id,
        description=description,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.User)
async def read_current_user_profile(
    request: Request,
    current_user: models.User = CasbinAuth,  # <-- THAY ĐỔI
):
    """
    Lấy thông tin profile của chính người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền GET /api/profile)
    """
    return current_user


# === HÀM ĐÃ ĐƯỢỢC CẬP NHẬT ===
@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put("", response_model=schemas.User)
async def update_current_user_profile(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),
):
    """
    Cập nhật thông tin profile cho người dùng đang đăng nhập.
    (Casbin sẽ kiểm tra quyền PUT /api/profile)
    """
    # Form-data convention (xem admin/users.py): empty string "" → clear
    # (set NULL) cho nullable column; field không gửi → skip; có value → set.
    update_dict = {}
    if full_name is not None:
        stripped = full_name.strip()
        update_dict["full_name"] = stripped if stripped else None
    if phone_number is not None:
        stripped = phone_number.strip()
        update_dict["phone_number"] = stripped if stripped else None

    # --- SỬA LỖI LOGIC TẠI ĐÂY ---
    if email is not None and email.strip():
        cleaned_email = email.strip()
        try:
            EmailStrAdapter = TypeAdapter(EmailStr)
            valid_email = EmailStrAdapter.validate_python(cleaned_email)

            # Chỉ kiểm tra DB nếu email thực sự thay đổi
            if valid_email != current_user.email:
                existing_user = await user_service.get_user_by_email(
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

    # ✅ REFACTORED (Issue #3): Read avatar file content in router layer
    avatar_content = None
    avatar_filename = None
    if avatar and avatar.filename:
        from app.config import settings
        # Validate file size before reading (DoS protection)
        avatar.file.seek(0, 2)  # Seek to end
        file_size = avatar.file.tell()
        avatar.file.seek(0)  # Reset to beginning

        if file_size > settings.MAX_AVATAR_CONTENT_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File size cannot exceed {settings.MAX_AVATAR_SIZE_MB}MB."
            )

        avatar_content = await avatar.read()
        avatar_filename = avatar.filename

    updated_user, callback = await user_service.update_profile(
        db, db_user=current_user, user_in=update_data,
        avatar_content=avatar_content,  # ✅ REFACTORED: Pass bytes instead of UploadFile
        avatar_filename=avatar_filename,  # ✅ REFACTORED: Pass filename
    )

    # ✅ TRANSACTION PATTERN: Commit and execute callback
    await db.commit()
    await callback()

    # Best-effort audit log — business change already committed above
    try:
        await log_profile_activity(
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
        await db.commit()
    except Exception:
        log.error("Failed to persist audit log for profile update", user_id=current_user.id, exc_info=True)

    return updated_user