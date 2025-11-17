# app/routers/applications.py
"""
Router cho Application (Hồ sơ Tuyển sinh).

Endpoints:
- POST /api/leads/{lead_id}/applications - Tạo Application cho Lead
- PUT /api/applications/{application_id} - Cập nhật Application
- GET /api/applications/{application_id} - Lấy Application theo ID
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import application_service
from ..utils.exceptions import ResourceNotFoundError, BadRequest

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
        application = await application_service.update_application(
            db=db,
            application_id=application_id,
            update_data=update_data,
        )
        return application
    except ResourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
