# app/routers/admin_thcs_school_mapping.py
"""Admin — công cụ ghép tên trường THCS gõ tay (đề xuất danh mục THCS Phần B1, owner 22-11).

Prefix ``/api/v2/admin/vn-school/thcs-mapping``. CHỈ Admin (``require_admin``). Thuộc miền DANH MỤC trường (không phải
miền tuyển sinh): các đường ghi ở đây chỉ ghi bảng ghép / danh mục trường, KHÔNG sửa hồ sơ ⇒ không bị cần gạt đóng
băng tuyển sinh. Lượt áp ghép (sửa lịch sử học hồ sơ) ở router RIÊNG dưới ``/api/v2/admissions`` (bị đóng băng):
``app/routers/admissions_thcs_school_mapping.py``.

Không trả dữ liệu cá nhân thí sinh: nhóm chỉ mang tên trường gõ tay + số đếm.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import require_admin
from app.routers.admin_vn_school import _school_resp
from app.schemas.thcs_school_mapping import (
    ThcsCreateSchoolFromGroupRequest,
    ThcsCreateSchoolFromGroupResponse,
    ThcsMappingResponse,
    ThcsMapRequest,
    ThcsNameGroupListResponse,
    ThcsUnmapRequest,
)
from app.services.thcs_school_mapping_service import ThcsSchoolMappingService
from app.services.vn_school_service import VnSchoolService

log = structlog.get_logger(__name__)

admin_router = APIRouter(
    prefix="/api/v2/admin/vn-school/thcs-mapping",
    tags=["Admin v2 - THCS school name mapping"],
)


@admin_router.get("/groups", response_model=ThcsNameGroupListResponse)
async def list_groups(
    page: int = 1,
    page_size: int = 50,
    mapped: Optional[bool] = Query(default=None, description="true = đã ghép · false = chưa ghép · trống = tất cả"),
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> ThcsNameGroupListResponse:
    service = ThcsSchoolMappingService(db)
    return ThcsNameGroupListResponse(
        **await service.list_groups(page=page, page_size=page_size, mapped=mapped)
    )


@admin_router.post(
    "/groups/map",
    response_model=ThcsMappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def map_group(
    payload: ThcsMapRequest,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> ThcsMappingResponse:
    service = ThcsSchoolMappingService(db)
    row = await service.map_group(payload.normalized_name, payload.school_id, user.id)
    out = ThcsMappingResponse.model_validate(row)
    await db.commit()
    log.info("thcs_mapping_mapped", mapping_id=out.id, school_id=out.school_id, actor=user.id)
    return out


@admin_router.post("/groups/unmap")
async def unmap_group(
    payload: ThcsUnmapRequest,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> dict:
    service = ThcsSchoolMappingService(db)
    old = await service.unmap_group(payload.normalized_name, user.id)
    await db.commit()
    log.info("thcs_mapping_unmapped", school_id=old["school_id"], actor=user.id)
    return {"normalized_name": old["normalized_name"], "school_id": old["school_id"]}


@admin_router.post(
    "/groups/create-school",
    response_model=ThcsCreateSchoolFromGroupResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_school_from_group(
    payload: ThcsCreateSchoolFromGroupRequest,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> ThcsCreateSchoolFromGroupResponse:
    service = ThcsSchoolMappingService(db)
    school, mapping = await service.create_school_from_group(
        payload.normalized_name, payload.school.model_dump(), user.id
    )
    mapping_out = ThcsMappingResponse.model_validate(mapping)
    await db.commit()
    log.info(
        "thcs_mapping_school_created",
        school_id=school.id,
        moet_code=school.moet_school_code,
        mapping_id=mapping_out.id,
        actor=user.id,
    )
    return ThcsCreateSchoolFromGroupResponse(
        school=_school_resp(school, await VnSchoolService(db).current_kv(school.id)),
        mapping=mapping_out,
    )
