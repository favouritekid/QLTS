# app/routers/admission_review.py
"""API "Lần xét tuyển" GĐ2 (đặc tả GĐ2 bản 3 §11) — router MỎNG. PR đầu (GĐ2-A) chỉ có bảng chỉ tiêu năm / nhóm ngành;
lần xét, Ban thư ký, run, điều chỉnh, khoá lần xét đến ở GĐ2-B trở đi.

Dưới tiền tố ``/api/admission-config`` — tiền tố ĐÃ nằm trong ``FROZEN_PREFIXES`` (``app/middleware/admission_freeze.py``)
và khối đóng băng của nginx ⇒ cần gạt đóng băng tuyển sinh chặn mọi route GHI ở đây (503). Module khai trong
``ADMISSION_ROUTER_MODULES``, ba route ghi trong ``ADMISSION_WRITE_ROUTES``.

Quyền (đặc tả §10: "Bảng chỉ tiêu … Admin — lớp 'chỉ Admin'"): ``CasbinAuth`` (chỉ admin có dòng — wildcard) +
``deps.require_quota_table_admin`` (lớp phụ fail-closed) cho ba route GHI. GĐ2-C C2 (ĐT3 §11 "GET + Ban thư ký"; thiết kế GĐ2-C
§4): route GET mở cho Ban thư ký — Casbin cán bộ allow (``policy_templates.GD2C_REVIEW_SECRETARY_OBJECTS``) +
``deps.require_review_secretary`` (Admin đang hoạt động, hoặc Quản lý / Cán bộ có quyền gán còn hiệu lực; không đạt ⇒ 404).
Người xem không ghi được (``deps.quota_table_write_allowed`` sai) ⇒ ``available_actions`` rỗng.

Log chỉ năm + số đếm; không dữ liệu cá nhân (bảng chỉ tiêu không mang dữ liệu cá nhân).
"""
import structlog
from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.rate_limits import RateLimits, limiter
from ..schemas.admission_quota_table import (
    QuotaTableLockIn,
    QuotaTableOut,
    QuotaTablePut,
    QuotaTableUnlockIn,
)
from ..services import admission_quota_table_service as quota_table_service

log = structlog.get_logger(__name__)

#: Tiền tố (dưới ``/api``) — dùng chung tiền tố đã đóng băng của cấu hình tuyển sinh.
ROUTER_PREFIX = "/admission-config"

router = APIRouter(prefix=ROUTER_PREFIX, tags=["Lần xét tuyển GĐ2 — bảng chỉ tiêu"])

@router.get(
    "/quota-tables/{academic_year}",
    response_model=QuotaTableOut,
    summary="Bảng chỉ tiêu năm: nhóm ngành, trần, ngành thành viên, chỉ tiêu ngành, số đã dùng (tham khảo)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_quota_table(
    request: Request,
    academic_year: int = Path(..., ge=2000, le=2100, description="Năm tuyển sinh"),
    current_user: models.User = deps.CasbinAuth,
    _secretary: models.User = Depends(deps.require_review_secretary),
    db: AsyncSession = Depends(database.get_db),
):
    return await quota_table_service.get_quota_table(
        db, academic_year, can_write=deps.quota_table_write_allowed(current_user)
    )


@router.put(
    "/quota-tables/{academic_year}",
    response_model=QuotaTableOut,
    summary="Thay toàn bộ nội dung bảng chỉ tiêu năm (chỉ khi chưa khoá; version 0 = tạo mới)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def put_quota_table(
    request: Request,
    payload: QuotaTablePut,
    academic_year: int = Path(..., ge=2000, le=2100, description="Năm tuyển sinh"),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_quota_table_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await quota_table_service.replace_quota_table(db, academic_year, payload, actor_id=current_user.id)
    await db.commit()
    return out


@router.post(
    "/quota-tables/{academic_year}/lock",
    response_model=QuotaTableOut,
    summary="Khoá bảng chỉ tiêu năm (sau khoá CSDL chặn sửa chỉ tiêu / nhóm / trần)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def lock_quota_table(
    request: Request,
    payload: QuotaTableLockIn,
    academic_year: int = Path(..., ge=2000, le=2100, description="Năm tuyển sinh"),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_quota_table_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await quota_table_service.lock_quota_table(
        db,
        academic_year,
        expected_version=payload.version,
        expected_quota_fingerprint=payload.quota_fingerprint,
        actor_id=current_user.id,
    )
    await db.commit()
    return out


@router.post(
    "/quota-tables/{academic_year}/unlock",
    response_model=QuotaTableOut,
    summary="Mở khoá bảng chỉ tiêu năm (bắt buộc lý do, lưu vết)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def unlock_quota_table(
    request: Request,
    payload: QuotaTableUnlockIn,
    academic_year: int = Path(..., ge=2000, le=2100, description="Năm tuyển sinh"),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_quota_table_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await quota_table_service.unlock_quota_table(
        db, academic_year, expected_version=payload.version, reason=payload.reason, actor_id=current_user.id
    )
    await db.commit()
    return out
