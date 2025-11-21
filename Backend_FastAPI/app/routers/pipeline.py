# app/routers/pipeline.py
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas
from ..core import deps
from ..services import pipeline_service

router = APIRouter(tags=["Pipeline"])

PermissionDep = Depends(deps.check_permission)


@router.get("/stages", response_model=List[schemas.PipelineStage])
async def get_pipeline_stages(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """Lấy danh sách tất cả các giai đoạn Pipeline (chỉ đọc)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    return stages


@router.get("/all", response_model=schemas.FullPipeline)
async def get_full_pipeline(
    db: AsyncSession = Depends(database.get_db),
    # <<< SỬA Ở ĐÂY: Đổi dependency để kiểm tra quyền >>>
    current_user: models.User = PermissionDep,  # Yêu cầu Casbin check
    # Hoặc dùng: current_user: models.User = deps.OfficerRequired, # Nếu chỉ officer trở lên
):
    """Lấy toàn bộ cấu trúc Pipeline (Stages và Statuses)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    statuses = await pipeline_service.get_all_consultation_statuses(db)
    return {"stages": stages, "statuses": statuses}


@router.get("/allowed-next-statuses", response_model=List[schemas.ConsultationStatus])
async def get_allowed_next_statuses(
    current_status_id: str | None = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = PermissionDep,
):
    """
    Lấy danh sách các trạng thái được phép chuyển đến từ trạng thái hiện tại.

    Sử dụng state machine workflow để xác định các trạng thái hợp lệ tiếp theo.
    Nếu current_status_id không được cung cấp, trả về tất cả statuses (dành cho lead mới).

    **Query Parameters:**
    - current_status_id (optional): ID của consultation status hiện tại

    **Returns:**
    - Danh sách ConsultationStatus được phép chuyển đến
    """
    return await pipeline_service.get_allowed_next_statuses(db, current_status_id)
