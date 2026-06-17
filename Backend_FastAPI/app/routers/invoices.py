# app/routers/invoices.py
"""
Router for Invoice Management (Finance Module Phase 4).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- Transaction Management: Router calls db.commit() after service returns
- RBAC: All endpoints protected by CasbinAuth dependency
- Error Handling: Convert custom exceptions to HTTPException
- IDOR Protection: Unit-based access control via service layer

Endpoints:
- GET /api/invoices/{invoice_id} - Get invoice details with payments
- GET /api/invoices/by-fee/{fee_id} - Get all invoices for a fee
- PUT /api/invoices/{invoice_id}/issue - Issue invoice
- PUT /api/invoices/{invoice_id}/cancel - Cancel invoice
- POST /api/invoices/{invoice_id}/apply-penalty - Apply late payment penalty
"""

import base64
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models
from app.core.constants import UserRole
from app.core.deps import CasbinAuth, RequireManager, finance_scope_unit_id
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.models.finance import PAYABLE_INVOICE_STATUSES
from app.services.invoice_service import InvoiceService
from app.services.system_config_service import SystemConfigService
from app.repositories.fee_repository import InvoiceRepository
from app.utils.id_helpers import format_profile_code
from app.utils.text_helpers import to_bank_transfer_note
from app.utils.vietqr import build_vietqr_payload, render_qr_png
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/invoices", tags=["Finance - Invoices"])


# H1 cleanup (2026-05-14): the local ``def get_client_ip`` previously
# living here was dead code — never used as a slowapi ``key_func`` in
# this file. Canonical helper lives in ``app.core.client_ip``.


# ==============================================================================
# INVOICE LIST
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "",
    response_model=finance_schemas.InvoicesPage,
    summary="List invoices with pagination and filters",
)
async def list_invoices(
    request: Request,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    fee_id: Optional[int] = Query(None, description="Filter by fee ID"),
    overdue_only: Optional[bool] = Query(
        None, description="Filter only overdue invoices"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List invoices with pagination and filters.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'invoices:read' permission
    """
    invoice_repo = InvoiceRepository(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    # Convert page/page_size to skip/limit
    skip = (page - 1) * page_size
    limit = min(page_size, 100)

    # Parse comma-separated values
    statuses: Optional[List[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    invoices, total = await invoice_repo.get_filtered_with_count(
        skip=skip,
        limit=limit,
        unit_id=unit_id,
        statuses=statuses,
        fee_id=fee_id,
        overdue_only=overdue_only,
    )

    # Build response items with profile name and fee type
    items = []
    for invoice in invoices:
        profile_name = None
        fee_type = None

        # Get profile name and fee type from relationship
        if invoice.fee:
            fee_type = invoice.fee.fee_type
            if invoice.fee.admission_profile and invoice.fee.admission_profile.lead:
                profile_name = invoice.fee.admission_profile.lead.full_name

        items.append(finance_schemas.InvoiceListItem(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            installment_no=invoice.installment_no,
            amount=invoice.amount,
            paid_amount=invoice.paid_amount,
            remaining_amount=invoice.amount - invoice.paid_amount,
            due_date=invoice.due_date,
            status=invoice.status,
            profile_name=profile_name,
            fee_type=fee_type,
        ))

    return finance_schemas.InvoicesPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ==============================================================================
# INVOICE RETRIEVAL
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{invoice_id}",
    response_model=finance_schemas.InvoiceDetailResponse,
    summary="Get invoice details",
)
async def get_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get invoice details including payments.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'invoices:read' permission
    """
    invoice_service = InvoiceService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        invoice = await invoice_service.get_invoice(invoice_id, unit_id)

        return _build_invoice_detail_response(
            invoice, current_user_role=current_user.role
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/by-fee/{fee_id}",
    response_model=List[finance_schemas.InvoiceSummaryResponse],
    summary="Get all invoices for a fee",
)
async def get_invoices_by_fee(
    request: Request,
    fee_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get all invoices for a specific fee.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'invoices:read' permission
    """
    invoice_repo = InvoiceRepository(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    invoices = await invoice_repo.get_by_fee_id(fee_id, unit_id)

    return [
        finance_schemas.InvoiceSummaryResponse(
            id=inv.id,
            invoice_number=inv.invoice_number,
            installment_no=inv.installment_no,
            amount=inv.amount,
            paid_amount=inv.paid_amount,
            remaining_amount=inv.amount - inv.paid_amount,
            due_date=inv.due_date,
            status=inv.status,
        )
        for inv in invoices
    ]


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{invoice_id}/vietqr",
    response_model=finance_schemas.VietQRResponse,
    summary="Get VietQR transfer payload for an invoice",
)
async def get_invoice_vietqr(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get a VietQR code for offline bank transfer.

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires invoice read permission
    - Bank collection config is public collection information, not a secret
    """
    invoice_service = InvoiceService(db)
    config_service = SystemConfigService(db)
    unit_id = finance_scope_unit_id(current_user)

    try:
        invoice = await invoice_service.get_invoice(invoice_id, unit_id)

        # F3: only payable invoices may produce a transfer QR. A draft/cancelled
        # invoice can carry a positive remaining amount but cannot be paid through
        # normal payment recording, so a QR for it would mislead the applicant.
        # Mirror record_manual_payment's allowed statuses.
        if invoice.status not in PAYABLE_INVOICE_STATUSES:
            raise BadRequest(
                f"VietQR is only available for payable invoices "
                f"(issued/partial/overdue); current status: '{invoice.status}'"
            )

        bank_account = await config_service.get_value("bank_collection_account")
        if not isinstance(bank_account, dict):
            raise ResourceNotFoundError("Bank collection account is not configured")

        bank_bin = str(bank_account.get("bank_bin") or "").strip()
        account_number = str(bank_account.get("account_number") or "").strip()
        account_name = str(bank_account.get("account_name") or "").strip()
        if not bank_bin or not account_number or not account_name:
            raise ResourceNotFoundError("Bank collection account is not configured")

        fee = invoice.fee
        profile = fee.admission_profile if fee else None
        lead = profile.lead if profile and getattr(profile, "lead", None) else None
        profile_code = format_profile_code(profile.id) if profile else "HS-000000"
        raw_note = (
            f"{lead.full_name if lead else 'Unknown'} "
            f"{profile_code} thanh toan hoc phi"
        )
        content = to_bank_transfer_note(raw_note, max_len=90)
        # Quantize to whole VND (zero-decimal currency) so the QR-encoded amount
        # and the returned/displayed amount are identical — build_vietqr_payload
        # emits int(amount), so a fractional remaining would otherwise diverge.
        amount = invoice.remaining_amount.quantize(Decimal("1"))

        payload = build_vietqr_payload(
            bank_bin=bank_bin,
            account_number=account_number,
            account_name=to_bank_transfer_note(account_name, max_len=25),
            amount=amount,
            add_info=content,
        )
        qr_png = render_qr_png(payload)

        return finance_schemas.VietQRResponse(
            qr_payload=payload,
            qr_image_base64=base64.b64encode(qr_png).decode("ascii"),
            bank_account=finance_schemas.VietQRBankAccount(
                bank_bin=bank_bin,
                account_number=account_number,
                account_name=account_name,
            ),
            amount=amount,
            content=content,
        )

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except (BadRequest, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# INVOICE LIFECYCLE
# ==============================================================================

@limiter.limit(RateLimits.DATA_WRITE)
@router.put(
    "/{invoice_id}/issue",
    response_model=finance_schemas.InvoiceResponse,
    summary="Issue invoice",
)
async def issue_invoice(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Issue a draft invoice, making it payable.

    **Business Rules:**
    - Only draft invoices can be issued
    - Sets issued_at timestamp
    - Changes status from 'draft' to 'issued'

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'invoices:issue' permission
    """
    invoice_service = InvoiceService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        invoice, _ = await invoice_service.issue_invoice(
            invoice_id=invoice_id,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "invoice_issued_via_api",
            invoice_id=invoice_id,
            invoice_number=invoice.invoice_number,
            user_id=current_user.id,
        )

        await db.refresh(invoice)
        return _build_invoice_response(invoice, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.put(
    "/{invoice_id}/cancel",
    response_model=finance_schemas.InvoiceResponse,
    summary="Cancel invoice",
)
async def cancel_invoice(
    request: Request,
    invoice_id: int,
    reason: str = Query(
        ..., min_length=1, max_length=500, description="Cancellation reason"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireManager,
):
    """
    Cancel an invoice.

    **Business Rules:**
    - Cannot cancel if any payments exist
    - Requires manager or admin role
    - Reason is required for audit

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Role enforced via RequireManager dependency
    """
    invoice_service = InvoiceService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        invoice, _ = await invoice_service.cancel_invoice(
            invoice_id=invoice_id,
            reason=reason,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "invoice_cancelled_via_api",
            invoice_id=invoice_id,
            reason=reason,
            user_id=current_user.id,
        )

        await db.refresh(invoice)
        return _build_invoice_response(invoice, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/{invoice_id}/apply-penalty",
    response_model=finance_schemas.InvoiceResponse,
    summary="Apply late payment penalty",
)
async def apply_penalty(
    request: Request,
    invoice_id: int,
    penalty_amount: Optional[Decimal] = Query(
        None, gt=0, description="Penalty amount (auto-calculated if not provided)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireManager,
):
    """
    Apply late payment penalty to an overdue invoice.

    **Business Rules:**
    - Only applies to overdue invoices
    - If penalty_amount not provided, calculated based on installment plan penalty_rate
    - Requires manager or admin role

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Role enforced via RequireManager dependency
    """
    invoice_service = InvoiceService(db)
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id

    try:
        invoice, _ = await invoice_service.apply_penalty(
            invoice_id=invoice_id,
            penalty_amount=penalty_amount,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "penalty_applied_via_api",
            invoice_id=invoice_id,
            penalty_amount=str(invoice.penalty_amount),
            user_id=current_user.id,
        )

        await db.refresh(invoice)
        return _build_invoice_response(invoice, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _build_invoice_response(
    invoice, current_user_role: str = None
) -> finance_schemas.InvoiceResponse:
    """
    Build InvoiceResponse from Invoice model.

    Args:
        invoice: Invoice ORM model
        current_user_role: Current user's role for role-aware permission flags

    Permission Flags Logic (Role-Aware):
        - can_issue: status == 'draft' (any role with permission)
        - can_cancel: status not terminal AND paid == 0 AND role in [admin, manager]
        - can_record_payment: status == 'issued' AND remaining > 0 (any role)
        - can_apply_penalty: status == 'overdue' AND role in [admin, manager]
    """
    # P1: Compute permission flags based on status, amounts, AND role
    status_value = (
        invoice.status.value if hasattr(invoice.status, "value") else invoice.status
    )
    # QW-B fix #1: use the model's remaining_amount property (= amount +
    # penalty_amount - paid_amount) so the response is internally consistent
    # with total_due (= amount + penalty). The old `amount - paid_amount`
    # ignored penalty → contradicted total_due when penalty > 0.
    remaining_amount = invoice.remaining_amount

    # Role-aware permission computation
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]

    can_issue = status_value == "draft"
    can_cancel = (
        status_value not in ["paid", "cancelled"]
        and invoice.paid_amount == 0
        and is_manager_or_admin
    )
    can_record_payment = status_value == "issued" and remaining_amount > 0
    can_apply_penalty = status_value == "overdue" and is_manager_or_admin

    return finance_schemas.InvoiceResponse(
        id=invoice.id,
        fee_id=invoice.fee_id,
        invoice_number=invoice.invoice_number,
        installment_no=invoice.installment_no,
        amount=invoice.amount,
        due_date=invoice.due_date,
        status=invoice.status,
        paid_amount=invoice.paid_amount,
        remaining_amount=remaining_amount,
        # QW-B fix #1: these are now REQUIRED on InvoiceResponse. This builder
        # constructs the schema by explicit kwargs (NOT model_validate), so
        # from_attributes does NOT fill them → must pass explicitly or every
        # invoice endpoint 500s.
        penalty_amount=invoice.penalty_amount,
        total_due=invoice.total_due,
        issued_at=invoice.issued_at,
        paid_at=invoice.paid_at,
        cancelled_at=invoice.cancelled_at,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at,
        # P1: Permission flags
        can_issue=can_issue,
        can_cancel=can_cancel,
        can_record_payment=can_record_payment,
        can_apply_penalty=can_apply_penalty,
    )


def _build_invoice_detail_response(
    invoice, current_user_role: str = None
) -> finance_schemas.InvoiceDetailResponse:
    """Build InvoiceDetailResponse from Invoice model with payments."""
    base_response = _build_invoice_response(
        invoice, current_user_role=current_user_role
    )

    payment_summaries = [
        finance_schemas.PaymentSummaryResponse(
            id=p.id,
            invoice_id=p.invoice_id,
            amount=p.amount,
            status=p.status,
            payment_date=p.payment_date,
            created_at=p.created_at,
        )
        for p in invoice.payments
    ]

    fee_summary = None
    if invoice.fee:
        fee = invoice.fee
        fee_summary = finance_schemas.FeeSummaryResponse(
            id=fee.id,
            fee_type=fee.fee_type,
            academic_year=f"{fee.academic_year}-{fee.academic_year + 1}",
            final_amount=fee.final_amount,
            paid_amount=fee.paid_amount,
            remaining_amount=fee.remaining_amount,
            status=fee.status,
        )

    return finance_schemas.InvoiceDetailResponse(
        **base_response.model_dump(),
        payments=payment_summaries,
        fee=fee_summary,
    )
