# app/services/application_service.py
"""
Service layer cho Application (Hồ sơ Tuyển sinh).

Tuân thủ kiến trúc phân lớp:
- Service chứa 100% logic nghiệp vụ và truy vấn Database
- Không phụ thuộc vào Request/Response của FastAPI
- Sử dụng selectinload, joinedload để tránh N+1
"""
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import models, schemas
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

    log.info(
        "Application created",
        application_id=new_application.id,
        lead_id=lead_id,
        officer_id=current_user.id,
    )

    return new_application


async def get_application_by_id(
    db: AsyncSession,
    application_id: int,
    load_relationships: bool = True,
) -> Optional[models.Application]:
    """
    Lấy Application theo ID.

    Args:
        db: Database session
        application_id: ID của Application
        load_relationships: Load relationships (major_program, program_offering)

    Returns:
        Application hoặc None nếu không tìm thấy
    """
    stmt = select(models.Application).where(models.Application.id == application_id)

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
) -> models.Application:
    """
    Cập nhật Application.

    Args:
        db: Database session
        application_id: ID của Application
        update_data: Dữ liệu cập nhật

    Returns:
        Application đã cập nhật

    Raises:
        ResourceNotFoundError: Nếu Application không tồn tại
    """
    application = await get_application_by_id(db, application_id, load_relationships=False)

    if not application:
        log.warning("Application not found", application_id=application_id)
        raise ResourceNotFoundError(f"Hồ sơ với ID {application_id} không tồn tại")

    # Cập nhật các trường (chỉ cập nhật nếu có trong update_data)
    update_dict = update_data.model_dump(exclude_unset=True)

    for field, value in update_dict.items():
        # Xử lý đặc biệt cho documents (convert Pydantic model sang dict)
        if field == "documents" and value is not None:
            if isinstance(value, schemas.ApplicationDocuments):
                setattr(application, field, value.model_dump(exclude_none=True))
            else:
                setattr(application, field, value)
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

    return application


async def get_application_by_lead_id(
    db: AsyncSession,
    lead_id: int,
    load_relationships: bool = True,
) -> Optional[models.Application]:
    """
    Lấy Application theo Lead ID.

    Args:
        db: Database session
        lead_id: ID của Lead
        load_relationships: Load relationships

    Returns:
        Application hoặc None nếu không tìm thấy
    """
    stmt = select(models.Application).where(models.Application.lead_id == lead_id)

    if load_relationships:
        stmt = stmt.options(
            selectinload(models.Application.major_program),
            selectinload(models.Application.program_offering),
            selectinload(models.Application.officer),
        )

    result = await db.execute(stmt)
    return result.scalar_one_or_none()
