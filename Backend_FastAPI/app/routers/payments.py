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

import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional
from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models, schemas
from app.core import deps
from app.core.constants import UserRole
from app.core.deps import CasbinAuth, finance_scope_unit_id, require_finance_staff
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.services.payment_service import PaymentService
from app.services.payment_intent_service import PaymentIntentService
from app.services import payment_import_service
from app.repositories.payment_repository import PaymentRepository
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
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
    pending_manual_only: bool = Query(
        False,
        description="Maker-checker queue: only manual payments (intent_id IS "
        "NULL) awaiting verification. Online/gateway payments auto-verify and "
        "must NOT appear here. Ignores status/method_id when set.",
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List payments with pagination and filters.

    **Common Filters:**
    - pending_manual_only=true: maker-checker verification queue (manual,
      intent_id IS NULL only — never online/auto-verified payments)
    - status=verified: For verified payments
    - status=rejected: For rejected payments

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'payments:read' permission
    """
    payment_repo = PaymentRepository(db)
    unit_id = finance_scope_unit_id(current_user)

    # Convert page/page_size to skip/limit
    skip = (page - 1) * page_size
    limit = min(page_size, 100)

    if pending_manual_only:
        # Maker-checker queue: status=pending AND intent_id IS NULL, oldest-first.
        # This is the ONLY path that guarantees online (gateway, auto-verified)
        # payments never reach the manual verification queue — do NOT emulate it
        # with a generic status=pending filter, which would also surface a
        # pending online payment.
        payments, total = await payment_repo.get_pending_verification(
            unit_id=unit_id,
            skip=skip,
            limit=limit,
        )
    else:
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

    items = [
        _build_payment_list_item(payment, current_user.id, current_user.role)
        for payment in payments
    ]

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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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
            description=m.description,
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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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

    # PR1 Commit 5: do NOT log the raw, UNVERIFIED callback_data — it is
    # attacker-influenced (public IPN endpoint) and may carry sensitive gateway
    # fields or log-injection payloads. Signature verification + detailed
    # logging happen inside the service after verify.
    log.info(
        "payment_callback_received",
        gateway_code=gateway_code,
        content_type=content_type,
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
# BULK PAYMENT IMPORT (auto-verify) — BV-2: template + preview (read-only)
# ==============================================================================

# Giới hạn kích thước file import (chống nuốt RAM / DoS); 5000 dòng × vài cột.
_MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024  # 8 MB


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/import/template",
    summary="Tải file mẫu import thu học phí hàng loạt",
)
async def download_payment_import_template(
    request: Request,
    format: str = Query("xlsx", description="Định dạng: xlsx (khuyến nghị) hoặc csv"),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """File mẫu để kế toán điền số tiền đã thu offline → import tự xác minh.

    Cấp batch (chọn khi import, KHÔNG có trong file): **Năm học + Học kỳ**.
    Cột: Số CCCD · Họ và tên · Số tiền thu (VNĐ) · Ngày thu (dd/mm/yyyy) · Hình thức
    (TM/CK) · Mã tham chiếu (tùy chọn) · Ghi chú (tùy chọn). Cột CCCD + Mã tham chiếu
    định dạng TEXT để giữ số 0 đầu. Gate: Casbin (route grant) + finance staff.

    Sinh file ở service (``build_template``) — router chỉ stream (CLAUDE.md rule 1).
    """
    content, media_type, filename = payment_import_service.build_template(format)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/import/preview",
    response_model=finance_schemas.PaymentImportPreviewOut,
    summary="Xem trước (dry-run) import thu học phí hàng loạt — KHÔNG ghi tiền",
)
async def preview_payment_import(
    request: Request,
    file: UploadFile = File(..., description="File .xlsx/.csv theo mẫu"),
    academic_year: int = Form(
        ..., ge=2020, le=2100, description="Năm học (cấp batch)"
    ),
    semester_no: int = Form(
        ..., ge=1, le=12, description="Học kỳ (cấp batch, 1..12)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """Pha 1: đối chiếu từng dòng (CCCD → hồ sơ → học phí → đợt FIFO) READ-ONLY.

    Tạo 1 lô ``preview`` (chống re-import qua file_sha256) và trả về phân loại
    MATCHED / WARNING / ERROR + phân bổ FIFO dự kiến. **KHÔNG** tạo/ghi Payment —
    việc ghi tiền nằm ở pha commit (BV-3).
    """
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File rỗng."
        )
    if len(content) > _MAX_IMPORT_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File vượt giới hạn {_MAX_IMPORT_FILE_BYTES // (1024 * 1024)}MB.",
        )

    unit_id = finance_scope_unit_id(current_user)
    try:
        batch, preview = await payment_import_service.preview_import(
            db,
            content=content,
            filename=file.filename or "import.xlsx",
            academic_year=academic_year,
            semester_no=semester_no,
            created_by_id=current_user.id,
            unit_id=unit_id,
        )
        await db.commit()
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log.info(
        "payment_import_preview",
        batch_id=batch.id,
        academic_year=academic_year,
        semester_no=semester_no,
        matched=batch.matched_count,
        warned=batch.warned_count,
        failed=batch.failed_count,
        user_id=current_user.id,
    )
    return _build_payment_import_preview(batch, preview)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _build_payment_import_preview(
    batch, preview,
) -> finance_schemas.PaymentImportPreviewOut:
    """Map ``(PaymentImportBatch, PreviewResult)`` → schema response của pha preview.

    Phân bổ FIFO dự kiến (``allocations``) chỉ có trong ``preview`` in-memory (KHÔNG
    persist vào row) nên build từ ``preview.rows`` thay vì từ ORM rows.
    """
    return finance_schemas.PaymentImportPreviewOut(
        batch_id=batch.id,
        academic_year=batch.academic_year,
        semester_no=batch.semester_no,
        file_name=batch.file_name,
        status=batch.status,
        row_count=batch.row_count,
        matched_count=batch.matched_count,
        warned_count=batch.warned_count,
        failed_count=batch.failed_count,
        total_amount=batch.total_amount,
        rows=[
            finance_schemas.PaymentImportRowOut(
                row_no=r.row_no,
                status=r.status,
                message=r.message,
                citizen_id=r.citizen_id,
                profile_id=r.profile_id,
                fee_id=r.fee_id,
                amount=r.amount,
                method_code=r.method_code,
                payment_date=r.payment_date,
                reference=r.reference,
                allocations=[
                    finance_schemas.PaymentImportAllocationOut(
                        invoice_id=a.invoice_id,
                        installment_no=a.installment_no,
                        amount=a.amount,
                    )
                    for a in r.allocations
                ],
            )
            for r in preview.rows
        ],
    )


def _compute_payment_review_flags(
    payment, current_user_id: Optional[int], current_user_role: str
) -> tuple[bool, bool]:
    """Role-aware maker-checker can_verify/can_reject for a payment.

    SINGLE source for both the list/queue/collection (``_build_payment_list_item``)
    and the detail (``_build_payment_response``): a payment is verifiable/
    rejectable only while ``pending``, by a DIFFERENT user than the maker
    (no self-approval — also a DB CHECK), and only by a finance reviewer
    (admin/manager/accountant; Casbin grants accountant verify/reject on every
    unit). Returns ``(can_verify, can_reject)`` — identical today, kept as two
    values so a future divergence (e.g. reject-only) has a single edit point.
    """
    status_value = (
        payment.status.value if hasattr(payment.status, "value") else payment.status
    )
    is_pending = status_value == "pending"
    # Manual payments only (intent_id IS NULL): the maker-checker queue is
    # manual-only and gateway/online payments (intent_id set) auto-verify via
    # the callback, never by hand. Without this the collection drawer — which
    # rows EVERY payment — would surface manual verify/reject on a pending
    # gateway payment.
    is_manual = payment.intent_id is None
    is_different_user = (
        current_user_id is not None and payment.created_by_id != current_user_id
    )
    is_finance_reviewer = current_user_role in [
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.ACCOUNTANT,
    ]
    can = (
        is_pending and is_manual and is_different_user and is_finance_reviewer
    )
    return can, can


def _build_payment_list_item(
    payment,
    current_user_id: Optional[int] = None,
    current_user_role: str = None,
) -> finance_schemas.PaymentListItem:
    """Build an enriched ``PaymentListItem`` from a Payment model.

    SINGLE builder for the payment list, the manual-pending maker-checker queue
    (``pending_manual_only``) AND the profile-collection drawer so every surface
    shows the same enriched columns (``reference_code`` / ``payer_name`` for
    reconciliation, ``is_online`` to tell gateway payments apart) and the same
    role-aware can_verify/can_reject.

    Requires ``payment.invoice.fee.admission_profile.lead`` (profile_name),
    ``payment.method`` and ``payment.created_by`` eager-loaded — all relationship
    access happens HERE in async context, never during Pydantic serialization.
    """
    profile_name = None
    if payment.invoice and payment.invoice.fee:
        fee = payment.invoice.fee
        if fee.admission_profile and fee.admission_profile.lead:
            profile_name = fee.admission_profile.lead.full_name

    method_name = payment.method.name if payment.method else None
    created_by_name = None
    if payment.created_by:
        created_by_name = payment.created_by.full_name or payment.created_by.email

    can_verify, can_reject = _compute_payment_review_flags(
        payment, current_user_id, current_user_role
    )
    is_own = current_user_id is not None and payment.created_by_id == current_user_id

    return finance_schemas.PaymentListItem(
        id=payment.id,
        invoice_id=payment.invoice_id,
        amount=payment.amount,
        status=payment.status,
        payment_date=payment.payment_date,
        created_at=payment.created_at,
        reference_code=payment.reference_code,
        payer_name=payment.payer_name,
        is_online=payment.intent_id is not None,
        is_own=is_own,
        profile_name=profile_name,
        method_name=method_name,
        created_by_name=created_by_name,
        can_verify=can_verify,
        can_reject=can_reject,
    )


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
        - can_verify: pending, different user, role in [admin/manager/accountant]
        - can_reject: pending, different user, role in [admin/manager/accountant]

    Denormalized Names (P2):
        - Extracted from payment.created_by and payment.verified_by relationships
    """
    # P1: Permission flags — shared maker-checker + role logic (single source
    # with the list/queue builder so a button shown in one view is never denied
    # by the route the other view would call).
    can_verify, can_reject = _compute_payment_review_flags(
        payment, current_user_id, current_user_role
    )

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
