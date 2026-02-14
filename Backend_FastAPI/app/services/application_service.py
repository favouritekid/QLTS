# app/services/application_service.py
"""
Service layer cho Application (Hồ sơ Tuyển sinh).

✅ REFACTORED: Now uses notification_dispatcher for all notifications.
This ensures notifications are persisted to database AND sent via Socket.IO/Email.

Tuân thủ kiến trúc phân lớp:
- Service chứa 100% logic nghiệp vụ và truy vấn Database
- Không phụ thuộc vào Request/Response của FastAPI
- Sử dụng selectinload, joinedload để tránh N+1
"""
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
from ..core.events import SystemEvents
from .notification_dispatcher import dispatch
from ..utils.exceptions import ResourceNotFoundError, BadRequest

log = structlog.get_logger(__name__)


async def create_application(
    db: AsyncSession,
    lead_id: int,
    current_user: models.User,
) -> Tuple[models.Application, Callable]:
    """
    Tạo Application mới cho Lead.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        lead_id: ID của Lead
        current_user: User hiện tại (để set officer_id)

    Returns:
        Tuple of (application, post_commit_callback)

    Raises:
        ResourceNotFoundError: Nếu Lead không tồn tại
        BadRequest: Nếu Lead đã có Application
    """
    # ✅ SPRINT 4 REFACTORED: Use ApplicationRepository for data access
    from app.repositories import ApplicationRepository
    
    repo = ApplicationRepository(db)
    
    # Kiểm tra Lead tồn tại
    lead = await repo.check_lead_exists(lead_id)
    if not lead:
        log.warning("Lead not found", lead_id=lead_id)
        raise ResourceNotFoundError(f"Lead với ID {lead_id} không tồn tại")

    # Kiểm tra Lead đã có Application chưa
    existing_app = await repo.get_by_lead_id(lead_id, load_relationships=False, include_deleted=True)
    if existing_app:
        log.warning("Application already exists", lead_id=lead_id, application_id=existing_app.id)
        raise BadRequest(f"Lead này đã có hồ sơ tuyển sinh (ID: {existing_app.id})")

    # Tạo Application mới với status mặc định là "pending"
    new_application = models.Application(
        lead_id=lead_id,
        status="pending",
        officer_id=current_user.id,
        documents=None,  # Sẽ được cập nhật sau khi chọn criterion
        major_program_id=None,
        program_offering_id=None,
        criterion_id=None,
    )

    db.add(new_application)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(new_application)

    # Load relationships for socket event payload via repository
    new_application = await repo.get_with_lead_for_event(new_application.id)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Application created",
            application_id=new_application.id,
            lead_id=lead_id,
            officer_id=current_user.id,
        )

        # === ✅ REFACTOR: Dispatch notification instead of direct socket emit ===
        try:
            _, notif_cb = await dispatch(
                db=db,
                event=SystemEvents.APPLICATION_CREATED,
                payload={
                    "application_id": new_application.id,
                    "lead_id": lead_id,
                    "officer_id": current_user.id,
                    "major_program_name": new_application.major_program.name if new_application.major_program else "N/A",
                    "actor_id": current_user.id
                },
                dedupe_key=f"application_created:{new_application.id}",
            )
            await db.commit()
            if notif_cb:
                await notif_cb()
            log.info("Application creation notification dispatched", application_id=new_application.id)
        except Exception as e:
            log.error(
                "Failed to dispatch application creation notification",
                application_id=new_application.id,
                error=str(e)
            )

    return new_application, _post_commit


async def get_application_by_id(
    db: AsyncSession,
    application_id: int,
    load_relationships: bool = True,
    load_lead: bool = False,
    include_deleted: bool = False,
) -> Optional[models.Application]:
    """
    Lấy Application theo ID.

    ✅ SPRINT 4 REFACTORED: Now uses ApplicationRepository for data access.
    
    Args:
        db: Database session
        application_id: ID của Application
        load_relationships: Load relationships (major_program, program_offering)
        load_lead: If True, eager load the associated lead (for IDOR check). When True, also loads lead's officer and unit.
        include_deleted: If True, include soft-deleted applications (default: False)

    Returns:
        Application hoặc None nếu không tìm thấy
    """
    from app.repositories import ApplicationRepository
    
    repo = ApplicationRepository(db)
    return await repo.get_by_id(
        application_id,
        load_relationships=load_relationships,
        load_lead=load_lead,
        include_deleted=include_deleted
    )


async def update_application(
    db: AsyncSession,
    application_id: int,
    update_data: schemas.ApplicationUpdate,
    current_user: Optional[models.User] = None,
) -> Tuple[models.Application, Callable]:
    """
    Cập nhật Application.

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        application_id: ID của Application
        update_data: Dữ liệu cập nhật
        current_user: User thực hiện update (for Socket.IO events)

    Returns:
        Tuple of (application, post_commit_callback)

    Raises:
        ResourceNotFoundError: Nếu Application không tồn tại
    """
    application = await get_application_by_id(db, application_id, load_relationships=False)

    if not application:
        log.warning("Application not found", application_id=application_id)
        raise ResourceNotFoundError(f"Hồ sơ với ID {application_id} không tồn tại")

    # Track old values for Socket.IO events
    old_status = application.status
    old_documents = application.documents

    # Cập nhật các trường (chỉ cập nhật nếu có trong update_data)
    update_dict = update_data.model_dump(exclude_unset=True)

    # Track what changed
    status_changed = False
    documents_changed = False

    for field, value in update_dict.items():
        # Xử lý đặc biệt cho documents (convert Pydantic model sang dict)
        if field == "documents" and value is not None:
            if isinstance(value, schemas.ApplicationDocuments):
                setattr(application, field, value.model_dump(exclude_none=True))
            else:
                setattr(application, field, value)
            documents_changed = True
        elif field == "status":
            setattr(application, field, value)
            status_changed = True
        else:
            setattr(application, field, value)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(application)

    # ✅ SPRINT 4 REFACTORED: Load relationships after flush via repository
    from app.repositories import ApplicationRepository
    
    repo = ApplicationRepository(db)
    application = await repo.get_full_for_update(application_id)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Application updated",
            application_id=application_id,
            updated_fields=list(update_dict.keys()),
        )

        # === ✅ REFACTOR: Dispatch notifications instead of direct socket emits ===
        if current_user and application.officer_id:
            # Dispatch status changed notification
            if status_changed and old_status != application.status:
                try:
                    _, notif_cb = await dispatch(
                        db=db,
                        event=SystemEvents.APPLICATION_STATUS_CHANGED,
                        payload={
                            "application_id": application.id,
                            "lead_id": application.lead_id,
                            "officer_id": application.officer_id,
                            "old_status": old_status,
                            "new_status": application.status,
                            "actor_id": current_user.id
                        },
                        dedupe_key=f"application_status_changed:{application.id}:{application.status}",
                    )
                    await db.commit()
                    if notif_cb:
                        await notif_cb()
                    log.info("Application status change notification dispatched", application_id=application.id)
                except Exception as e:
                    log.error(
                        "Failed to dispatch application status change notification",
                        application_id=application.id,
                        error=str(e)
                    )

            # Dispatch documents updated notification
            if documents_changed and old_documents != application.documents:
                try:
                    _, notif_cb = await dispatch(
                        db=db,
                        event=SystemEvents.APPLICATION_DOCUMENTS_UPDATED,
                        payload={
                            "application_id": application.id,
                            "lead_id": application.lead_id,
                            "officer_id": application.officer_id,
                            "document_summary": "Documents checklist updated",
                            "actor_id": current_user.id
                        },
                        dedupe_key=f"application_documents_updated:{application.id}:{datetime.now(timezone.utc).isoformat()}",
                    )
                    await db.commit()
                    if notif_cb:
                        await notif_cb()
                    log.info("Application documents update notification dispatched", application_id=application.id)
                except Exception as e:
                    log.error(
                        "Failed to dispatch application documents update notification",
                        application_id=application.id,
                        error=str(e)
                    )

    return application, _post_commit


async def get_application_by_lead_id(
    db: AsyncSession,
    lead_id: int,
    load_relationships: bool = True,
    include_deleted: bool = False,
) -> Optional[models.Application]:
    """
    Lấy Application theo Lead ID.

    ✅ SPRINT 4 REFACTORED: Now uses ApplicationRepository for data access.
    
    Args:
        db: Database session
        lead_id: ID của Lead
        load_relationships: Load relationships
        include_deleted: If True, include soft-deleted applications (default: False)

    Returns:
        Application hoặc None nếu không tìm thấy
    """
    from app.repositories import ApplicationRepository
    
    repo = ApplicationRepository(db)
    return await repo.get_by_lead_id(
        lead_id,
        load_relationships=load_relationships,
        include_deleted=include_deleted
    )


async def delete_application(
    db: AsyncSession,
    application_id: int,
    deleted_by: models.User,
) -> Tuple[models.Application, Callable]:
    """
    Soft delete an Application (Admin only).

    IMPORTANT: This function does NOT commit the transaction.
    Router must call db.commit() and then execute the returned callback.

    Args:
        db: Database session
        application_id: ID của Application cần xóa
        deleted_by: User thực hiện xóa (Admin)

    Returns:
        Tuple of (application, post_commit_callback)

    Raises:
        ResourceNotFoundError: Nếu Application không tồn tại hoặc đã bị xóa
    """
    # Get application (exclude already deleted ones)
    application = await get_application_by_id(
        db, application_id, load_relationships=False, include_deleted=False
    )

    if not application:
        log.warning("Application not found or already deleted", application_id=application_id)
        raise ResourceNotFoundError(
            f"Hồ sơ với ID {application_id} không tồn tại hoặc đã bị xóa"
        )

    # Mark as soft deleted
    # Note: We don't change status to "deleted" because it's not in ApplicationStatus enum
    # The deleted_at timestamp is sufficient for soft delete filtering
    application.deleted_at = datetime.now(timezone.utc)

    db.add(application)

    # ✅ TRANSACTION FIX: Flush instead of commit
    await db.flush()
    await db.refresh(application)

    # ✅ Create post-commit callback
    async def _post_commit():
        """Execute after router commits the transaction."""
        log.info(
            "Application soft-deleted",
            application_id=application_id,
            deleted_by_user_id=deleted_by.id,
            deleted_by_role=deleted_by.role,
            deleted_by_username=deleted_by.username,
        )

    return application, _post_commit
