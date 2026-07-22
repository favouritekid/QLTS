"""Admin/manager read-only admission reports (v2).

Dumb HTTP translator: validates query params, delegates to
``AdmissionReportService``. Scope (admin = all / chosen unit; manager = own unit)
is enforced inside the service via domain exceptions. Read-only → no commit.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.deps import require_admin_or_manager
from app.core.rate_limits import RateLimits, limiter
from app.database import get_db
from app.schemas.admission_report import (
    AdmissionTrendResponse,
    AdmissionWeeklyReportResponse,
    OfficerMajorMatrixResponse,
    PipelineFunnelResponse,
    ReportFilters,
)
from app.services.admission_report_service import AdmissionReportService
from app.services.admission_summary_export_service import (
    AdmissionSummaryExportService,
)

router = APIRouter(prefix="/api/v2/admin/reports", tags=["Admin v2 - Reports"])

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/admission-weekly", response_model=AdmissionWeeklyReportResponse)
async def get_admission_weekly_report(
    academic_year: int = Query(..., ge=2020, le=2100),
    group_by: str = Query("major", pattern="^(major|officer)$"),
    round_code: Optional[str] = Query(None, max_length=20),
    week_start: Optional[date] = Query(
        None, description="Bất kỳ ngày trong tuần (VN); bỏ trống = tuần hiện tại"
    ),
    officer_id: Optional[int] = Query(None, ge=1),
    unit_id: Optional[int] = Query(
        None, ge=1, description="Admin chọn đơn vị; manager bị ép về đơn vị của mình"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> AdmissionWeeklyReportResponse:
    service = AdmissionReportService(db)
    return await service.get_weekly_report(
        current_user=current_user,
        academic_year=academic_year,
        group_by=group_by,
        round_code=round_code,
        week_start=week_start,
        officer_id=officer_id,
        unit_id=unit_id,
    )


@router.get("/admission-weekly/filters", response_model=ReportFilters)
async def get_admission_weekly_report_filters(
    academic_year: Optional[int] = Query(
        None, ge=2020, le=2100, description="Truyền để lấy danh sách đợt của năm đó"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> ReportFilters:
    """Năm (config ∪ data) + đợt cho bộ lọc báo cáo — admin & manager (cùng cổng)."""
    service = AdmissionReportService(db)
    return await service.get_filter_options(academic_year)


@router.get("/admission-weekly/pipeline-funnel", response_model=PipelineFunnelResponse)
async def get_admission_pipeline_funnel(
    academic_year: int = Query(..., ge=2020, le=2100),
    round_code: Optional[str] = Query(None, max_length=20),
    unit_id: Optional[int] = Query(
        None, ge=1, description="Admin chọn đơn vị; manager bị ép về đơn vị của mình"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> PipelineFunnelResponse:
    """Phễu lead theo giai đoạn pipeline hiện tại (cohort = đợt/năm, scope IDOR)."""
    service = AdmissionReportService(db)
    return await service.get_pipeline_funnel(
        current_user=current_user,
        academic_year=academic_year,
        round_code=round_code,
        unit_id=unit_id,
    )


@router.get("/admission-weekly/trend", response_model=AdmissionTrendResponse)
async def get_admission_trend(
    academic_year: int = Query(..., ge=2020, le=2100),
    round_code: Optional[str] = Query(None, max_length=20),
    unit_id: Optional[int] = Query(
        None, ge=1, description="Admin chọn đơn vị; manager bị ép về đơn vị của mình"
    ),
    weeks: int = Query(8, ge=2, le=26, description="Số tuần tích luỹ trả về"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> AdmissionTrendResponse:
    """Chuỗi thời gian N tuần tích luỹ (nộp hồ sơ / đủ điều kiện / nhập học)."""
    service = AdmissionReportService(db)
    return await service.get_trend(
        current_user=current_user,
        academic_year=academic_year,
        round_code=round_code,
        unit_id=unit_id,
        weeks=weeks,
    )


@router.get(
    "/admission-weekly/officer-major-matrix",
    response_model=OfficerMajorMatrixResponse,
)
async def get_admission_officer_major_matrix(
    academic_year: int = Query(..., ge=2020, le=2100),
    round_code: Optional[str] = Query(None, max_length=20),
    unit_id: Optional[int] = Query(
        None, ge=1, description="Admin chọn đơn vị; manager bị ép về đơn vị của mình"
    ),
    metric: str = Query("enrolled", pattern="^(enrolled|submitted)$"),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> OfficerMajorMatrixResponse:
    """Heatmap cán bộ × ngành — đếm enrolled + submitted (cumulative-to-now)."""
    service = AdmissionReportService(db)
    return await service.get_officer_major_matrix(
        current_user=current_user,
        academic_year=academic_year,
        round_code=round_code,
        unit_id=unit_id,
        metric=metric,
    )


@limiter.limit(RateLimits.DATA_EXPORT)  # 20/hour — heavyweight workbook build
@router.get("/admission-summary/export.xlsx")
async def export_admission_summary(
    request: Request,  # required by slowapi rate limiter
    academic_year: int = Query(..., ge=2020, le=2100),
    unit_id: Optional[int] = Query(
        None, ge=1, description="Admin chọn đơn vị; manager bị ép về đơn vị của mình"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> Response:
    """Xuất báo cáo tuyển sinh (snapshot) ra Excel — số liệu CẢ NĂM tại thời điểm xuất.

    3 sheet: Số liệu chung (ngành × trạng thái) · Chia theo nhân viên · Quy ước.
    Read-only → không commit. Scope theo vai trò (admin toàn trường / manager đơn vị).
    """
    service = AdmissionSummaryExportService(db)
    content, filename = await service.build_xlsx(
        current_user=current_user, academic_year=academic_year, unit_id=unit_id
    )
    # Plain Response (not StreamingResponse(iter([...]))) so Content-Length is set.
    return Response(
        content=content,
        media_type=_XLSX_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
