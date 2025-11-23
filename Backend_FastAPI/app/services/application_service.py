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
from typing import Optional

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
) -> models.Application:
    """
    Tạo Application mới cho Lead.

    Args:
        db: Database session
        lead_id: ID của Lead
        current_user: User hiện tại (để set officer_id)

    Returns:
        Application đã tạo

    Raises:
        ResourceNotFoundError: Nếu Lead không tồn tại
        BadRequest: Nếu Lead đã có Application
    """
    # Kiểm tra Lead tồn tại
    stmt = select(models.Lead).where(models.Lead.id == lead_id)
    result = await db.execute(stmt)
    lead = result.scalar_one_or_none()

    if not lead:
        log.warning("Lead not found", lead_id=lead_id)
        raise ResourceNotFoundError(f"Lead với ID {lead_id} không tồn tại")

    # Kiểm tra Lead đã có Application chưa
    stmt_check = select(models.Application).where(models.Application.lead_id == lead_id)
    result_check = await db.execute(stmt_check)
    existing_app = result_check.scalar_one_or_none()

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
    await db.commit()
    await db.refresh(new_application)

    # Load relationships for socket event payload
    stmt_reload = (
        select(models.Application)
        .where(models.Application.id == new_application.id)
        .options(
            selectinload(models.Application.lead),
            selectinload(models.Application.major_program),
        )
    )
    result_reload = await db.execute(stmt_reload)
    new_application = result_reload.scalar_one()

    log.info(
        "Application created",
        application_id=new_application.id,
        lead_id=lead_id,
        officer_id=current_user.id,
    )

    # === ✅ REFACTOR: Dispatch notification instead of direct socket emit ===
    try:
        await dispatch(
            db=db,
            event=SystemEvents.APPLICATION_CREATED,
            payload={
                "application_id": new_application.id,
                "lead_id": lead_id,
                "officer_id": current_user.id,
                "major_program_name": new_application.major_program.name if new_application.major_program else "N/A",
                "actor_id": current_user.id
            },
            dedupe_key=f"application_created:{new_application.id}"
        )
        log.info("Application creation notification dispatched", application_id=new_application.id)
    except Exception as e:
        log.error(
            "Failed to dispatch application creation notification",
            application_id=new_application.id,
            error=str(e)
        )

    return new_application


async def get_application_by_id(
    db: AsyncSession,
    application_id: int,
    load_relationships: bool = True,
    include_deleted: bool = False,
) -> Optional[models.Application]:
    """
    Lấy Application theo ID.

    Args:
        db: Database session
        application_id: ID của Application
        load_relationships: Load relationships (major_program, program_offering)
        include_deleted: If True, include soft-deleted applications (default: False)

    Returns:
        Application hoặc None nếu không tìm thấy
    """
    stmt = select(models.Application).where(models.Application.id == application_id)

    # Filter out soft-deleted applications by default
    if not include_deleted:
        stmt = stmt.where(models.Application.deleted_at.is_(None))

    if load_relationships:
        stmt = stmt.options(
            selectinload(models.Application.major_program),
            selectinload(models.Application.program_offering),
            selectinload(models.Application.officer),
            selectinload(models.Application.lead),
        )

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def update_application(
    db: AsyncSession,
    application_id: int,
    update_data: schemas.ApplicationUpdate,
    current_user: Optional[models.User] = None,
) -> models.Application:
    """
    Cập nhật Application.

    Args:
        db: Database session
        application_id: ID của Application
        update_data: Dữ liệu cập nhật
        current_user: User thực hiện update (for Socket.IO events)

    Returns:
        Application đã cập nhật

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

    await db.commit()
    await db.refresh(application)

    # Load relationships sau khi commit
    stmt = (
        select(models.Application)
        .where(models.Application.id == application_id)
        .options(
            selectinload(models.Application.major_program),
            selectinload(models.Application.program_offering),
            selectinload(models.Application.officer),
            selectinload(models.Application.lead),
        )
    )
    result = await db.execute(stmt)
    application = result.scalar_one()

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
                await dispatch(
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
                    dedupe_key=f"application_status_changed:{application.id}:{application.status}"
                )
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
                await dispatch(
                    db=db,
                    event=SystemEvents.APPLICATION_DOCUMENTS_UPDATED,
                    payload={
                        "application_id": application.id,
                        "lead_id": application.lead_id,
                        "officer_id": application.officer_id,
                        "document_summary": "Documents checklist updated",
                        "actor_id": current_user.id
                    },
                    dedupe_key=f"application_documents_updated:{application.id}:{datetime.now(timezone.utc).isoformat()}"
                )
                log.info("Application documents update notification dispatched", application_id=application.id)
            except Exception as e:
                log.error(
                    "Failed to dispatch application documents update notification",
                    application_id=application.id,
                    error=str(e)
                )

    return application


async def get_application_by_lead_id(
    db: AsyncSession,
    lead_id: int,
    load_relationships: bool = True,
    include_deleted: bool = False,
) -> Optional[models.Application]:
    """
    Lấy Application theo Lead ID.

    Args:
        db: Database session
        lead_id: ID của Lead
        load_relationships: Load relationships
        include_deleted: If True, include soft-deleted applications (default: False)

    Returns:
        Application hoặc None nếu không tìm thấy
    """
    stmt = select(models.Application).where(models.Application.lead_id == lead_id)

    # Filter out soft-deleted applications by default
    if not include_deleted:
        stmt = stmt.where(models.Application.deleted_at.is_(None))

    if load_relationships:
        stmt = stmt.options(
            selectinload(models.Application.major_program),
            selectinload(models.Application.program_offering),
            selectinload(models.Application.officer),
        )

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_application(
    db: AsyncSession,
    application_id: int,
    deleted_by: models.User,
) -> models.Application:
    """
    Soft delete an Application (Admin only).

    Args:
        db: Database session
        application_id: ID của Application cần xóa
        deleted_by: User thực hiện xóa (Admin)

    Returns:
        Application đã được đánh dấu xóa

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
    await db.commit()
    await db.refresh(application)

    log.info(
        "Application soft-deleted",
        application_id=application_id,
        deleted_by_user_id=deleted_by.id,
        deleted_by_role=deleted_by.role,
        deleted_by_username=deleted_by.username,
    )

    return application
