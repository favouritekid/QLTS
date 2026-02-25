# app/services/commission_service.py
"""
Commission Service - Business logic for commission calculation and workflow.

Pure Python service — NO FastAPI imports.
Returns (result, post_commit_callback) tuples.
Raises domain exceptions, never HTTPException.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, List, Optional, Tuple

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app import models
from app.models.commission import CommissionPolicy, CommissionRecord
from app.repositories.commission_repository import (
    CommissionPolicyRepository,
    CommissionRecordRepository,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)


# ============================================================================
# TRIGGER (Event-Driven)
# ============================================================================


async def check_and_create_commission(
    db: AsyncSession,
    lead_id: int,
    new_status_id: str,
    actor_id: int,
) -> Tuple[List[CommissionRecord], Optional[Callable]]:
    """
    Check if lead status change should trigger commission creation.

    1. Load lead (referrer_id required)
    2. M1: validity_status IN ('valid', 'qualified') — skip otherwise
    3. Verify collaborator is active
    4. Find matching policies for this trigger_status_id + scope
    5. For each policy: calculate amount → insert record (savepoint for race safety)
    6. Return records + notification callback
    """
    lead = await db.get(models.Lead, lead_id)
    if not lead:
        log.warning("Commission check: Lead not found", lead_id=lead_id)
        return [], None

    # Must have a referrer (CTV)
    if not lead.referrer_id:
        return [], None

    # M1: Only valid/qualified leads can earn commission
    if lead.validity_status not in ("valid", "qualified"):
        log.debug(
            "Commission check: Lead validity not eligible",
            lead_id=lead_id,
            validity_status=lead.validity_status,
        )
        return [], None

    # Verify collaborator is active
    collaborator = await db.get(models.Collaborator, lead.referrer_id)
    if not collaborator or collaborator.status != "active" or collaborator.deleted_at:
        log.debug(
            "Commission check: Collaborator not active",
            lead_id=lead_id,
            referrer_id=lead.referrer_id,
        )
        return [], None

    # Find matching policies
    policy_repo = CommissionPolicyRepository(db)
    policies = await policy_repo.get_active_policies_for_status(
        trigger_status_id=new_status_id,
        unit_id=lead.unit_id,
        offering_id=getattr(lead, "offering_id", None),
    )

    if not policies:
        return [], None

    records = []
    record_repo = CommissionRecordRepository(db)

    for policy in policies:
        # Check if commission already exists for this lead+policy (idempotent)
        existing = await record_repo.get_by_lead_and_policy(lead_id, policy.id)
        if existing:
            log.debug(
                "Commission already exists, skipping",
                lead_id=lead_id,
                policy_id=policy.id,
            )
            continue

        # Calculate amount
        amount, detail = await calculate_amount(policy, lead, db)
        if amount <= 0:
            log.debug(
                "Commission amount <= 0, skipping",
                lead_id=lead_id,
                policy_id=policy.id,
                amount=amount,
            )
            continue

        # EC-6: Use savepoint to handle race condition
        try:
            async with db.begin_nested():
                record = CommissionRecord(
                    collaborator_id=collaborator.id,
                    lead_id=lead_id,
                    policy_id=policy.id,
                    amount=amount,
                    calculation_detail=detail,
                    status="pending",
                    trigger_status_id=new_status_id,
                    triggered_at=datetime.now(timezone.utc),
                )
                db.add(record)
                await db.flush()
                records.append(record)

            log.info(
                "Commission record created",
                record_id=record.id,
                collaborator_id=collaborator.id,
                lead_id=lead_id,
                policy_id=policy.id,
                amount=str(amount),
            )
        except IntegrityError:
            log.debug(
                "Commission already exists (race condition caught)",
                lead_id=lead_id,
                policy_id=policy.id,
            )
            continue

    if not records:
        return [], None

    # Build notification callback
    async def _notify():
        from app.core.events import SystemEvents
        from app.services.notification_dispatcher import safe_dispatch

        for record in records:
            await safe_dispatch(
                db=db,
                event=SystemEvents.CTV_COMMISSION_CREATED,
                payload={
                    "collaborator_id": collaborator.id,
                    "commission_id": record.id,
                    "amount": str(record.amount),
                    "lead_id": lead_id,
                    "user_id": collaborator.user_id,
                    "actor_id": actor_id,
                },
                dedupe_key=f"ctv_commission_created:{record.id}",
            )

    return records, _notify


# ============================================================================
# CALCULATION
# ============================================================================


async def calculate_amount(
    policy: CommissionPolicy,
    lead: models.Lead,
    db: AsyncSession,
) -> Tuple[Decimal, dict]:
    """
    Calculate commission amount based on policy type.

    Returns:
        (amount, calculation_detail) tuple
    """
    if policy.calculation_type == "fixed":
        amount = policy.fixed_amount or Decimal("0")
        detail = {
            "type": "fixed",
            "fixed_amount": str(amount),
            "policy_name": policy.name,
            "policy_id": policy.id,
        }
        return amount, detail

    elif policy.calculation_type == "percentage":
        # Query fee amount for percentage calculation
        base_amount = Decimal("0")
        from app.models.finance import Fee
        fee_result = await db.execute(
            select(Fee.final_amount).where(
                Fee.admission_profile_id == select(
                    models.AdmissionProfile.id
                ).where(
                    models.AdmissionProfile.lead_id == lead.id
                ).correlate_except(Fee).scalar_subquery(),
                Fee.fee_type == "tuition",
            )
        )
        fee_amount = fee_result.scalar_one_or_none()
        if fee_amount:
            base_amount = Decimal(str(fee_amount))

        percentage = policy.percentage or Decimal("0")
        amount = (base_amount * percentage / Decimal("100")).quantize(Decimal("1"))

        detail = {
            "type": "percentage",
            "percentage": str(percentage),
            "base_amount": str(base_amount),
            "calculated_amount": str(amount),
            "policy_name": policy.name,
            "policy_id": policy.id,
        }
        return amount, detail

    return Decimal("0"), {"type": "unknown", "error": "Unknown calculation type"}


# ============================================================================
# WORKFLOW
# ============================================================================


async def approve_commission(
    db: AsyncSession,
    record: CommissionRecord,
    approved_by: models.User,
) -> Tuple[CommissionRecord, None]:
    """Approve a pending commission record."""
    if record.status != "pending":
        raise BusinessRuleViolation(f"Chỉ commission pending mới có thể duyệt (hiện tại: {record.status})")

    record.status = "approved"
    record.approved_by_id = approved_by.id
    record.approved_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "Commission approved",
        record_id=record.id,
        approved_by=approved_by.id,
    )
    return record, None


async def reject_commission(
    db: AsyncSession,
    record: CommissionRecord,
    rejected_by: models.User,
    reason: str,
) -> Tuple[CommissionRecord, None]:
    """Reject a pending commission record."""
    if record.status != "pending":
        raise BusinessRuleViolation(f"Chỉ commission pending mới có thể từ chối (hiện tại: {record.status})")

    record.status = "rejected"
    record.rejected_by_id = rejected_by.id
    record.rejected_at = datetime.now(timezone.utc)
    record.rejection_reason = reason
    await db.flush()

    log.info(
        "Commission rejected",
        record_id=record.id,
        rejected_by=rejected_by.id,
        reason=reason,
    )
    return record, None


async def pay_commission(
    db: AsyncSession,
    record: CommissionRecord,
    paid_by: models.User,
    payment_reference: Optional[str] = None,
) -> Tuple[CommissionRecord, None]:
    """Mark a commission as paid."""
    if record.status != "approved":
        raise BusinessRuleViolation(f"Chỉ commission đã duyệt mới có thể thanh toán (hiện tại: {record.status})")

    record.status = "paid"
    record.paid_by_id = paid_by.id
    record.paid_at = datetime.now(timezone.utc)
    record.payment_reference = payment_reference
    await db.flush()

    log.info(
        "Commission paid",
        record_id=record.id,
        paid_by=paid_by.id,
        payment_reference=payment_reference,
    )
    return record, None


# ============================================================================
# CANCEL TRIGGERS
# ============================================================================


async def cancel_commissions_for_lead(
    db: AsyncSession,
    lead_id: int,
    reason: str,
    cancelled_by_id: Optional[int] = None,
) -> int:
    """Cancel all pending/approved commissions for a lead."""
    record_repo = CommissionRecordRepository(db)
    count = await record_repo.cancel_pending_for_lead(lead_id, reason, cancelled_by_id)
    if count > 0:
        log.info(
            "Commissions cancelled for lead",
            lead_id=lead_id,
            count=count,
            reason=reason,
        )
    return count


async def cancel_commissions_for_collaborator(
    db: AsyncSession,
    collaborator_id: int,
    reason: str,
) -> int:
    """Cancel all pending commissions for a collaborator (e.g., when suspended)."""
    from sqlalchemy import update as sa_update
    now = datetime.now(timezone.utc)
    result = await db.execute(
        sa_update(CommissionRecord)
        .where(
            CommissionRecord.collaborator_id == collaborator_id,
            CommissionRecord.status.in_(["pending", "approved"]),
        )
        .values(
            status="cancelled",
            cancelled_at=now,
            cancellation_reason=reason,
        )
    )
    count = result.rowcount
    if count > 0:
        log.info(
            "Commissions cancelled for collaborator",
            collaborator_id=collaborator_id,
            count=count,
            reason=reason,
        )
    return count


# ============================================================================
# POLICY CRUD (Admin)
# ============================================================================


async def create_policy(
    db: AsyncSession,
    data: dict,
    created_by: models.User,
) -> Tuple[CommissionPolicy, None]:
    """Create a new commission policy."""
    policy = CommissionPolicy(
        name=data["name"],
        description=data.get("description"),
        trigger_status_id=data["trigger_status_id"],
        calculation_type=data["calculation_type"],
        fixed_amount=data.get("fixed_amount"),
        percentage=data.get("percentage"),
        unit_id=data.get("unit_id"),
        offering_id=data.get("offering_id"),
        effective_from=data["effective_from"],
        effective_to=data.get("effective_to"),
        is_active=data.get("is_active", True),
        created_by_id=created_by.id,
    )
    db.add(policy)
    await db.flush()

    log.info("Commission policy created", policy_id=policy.id, name=policy.name)
    return policy, None


async def update_policy(
    db: AsyncSession,
    policy: CommissionPolicy,
    data: dict,
) -> Tuple[CommissionPolicy, None]:
    """Update an existing commission policy."""
    ALLOWED_FIELDS = {
        "name", "description", "trigger_status_id", "calculation_type",
        "fixed_amount", "percentage", "unit_id", "offering_id",
        "effective_from", "effective_to", "is_active",
    }
    for field, value in data.items():
        if field in ALLOWED_FIELDS:
            setattr(policy, field, value)

    policy.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info("Commission policy updated", policy_id=policy.id)
    return policy, None


# ============================================================================
# CENTRALIZED STATUS-CHANGE HANDLER
# ============================================================================


async def safe_check_commission_on_status_change(
    db: AsyncSession,
    lead_id: int,
    old_status: str,
    new_status: str,
    actor_id: int,
):
    """
    Centralized commission check called from ALL status-change paths after commit.

    Handles both:
    1. Forward: Create commissions when lead reaches a trigger status
    2. Regression: Cancel pending commissions when lead leaves a trigger status

    Non-critical: all exceptions are caught and logged so they never
    break the main status-change flow.
    """
    if old_status == new_status:
        return
    try:
        # 1. Forward: try to create commissions for new_status
        records, callback = await check_and_create_commission(
            db, lead_id, new_status, actor_id
        )
        if records:
            await db.commit()
            if callback:
                await callback()

        # 2. Regression: cancel pending commissions triggered by old_status
        record_repo = CommissionRecordRepository(db)
        cancelled = await record_repo.cancel_by_trigger_status(
            lead_id=lead_id,
            trigger_status_id=old_status,
            reason=f"Status changed: {old_status} → {new_status}",
            cancelled_by_id=actor_id,
        )
        if cancelled > 0:
            await db.commit()
            log.info(
                "Commissions cancelled due to status regression",
                lead_id=lead_id,
                old_status=old_status,
                new_status=new_status,
                cancelled_count=cancelled,
            )
    except Exception as e:
        log.warning(
            "Commission check failed (non-critical)",
            lead_id=lead_id,
            error=str(e),
        )
