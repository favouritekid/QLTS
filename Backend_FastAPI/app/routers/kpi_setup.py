# app/routers/kpi_setup.py
"""
KPI Setup — Coverage Dashboard (Phase 1: Read-Only).
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.deps import require_admin_or_manager
from app.database import get_db
from app.schemas.kpi_setup import CoverageReport
from app.services import kpi_setup_service

router = APIRouter(prefix="/api/admin/kpi-setup", tags=["KPI Setup"])


@router.get("/coverage", response_model=CoverageReport)
async def get_coverage(
    fiscal_year: int = Query(..., ge=2020, le=2100),
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """
    Get KPI coverage report for all units (admin) or own unit (manager).
    """
    if current_user.role != "admin":
        if current_user.unit_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Manager chưa được gán đơn vị, không thể xem KPI coverage.",
            )
        scope_unit_id = current_user.unit_id
    else:
        scope_unit_id = None

    return await kpi_setup_service.get_coverage_report(
        db, fiscal_year, scope_unit_id
    )
