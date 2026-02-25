# app/routers/commissions.py
"""
Commission Router - Admin commission management + CTV commission view.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import (
    get_commission_policy_for_admin,
    get_commission_record_for_user,
    get_own_collaborator,
    require_admin,
    require_admin_or_manager,
)
from app.core.rate_limits import limiter, RateLimits
from app.repositories.commission_repository import (
    CommissionPolicyRepository,
    CommissionRecordRepository,
)
from app.schemas.commission import (
    CommissionPay,
    CommissionPoliciesPage,
    CommissionPolicyCreate,
    CommissionPolicyResponse,
    CommissionPolicyUpdate,
    CommissionRecordResponse,
    CommissionRecordsPage,
    CommissionReject,
    CommissionStats,
)
from app.services import commission_service


# ============================================================================
# ADMIN POLICY ROUTER
# ============================================================================

policy_router = APIRouter(
    prefix="/admin/commission-policies",
    tags=["Commission Policies (Admin)"],
)


@policy_router.get("", response_model=CommissionPoliciesPage)
async def list_policies(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    is_active: Optional[bool] = None,
    trigger_status_id: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """List all commission policies."""
    repo = CommissionPolicyRepository(db)
    total, policies = await repo.get_filtered(
        skip=skip,
        limit=limit,
        is_active=is_active,
        trigger_status_id=trigger_status_id,
    )
    return CommissionPoliciesPage(total_count=total, policies=policies)


@policy_router.post("", response_model=CommissionPolicyResponse, status_code=201)
async def create_policy(
    data: CommissionPolicyCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """Create a new commission policy."""
    policy, _ = await commission_service.create_policy(
        db, data.model_dump(), current_user
    )
    await db.commit()

    repo = CommissionPolicyRepository(db)
    policy = await repo.get_by_id(policy.id)
    return policy


@policy_router.get("/{policy_id}", response_model=CommissionPolicyResponse)
async def get_policy(
    policy: models.CommissionPolicy = Depends(get_commission_policy_for_admin),
):
    """Get commission policy detail."""
    return policy


@policy_router.put("/{policy_id}", response_model=CommissionPolicyResponse)
async def update_policy(
    data: CommissionPolicyUpdate,
    policy: models.CommissionPolicy = Depends(get_commission_policy_for_admin),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """Update a commission policy."""
    updated, _ = await commission_service.update_policy(
        db, policy, data.model_dump(exclude_unset=True)
    )
    await db.commit()

    repo = CommissionPolicyRepository(db)
    updated = await repo.get_by_id(updated.id)
    return updated


# ============================================================================
# ADMIN COMMISSION RECORDS ROUTER
# ============================================================================

record_router = APIRouter(
    prefix="/admin/commissions",
    tags=["Commissions (Admin)"],
)


@record_router.get("", response_model=CommissionRecordsPage)
async def list_commissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    collaborator_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """List commission records with filters."""
    repo = CommissionRecordRepository(db)

    # Manager: filter by own unit
    unit_id = None
    if current_user.role == "manager":
        unit_id = current_user.unit_id

    total, records = await repo.get_filtered(
        skip=skip,
        limit=limit,
        collaborator_id=collaborator_id,
        status=status,
        unit_id=unit_id,
    )
    return CommissionRecordsPage(total_count=total, records=records)


@record_router.get("/{record_id}", response_model=CommissionRecordResponse)
async def get_commission(
    record: models.CommissionRecord = Depends(get_commission_record_for_user),
):
    """Get commission record detail."""
    return record


@record_router.post("/{record_id}/approve", response_model=CommissionRecordResponse)
async def approve_commission(
    record: models.CommissionRecord = Depends(get_commission_record_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Approve a pending commission record."""
    updated, _ = await commission_service.approve_commission(
        db, record, current_user
    )
    await db.commit()

    repo = CommissionRecordRepository(db)
    updated = await repo.get_by_id(updated.id)
    return updated


@record_router.post("/{record_id}/reject", response_model=CommissionRecordResponse)
async def reject_commission(
    data: CommissionReject,
    record: models.CommissionRecord = Depends(get_commission_record_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Reject a pending commission record."""
    updated, _ = await commission_service.reject_commission(
        db, record, current_user, data.rejection_reason
    )
    await db.commit()

    repo = CommissionRecordRepository(db)
    updated = await repo.get_by_id(updated.id)
    return updated


@record_router.post("/{record_id}/pay", response_model=CommissionRecordResponse)
async def pay_commission(
    data: CommissionPay,
    record: models.CommissionRecord = Depends(get_commission_record_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Mark a commission as paid."""
    updated, _ = await commission_service.pay_commission(
        db, record, current_user, data.payment_reference
    )
    await db.commit()

    repo = CommissionRecordRepository(db)
    updated = await repo.get_by_id(updated.id)
    return updated


# ============================================================================
# CTV COMMISSION ENDPOINTS (added to ctv_router in collaborators.py)
# ============================================================================

ctv_commission_router = APIRouter(
    prefix="/ctv/commissions",
    tags=["CTV Commissions"],
)


@ctv_commission_router.get("", response_model=CommissionRecordsPage)
async def list_own_commissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """List own commission records."""
    repo = CommissionRecordRepository(db)
    total, records = await repo.get_filtered(
        skip=skip,
        limit=limit,
        collaborator_id=collaborator.id,
        status=status,
    )
    return CommissionRecordsPage(total_count=total, records=records)


@ctv_commission_router.get("/stats", response_model=CommissionStats)
async def get_own_commission_stats(
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """Get own commission statistics."""
    repo = CommissionRecordRepository(db)
    stats = await repo.get_stats_by_collaborator(collaborator.id)
    return stats
