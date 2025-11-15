# app/routers/officer.py
"""
Officer Command Center API - Dashboard endpoints for officers.

Security:
- All endpoints require officer role
- Officers can only access their own data
- Real-time Socket.IO integration
"""
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..core.deps import PermissionDep, get_current_user, get_db
from ..services import officer_service
from ..socket_manager import emit_to_all

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/officer", tags=["Officer Dashboard"])


# === Pydantic Schemas ===

class AvailabilityUpdate(BaseModel):
    """Request schema for updating officer availability status."""
    availability_status: str = Field(
        ...,
        pattern="^(available|busy|offline)$",
        description="Officer availability status",
        examples=["available"]
    )


class OfficerStatsResponse(BaseModel):
    """Response schema for officer dashboard statistics."""
    status_overview: dict
    performance_trends: list
    sales_funnel: list
    actionable_lists: dict

    model_config = {
        "json_schema_extra": {
            "example": {
                "status_overview": {
                    "workload": 15,
                    "max_capacity": 20,
                    "utilization": 75.0,
                    "availability_status": "available",
                    "last_assigned_at": "2025-11-15T10:30:00Z"
                },
                "performance_trends": [
                    {
                        "date": "2025-11-09",
                        "leads_assigned": 3,
                        "consultations": 5,
                        "converted": 1
                    }
                ],
                "sales_funnel": [
                    {"stage_name": "New", "stage_order": 1, "lead_count": 5},
                    {"stage_name": "Contacted", "stage_order": 2, "lead_count": 3}
                ],
                "actionable_lists": {
                    "high_score": [],
                    "stale": [],
                    "upcoming": []
                }
            }
        }
    }


# === Endpoints ===

@router.get(
    "/stats",
    response_model=OfficerStatsResponse,
    summary="Get Officer Dashboard Statistics",
    description="""
    Retrieve comprehensive dashboard statistics for the authenticated officer.

    **Includes:**
    - Status Overview: Workload, capacity, utilization, availability
    - Performance Trends: 7-day chart data (leads, consultations, conversions)
    - Sales Funnel: Lead distribution across pipeline stages
    - Actionable Lists: High-score leads, stale leads, upcoming consultations

    **Security:** Officer role required. Returns data only for current user.

    **Performance:** Optimized with DB-level aggregations (no N+1 queries).
    """
)
async def get_officer_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_user)],
    _permission: Annotated[bool, PermissionDep("officer", "read", "dashboard")]
):
    """
    GET /api/officer/stats

    Returns dashboard statistics for the authenticated officer.
    """
    try:
        # Verify user is an officer
        if current_user.role != "officer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint is only accessible to officers"
            )

        # Fetch dashboard stats (officers can only see their own data)
        stats = await officer_service.get_officer_dashboard_stats(
            db=db,
            officer_id=current_user.id
        )

        log.info(
            "Officer stats retrieved",
            officer_id=current_user.id,
            workload=stats["status_overview"]["workload"]
        )

        return stats

    except ValueError as e:
        log.error(
            "Validation error in get_officer_stats",
            officer_id=current_user.id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        log.error(
            "Unexpected error in get_officer_stats",
            officer_id=current_user.id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch officer statistics"
        )


@router.post(
    "/availability",
    response_model=dict,
    summary="Update Officer Availability Status",
    description="""
    Toggle officer's availability status for receiving new lead assignments.

    **Statuses:**
    - `available`: Ready to receive new leads (default)
    - `busy`: Temporarily unavailable (existing leads maintained)
    - `offline`: Not available (won't receive auto-assignments)

    **Real-time:** Emits Socket.IO event to notify admins of status change.

    **Security:** Officer role required. Can only update own status.
    """
)
async def update_availability(
    availability_data: AvailabilityUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, Depends(get_current_user)],
    _permission: Annotated[bool, PermissionDep("officer", "update", "availability")]
):
    """
    POST /api/officer/availability

    Update the officer's availability status.
    Body: {"availability_status": "available|busy|offline"}
    """
    try:
        # Verify user is an officer
        if current_user.role != "officer":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This endpoint is only accessible to officers"
            )

        # Update availability status
        updated_officer = await officer_service.update_officer_availability(
            db=db,
            officer_id=current_user.id,
            availability_status=availability_data.availability_status
        )

        # === Real-time Socket.IO Notification ===
        # Notify admins that officer's availability changed
        try:
            await emit_to_all(
                event="officer_availability_changed",
                data={
                    "officer_id": updated_officer.id,
                    "officer_name": updated_officer.username,
                    "old_status": current_user.availability_status,  # From before update
                    "new_status": updated_officer.availability_status,
                    "unit_id": updated_officer.unit_id,
                    "timestamp": updated_officer.updated_at.isoformat() if updated_officer.updated_at else None
                }
            )
            log.info(
                "Officer availability change broadcasted via Socket.IO",
                officer_id=updated_officer.id,
                new_status=updated_officer.availability_status
            )
        except Exception as socket_err:
            # Don't fail the request if Socket.IO fails
            log.error(
                "Failed to emit officer availability Socket.IO event",
                officer_id=updated_officer.id,
                error=str(socket_err),
                exc_info=True
            )

        return {
            "success": True,
            "message": f"Availability status updated to '{updated_officer.availability_status}'",
            "officer_id": updated_officer.id,
            "availability_status": updated_officer.availability_status
        }

    except ValueError as e:
        log.error(
            "Validation error in update_availability",
            officer_id=current_user.id,
            error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        log.error(
            "Unexpected error in update_availability",
            officer_id=current_user.id,
            error=str(e),
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update availability status"
        )
