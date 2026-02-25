# app/routers/collaborators.py
"""
Collaborator (CTV) Router - Phase 1

Two separate routers:
- admin_router: Admin/Manager endpoints for CTV management
- ctv_router: CTV self-service endpoints
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.constants import UserRole
from app.core.deps import (
    check_permission,
    get_collaborator_for_user,
    get_lead_claim_for_review,
    get_own_collaborator,
    require_admin_or_manager,
)
from app.repositories.collaborator_repository import CollaboratorRepository
from app.repositories.lead_claim_repository import LeadClaimRepository
from app.repositories.lead_repository import LeadRepository
from app.schemas.collaborator import (
    CollaboratorApproveResponse,
    CollaboratorCreate,
    CollaboratorListItem,
    CollaboratorResponse,
    CollaboratorShallow,
    CollaboratorsPage,
    CollaboratorStats,
    CollaboratorUpdate,
    CTVRegistrationResponse,
    CTVRegistrationStatus,
    CTVSelfRegistration,
    LeadClaimCreate,
    LeadClaimResponse,
    LeadClaimReview,
    LeadClaimsPage,
    LeadForCTV,
    LeadForCTVPage,
    PhoneCheckResponse,
)
from app.core.events import SystemEvents
from app.core.rate_limits import limiter, RateLimits
from app.services import collaborator_service
from app.services.notification_dispatcher import safe_dispatch
from app.utils.exceptions import ResourceNotFoundError

# ============================================================================
# ADMIN/MANAGER ROUTER
# ============================================================================

admin_router = APIRouter(prefix="/collaborators", tags=["Collaborators (Admin)"])


@admin_router.get("", response_model=CollaboratorsPage)
async def list_collaborators(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    unit_id: Optional[int] = None,
    managed_by_officer_id: Optional[int] = None,
    search: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc",
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(check_permission),
):
    """List collaborators with filters."""
    repo = CollaboratorRepository(db)

    # Manager: force own unit filter
    if current_user.role == UserRole.MANAGER:
        unit_id = current_user.unit_id

    # Officer: force own managed CTV only + active status
    if current_user.role == UserRole.OFFICER:
        managed_by_officer_id = current_user.id
        status = "active"

    total, collaborators = await repo.get_filtered(
        skip=skip,
        limit=limit,
        status=status,
        unit_id=unit_id,
        managed_by_officer_id=managed_by_officer_id,
        search=search,
        sort_by=sort_by,
        order=order,
    )
    return CollaboratorsPage(total_count=total, collaborators=collaborators)


@admin_router.post("", response_model=CollaboratorResponse, status_code=201)
async def create_collaborator(
    data: CollaboratorCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Create a new collaborator."""
    collab, callback = await collaborator_service.create_collaborator(
        db, data, current_user
    )
    await db.commit()
    if callback:
        await callback()

    # Reload with relationships
    repo = CollaboratorRepository(db)
    collab = await repo.get_by_id(collab.id)
    return collab


# ⚠️ ROUTE ORDERING: Static routes (/claims) MUST be declared BEFORE parameterized (/{id})


@admin_router.get("/claims", response_model=LeadClaimsPage)
async def list_claims(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    collaborator_id: Optional[int] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(check_permission),
):
    """List all lead claims."""
    # Defensive: Officers should not access claims list (Casbin already blocks, but defense-in-depth)
    if current_user.role == UserRole.OFFICER:
        raise ResourceNotFoundError("Not found")

    repo = LeadClaimRepository(db)

    # Manager: filter by own unit
    unit_id = None
    if current_user.role == UserRole.MANAGER:
        unit_id = current_user.unit_id

    total, claims = await repo.get_filtered(
        skip=skip,
        limit=limit,
        status=status,
        collaborator_id=collaborator_id,
        unit_id=unit_id,
    )

    # Build response with masked lead data
    claim_responses = []
    for claim in claims:
        claim_resp = _build_claim_response(claim)
        claim_responses.append(claim_resp)

    return LeadClaimsPage(total_count=total, claims=claim_responses)


@admin_router.get("/claims/{claim_id}", response_model=LeadClaimResponse)
async def get_claim_detail(
    claim: models.LeadClaim = Depends(get_lead_claim_for_review),
):
    """Get claim detail with IDOR protection."""
    return _build_claim_response(claim)


@admin_router.post("/claims/{claim_id}/review", response_model=LeadClaimResponse)
async def review_claim(
    review_data: LeadClaimReview,
    claim: models.LeadClaim = Depends(get_lead_claim_for_review),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Review a lead claim (approve/reject)."""
    updated_claim, callback = await collaborator_service.review_lead_claim(
        db, claim, review_data, current_user
    )
    await db.commit()
    if callback:
        await callback()

    # Dispatch notification to CTV
    ctv_user_id = claim.collaborator.user_id if claim.collaborator else None
    if review_data.status == "approved":
        await safe_dispatch(
            db=db,
            event=SystemEvents.CTV_CLAIM_APPROVED,
            payload={
                "collaborator_id": claim.collaborator_id,
                "claim_id": claim.id,
                "lead_id": claim.lead_id,
                "user_id": ctv_user_id,
                "actor_id": current_user.id,
            },
            dedupe_key=f"ctv_claim_approved:{claim.id}",
        )
    else:
        await safe_dispatch(
            db=db,
            event=SystemEvents.CTV_CLAIM_REJECTED,
            payload={
                "collaborator_id": claim.collaborator_id,
                "claim_id": claim.id,
                "lead_id": claim.lead_id,
                "rejection_reason": review_data.rejection_reason or "Không rõ lý do",
                "user_id": ctv_user_id,
                "actor_id": current_user.id,
            },
            dedupe_key=f"ctv_claim_rejected:{claim.id}",
        )

    # Reload for response
    claim_repo = LeadClaimRepository(db)
    reloaded = await claim_repo.get_by_id(updated_claim.id)
    return _build_claim_response(reloaded)


@admin_router.get("/{collaborator_id}", response_model=CollaboratorResponse)
async def get_collaborator(
    collaborator: models.Collaborator = Depends(get_collaborator_for_user),
):
    """Get collaborator detail with IDOR protection."""
    return collaborator


@admin_router.put("/{collaborator_id}", response_model=CollaboratorResponse)
async def update_collaborator_endpoint(
    data: CollaboratorUpdate,
    collaborator: models.Collaborator = Depends(get_collaborator_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Update a collaborator."""
    updated, callback = await collaborator_service.update_collaborator(
        db, collaborator, data
    )
    await db.commit()
    if callback:
        await callback()

    # Reload with relationships
    repo = CollaboratorRepository(db)
    updated = await repo.get_by_id(updated.id)
    return updated


@admin_router.post("/{collaborator_id}/approve", response_model=CollaboratorApproveResponse)
async def approve_collaborator_endpoint(
    request: Request,
    collaborator: models.Collaborator = Depends(get_collaborator_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Approve a pending collaborator. Auto-creates User account if needed."""
    enforcer = getattr(request.app.state, "enforcer", None)
    approved, temp_password = await collaborator_service.approve_collaborator(
        db, collaborator, current_user, enforcer=enforcer
    )
    await db.commit()

    # Dispatch notification (user_id is always set after approve now)
    if approved.user_id:
        await safe_dispatch(
            db=db,
            event=SystemEvents.CTV_APPROVED,
            payload={
                "collaborator_id": approved.id,
                "user_id": approved.user_id,
                "actor_id": current_user.id,
            },
            dedupe_key=f"ctv_approved:{approved.id}",
        )

    # Reload with relationships
    repo = CollaboratorRepository(db)
    approved = await repo.get_by_id(approved.id)

    account_created = temp_password is not None
    return CollaboratorApproveResponse(
        collaborator=approved,
        account_created=account_created,
        username=approved.phone if account_created else None,
        temp_password=temp_password,
        message="Đã duyệt CTV. Tài khoản đăng nhập đã được tạo tự động." if account_created
        else "Đã duyệt CTV.",
    )


@admin_router.post("/{collaborator_id}/reactivate", response_model=CollaboratorResponse)
async def reactivate_collaborator_endpoint(
    collaborator: models.Collaborator = Depends(get_collaborator_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Reactivate a suspended collaborator."""
    reactivated, _ = await collaborator_service.reactivate_collaborator(
        db, collaborator, current_user
    )
    await db.commit()

    repo = CollaboratorRepository(db)
    reactivated = await repo.get_by_id(reactivated.id)
    return reactivated


@admin_router.post("/{collaborator_id}/suspend", response_model=CollaboratorResponse)
async def suspend_collaborator_endpoint(
    collaborator: models.Collaborator = Depends(get_collaborator_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
):
    """Suspend an active collaborator."""
    suspended, _ = await collaborator_service.suspend_collaborator(db, collaborator)
    await db.commit()

    if collaborator.user_id:
        await safe_dispatch(
            db=db,
            event=SystemEvents.CTV_SUSPENDED,
            payload={
                "collaborator_id": collaborator.id,
                "user_id": collaborator.user_id,
                "actor_id": current_user.id,
            },
            dedupe_key=f"ctv_suspended:{collaborator.id}",
        )

    repo = CollaboratorRepository(db)
    suspended = await repo.get_by_id(suspended.id)
    return suspended


# ============================================================================
# CTV SELF-SERVICE ROUTER
# ============================================================================

ctv_router = APIRouter(prefix="/ctv", tags=["CTV Self-Service"])


@ctv_router.get("/profile", response_model=CollaboratorResponse)
async def get_own_profile(
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """Get own CTV profile."""
    return collaborator


@ctv_router.get("/leads", response_model=LeadForCTVPage)
async def list_own_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """List own referred leads (LeadForCTV schema, NO unit filter — EC-5)."""
    lead_repo = LeadRepository(db)
    total, leads = await lead_repo.get_leads_by_referrer(
        referrer_id=collaborator.id,
        skip=skip,
        limit=limit,
    )

    leads_response = [
        LeadForCTV(
            id=lead.id,
            full_name=lead.full_name,
            phone_masked=collaborator_service.mask_phone(lead.phone),
            status=lead.status,
            validity_status=lead.validity_status,
            created_at=lead.created_at,
        )
        for lead in leads
    ]

    return {"total_count": total, "leads": leads_response}


@ctv_router.post("/leads/submit", response_model=LeadClaimResponse, status_code=201)
@limiter.limit("10/minute")
async def submit_lead(
    request: Request,
    claim_data: LeadClaimCreate,
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """Submit a new lead (claim workflow)."""
    (lead, claim), callback = await collaborator_service.submit_lead_claim(
        db, collaborator, claim_data
    )
    await db.commit()
    if callback:
        await callback()

    # Dispatch notification
    await safe_dispatch(
        db=db,
        event=SystemEvents.CTV_CLAIM_SUBMITTED,
        payload={
            "collaborator_id": collaborator.id,
            "claim_id": claim.id,
            "lead_id": lead.id,
            "unit_id": collaborator.unit_id,
            "collaborator_name": collaborator.full_name,
            "lead_name": lead.full_name or f"Lead #{lead.id}",
            "actor_id": collaborator.user_id or 0,
        },
        dedupe_key=f"ctv_claim_submitted:{claim.id}",
    )

    # Reload for response
    claim_repo = LeadClaimRepository(db)
    reloaded = await claim_repo.get_by_id(claim.id)
    return _build_claim_response(reloaded)


@ctv_router.get("/leads/check-phone", response_model=PhoneCheckResponse)
@limiter.limit("30/minute")
async def check_phone(
    request: Request,
    phone: str = Query(..., min_length=1),
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """Check if phone number is available for claim."""
    result = await collaborator_service.check_phone_available(db, phone)
    return result


@ctv_router.get("/claims", response_model=LeadClaimsPage)
async def list_own_claims(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """List own claims."""
    claim_repo = LeadClaimRepository(db)
    total, claims = await claim_repo.get_claims_by_collaborator(
        collaborator_id=collaborator.id,
        skip=skip,
        limit=limit,
    )

    claim_responses = [_build_claim_response(c) for c in claims]
    return LeadClaimsPage(total_count=total, claims=claim_responses)


@ctv_router.get("/stats", response_model=CollaboratorStats)
async def get_own_stats(
    db: AsyncSession = Depends(database.get_db),
    collaborator: models.Collaborator = Depends(get_own_collaborator),
):
    """Get own performance stats."""
    stats = await collaborator_service.get_collaborator_stats(db, collaborator.id)
    return stats


# ============================================================================
# HELPER
# ============================================================================


def _build_claim_response(claim: models.LeadClaim) -> LeadClaimResponse:
    """Build LeadClaimResponse with masked lead data for CTV."""
    lead_for_ctv = None
    if claim.lead:
        lead_for_ctv = LeadForCTV(
            id=claim.lead.id,
            full_name=claim.lead.full_name,
            phone_masked=collaborator_service.mask_phone(claim.lead.phone),
            status=claim.lead.status,
            validity_status=claim.lead.validity_status,
            created_at=claim.lead.created_at,
        )

    collaborator_shallow = None
    if claim.collaborator:
        collaborator_shallow = CollaboratorShallow(
            id=claim.collaborator.id,
            code=claim.collaborator.code,
            full_name=claim.collaborator.full_name,
            phone=claim.collaborator.phone,
        )

    return LeadClaimResponse(
        id=claim.id,
        collaborator_id=claim.collaborator_id,
        lead_id=claim.lead_id,
        status=claim.status,
        claim_data=claim.claim_data,
        reviewed_by_id=claim.reviewed_by_id,
        reviewed_at=claim.reviewed_at,
        rejection_reason=claim.rejection_reason,
        created_at=claim.created_at,
        lead=lead_for_ctv,
        collaborator=collaborator_shallow,
    )


# ============================================================================
# PUBLIC ROUTER — CTV Self-Registration (no auth required)
# ============================================================================

public_router = APIRouter(prefix="/ctv-register", tags=["CTV Registration (Public)"])


@public_router.post("", response_model=CTVRegistrationResponse, status_code=201)
@limiter.limit("5/hour")
async def register_ctv(
    request: Request,
    data: CTVSelfRegistration,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Public CTV self-registration.
    Rate limited: 5 per hour per IP.
    Creates a pending collaborator awaiting admin approval.
    Returns only safe fields (code, status, message) — no PII.
    """
    collab, _ = await collaborator_service.register_ctv(db, data)
    await db.commit()

    return CTVRegistrationResponse(
        code=collab.code,
        status=collab.status,
        message="Đăng ký thành công. Tài khoản đang chờ admin duyệt.",
    )


@public_router.get("/status", response_model=CTVRegistrationStatus)
@limiter.limit("10/minute")
async def check_registration_status(
    request: Request,
    phone: str = Query(..., min_length=1),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Check CTV registration status by phone number.
    Rate limited: 10 per minute per IP.
    Only returns status + message (no sensitive data).
    """
    result = await collaborator_service.get_ctv_registration_status(db, phone)
    return result
