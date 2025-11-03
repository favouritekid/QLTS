
# app/services/user_service.py
from typing import Any, Dict, List, Optional, Tuple

import structlog
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from .. import models, schemas

from ..config import settings
from ..database import safe_redis_delete, safe_redis_set
from ..security import (
    create_password_reset_token,
    get_password_hash,
    verify_password,
    verify_password_reset_token,
)
from ..utils import file_helpers
from ..utils.exceptions import (
    BadRequest,
    DuplicateResourceError,
    InvalidCredentials,
    InvalidToken,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


# --- Các hàm lấy User (Read-only, không cần rollback) ---


async def get_user_by_username(
    db: AsyncSession, username: str
) -> Optional[models.User]:
    query = select(models.User).where(models.User.username == username.strip())
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
        await db.refresh(user) # Vẫn refresh
        return user # <-- SỬA: Trả về user
    return None # <-- SỬA: Trả về None nếu không tìm thấy


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    cleaned_email = email.strip()
    query = select(models.User).where(models.User.email == cleaned_email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    if user:
         await db.refresh(user) # Vẫn refresh
         return user # <-- SỬA: Trả về user
    return None # <-- SỬA: Trả về None nếu không tìm thấy


async def get_user_by_id(db: AsyncSession, user_id: int) -> models.User:
    user = await db.get(models.User, user_id)
    if not user:
        raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
    await db.refresh(user) # <-- THÊM DÒNG NÀY
    return user


async def authenticate_user(
    db: AsyncSession, username: str, password: str
) -> models.User:
    """
    Xác thực người dùng.
    ✅ FIXED: Chống Timing Attack bằng cách luôn thực hiện hash comparison.
    """
    user = await get_user_by_username(db, username)

    # === ⭐️ SỬA LỖI TIMING ATTACK ===
    # 1. Chuẩn bị một dummy hash hợp lệ (phải bắt đầu bằng $2b$ và có độ dài đúng)
    # Bạn có thể tạo hash này một lần từ một mật khẩu ngẫu nhiên.
    # Ví dụ: get_password_hash("a_very_random_dummy_password_for_timing_attack")
    dummy_hash = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"  # Thay bằng hash thật

    # 2. Xác định hash nào sẽ được dùng để kiểm tra
    hash_to_check = user.password_hash if user else dummy_hash

    # 3. LUÔN LUÔN thực hiện việc kiểm tra mật khẩu (tốn thời gian)
    is_password_valid = verify_password(password, hash_to_check)

    # 4. KIỂM TRA KẾT QUẢ SAU KHI ĐÃ VERIFY
    # Lỗi nếu user không tồn tại HOẶC mật khẩu không hợp lệ
    if not user or not is_password_valid:
        await log.warning("Authentication failed", username=username, reason="Invalid user or password")
        raise InvalidCredentials()

    await db.refresh(user) # <-- THÊM DÒNG NÀY
    await log.info("Authentication successful", username=username)
    return user


# --- Hàm Tạo User ---


async def create_user(db: AsyncSession, user_in: schemas.UserCreate) -> models.User:
    try:
        hashed_password = get_password_hash(user_in.password)
        db_user = models.User(
            username=user_in.username.strip(),
            email=user_in.email.strip(),
            full_name=user_in.full_name,
            password_hash=hashed_password,
            role="user",
            status="active",
        )
        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create user",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


async def create_user_by_admin(
    db: AsyncSession,
    user_in: schemas.AdminUserCreate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    try:
        hashed_password = get_password_hash(user_in.password)
        db_user = models.User(
            username=user_in.username.strip(),
            email=user_in.email.strip(),
            full_name=user_in.full_name,
            password_hash=hashed_password,
            role=user_in.role,
            status=user_in.status,
            avatar_url=None,
        )
        if avatar_file:
            await log.debug(
                "Processing avatar for new admin-created user",
                filename=avatar_file.filename,
            )
            # Lỗi 413 từ save_avatar sẽ bị bắt bởi khối except bên ngoài
            new_avatar_url = await file_helpers.save_avatar(avatar_file)
            db_user.avatar_url = new_avatar_url
            await log.info(
                "Avatar saved for new user", user=user_in.username, url=new_avatar_url
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to create user by admin",
            username=user_in.username,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Lấy danh sách User (Read-only) ---


async def get_users(
    db: AsyncSession, params: Dict[str, Any], skip: int = 0, limit: int = 100
) -> Tuple[int, List[models.User]]:
    # ... (Không thay đổi, read-only) ...
    query = select(models.User)

    allowed_filters = {
        "role": models.User.role,
        "status": models.User.status,
    }
    text_search_fields = [
        models.User.username,
        models.User.full_name,
        models.User.email,
    ]

    for key, value in params.items():
        if key in allowed_filters and value:
            values_to_filter = [v.strip() for v in value.split(",")]
            query = query.filter(allowed_filters[key].in_(values_to_filter))
        elif key == "search" and value:
            search_term = f"%{value.strip()}%"
            search_conditions = [
                field.ilike(search_term) for field in text_search_fields
            ]
            query = query.filter(or_(*search_conditions))

    count_query = select(func.count()).select_from(query.alias())
    total_count_result = await db.execute(count_query)
    total_count = total_count_result.scalar_one()

    sort = params.get("sort", "id")
    order = params.get("order", "asc")
    if hasattr(models.User, sort):
        sort_column = getattr(models.User, sort)
        if order.lower() == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

    paged_query = query.offset(skip).limit(limit)
    users_result = await db.execute(paged_query)
    users = users_result.scalars().all()

    return total_count, users


# --- Hàm Cập nhật User ---


async def update_user(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        if "email" in update_data and update_data["email"] != db_user.email:
            # get_user_by_email đã có refresh bên trong
            existing_user = await get_user_by_email(db, update_data["email"])
            # So sánh ID an toàn vì existing_user đã được refresh (nếu tìm thấy)
            if existing_user and existing_user.id != user_id_for_logging: # Sử dụng biến cục bộ
                raise DuplicateResourceError(
                    detail="Email already registered by another user"
                )

        for field, value in update_data.items():
            if value is not None:
                setattr(
                    db_user, field, value.strip() if isinstance(value, str) else value
                )

        if avatar_file:
            await log.debug(
                "Processing avatar update for user",
                user_id=db_user.id,
                filename=avatar_file.filename,
            )
            # Lỗi 413 từ save_avatar sẽ bị bắt
            new_avatar_url = await file_helpers.save_avatar(
                avatar_file, old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            await log.info(
                "Avatar updated successfully for user",
                user_id=db_user.id,
                url=new_avatar_url,
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update user",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


async def update_profile(
    db: AsyncSession,
    db_user: models.User,
    user_in: schemas.UserUpdate,
    avatar_file: Optional[UploadFile] = None,
) -> models.User:
    user_id_for_logging = db_user.id
    try:
        update_data = user_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            if field in ["full_name", "phone_number", "email"]:
                if value is not None:
                    setattr(
                        db_user,
                        field,
                        value.strip() if isinstance(value, str) else value,
                    )

        if avatar_file:
            await log.debug(
                "Processing profile avatar update",
                user_id=user_id_for_logging, 
                filename=avatar_file.filename,
            )
            # Lỗi 413 từ save_avatar sẽ bị bắt
            new_avatar_url = await file_helpers.save_avatar(
                avatar_file, old_avatar_url=db_user.avatar_url
            )
            db_user.avatar_url = new_avatar_url
            await log.info(
                "Profile avatar updated successfully",
                user_id=user_id_for_logging, 
                url=new_avatar_url,
            )

        db.add(db_user)
        await db.commit()
        await db.refresh(db_user)
        return db_user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to update profile",
            user_id=user_id_for_logging,
            error=str(e),
            exc_info=True,
        )
        raise e


# --- Hàm Xóa User ---


async def delete_user(db: AsyncSession, user_id: int):
    """Xóa một user. Ném ResourceNotFound nếu không tìm thấy."""
    try:
        user_to_delete = await db.get(models.User, user_id)
        if not user_to_delete:
            raise ResourceNotFoundError(detail=f"User with id {user_id} not found.")
        await db.delete(user_to_delete)
        await db.commit()
    except Exception as e:
        await db.rollback()
        await log.error("Failed to delete user", user_id=user_id, error=str(e), exc_info=True)
        raise e


# --- Logic Password (Hàm handle_forgot_password chỉ đọc, không commit) ---


async def handle_forgot_password(db: AsyncSession, email_in: str):
    from ..celery_utils import send_password_reset_email_task
    cleaned_email = email_in.strip()
    user = await get_user_by_email(db, email=cleaned_email)
    if not user:
        await log.debug("User not found for forgot password request", email=cleaned_email)
        return

    await log.info(
        "User found for forgot password request. Sending reset email.", user_id=user.id
    )
    token = create_password_reset_token(email=user.email)
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    send_password_reset_email_task.delay(
        email_to=user.email, reset_url=reset_url, username=user.username
    )
    # Không raise lỗi ở đây vì đã trả về 202 cho client


async def reset_password(
    db: AsyncSession, token: str, new_password: str
) -> models.User:
    """Đặt lại mật khẩu từ token. Ném InvalidToken hoặc ResourceNotFound."""
    try:
        email = verify_password_reset_token(token)
        if not email:
            await log.warning("Invalid reset token attempt", token_prefix=token[:10])
            raise InvalidToken()
        
        user = await get_user_by_email(db, email=email)
        if not user:
            await log.warning("Reset token for non-existent user", email=email)
            raise ResourceNotFoundError(
                detail="User associated with this token not found."
            )

        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        await log.info("User password reset successfully", user_id=user.id)
        return user
    except Exception as e:
        await db.rollback()
        await log.error("Failed to reset password", token=token, error=str(e), exc_info=True)
        raise e


async def change_password(
    db: AsyncSession, user: models.User, old_password: str, new_password: str
):
    """Người dùng tự đổi mật khẩu. Ném BadRequest nếu mật khẩu cũ sai."""
    user_id_for_logging = user.id
    try:
        if not verify_password(old_password, user.password_hash):
            raise BadRequest(detail="Incorrect old password")

        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        await log.info("User changed password successfully", user_id=user_id_for_logging)
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to change password", user_id=user_id_for_logging, error=str(e), exc_info=True
        )
        raise e

async def remove_user_from_global_blacklist(user_id: int):
    """Xóa user khỏi global blacklist (thường gọi sau khi login thành công)."""
    blacklist_key = f"user_blacklist:{user_id}"
    try:
        deleted_count = await safe_redis_delete(blacklist_key)
        if deleted_count > 0:
            await log.info("Removed user from global blacklist", user_id=user_id)
    except Exception as e:
        await log.error("Failed to remove user from global blacklist", user_id=user_id, error=str(e))
        raise # Ném lại lỗi để router có thể bắt


async def set_password_by_admin(
    db: AsyncSession, user_id: int, new_password: str
) -> models.User:
    """Admin đặt lại mật khẩu cho người dùng. Ném ResourceNotFound."""
    try:
        user = await get_user_by_id(db, user_id)  # Hàm này đã raise 404
        user.password_hash = get_password_hash(new_password)
        db.add(user)
        await db.commit()
        await log.info(
            "Admin set password for user successfully",
            admin_user="admin",
            user_id=user.id,
        )
        return user
    except Exception as e:
        await db.rollback()
        await log.error(
            "Failed to set password by admin",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise e


async def invalidate_all_sessions(db: AsyncSession, user: models.User):
    """
    Vô hiệu hóa tất cả các phiên hoạt động của người dùng (thường sau khi đổi mật khẩu).
    """
    try:
        # 1. Xóa JTI đang hoạt động trong DB
        user.active_jti = None
        db.add(user)

        # 2. Xóa JTI refresh token hiện tại khỏi Redis
        try:
            await safe_redis_delete(f"refresh_jti:{user.id}")
            await log.info("Refresh JTI deleted during session invalidation", user_id=user.id)
        except Exception as e_redis_del:
            # Ghi log nhưng không dừng lại nếu xóa Redis lỗi
            await log.error(
                "Failed to delete refresh JTI during session invalidation",
                user_id=user.id,
                error=str(e_redis_del),
            )

        # 3. Thêm user ID vào blacklist toàn cục trên Redis
        # Thời gian sống bằng thời gian sống tối đa của refresh token
        # (Để đảm bảo mọi token cũ đều bị chặn cho đến khi hết hạn tự nhiên)
        max_token_lifetime_seconds = int(
            settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        )

        # Đảm bảo TTL không âm
        if max_token_lifetime_seconds <= 0:
            max_token_lifetime_seconds = 60  # Đặt TTL tối thiểu là 1 phút

        try:
            blacklist_key = f"user_blacklist:{user.id}"
            await safe_redis_set(
                blacklist_key, "sessions_invalidated", ex=max_token_lifetime_seconds
            )
            await log.info(
                "User added to global blacklist",
                user_id=user.id,
                ttl_seconds=max_token_lifetime_seconds,
            )
        except Exception as e_redis_set:
            # Lỗi nghiêm trọng nếu không thể blacklist user, rollback DB
            await log.error(
                "CRITICAL: Failed to add user to global blacklist, rolling back DB changes",
                user_id=user.id,
                error=str(e_redis_set),
            )
            await db.rollback()  # Rollback việc xóa active_jti
            raise  # Ném lại lỗi để báo 500

        # 4. Commit DB (chỉ khi Redis blacklist thành công)
        await db.commit()
        await log.info("All sessions invalidated successfully for user", user_id=user.id)

    except Exception as e:
        # Bắt các lỗi khác (ngoài lỗi Redis blacklist đã xử lý)
        await db.rollback()
        await log.error(
            "Failed to invalidate sessions",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        # Không ném lại lỗi ở đây trừ khi lỗi Redis blacklist xảy ra
        if "Failed to add user to global blacklist" not in str(e):
            # Ném lỗi khác để router xử lý (vd: lỗi DB commit)
            raise HTTPException(status_code=500, detail="Could not invalidate sessions")


# --- Logic Logout ---


async def logout_user(db: AsyncSession, user: models.User):
    try:
        user.active_jti = None
        db.add(user)
        await db.commit()
        await log.info("User logged out successfully", user_id=user.id)
    except Exception as e:
        await db.rollback()
        await log.error("Failed to logout user", user_id=user.id, error=str(e), exc_info=True)
        raise e


# --- Bulk Action ---

async def perform_bulk_action(
    db: AsyncSession,
    action: str,
    user_ids: List[int],
    admin_user: models.User,
    new_status: Optional[str] = None,
):
    """
    Performs bulk actions (delete, change_status) on users.
    ✅ IMPROVED: Validates 'new_status' before querying DB for 'change_status'.
    """
    try:
        # --- IMPROVEMENT: Validate input BEFORE DB query ---
        if action == "change_status":
            # Check if new_status is provided and valid *early*
            if new_status not in ["active", "pending", "banned"]:
                await log.warning(
                    "Bulk action failed: Invalid status value provided.",
                    action=action,
                    provided_status=new_status,
                    admin_id=admin_user.id
                )
                raise BadRequest(detail=f"Invalid status value: {new_status}")
        elif action not in ["delete"]: # Check if action itself is valid
             await log.warning(
                    "Bulk action failed: Unsupported action.",
                    action=action,
                    admin_id=admin_user.id
                )
             raise BadRequest(detail=f"Unsupported bulk action: {action}.")
        # --- END IMPROVEMENT ---

        # Proceed only if the action and status (if applicable) are valid

        # Query users *after* initial validation
        query = select(models.User).where(models.User.id.in_(user_ids))
        users_to_process_result = await db.execute(query)
        users_to_process = users_to_process_result.scalars().all()

        if not users_to_process:
            # It's okay if no users match, just return an appropriate message
            await log.info("Bulk action: No users found matching provided IDs.", user_ids=user_ids, admin_id=admin_user.id)
            return "No users found for the provided IDs. 0 users affected."
            # raise ResourceNotFoundError(detail="No users found for the provided IDs.") # Changed behavior

        processed_count = 0
        message = ""
        if action == "delete":
            ids_to_delete = []
            for user in users_to_process:
                if user.id == admin_user.id:
                    await log.warning(
                        "Admin attempted to delete self during bulk action, skipping.",
                        admin_id=admin_user.id,
                    )
                    continue
                await db.delete(user) # Mark for deletion
                ids_to_delete.append(user.id)
                processed_count += 1
            message = f"Successfully deleted {processed_count} users."
            await log.info(
                "Admin bulk deleted users",
                admin_id=admin_user.id,
                deleted_ids=ids_to_delete,
            )

        elif action == "change_status":
            # We already validated new_status earlier
            ids_changed = []
            for user in users_to_process:
                if user.status != new_status: # Only update if status is different
                    user.status = new_status
                    db.add(user) # Mark for update
                    ids_changed.append(user.id)
                    processed_count += 1
                else:
                    await log.debug("Skipping status update for user already in desired state.", user_id=user.id, status=new_status)

            message = f"Successfully updated status to '{new_status}' for {processed_count} users."
            if ids_changed: # Only log if changes were actually made
                await log.info(
                    "Admin bulk changed user status",
                    admin_id=admin_user.id,
                    changed_ids=ids_changed,
                    new_status=new_status,
                )

        await db.commit() # Commit all changes (deletes or updates)
        return message

    except Exception as e:
        await db.rollback() # Ensure rollback on any error
        await log.error(
            "Failed to perform bulk action",
            action=action,
            admin_id=admin_user.id,
            error=str(e),
            exc_info=True,
        )
        # Re-raise the original exception if it's a known validation error,
        # otherwise raise a generic error.
        if isinstance(e, (BadRequest, ResourceNotFoundError)):
             raise e
        else:
             # You might want to raise a more generic 500 error here
             # depending on your desired API behavior for unexpected errors.
             raise # Re-raise the original unexpected error for now
