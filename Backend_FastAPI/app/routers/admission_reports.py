"""Admin/manager read-only admission reports (v2).

Dumb HTTP translator: validates query params, delegates to
``AdmissionReportService``. Scope (admin = all / chosen unit; manager = own unit)
is enforced inside the service via domain exceptions. Read-only → no commit.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.deps import require_admin_or_manager
from app.database import get_db
from app.schemas.admission_report import AdmissionWeeklyReportResponse, ReportFilters
from app.services.admission_report_service import AdmissionReportService

router = APIRouter(prefix="/api/v2/admin/reports", tags=["Admin v2 - Reports"])


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
