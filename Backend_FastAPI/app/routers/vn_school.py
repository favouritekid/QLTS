"""Phase D.0b — VnSchool public search router.

GET /api/v2/vn-school/search — candidate FE dropdown source (Phase D.1
AcademicHistoryTab). Diacritic-insensitive search via pg_unaccent
extension (enabled by migration q9_07_d0a).

Auth: authenticated user (any role) — candidate must be logged in to
fill admission profile. Per QLTS V3 architecture (memory CLAUDE.md):
- Router dumb HTTP translator
- Service called via dependency injection
- get_current_active_user gates auth

Query params:
- q (required, min 2 chars): search text (diacritic-insensitive)
- level (optional): THCS | THPT | THCS_THPT | TRUNG_HOC_NGHE | OTHER
- province (optional): MOET province code (3 char, vd "038", "040")
- limit (default 20, max 100)
- offset (default 0)
"""
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import get_current_active_user
from app.schemas.vn_locality import VnSchoolSearchItem, VnSchoolSearchResponse
from app.services.vn_school_service import VnSchoolService


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/vn-school",
    tags=["v2 - VN School (Q9 #07 Phase D)"],
)


@router.get(
    "/search",
    response_model=VnSchoolSearchResponse,
    status_code=status.HTTP_200_OK,
)
async def search_vn_schools(
    q: Annotated[str, Query(min_length=2, max_length=100, description="Search query (diacritic-insensitive)")],
    level: Annotated[Optional[str], Query(description="Filter by school level")] = None,
    province: Annotated[Optional[str], Query(min_length=3, max_length=3, description="MOET province code")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> VnSchoolSearchResponse:
    """Search active vn_school rows by name (diacritic-insensitive).

    Returns paginated list with current KV (latest active assignment).
    """
    # Validate level enum (defensive — Query doesn't enforce enum)
    if level is not None:
        valid_levels = {"THCS", "THPT", "THCS_THPT", "TRUNG_HOC_NGHE", "OTHER"}
        if level not in valid_levels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"level must be one of {sorted(valid_levels)}",
            )

    service = VnSchoolService(db)
    rows, total = await service.search_schools(
        query=q,
        level=level,
        province=province,
        limit=limit,
        offset=offset,
    )

    items = [VnSchoolSearchItem.model_validate(row) for row in rows]
    return VnSchoolSearchResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
