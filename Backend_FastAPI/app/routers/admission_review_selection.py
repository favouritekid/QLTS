# app/routers/admission_review_selection.py
"""API GĐ2-C C2 — lựa chọn của Ban thư ký (ĐT3 §11: ``PUT /review-sessions/{id}/selections/{profile_id}`` — Ban thư ký) + hai
route đọc (danh sách lựa chọn hiệu lực của lần xét; lịch sử lựa chọn của một hồ sơ). Router MỎNG: quyền ở ``deps``, luật ở
``admission_review_selection_service``, router commit.

Dưới tiền tố ``/api/admission-config`` — tiền tố ĐÃ nằm trong ``FROZEN_PREFIXES`` (``app/middleware/admission_freeze.py``) và
khối đóng băng của nginx ⇒ cần gạt đóng băng tuyển sinh chặn route GHI ở đây (503). Module khai trong
``ADMISSION_ROUTER_MODULES``, route ghi trong ``ADMISSION_WRITE_ROUTES``.

Quyền (thiết kế GĐ2-C §4 + bổ sung C1): ``CasbinAuth`` (cán bộ allow — Quản lý / Kế toán kế thừa, Admin wildcard;
``policy_templates.GD2C_REVIEW_SECRETARY_OBJECTS``) + ``deps.require_review_secretary`` — Admin đang hoạt động, hoặc Quản lý /
Cán bộ đang hoạt động có quyền gán còn hiệu lực; dòng người + dòng quyền khoá ``FOR SHARE`` tới hết giao dịch của CHÍNH yêu cầu
(route khai ``Depends(database.get_db)`` ⇒ cùng phiên). Không đạt ⇒ 404 cùng thân (không lộ lần xét có tồn tại). Toàn trường —
không lọc đơn vị (owner C2 22-11).

Module RIÊNG (không vào ``admission_review.py`` — tệp ấy thuộc lát L4 của GĐ2-B) để hai nhánh gộp không chồng tệp.
"""
from fastapi import APIRouter, Depends, Path, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..core import deps
from ..core.rate_limits import RateLimits, limiter
from ..schemas.admission_review_selection import (
    INT4_MAX,
    SelectionHistoryOut,
    SelectionListOut,
    SelectionPut,
    SelectionView,
)
from ..services import admission_review_selection_service as selection_service

#: Tiền tố (dưới ``/api``) — dùng chung tiền tố đã đóng băng của cấu hình tuyển sinh.
ROUTER_PREFIX = "/admission-config"

router = APIRouter(prefix=ROUTER_PREFIX, tags=["Lần xét tuyển GĐ2-C — lựa chọn của Ban thư ký"])


@router.get(
    "/review-sessions/{session_id}/selections",
    response_model=SelectionListOut,
    summary="Lựa chọn HIỆU LỰC của Ban thư ký cho mọi hồ sơ của lần xét (kèm cờ 'đã cũ' so với lượt kiểm mới nhất)",
)
@limiter.limit(RateLimits.DATA_READ)
async def list_review_selections(
    request: Request,
    session_id: int = Path(..., ge=1, le=INT4_MAX),
    current_user: models.User = deps.CasbinAuth,
    _secretary: models.User = Depends(deps.require_review_secretary),
    db: AsyncSession = Depends(database.get_db),
):
    return await selection_service.list_selections(db, session_id=session_id)


@router.get(
    "/review-sessions/{session_id}/selections/{profile_id}",
    response_model=SelectionHistoryOut,
    summary="Lịch sử lựa chọn của Ban thư ký cho MỘT hồ sơ trong lần xét (mới trước) + lựa chọn hiệu lực",
)
@limiter.limit(RateLimits.DATA_READ)
async def get_review_selection_history(
    request: Request,
    session_id: int = Path(..., ge=1, le=INT4_MAX),
    profile_id: int = Path(..., ge=1, le=INT4_MAX),
    current_user: models.User = deps.CasbinAuth,
    _secretary: models.User = Depends(deps.require_review_secretary),
    db: AsyncSession = Depends(database.get_db),
):
    return await selection_service.selection_history(db, session_id=session_id, profile_id=profile_id)


@router.put(
    "/review-sessions/{session_id}/selections/{profile_id}",
    response_model=SelectionView,
    summary="Ban thư ký ghi lựa chọn cho một hồ sơ (chỉ thêm; dựa đúng dòng của lượt kiểm mới nhất; chỉ khi lần xét nháp)",
)
@limiter.limit(RateLimits.DATA_WRITE)
async def put_review_selection(
    request: Request,
    payload: SelectionPut,
    session_id: int = Path(..., ge=1, le=INT4_MAX),
    profile_id: int = Path(..., ge=1, le=INT4_MAX),
    current_user: models.User = deps.CasbinAuth,
    _secretary: models.User = Depends(deps.require_review_secretary),
    db: AsyncSession = Depends(database.get_db),
):
    out = await selection_service.record_selection(
        db,
        session_id=session_id,
        profile_id=profile_id,
        kind=payload.kind,
        based_on_row_hash=payload.based_on_row_hash,
        supersedes_id=payload.supersedes_id,
        note=payload.note,
        actor_id=current_user.id,
    )
    await db.commit()
    return out
