# app/routers/applications.py
"""
Router cho Application (Hồ sơ Tuyển sinh).

Endpoints:
- POST /api/leads/{lead_id}/applications - Tạo Application cho Lead
- PUT /api/applications/{application_id} - Cập nhật Application
- GET /api/applications/{application_id} - Lấy Application theo ID
- DELETE /api/applications/{application_id} - Xóa Application (Admin only, soft delete)
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models, schemas
from ..core import deps
from ..services import application_service
from ..services.notification_dispatcher import dispatch  # ✅ NOTIFICATION 2.0
from ..core.events import SystemEvents  # ✅ NOTIFICATION 2.0
from ..utils.exceptions import ResourceNotFoundError, BadRequest

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Applications"])

PermissionDep = Depends(deps.check_permission)


@router.post(
    "/leads/{lead_id}/applications",
    response_model=schemas.Application,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo hồ sơ tuyển sinh cho Lead",
)
async def create_application_for_lead(
    lead_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Tạo Application (Hồ sơ Tuyển sinh) mới cho Lead.

    **Yêu cầu:**
    - Lead phải tồn tại
    - Lead chưa có Application

    **Trả về:**
    - Application mới với status = "pending"
    - Các trường major_program_id, program_offering_id, criterion_id = null
    - documents = null (sẽ được cập nhật sau)

    **Lỗi:**
    - 404: Lead không tồn tại
    - 400: Lead đã có Application
    """
    try:
        application = await application_service.create_application(
            db=db,
            lead_id=lead_id,
            current_user=current_user,
        )

        # ✅ NOTIFICATION 2.0: Dispatch APPLICATION_CREATED event
        try:
            await dispatch(
                db=db,
                event=SystemEvents.APPLICATION_CREATED,
                payload={
                    "application_id": application.id,
                    "lead_id": application.lead_id,
                    "officer_id": application.officer_id,
                    "major_program_name": None,  # Will be updated later
                    "actor_id": current_user.id,
                },
                dedupe_key=f"application_created:{application.id}"
            )
        except Exception as e:
            log.warning(
                "Failed to dispatch application submitted notification",
                application_id=application.id,
                error=str(e)
            )

        return application
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except BadRequest as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/applications/{application_id}",
    response_model=schemas.Application,
    summary="Lấy thông tin hồ sơ tuyển sinh",
)
async def get_application(
    application_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Lấy thông tin chi tiết của Application theo ID.

    **Bao gồm:**
    - Thông tin Application
    - Relationships: major_program, program_offering, officer, lead

    **Lỗi:**
    - 404: Application không tồn tại
    """
    application = await application_service.get_application_by_id(
        db=db,
        application_id=application_id,
        load_relationships=True,
    )

    if not application:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hồ sơ với ID {application_id} không tồn tại",
        )

    return application


@router.put(
    "/applications/{application_id}",
    response_model=schemas.Application,
    summary="Cập nhật hồ sơ tuyển sinh",
)
async def update_application(
    application_id: int,
    update_data: schemas.ApplicationUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Cập nhật thông tin Application (Hồ sơ Tuyển sinh).

    **Có thể cập nhật:**
    - status: Trạng thái hồ sơ (pending, missing_documents, completed, passed, failed)
    - major_program_id: ID ngành đào tạo
    - program_offering_id: ID loại hình đào tạo
    - criterion_id: ID phương thức xét tuyển
    - documents: Dữ liệu JSON (scores, checklist)

    **Lưu ý:**
    - documents.scores: Dict[str, float] - Điểm các môn
    - documents.checklist: List[ChecklistItem] - Danh sách hồ sơ

    **Lỗi:**
    - 404: Application không tồn tại
    """
    try:
        # Get old application for comparison
        old_application = await application_service.get_application_by_id(db, application_id)
        old_status = old_application.status
        old_documents = old_application.documents

        # Update application
        application = await application_service.update_application(
            db=db,
            application_id=application_id,
            update_data=update_data,
            current_user=current_user,
        )

        # ✅ NOTIFICATION 2.0: Dispatch APPLICATION_DOCUMENTS_UPDATED if documents changed
        if update_data.documents is not None and update_data.documents != old_documents:
            try:
                await dispatch(
                    db=db,
                    event=SystemEvents.APPLICATION_DOCUMENTS_UPDATED,
                    payload={
                        "application_id": application.id,
                        "lead_id": application.lead_id,
                        "officer_id": application.officer_id,
                        "document_summary": f"Documents updated for application #{application.id}",
                        "actor_id": current_user.id,
                    },
                    dedupe_key=f"application_documents_updated:{application.id}"
                )
            except Exception as e:
                log.warning(
                    "Failed to dispatch application documents updated notification",
                    application_id=application.id,
                    error=str(e)
                )

        # ✅ NOTIFICATION 2.0: Dispatch APPLICATION_STATUS_CHANGED if status changed
        if update_data.status and update_data.status != old_status:
            try:
                await dispatch(
                    db=db,
                    event=SystemEvents.APPLICATION_STATUS_CHANGED,
                    payload={
                        "application_id": application.id,
                        "applicant_id": application.lead_id,
                        "applicant_name": application.lead.full_name if application.lead else "Unknown",
                        "applicant_email": application.lead.email if application.lead else "",
                        "officer_id": application.officer_id,
                        "officer_name": application.officer.full_name if application.officer else "Unknown",
                        "old_status": old_status,
                        "new_status": application.status,
                        "actor_id": current_user.id,
                        "actor_name": current_user.full_name,
                    },
                    dedupe_key=f"application_status_changed:{application.id}:{application.status}"
                )
            except Exception as e:
                log.warning(
                    "Failed to dispatch application status changed notification",
                    application_id=application.id,
                    error=str(e)
                )

        return application
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

@router.delete(
    "/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa hồ sơ tuyển sinh (Admin only)",
)
async def delete_application(
    application_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Soft delete Application (Admin only).

    **Chức năng:**
    - Đánh dấu Application là đã xóa (soft delete)
    - Chỉ Admin mới có quyền xóa
    - Application đã xóa sẽ không hiển thị trong danh sách

    **Quyền truy cập:**
    - Admin: Có quyền xóa bất kỳ Application nào

    **Lỗi:**
    - 403: Không có quyền xóa (chỉ Admin)
    - 404: Application không tồn tại hoặc đã bị xóa

    **Lưu ý:**
    - Đây là soft delete (deleted_at timestamp), không xóa vĩnh viễn
    - Application đã xóa có thể phục hồi bởi Admin nếu cần
    """
    try:
        # Get application info before deletion for notification
        app_info = await application_service.get_application_by_id(
            db, application_id, load_relationships=True, include_deleted=False
        )
        if not app_info:
            raise ResourceNotFoundError(f"Hồ sơ với ID {application_id} không tồn tại")

        # Store info for notification before deletion
        officer_id = app_info.lead.assigned_officer_id if app_info.lead else None
        lead_name = app_info.lead.full_name if app_info.lead else "Unknown"
        lead_id = app_info.lead_id

        deleted_app = await application_service.delete_application(
            db=db,
            application_id=application_id,
            deleted_by=current_user,
        )

        # Dispatch notification for application deletion
        try:
            from ..services.notification_dispatcher import dispatch
            from ..core.events import SystemEvents
            await dispatch(
                db=db,
                event=SystemEvents.APPLICATION_DELETED,
                payload={
                    "application_id": deleted_app.id,
                    "lead_id": lead_id,
                    "officer_id": officer_id,
                    "lead_name": lead_name,
                    "actor_id": current_user.id,
                },
                dedupe_key=f"application_deleted:{deleted_app.id}"
            )
        except Exception as e:
            # Log but don't fail - deletion already succeeded
            import logging
            logging.warning(f"Failed to dispatch application deletion notification: {e}")

        return None
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
