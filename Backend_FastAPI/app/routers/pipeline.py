# app/routers/pipeline.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, schemas, models
from ..core import deps
from ..services import pipeline_service

router = APIRouter(tags=["Pipeline"])

PermissionDep = Depends(deps.check_permission)

@router.get("/all", response_model=schemas.FullPipeline)
async def get_full_pipeline(
    db: AsyncSession = Depends(database.get_db),
    # <<< SỬA Ở ĐÂY: Đổi dependency để kiểm tra quyền >>>
    current_user: models.User = PermissionDep, # Yêu cầu Casbin check
    # Hoặc dùng: current_user: models.User = deps.OfficerRequired, # Nếu chỉ officer trở lên
):
    """Lấy toàn bộ cấu trúc Pipeline (Stages và Statuses)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    statuses = await pipeline_service.get_all_consultation_statuses(db)
    return {"stages": stages, "statuses": statuses}