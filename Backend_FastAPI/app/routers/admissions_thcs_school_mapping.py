# app/routers/admissions_thcs_school_mapping.py
"""Áp ghép tên trường THCS vào lịch sử học hồ sơ (đề xuất danh mục THCS Phần B2, owner 22-11).

``POST /api/v2/admissions/thcs-school-mapping/apply`` — CHỈ Admin. Nằm dưới tiền tố ``/api/v2/admissions`` (miền tuyển
sinh, bị cần gạt đóng băng chặn ở CẢ hai tầng middleware + nginx) vì chế độ thật SỬA ``admission_profile``.

* ``dry_run`` mặc định ``true`` — chỉ đếm, không ghi.
* Chế độ thật: cờ ``THCS_MAPPING_APPLY_ENABLED`` (mặc định tắt) — tắt ⇒ 409, không ghi gì. Tầng chủ sở hữu của cờ là
  service (``ThcsSchoolMappingService.apply_mappings``), không phải router.

Router này phải được đăng ký TRƯỚC ``admissions_v2`` (``main.py``) — cùng tiền tố, tránh route có tham số đường dẫn
khớp nhầm.
"""
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import require_admin
from app.schemas.thcs_school_mapping import ThcsMappingApplyRequest, ThcsMappingApplyResult
from app.services.thcs_school_mapping_service import ThcsSchoolMappingService

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admissions/thcs-school-mapping",
    tags=["v2 - THCS school name mapping apply"],
)


@router.post("/apply", response_model=ThcsMappingApplyResult)
async def apply_thcs_school_mapping(
    payload: ThcsMappingApplyRequest,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> ThcsMappingApplyResult:
    service = ThcsSchoolMappingService(db)
    result = await service.apply_mappings(
        dry_run=payload.dry_run,
        actor_id=user.id,
        expected_rows_to_change=payload.expected_rows_to_change,
        expected_profiles_to_change=payload.expected_profiles_to_change,
    )
    if result["applied"]:
        await db.commit()
    log.info(
        "thcs_mapping_apply",
        dry_run=payload.dry_run,
        applied=result["applied"],
        rows=result["rows_to_change"],
        profiles=result["profiles_to_change"],
        actor=user.id,
    )
    return ThcsMappingApplyResult(**result)
