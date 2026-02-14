# app/routers/admin/__init__.py
"""
Admin router module - Split from monolithic admin.py

This module aggregates specialized admin routers for better organization
and maintainability.

PHASE 2A: users.py + roles.py ✅
PHASE 2B: organization.py + config.py ✅
PHASE 2C: pipeline.py ✅
PHASE 2D: sync.py ✅ (Backward compatible aliases)
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import CasbinAuth  # ✅ Phase 2.2: Use standard alias
from app.services import activity_service

# PHASE 2A routers
from . import users, roles

# PHASE 2B routers
from . import organization, config

# PHASE 2C routers
from . import pipeline

# PHASE 2D routers (Backward compatibility)
from . import sync

# Tuition Discount Policy router
from . import tuition_discount

# Installment Plans router
from . import installment_plans

# Cache Management router
from . import cache

# System Management router (NOTIFICATION 2.0)
from . import system

# Deleted Items Management router
from . import deleted_items

# Audit Logs router
from . import audit_logs

# Create main admin router
router = APIRouter(prefix="/admin", tags=["Admin"])


# =============================================================================
# TOP-LEVEL ADMIN ENDPOINTS (not specific to any sub-resource)
# =============================================================================

@router.get("/activity-logs")
async def get_activity_logs(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = CasbinAuth,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    actor_id: Optional[int] = Query(None),
    target_user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
):
    """(Admin only) Get activity logs with filters - supports all resource types including casbin_policy."""
    skip = (page - 1) * page_size

    total, logs = await activity_service.get_activity_logs(
        db=db,
        skip=skip,
        limit=page_size,
        actor_id=actor_id,
        target_user_id=target_user_id,
        action=action,
        resource_type=resource_type,
    )

    return {"total_count": total, "logs": logs}


# =============================================================================
# SUB-ROUTERS
# =============================================================================

# Include PHASE 2A routers
router.include_router(users.router)    # /api/admin/users/*
router.include_router(roles.router)    # /api/admin/roles/*

# Include PHASE 2B routers
router.include_router(organization.router)  # /api/admin/organization-units/*, /api/admin/programs/*, /api/admin/offerings/*
router.include_router(config.router)        # /api/admin/assignment-config/*, /api/admin/skill-rules/*

# Include PHASE 2C routers
router.include_router(pipeline.router)      # /api/admin/pipeline-stages/*, /api/admin/consultation-statuses/*, /api/admin/allowed-transitions/*, /api/admin/leads/*/revert-status

# Include PHASE 2D routers (Backward compatibility aliases)
router.include_router(sync.router)          # /api/admin/sync/status, /api/admin/sync (aliases to users router)

# Include Tuition Discount Policy router
router.include_router(tuition_discount.router)  # /api/admin/tuition-discount-policies/*

# Include Installment Plans router
router.include_router(installment_plans.router)  # /api/admin/installment-plans/*

# Include Cache Management router
router.include_router(cache.router)  # /api/admin/cache/*

# Include System Management router (NOTIFICATION 2.0)
router.include_router(system.router)  # /api/admin/system/*

# Include Deleted Items Management router
router.include_router(deleted_items.router)  # /api/admin/deleted-items/*

# Include Audit Logs router
router.include_router(audit_logs.router)  # /api/admin/audit-logs/*
