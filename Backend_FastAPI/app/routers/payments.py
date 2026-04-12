# app/routers/payments.py
"""
Router for Payment Management (Finance Module Phase 4).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- Transaction Management: Router calls db.commit() after service returns
- RBAC: All endpoints protected by CasbinAuth dependency
- Error Handling: Convert custom exceptions to HTTPException
- IDOR Protection: Unit-based access control via service layer

Payment Flows:
1. Manual Payment (bank transfer, cash):
   - POST /api/payments - Record payment (officer)
   - PUT /api/payments/{id}/verify - Verify payment (manager/admin)
   - PUT /api/payments/{id}/reject - Reject payment (manager/admin)

2. Online Payment (VNPay, MoMo):
   - POST /api/payments/intents - Create payment intent
   - GET /api/payments/intents/{id} - Get intent status
   - POST /api/payments/callback/{gateway} - Gateway callback (IPN)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models, schemas
from app.core import deps
from app.core.constants import UserRole
from app.core.deps import CasbinAuth
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.services.payment_service import PaymentService
from app.services.payment_intent_service import PaymentIntentService
from app.repositories.payment_repository import PaymentRepository
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/payments", tags=["Finance - Payments"])


# ==============================================================================
# PAYMENT LIST
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "",
    response_model=finance_schemas.PaymentsPage,
    summary="List payments with pagination and filters",
)
async def list_payments(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(None, description="Filter by status (comma-separated)"),
    invoice_id: Optional[int] = Query(None, description="Filter by invoice ID"),
    method_id: Optional[int] = Query(None, description="Filter by payment method ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List payments with pagination and filters.

    **Common Filters:**
    - status=pending: For verification queue (Checker workflow)
    - status=verified: For verified payments
    - status=rejected: For rejected payments

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:read' permission
    """
    payment_repo = PaymentRepository(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    # Convert page/page_size to skip/limit
    skip = (page - 1) * page_size
    limit = min(page_size, 100)

    # Parse comma-separated values
    statuses: Optional[List[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    payments, total = await payment_repo.get_filtered_with_count(
        skip=skip,
        limit=limit,
        unit_id=unit_id,
        statuses=statuses,
        invoice_id=invoice_id,
        method_id=method_id,
    )

    # Build response items with profile name and method name
    items = []
    for payment in payments:
        profile_name = None
        method_name = None
        created_by_name = None

        # Get profile name from relationship
        if payment.invoice and payment.invoice.fee:
            fee = payment.invoice.fee
            if fee.admission_profile and fee.admission_profile.lead:
                profile_name = fee.admission_profile.lead.full_name

        # Get method name from relationship
        if payment.method:
            method_name = payment.method.name

        # Get creator name from relationship
        if payment.created_by:
            created_by_name = payment.created_by.full_name or payment.created_by.email

        # Compute permission flags for maker-checker
        status_value = payment.status.value if hasattr(payment.status, "value") else payment.status
        is_pending = status_value == "pending"
        is_different_user = payment.created_by_id != current_user.id
        is_manager_or_admin = current_user.role in [UserRole.ADMIN, UserRole.MANAGER]
        can_verify = is_pending and is_different_user and is_manager_or_admin
        can_reject = is_pending and is_different_user and is_manager_or_admin

        items.append(finance_schemas.PaymentListItem(
            id=payment.id,
            invoice_id=payment.invoice_id,
            amount=payment.amount,
            status=payment.status,
            payment_date=payment.payment_date,
            created_at=payment.created_at,
            profile_name=profile_name,
            method_name=method_name,
            created_by_name=created_by_name,
            can_verify=can_verify,
            can_reject=can_reject,
        ))

    return finance_schemas.PaymentsPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ==============================================================================
# MANUAL PAYMENT FLOW
# ==============================================================================

@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "",
    response_model=finance_schemas.PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record manual payment",
)
async def record_payment(
    request: Request,
    data: finance_schemas.PaymentCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Record a manual payment (bank transfer, cash).

    **Business Rules:**
    - Payment goes to 'pending' status awaiting verification
    - Maker-checker: Different user must verify
    - Amount cannot exceed invoice remaining balance

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:create' permission
    """
    payment_service = PaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        payment, callback = await payment_service.record_manual_payment(
            invoice_id=data.invoice_id,
            method_id=data.method_id,
            amount=data.amount,
            user_id=current_user.id,
            payment_date=data.payment_date or datetime.now(timezone.utc),
            reference_code=data.reference_code,
            payer_name=data.payer_name,
            payer_account=data.payer_account,
            notes=data.notes,
            unit_id=unit_id,
        )

        await db.commit()
        if callback:
            await callback()

        log.info(
            "manual_payment_recorded",
            payment_id=payment.id,
            invoice_id=data.invoice_id,
            amount=str(data.amount),
            user_id=current_user.id,
        )

        # Reload with relationships for P2 denormalized names
        payment_repo = PaymentRepository(db)
        payment = await payment_repo.get_by_id_with_relations(payment.id, unit_id)
        return _build_payment_response(
            payment,
            current_user_id=current_user.id,
            current_user_role=current_user.role,
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.put(
    "/{payment_id}/verify",
    response_model=finance_schemas.PaymentResponse,
    summary="Verify payment",
)
async def verify_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Verify a pending manual payment.

    **Business Rules:**
    - Maker-checker: Verifier must be different from creator (C3)
    - Only pending payments can be verified
    - Updates invoice and fee paid amounts

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:verify' permission (Casbin RBAC)
    """
    payment_service = PaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        payment, callback = await payment_service.verify_payment(
            payment_id=payment_id,
            verifier_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()
        if callback:
            await callback()

        log.info(
            "payment_verified",
            payment_id=payment_id,
            verifier_id=current_user.id,
        )

        # Reload with relationships for P2 denormalized names
        payment_repo = PaymentRepository(db)
        payment = await payment_repo.get_by_id_with_relations(payment_id, unit_id)
        return _build_payment_response(
            payment,
            current_user_id=current_user.id,
            current_user_role=current_user.role,
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.put(
    "/{payment_id}/reject",
    response_model=finance_schemas.PaymentResponse,
    summary="Reject payment",
)
async def reject_payment(
    request: Request,
    payment_id: int,
    reason: str = Query(..., min_length=1, max_length=500, description="Rejection reason"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Reject a pending manual payment.

    **Business Rules:**
    - Only pending payments can be rejected
    - Reason is required for audit
    - Does not affect invoice/fee paid amounts

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:reject' permission (Casbin RBAC)
    """
    payment_service = PaymentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        payment, callback = await payment_service.reject_payment(
            payment_id=payment_id,
            rejector_id=current_user.id,
            reason=reason,
            unit_id=unit_id,
        )

        await db.commit()
        if callback:
            await callback()

        log.info(
            "payment_rejected",
            payment_id=payment_id,
            reason=reason,
            rejector_id=current_user.id,
        )

        # Reload with relationships for P2 denormalized names
        payment_repo = PaymentRepository(db)
        payment = await payment_repo.get_by_id_with_relations(payment_id, unit_id)
        return _build_payment_response(
            payment,
            current_user_id=current_user.id,
            current_user_role=current_user.role,
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# PAYMENT METHODS (must be before /{payment_id} to avoid route conflict)
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/methods",
    response_model=List[finance_schemas.PaymentMethodResponse],
    summary="Get available payment methods",
)
async def get_payment_methods(
    request: Request,
    is_online: Optional[bool] = Query(None, description="Filter by online/offline"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get list of available payment methods.

    **Security:**
    - Requires authentication
    - No IDOR check (payment methods are global)
    """
    payment_repo = PaymentRepository(db)

    methods = await payment_repo.get_active_payment_methods(is_online=is_online)

    return [
        finance_schemas.PaymentMethodResponse(
            id=m.id,
            code=m.code,
            name=m.name,
            is_online=m.is_online,
            requires_verification=m.requires_verification,
            gateway_code=m.gateway_code,
            display_order=m.display_order,
            is_active=m.is_active,
            created_at=m.created_at,
        )
        for m in methods
    ]


# ==============================================================================
# PAYMENTS BY INVOICE (must be before /{payment_id} to avoid route conflict)
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/by-invoice/{invoice_id}",
    response_model=List[finance_schemas.PaymentSummaryResponse],
    summary="Get payments for invoice",
)
async def get_payments_by_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get all payments for an invoice.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:read' permission
    """
    payment_repo = PaymentRepository(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    payments = await payment_repo.get_by_invoice_id(invoice_id, unit_id)

    return [
        finance_schemas.PaymentSummaryResponse(
            id=p.id,
            invoice_id=p.invoice_id,
            amount=p.amount,
            status=p.status,
            payment_date=p.payment_date,
            created_at=p.created_at,
        )
        for p in payments
    ]


# ==============================================================================
# PAYMENT DETAIL
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{payment_id}",
    response_model=finance_schemas.PaymentResponse,
    summary="Get payment details",
)
async def get_payment(
    request: Request,
    payment_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get payment details.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:read' permission
    """
    payment_repo = PaymentRepository(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    # Use get_by_id_with_relations to load user relationships for P2 denormalized names
    payment = await payment_repo.get_by_id_with_relations(payment_id, unit_id)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    return _build_payment_response(
            payment,
            current_user_id=current_user.id,
            current_user_role=current_user.role,
        )


# ==============================================================================
# ONLINE PAYMENT FLOW (Payment Intents)
# ==============================================================================

@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/intents",
    response_model=finance_schemas.PaymentIntentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create payment intent",
)
async def create_payment_intent(
    request: Request,
    data: finance_schemas.PaymentIntentCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Create a payment intent for online payment.

    **Flow:**
    1. Create intent with gateway
    2. Return pay_url for redirect
    3. User completes payment on gateway
    4. Gateway sends callback to /callback/{gateway}

    **Idempotency:**
    - Same idempotency_key returns existing intent

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:create' permission
    """
    intent_service = PaymentIntentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        intent, is_existing = await intent_service.create_or_get_intent(
            invoice_id=data.invoice_id,
            method_id=data.method_id,
            amount=data.amount,
            idempotency_key=data.idempotency_key,
            return_url=data.return_url,
            unit_id=unit_id,
        )

        if not is_existing:
            await db.commit()

            log.info(
                "payment_intent_created",
                intent_id=intent.id,
                invoice_id=data.invoice_id,
                amount=str(data.amount),
                idempotency_key=data.idempotency_key,
            )

        return _build_intent_response(intent)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/intents/{intent_id}",
    response_model=finance_schemas.PaymentIntentResponse,
    summary="Get payment intent status",
)
async def get_payment_intent(
    request: Request,
    intent_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get payment intent status.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:read' permission
    """
    intent_service = PaymentIntentService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        intent = await intent_service.get_intent(intent_id, unit_id)
        await db.commit()  # Persist auto-expire status change if any
        return _build_intent_response(intent)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/callback/{gateway_code}",
    summary="Gateway callback (IPN)",
)
async def payment_callback(
    request: Request,
    gateway_code: str,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Handle payment gateway callback (IPN).

    **Important:**
    - Always returns 200 OK to prevent retry storms
    - Verifies gateway signature before processing
    - Creates payment record on success

    **Security:**
    - No auth required (gateway callback)
    - Signature verification for authenticity
    """
    # Parse callback data from request
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        callback_data = await request.json()
    else:
        # Form data (VNPay style)
        form = await request.form()
        callback_data = dict(form)

    log.info(
        "payment_callback_received",
        gateway_code=gateway_code,
        callback_data=callback_data,
    )

    intent_service = PaymentIntentService(db)

    try:
        # Process callback (verify signature, create payment).
        # process_gateway_callback returns (result_dict, post_commit_callback).
        # The callback carries the PAYMENT_VERIFIED dispatch — we MUST await
        # it after db.commit(), otherwise the notification is silently lost.
        result, callback = await intent_service.process_gateway_callback(
            gateway_code=gateway_code,
            callback_data=callback_data,
        )

        await db.commit()

        if callback is not None:
            await callback()

        log.info(
            "payment_callback_processed",
            gateway_code=gateway_code,
            success=result.get("success", False),
            intent_id=result.get("intent_id"),
        )

        # Always return 200 to gateway
        return {"status": "ok", "message": result.get("message", "Processed")}

    except Exception as e:
        # Log error but still return 200 to prevent retry storms
        log.error(
            "payment_callback_error",
            gateway_code=gateway_code,
            error=str(e),
        )
        await db.rollback()
        return {"status": "error", "message": "Processing failed, will retry"}


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _build_payment_response(
    payment,
    current_user_id: Optional[int] = None,
    current_user_role: str = None,
) -> finance_schemas.PaymentResponse:
    """
    Build PaymentResponse from Payment model.

    Args:
        payment: Payment ORM model (with relationships loaded)
        current_user_id: Current user's ID for permission flag computation
        current_user_role: Current user's role for role-aware permission flags

    Permission Flags (Maker-Checker + Role-Aware):
        - can_verify: pending AND different_user AND role in [admin, manager]
        - can_reject: pending AND different_user AND role in [admin, manager]

    Denormalized Names (P2):
        - Extracted from payment.created_by and payment.verified_by relationships
    """
    # P1: Compute permission flags based on maker-checker rule AND role
    status_value = payment.status.value if hasattr(payment.status, "value") else payment.status
    is_pending = status_value == "pending"
    is_different_user = current_user_id is not None and payment.created_by_id != current_user_id

    # Role-aware permission computation
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]

    can_verify = is_pending and is_different_user and is_manager_or_admin
    can_reject = is_pending and is_different_user and is_manager_or_admin

    # P2: Extract denormalized user names from relationships
    created_by_name = None
    verified_by_name = None

    # Try to get creator name from relationship
    if hasattr(payment, "created_by") and payment.created_by is not None:
        created_by_name = payment.created_by.full_name or payment.created_by.email

    # Try to get verifier name from relationship
    if hasattr(payment, "verified_by") and payment.verified_by is not None:
        verified_by_name = payment.verified_by.full_name or payment.verified_by.email

    return finance_schemas.PaymentResponse(
        id=payment.id,
        invoice_id=payment.invoice_id,
        method_id=payment.method_id,
        intent_id=payment.intent_id,
        amount=payment.amount,
        status=payment.status,
        reference_code=payment.reference_code,
        payer_name=payment.payer_name,
        payment_date=payment.payment_date,
        verified_at=payment.verified_at,
        rejected_at=payment.rejected_at,
        created_by_id=payment.created_by_id,
        verified_by_id=payment.verified_by_id,
        rejection_reason=payment.rejection_reason,
        notes=payment.notes,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        # P1: Permission flags
        can_verify=can_verify,
        can_reject=can_reject,
        # P2: Denormalized names
        created_by_name=created_by_name,
        verified_by_name=verified_by_name,
    )


def _build_intent_response(intent) -> finance_schemas.PaymentIntentResponse:
    """Build PaymentIntentResponse from PaymentIntent model."""
    return finance_schemas.PaymentIntentResponse(
        id=intent.id,
        invoice_id=intent.invoice_id,
        method_id=intent.method_id,
        amount=intent.amount,
        currency=intent.currency,
        status=intent.status,
        gateway_ref=intent.gateway_ref,
        gateway_status=intent.gateway_status,
        pay_url=intent.pay_url,
        expires_at=intent.expires_at,
        created_at=intent.created_at,
    )
