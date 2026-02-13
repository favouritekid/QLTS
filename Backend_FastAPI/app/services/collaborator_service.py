# app/services/collaborator_service.py
"""
Collaborator (CTV) Service - Phase 1: Business Logic

Pure Python service — NO FastAPI imports.
Returns (result, post_commit_callback) tuples.
Raises domain exceptions, never HTTPException.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.constants import UserRole
from app.repositories.collaborator_repository import CollaboratorRepository
from app.repositories.lead_claim_repository import LeadClaimRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.collaborator import (
    CollaboratorCreate,
    CollaboratorUpdate,
    LeadClaimCreate,
    LeadClaimData,
    LeadClaimReview,
    LeadValidityUpdate,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    DuplicateResourceError,
    ResourceNotFoundError,
)
from .status_helper import StatusHelper

log = structlog.get_logger(__name__)

# Lead statuses considered "unprocessed" for CTV claim
CLAIMABLE_STATUSES = {"new"}

# Prep for Phase 2 zombie lock window
CONFIG_ATTRIBUTION_EXPIRE_DAYS = 90


def mask_phone(phone: str) -> str:
    """Mask phone number for CTV view: 0912***456."""
    if not phone or len(phone) < 7:
        return "***"
    return f"{phone[:4]}***{phone[-3:]}"


# ============================================================================
# COLLABORATOR CRUD
# ============================================================================


async def create_collaborator(
    db: AsyncSession,
    data: CollaboratorCreate,
    created_by: models.User,
) -> Tuple[models.Collaborator, Optional[callable]]:
    """
    Create a new collaborator.

    - Auto-generates code via sequence
    - Checks phone uniqueness
    - If user_id provided: validates user exists and not already linked
    - If managed_by_officer_id provided: validates officer exists & active
    - Auto-approve if created by admin
    """
    repo = CollaboratorRepository(db)

    # Check phone uniqueness
    is_unique = await repo.check_phone_unique(data.phone)
    if not is_unique:
        raise DuplicateResourceError("Số điện thoại CTV đã tồn tại trong hệ thống")

    # Validate user_id if provided
    if data.user_id:
        user = await db.get(models.User, data.user_id)
        if not user:
            raise ResourceNotFoundError(f"User {data.user_id} not found")
        existing_collab = await repo.get_by_user_id(data.user_id)
        if existing_collab:
            raise DuplicateResourceError(
                f"User {data.user_id} đã được liên kết với CTV {existing_collab.code}"
            )

    # Validate managed_by_officer_id if provided
    if data.managed_by_officer_id:
        officer = await db.get(models.User, data.managed_by_officer_id)
        if not officer:
            raise ResourceNotFoundError(f"Officer {data.managed_by_officer_id} not found")
        if officer.status != "active":
            raise BusinessRuleViolation("Officer không hoạt động")
        if officer.role not in [UserRole.OFFICER, UserRole.MANAGER, UserRole.ADMIN]:
            raise BusinessRuleViolation("User được chỉ định không phải là officer")

    # Generate code with retry for collision
    year = datetime.now(timezone.utc).year
    max_retries = 3
    collaborator = None

    for attempt in range(max_retries):
        try:
            async with db.begin_nested():
                code = await repo.generate_next_code(year)

                collaborator = models.Collaborator(
                    code=code,
                    full_name=data.full_name,
                    phone=data.phone,
                    email=data.email,
                    unit_id=data.unit_id,
                    user_id=data.user_id,
                    managed_by_officer_id=data.managed_by_officer_id,
                    id_card_number=data.id_card_number,
                    bank_account=data.bank_account,
                    bank_name=data.bank_name,
                    address=data.address,
                    notes=data.notes,
                )

                # Auto-approve if created by admin
                if created_by.role == UserRole.ADMIN:
                    collaborator.status = "active"
                    collaborator.approved_at = datetime.now(timezone.utc)
                    collaborator.approved_by_id = created_by.id
                else:
                    collaborator.status = "pending"

                db.add(collaborator)
                await db.flush()

                # If user_id provided, set user role to collaborator
                if data.user_id:
                    user = await db.get(models.User, data.user_id)
                    if user:
                        user.role = UserRole.COLLABORATOR
                        await db.flush()

            break
        except IntegrityError:
            if attempt == max_retries - 1:
                raise DuplicateResourceError("Không thể tạo mã CTV, vui lòng thử lại")
            continue

    log.info(
        "Collaborator created",
        collaborator_id=collaborator.id,
        code=collaborator.code,
        created_by=created_by.id,
    )

    return collaborator, None


async def update_collaborator(
    db: AsyncSession,
    collaborator: models.Collaborator,
    data: CollaboratorUpdate,
) -> Tuple[models.Collaborator, Optional[callable]]:
    """
    Update collaborator. Handles officer re-assignment (EC-1).
    """
    repo = CollaboratorRepository(db)

    # Check phone uniqueness if changed
    if data.phone and data.phone != collaborator.phone:
        is_unique = await repo.check_phone_unique(data.phone, exclude_id=collaborator.id)
        if not is_unique:
            raise DuplicateResourceError("Số điện thoại CTV đã tồn tại trong hệ thống")

    old_officer_id = collaborator.managed_by_officer_id
    post_callback = None

    # Apply updates
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(collaborator, field, value)

    collaborator.updated_at = datetime.now(timezone.utc)
    await db.flush()

    # EC-1: If managed_by_officer_id changed, reassign unprocessed leads
    new_officer_id = collaborator.managed_by_officer_id
    if (
        data.managed_by_officer_id is not None
        and old_officer_id != new_officer_id
        and old_officer_id is not None
        and new_officer_id is not None
    ):
        lead_repo = LeadRepository(db)
        new_officer = await db.get(models.User, new_officer_id)
        if new_officer and new_officer.status == "active":
            count = await lead_repo.reassign_unprocessed_leads(
                referrer_id=collaborator.id,
                from_officer_id=old_officer_id,
                to_officer_id=new_officer_id,
                to_unit_id=new_officer.unit_id,
                only_statuses=CLAIMABLE_STATUSES,
            )
            if count > 0:
                log.info(
                    "EC-1: Reassigned unprocessed leads after CTV officer change",
                    collaborator_id=collaborator.id,
                    from_officer=old_officer_id,
                    to_officer=new_officer_id,
                    count=count,
                )

    return collaborator, post_callback


async def approve_collaborator(
    db: AsyncSession,
    collaborator: models.Collaborator,
    approved_by: models.User,
) -> Tuple[models.Collaborator, None]:
    """Approve a pending collaborator."""
    if collaborator.status == "active":
        raise BusinessRuleViolation("CTV đã được duyệt")
    if collaborator.status == "suspended":
        raise BusinessRuleViolation("CTV đang bị đình chỉ, không thể duyệt")

    collaborator.status = "active"
    collaborator.approved_at = datetime.now(timezone.utc)
    collaborator.approved_by_id = approved_by.id
    collaborator.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "Collaborator approved",
        collaborator_id=collaborator.id,
        approved_by=approved_by.id,
    )
    return collaborator, None


async def suspend_collaborator(
    db: AsyncSession,
    collaborator: models.Collaborator,
) -> Tuple[models.Collaborator, None]:
    """Suspend an active collaborator."""
    if collaborator.status == "suspended":
        raise BusinessRuleViolation("CTV đã bị đình chỉ")

    collaborator.status = "suspended"
    collaborator.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info("Collaborator suspended", collaborator_id=collaborator.id)
    return collaborator, None


async def get_collaborator_stats(
    db: AsyncSession,
    collaborator_id: int,
) -> dict:
    """Get stats for a collaborator."""
    lead_repo = LeadRepository(db)
    stats = await lead_repo.count_leads_by_referrer_and_validity(collaborator_id)

    # Count pending claims
    claim_repo = LeadClaimRepository(db)
    pending_count_result = await claim_repo.get_filtered(
        limit=0, collaborator_id=collaborator_id, status="pending"
    )
    stats["pending_claims"] = pending_count_result[0]

    return stats


# ============================================================================
# LEAD CLAIM WORKFLOW
# ============================================================================


async def submit_lead_claim(
    db: AsyncSession,
    collaborator: models.Collaborator,
    claim_create: LeadClaimCreate,
) -> Tuple[Tuple[models.Lead, models.LeadClaim], Optional[callable]]:
    """
    CTV submits a lead through claim workflow.

    3-layer first-touch lock:
    1. Lead already has referrer → BLOCK
    2. Officer actively working lead (non-claimable status) → BLOCK
    3. Lead new/unprocessed → ALLOW (attach referrer)

    If no existing lead → create new one.
    """
    claim_data = claim_create.lead_data
    lead_repo = LeadRepository(db)
    claim_repo = LeadClaimRepository(db)

    # Pre-check: collaborator must be active
    if collaborator.status != "active":
        raise BusinessRuleViolation("Tài khoản CTV chưa được kích hoạt")

    # Block self-claim: CTV phone cannot match lead phone (M2)
    if collaborator.phone == claim_data.phone:
        raise BusinessRuleViolation("Không thể giới thiệu lead có cùng số điện thoại với CTV")

    # Determine officer for routing
    officer = None
    if collaborator.managed_by_officer_id:
        officer = await db.get(models.User, collaborator.managed_by_officer_id)
        # Fallback if officer inactive
        if officer and officer.status != "active":
            log.warning(
                "CTV officer inactive, fallback to independent mode",
                collaborator_id=collaborator.id,
                officer_id=collaborator.managed_by_officer_id,
            )
            officer = None

    # First-touch lock with FOR UPDATE
    # A1: LeadClaim created INSIDE savepoint for atomicity
    async with db.begin_nested():
        existing = await lead_repo.check_first_touch_for_update(claim_data.phone)

        if existing:
            # Layer 1: Already has referrer → BLOCK
            if existing.referrer_id:
                raise BusinessRuleViolation("Lead đã được CTV khác giới thiệu")

            # Layer 2: Officer already working OR lead progressed → BLOCK
            if (
                existing.assigned_officer_id
                and existing.status not in CLAIMABLE_STATUSES
            ):
                raise BusinessRuleViolation(
                    "Lead đang được tư vấn, không thể claim"
                )

            # Layer 3: Lead new/unprocessed → ALLOW
            existing.referrer_id = collaborator.id
            existing.source = "referral"
            lead = existing
        else:
            # Create new lead
            lead = models.Lead(
                full_name=claim_data.full_name,
                phone=claim_data.phone,
                email=claim_data.email,
                source="referral",
                referrer_id=collaborator.id,
                validity_status="raw",
                created_via="claim",
                unit_id=officer.unit_id if officer else collaborator.unit_id,
                assigned_officer_id=officer.id if officer else None,
                assignment_status="assigned" if officer else "pending",
            )
            db.add(lead)

            # A2: Set initial consultation status (same pattern as create_lead)
            initial_status = await StatusHelper.get_initial_status(db)
            if initial_status:
                await StatusHelper.sync_lead_status(lead, initial_status)
            else:
                lead.status = "new"

            await db.flush()

        # Create LeadClaim record (inside savepoint for atomicity)
        claim_data_dict = claim_data.model_dump()
        try:
            claim = models.LeadClaim(
                collaborator_id=collaborator.id,
                lead_id=lead.id,
                status="pending",
                claim_data=claim_data_dict,
            )
            db.add(claim)
            await db.flush()
        except IntegrityError:
            raise DuplicateResourceError(
                "CTV đã claim lead này trước đó. Mỗi CTV chỉ được claim 1 lead 1 lần."
            )

    log.info(
        "Lead claim submitted",
        collaborator_id=collaborator.id,
        lead_id=lead.id,
        claim_id=claim.id,
    )

    return (lead, claim), None


async def review_lead_claim(
    db: AsyncSession,
    claim: models.LeadClaim,
    review_data: LeadClaimReview,
    reviewer: models.User,
) -> Tuple[models.LeadClaim, Optional[callable]]:
    """
    Review a lead claim (approve or reject).

    Approve: lead.validity_status = "valid"
    Reject: lead.referrer_id = NULL, validity_status stays "raw"
    """
    claim_repo = LeadClaimRepository(db)

    # Lock claim for update
    locked_claim = await claim_repo.get_by_id_for_update(claim.id)
    if not locked_claim:
        raise ResourceNotFoundError("Claim not found")

    if locked_claim.status != "pending":
        raise BusinessRuleViolation(
            f"Claim đã được xử lý (trạng thái: {locked_claim.status})"
        )

    # Get the lead
    lead = await db.get(models.Lead, locked_claim.lead_id)
    if not lead:
        raise ResourceNotFoundError("Lead not found")

    locked_claim.reviewed_by_id = reviewer.id
    locked_claim.reviewed_at = datetime.now(timezone.utc)

    if review_data.status == "approved":
        locked_claim.status = "approved"
        lead.validity_status = "valid"
        log.info(
            "Claim approved",
            claim_id=locked_claim.id,
            lead_id=lead.id,
            reviewer_id=reviewer.id,
        )
    else:
        locked_claim.status = "rejected"
        locked_claim.rejection_reason = review_data.rejection_reason

        # Remove CTV attribution
        lead.referrer_id = None
        # Keep validity_status as "raw" — admin sets "invalid" separately if needed

        # If lead was created via claim, change source to "other"
        if lead.created_via == "claim":
            lead.source = "other"

        log.info(
            "Claim rejected",
            claim_id=locked_claim.id,
            lead_id=lead.id,
            reviewer_id=reviewer.id,
            reason=review_data.rejection_reason,
        )

    await db.flush()
    return locked_claim, None


# ============================================================================
# LEAD VALIDITY
# ============================================================================


async def update_lead_validity(
    db: AsyncSession,
    lead: models.Lead,
    data: LeadValidityUpdate,
) -> Tuple[models.Lead, None]:
    """Update lead validity status (admin/manager only)."""
    lead.validity_status = data.validity_status
    lead.updated_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "Lead validity updated",
        lead_id=lead.id,
        validity_status=data.validity_status,
    )
    return lead, None


# ============================================================================
# PHONE CHECK
# ============================================================================


async def check_phone_available(
    db: AsyncSession,
    phone: str,
    collaborator_id: int,
) -> dict:
    """
    Check if a phone number is available for CTV to claim.

    Returns:
        {"available": bool, "message": str | None}
    """
    lead_repo = LeadRepository(db)

    existing = await lead_repo.get_by_phone(phone)
    if not existing:
        return {"available": True, "message": None}

    # Lead exists — check if claimable
    if existing.referrer_id:
        return {"available": False, "message": "Số điện thoại đã được CTV khác giới thiệu"}

    if existing.assigned_officer_id and existing.status not in CLAIMABLE_STATUSES:
        return {"available": False, "message": "Lead đang được tư vấn"}

    # Lead exists but is claimable
    return {"available": True, "message": "Lead đã tồn tại, sẽ được gán CTV khi claim"}
