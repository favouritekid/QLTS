# app/routers/admission_review.py
"""API "Lần xét tuyển" GĐ2 — router MỎNG. GĐ2-A: bảng chỉ tiêu năm / nhóm ngành (đặc tả GĐ2 bản 3 §11). GĐ2-B (đợt 2, L4): 9
route của lần xét nháp, điểm sàn, chạy kiểm hồ sơ, xem run / dòng — hợp đồng API GĐ2-B bản 4 ``b877fba1…`` E1–E9. Ban thư ký,
lựa chọn, điều chỉnh, khoá lần xét đến ở GĐ2-C trở đi.

Dưới tiền tố ``/api/admission-config`` — tiền tố ĐÃ nằm trong ``FROZEN_PREFIXES`` (``app/middleware/admission_freeze.py``)
và khối đóng băng của nginx ⇒ cần gạt đóng băng tuyển sinh chặn mọi route GHI ở đây (503). Module khai trong
``ADMISSION_ROUTER_MODULES``; route ghi (3 của bảng chỉ tiêu + 4 của lần xét: E1, E4, E5, E6) trong ``ADMISSION_WRITE_ROUTES``.

Quyền: ``CasbinAuth`` (tầng chủ sở hữu vai — chỉ admin có dòng, wildcard) + lớp phụ fail-closed ``deps.require_quota_table_admin``
(bảng chỉ tiêu) / ``deps.require_review_admin`` (lần xét — QĐB:26 chỉ Admin ở GĐ2-B). Kiểm vai TRƯỚC khi đọc bất cứ gì của lần
xét; "lần xét / run không có" ⇒ 404 ở dịch vụ (biên bản K3 21-11).

Router chỉ dịch HTTP ↔ dịch vụ và COMMIT (dịch vụ chỉ ``flush``). Log chỉ id + số đếm; không dữ liệu cá nhân. E3, E8, E9 trả
``Cache-Control: no-store`` (hợp đồng §1.7); E6 trả 202 + ``Location`` (hợp đồng §2 E6 — GĐ2-B chạy đồng bộ, 202 đã mang run
``done``).
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request, Response
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
from ..schemas.admission_review import (
    LIST_PAGE_SIZE_DEFAULT,
    LIST_PAGE_SIZE_MAX,
    ROW_FLAG_PATTERN,
    ROW_REASON_CODE_PATTERN,
    ROWS_PAGE_SIZE_DEFAULT,
    ROWS_PAGE_SIZE_MAX,
    ReviewFloorsPutIn,
    ReviewRunCreateIn,
    ReviewSessionCancelIn,
    ReviewSessionCreateIn,
    RowPageOut,
    RowTab,
    RunOut,
    RunPageOut,
    SessionOut,
    SessionPageOut,
    SessionStatus,
)
from ..services import admission_quota_table_service as quota_table_service
from ..services import admission_review_run_service as review_run_service
from ..services import admission_review_service as review_service

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
    _admin: models.User = Depends(deps.require_quota_table_admin),
    db: AsyncSession = Depends(database.get_db),
):
    return await quota_table_service.get_quota_table(db, academic_year)


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


# =====================================================================================================================
# GĐ2-B — lần xét nháp (hợp đồng API bản 4 E1–E9). Thứ tự tham số: CasbinAuth → lớp phụ chỉ Admin → CSDL; FastAPI gọi
# dependency TRƯỚC khi báo lỗi dạng của thân / tham số ⇒ vai khác nhận 403 trước 422 / 404 (kiểm vai trước khi đọc).
# =====================================================================================================================
#: Đường dẫn con (dưới ``ROUTER_PREFIX``) — MỘT nguồn cho route, header ``Location`` và test kiểm kê.
REVIEW_SESSIONS_PATH = "/review-sessions"
REVIEW_TAG = "Lần xét tuyển GĐ2-B — lần xét nháp"
NO_STORE = "no-store"


def run_location(session_id: int, run_id: int) -> str:
    """Header ``Location`` của E6 — đường dẫn tuyệt đối (dưới ``/api``) tới E8 của run vừa tạo."""
    return "/api%s%s/%d/runs/%d" % (ROUTER_PREFIX, REVIEW_SESSIONS_PATH, int(session_id), int(run_id))


@router.post(
    REVIEW_SESSIONS_PATH,
    response_model=SessionOut,
    status_code=201,
    tags=[REVIEW_TAG],
    summary="E1 — tạo lần xét nháp cho một năm + một đợt (năm phải có bảng chỉ tiêu)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def create_review_session(
    request: Request,
    payload: ReviewSessionCreateIn,
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out, after_commit = await review_service.create_session(
        db,
        academic_year=payload.academic_year,
        admission_round_id=payload.admission_round_id,
        actor_user_id=current_user.id,
    )
    await db.commit()
    if after_commit is not None:
        await after_commit()
    return out


@router.get(
    REVIEW_SESSIONS_PATH,
    response_model=SessionPageOut,
    tags=[REVIEW_TAG],
    summary="E2 — danh sách lần xét (năm giảm dần, rồi số thứ tự giảm dần)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_review_sessions(
    request: Request,
    academic_year: Optional[int] = Query(None, ge=2000, le=2100, description="Lọc theo năm tuyển sinh"),
    status: Optional[SessionStatus] = Query(None, description="Lọc theo trạng thái lần xét"),
    page: int = Query(1, ge=1),
    page_size: int = Query(LIST_PAGE_SIZE_DEFAULT, ge=1, le=LIST_PAGE_SIZE_MAX),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    return await review_service.list_sessions(
        db, academic_year=academic_year, status=status, page=page, page_size=page_size
    )


@router.get(
    REVIEW_SESSIONS_PATH + "/{session_id}",
    response_model=SessionOut,
    tags=[REVIEW_TAG],
    summary="E3 — chi tiết lần xét + điểm sàn + run mới nhất",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_review_session(
    request: Request,
    response: Response,
    session_id: int = Path(..., ge=1),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await review_service.get_session_out(db, session_id)
    response.headers["Cache-Control"] = NO_STORE
    return out


@router.put(
    REVIEW_SESSIONS_PATH + "/{session_id}/floors",
    response_model=SessionOut,
    tags=[REVIEW_TAG],
    summary="E4 — thay TOÀN BỘ điểm sàn của lần xét nháp (phiên bản lạc quan)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def put_review_floors(
    request: Request,
    payload: ReviewFloorsPutIn,
    session_id: int = Path(..., ge=1),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out, after_commit = await review_service.replace_floors(
        db,
        session_id,
        version=payload.version,
        floors=[(f.offering_academic_info_id, f.floor_score) for f in payload.floors],
        actor_user_id=current_user.id,
    )
    await db.commit()
    if after_commit is not None:
        await after_commit()
    return out


@router.post(
    REVIEW_SESSIONS_PATH + "/{session_id}/cancel",
    response_model=SessionOut,
    tags=[REVIEW_TAG],
    summary="E5 — huỷ lần xét nháp (bắt buộc lý do; giải phóng mọi điểm sàn; trạng thái cuối)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def cancel_review_session(
    request: Request,
    payload: ReviewSessionCancelIn,
    session_id: int = Path(..., ge=1),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out, after_commit = await review_service.cancel_session(
        db, session_id, version=payload.version, reason=payload.reason, actor_user_id=current_user.id
    )
    await db.commit()
    if after_commit is not None:
        await after_commit()
    return out


@router.post(
    REVIEW_SESSIONS_PATH + "/{session_id}/runs",
    response_model=RunOut,
    status_code=202,
    tags=[REVIEW_TAG],
    summary="E6 — chạy kiểm hồ sơ (GĐ2-B: đồng bộ — 202 đã mang run 'done'; không đổi gì trên hồ sơ)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def create_review_run(
    request: Request,
    response: Response,
    payload: ReviewRunCreateIn,
    session_id: int = Path(..., ge=1),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    run, after_commit = await review_run_service.run_evaluate(
        db,
        engine=database.engine,
        session_id=session_id,
        session_version=payload.session_version,
        actor_user_id=current_user.id,
    )
    out = await review_service.run_out_for(db, session_id, run)
    await db.commit()
    if after_commit is not None:
        await after_commit()
    response.headers["Location"] = run_location(session_id, out["id"])
    return out


@router.get(
    REVIEW_SESSIONS_PATH + "/{session_id}/runs",
    response_model=RunPageOut,
    tags=[REVIEW_TAG],
    summary="E7 — danh sách run của lần xét (id giảm dần)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_review_runs(
    request: Request,
    session_id: int = Path(..., ge=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(LIST_PAGE_SIZE_DEFAULT, ge=1, le=LIST_PAGE_SIZE_MAX),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    return await review_service.list_runs(db, session_id, page=page, page_size=page_size)


@router.get(
    REVIEW_SESSIONS_PATH + "/{session_id}/runs/{run_id}",
    response_model=RunOut,
    tags=[REVIEW_TAG],
    summary="E8 — chi tiết run (đầu vào, tóm tắt, bảng chỉ tiêu tham khảo — bất biến)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_review_run(
    request: Request,
    response: Response,
    session_id: int = Path(..., ge=1),
    run_id: int = Path(..., ge=1),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await review_service.get_run_out(db, session_id, run_id)
    response.headers["Cache-Control"] = NO_STORE
    return out


@router.get(
    REVIEW_SESSIONS_PATH + "/{session_id}/runs/{run_id}/rows",
    response_model=RowPageOut,
    tags=[REVIEW_TAG],
    summary="E9 — dòng kết quả của run: bốn tab, lọc, phân trang (thứ tự cố định)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_review_run_rows(
    request: Request,
    response: Response,
    session_id: int = Path(..., ge=1),
    run_id: int = Path(..., ge=1),
    tab: Optional[RowTab] = Query(None, description="Một tab; vắng = mọi tab"),
    offering_academic_info_id: Optional[int] = Query(None, ge=1, description="Học vụ của NV được xếp"),
    reason_code: Optional[str] = Query(
        None, min_length=1, max_length=100, pattern=ROW_REASON_CODE_PATTERN, description="Dòng có mã này trong reason_codes"
    ),
    flag: Optional[str] = Query(
        None, min_length=1, max_length=100, pattern=ROW_FLAG_PATTERN, description="Dòng có cờ này trong flags"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(ROWS_PAGE_SIZE_DEFAULT, ge=1, le=ROWS_PAGE_SIZE_MAX),
    current_user: models.User = deps.CasbinAuth,
    _admin: models.User = Depends(deps.require_review_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await review_service.list_rows(
        db,
        session_id,
        run_id,
        tab=tab,
        offering_academic_info_id=offering_academic_info_id,
        reason_code=reason_code,
        flag=flag,
        page=page,
        page_size=page_size,
    )
    response.headers["Cache-Control"] = NO_STORE
    return out
