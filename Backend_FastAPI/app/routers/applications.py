# app/routers/applications.py
"""
Router cho Application (Hồ sơ Tuyển sinh).

Endpoints:
- POST /api/leads/{lead_id}/applications - Tạo Application cho Lead
- PUT /api/applications/{application_id} - Cập nhật Application
- GET /api/applications/{application_id} - Lấy Application theo ID
- DELETE /api/applications/{application_id} - Xóa Application (Admin only, soft delete)
"""
from app.core.rate_limits import limiter, RateLimits
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from .. import database, models, schemas
from ..core.deps import CasbinAuth, get_application_for_user  # ✅ Phase 2.2
from ..services import application_service
from ..services.notification_dispatcher import dispatch  # ✅ NOTIFICATION 2.0
from ..core.events import SystemEvents  # ✅ NOTIFICATION 2.0
from ..utils.exceptions import ResourceNotFoundError, BadRequest

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Applications"])


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post(
    "/leads/{lead_id}/applications",
    response_model=schemas.Application,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo hồ sơ tuyển sinh cho Lead",
)
async def create_application_for_lead(
    request: Request,
    lead_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
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
        application, callback = await application_service.create_application(
            db=db,
            lead_id=lead_id,
            current_user=current_user,
        )
        await db.commit()
        await callback()

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


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get(
    "/applications/{application_id}",
    response_model=schemas.Application,
    summary="Lấy thông tin hồ sơ tuyển sinh",
)
async def get_application(
    request: Request,
    application: models.Application = Depends(get_application_for_user),
):
    """
    Lấy thông tin chi tiết của Application theo ID.

    **Access Control:**
    - Admin: Có thể truy cập tất cả applications
    - Manager: Có thể truy cập applications trong các units mà họ quản lý
    - Officer: Chỉ có thể truy cập applications của các leads được gán cho họ

    **IDOR Prevention:**
    Endpoint này được bảo vệ bởi ownership verification. User không thể
    truy cập application của người khác bằng cách thay đổi application_id.

    **Bao gồm:**
    - Thông tin Application
    - Relationships: major_program, program_offering, officer, lead

    **Lỗi:**
    - 403: Không có quyền truy cập application này
    - 404: Application không tồn tại
    """
    # Application đã được verify ownership trong dependency
    return application


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.put(
    "/applications/{application_id}",
    response_model=schemas.Application,
    summary="Cập nhật hồ sơ tuyển sinh",
)
async def update_application(
    request: Request,
    update_data: schemas.ApplicationUpdate,
    application: models.Application = Depends(get_application_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Cập nhật thông tin Application (Hồ sơ Tuyển sinh).

    **Access Control:**
    - Admin: Có thể cập nhật tất cả applications
    - Manager: Có thể cập nhật applications trong các units mà họ quản lý
    - Officer: Chỉ có thể cập nhật applications của các leads được gán cho họ

    **IDOR Prevention:**
    Endpoint này được bảo vệ bởi ownership verification. User không thể
    cập nhật application của người khác bằng cách thay đổi application_id.

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
    - 403: Không có quyền cập nhật application này
    - 404: Application không tồn tại
    """
    try:
        # Update application using verified ID
        application, callback = await application_service.update_application(
            db=db,
            application_id=application.id,  # ✅ Use verified application ID
            update_data=update_data,
            current_user=current_user,
        )
        await db.commit()
        await callback()

        return application
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete(
    "/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa hồ sơ tuyển sinh",
)
async def delete_application(
    request: Request,
    application: models.Application = Depends(get_application_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Soft delete Application.

    **Access Control:**
    - Admin: Có thể xóa tất cả applications
    - Manager: Có thể xóa applications trong các units mà họ quản lý
    - Officer: Chỉ có thể xóa applications của các leads được gán cho họ

    **IDOR Prevention:**
    Endpoint này được bảo vệ bởi ownership verification. User không thể
    xóa application của người khác bằng cách thay đổi application_id.

    **Chức năng:**
    - Đánh dấu Application là đã xóa (soft delete)
    - Application đã xóa sẽ không hiển thị trong danh sách

    **Lỗi:**
    - 403: Không có quyền xóa application này
    - 404: Application không tồn tại hoặc đã bị xóa

    **Lưu ý:**
    - Đây là soft delete (deleted_at timestamp), không xóa vĩnh viễn
    - Application đã xóa có thể phục hồi bởi Admin nếu cần
    """
    try:
        # Delete using verified application ID
        deleted_app, callback = await application_service.delete_application(
            db=db,
            application_id=application.id,  # ✅ Use verified application ID
            deleted_by=current_user,
        )
        await db.commit()
        await callback()

        return None
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )