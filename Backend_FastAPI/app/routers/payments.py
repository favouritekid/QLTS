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
    APIRouter, Body, Depends, File, Form, HTTPException, Query, Request,
    UploadFile, status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models, schemas
from app.core import deps
from app.core.constants import UserRole
from app.core.deps import (
    CasbinAuth,
    finance_scope_unit_id,
    require_admin_or_manager,
    require_finance_staff,
)
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

# 422 viết thành số, không nhập từ `starlette.status`: Starlette đang đổi tên
# hằng này (`..._ENTITY` → `..._CONTENT`) và nhập nó thêm một cảnh báo
# deprecation vào mọi lượt chạy. Con số thì không đổi tên.
HTTP_422_UNPROCESSABLE = 422
#: Cùng lý do: hàm `list_payments` có tham số query tên `status` che mất module
#: `status` của FastAPI trong toàn bộ thân hàm.
HTTP_410_GONE = 410

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
    fee_id: Optional[int] = Query(
        None,
        ge=1,
        # Trần = INT4 max. Không có trần thì một số nguyên lớn hơn 2^31-1 lọt
        # qua Pydantic rồi vỡ ở tầng PostgreSQL/asyncpg ("integer out of
        # range") — người dùng nhận 500 cho một đầu vào đáng lẽ là 422.
        le=2_147_483_647,
        description="Filter by fee ID — trả phiếu thu của MỌI hoá đơn thuộc "
        "khoản phí đó. Dùng cho ô 'đang chờ duyệt' ở form ghi tiền: khoản phí "
        "nhiều đợt thì phiếu vừa nhập có thể nằm ở hoá đơn khác, lọc theo "
        "invoice_id sẽ không thấy. Kết hợp được với pending_manual_only.",
    ),
    method_id: Optional[int] = Query(None, description="Filter by payment method ID"),
    # ── Hai tham số ĐÃ GỠ. Giữ lại trong chữ ký CHỈ để từ chối tường minh.
    #
    # Xoá hẳn khỏi chữ ký là fail-OPEN, và im lặng: FastAPI bỏ qua query lạ, nên
    # một client cũ gọi `?fee_id=1&duplicate_amount=…&duplicate_date=…` sẽ nhận
    # 200 kèm DANH SÁCH PHIẾU THU THƯỜNG của khoản phí — rồi giao diện vẽ nó
    # thành "các phiếu nghi trùng". Một tập rộng hơn hẳn, trình bày như thể là
    # kết quả của luật dò trùng.
    #
    # Đường xem trước bị gỡ vì nó không còn quyền gì mà chi phí thì vẫn nguyên:
    # cache, debounce, đua request, kết quả rỗng đã cũ, và hai bộ ứng viên cùng
    # xuất hiện. Nó cũng tạo cảm giác sai rằng "không thấy cảnh báo nghĩa là an
    # toàn". Cảnh báo nay đến từ 409 của chính lần bấm Lưu, kèm một phiếu xác
    # nhận — xem `duplicate_review_token`.
    duplicate_amount: Optional[Decimal] = Query(
        None,
        deprecated=True,
        include_in_schema=False,
        description="ĐÃ GỠ — trả 410. Cảnh báo trùng nay đến từ 409 của POST "
        "/api/payments kèm review_token.",
    ),
    duplicate_date: Optional[datetime] = Query(
        None,
        deprecated=True,
        include_in_schema=False,
        description="ĐÃ GỠ — xem duplicate_amount.",
    ),
    pending_manual_only: bool = Query(
        False,
        description="Maker-checker queue: only manual payments (intent_id IS "
        "NULL) awaiting verification. Online/gateway payments auto-verify and "
        "must NOT appear here. Ignores status/method_id when set; fee_id is "
        "still honoured (AND) so a single fee's queue can be read.",
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

    if duplicate_amount is not None or duplicate_date is not None:
        # 410 GONE — từ chối TƯỜNG MINH, không im lặng bỏ qua.
        #
        # Đây là toàn bộ lý do hai tham số trên còn nằm trong chữ ký. Gỡ hẳn
        # chúng thì FastAPI bỏ qua query lạ và trả 200 kèm danh sách phiếu thu
        # THƯỜNG của khoản phí — một tập rộng hơn hẳn tập ứng viên trùng, mà
        # client cũ sẽ vẽ ra thành "các phiếu nghi trùng" rồi cho người dùng bấm
        # qua. Hỏng kiểu đó không có dòng đỏ nào để lần theo.
        #
        # 410 (không phải 404/422) vì đường này TỪNG tồn tại và đã bị gỡ có chủ
        # ý — đó đúng là điều client cần nghe.
        #
        # `HTTP_410_GONE` nhập thẳng, KHÔNG qua `status.HTTP_...`: hàm này có
        # một tham số query tên `status`, và nó che mất module `status` của
        # FastAPI trong toàn bộ thân hàm. Con số thì không bị che.
        raise HTTPException(
            status_code=HTTP_410_GONE,
            detail=(
                "Đường xem trước phiếu nghi trùng đã được gỡ. Cảnh báo trùng "
                "nay đến từ lỗi 409 của POST /api/payments, kèm một "
                "review_token để xác nhận và ghi tiếp."
            ),
        )

    if pending_manual_only:
        # Maker-checker queue: status=pending AND intent_id IS NULL, oldest-first.
        # This is the ONLY path that guarantees online (gateway, auto-verified)
        # payments never reach the manual verification queue — do NOT emulate it
        # with a generic status=pending filter, which would also surface a
        # pending online payment.
        # `fee_id` được AND vào (không phải bỏ qua): form ghi tiền cần đúng
        # hàng đợi này nhưng chỉ của một khoản phí, và nếu nó phải quay về
        # `status=pending` thì lại đếm nhầm cả phiếu online đang treo.
        payments, total = await payment_repo.get_pending_verification(
            unit_id=unit_id,
            skip=skip,
            limit=limit,
            fee_id=fee_id,
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
            fee_id=fee_id,
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
            review_token=data.review_token,
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
    # Chống DoS nuốt RAM: kiểm content-length TRƯỚC, rồi đọc CÓ GIỚI HẠN (max+1 byte)
    # để 1 upload khổng lồ không bị đọc trọn vào RAM trước khi tới chỗ check size.
    if file.size is not None and file.size > _MAX_IMPORT_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File vượt giới hạn {_MAX_IMPORT_FILE_BYTES // (1024 * 1024)}MB.",
        )
    content = await file.read(_MAX_IMPORT_FILE_BYTES + 1)
    if len(content) > _MAX_IMPORT_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File vượt giới hạn {_MAX_IMPORT_FILE_BYTES // (1024 * 1024)}MB.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="File rỗng."
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


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/import/{batch_id}/commit",
    response_model=finance_schemas.PaymentImportCommitOut,
    summary="Ghi tiền (auto-verify) các dòng MATCHED/WARNING của lô import",
)
async def commit_payment_import(
    request: Request,
    batch_id: int,
    body: Optional[finance_schemas.PaymentImportCommitIn] = Body(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """Pha 2: re-validate TOCTOU dưới khóa + auto-verify từng dòng (kế toán=maker,
    system_user=checker) + gộp lead-sync. Lô đã committed → 409 (không ghi lại).

    Dòng nghi trùng với phiếu đã ghi bị GIỮ LẠI (không ghi) và mang
    ``commit_status='duplicate_review_required'`` kèm một PHIẾU xác nhận riêng
    cho dòng đó; phần còn lại của lô vẫn vào. Muốn ghi tiếp những dòng ấy thì
    gọi lại kèm ``confirmed_rows`` — mỗi phần tử là ``row_no`` cộng đúng phiếu
    mà lượt trước trả về cho dòng đó.

    Không có cờ "bỏ qua cho TOÀN LÔ" nữa: một cờ như vậy bỏ qua cả những cảnh
    báo sinh ra SAU khi kế toán đã soát, và nó không nói được người bấm đã nhìn
    thấy những gì.
    """
    unit_id = finance_scope_unit_id(current_user)
    try:
        result, callback = await payment_import_service.commit_batch(
            db,
            batch_id=batch_id,
            importer_id=current_user.id,
            unit_id=unit_id,
            confirmed_tokens=(
                {r.row_no: r.review_token for r in body.confirmed_rows}
                if body and body.confirmed_rows
                else None
            ),
        )
        await db.commit()
        if callback:
            await callback()
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (BusinessRuleViolation, BadRequest) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log.info(
        "payment_import_commit",
        batch_id=batch_id,
        committed=result.committed_count,
        failed=result.failed_count,
        payments=result.payment_count,
        total=str(result.total_amount),
        user_id=current_user.id,
    )
    batch, rows = await payment_import_service.load_batch_with_rows(db, batch_id)
    return _build_payment_import_commit(result, batch, rows)


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/import/{batch_id}/void",
    response_model=finance_schemas.PaymentImportVoidOut,
    summary="Đảo (void) lô import đã ghi tiền — rút lại toàn bộ Payment",
)
async def void_payment_import(
    request: Request,
    batch_id: int,
    reason: str = Body(
        ..., embed=True, min_length=3, max_length=500,
        description="Lý do đảo lô (bắt buộc, lưu audit)",
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _mgr: models.User = Depends(require_admin_or_manager),
):
    """Đảo lô đã committed: rút lại invoice/fee.paid_amount + Payment→refunded +
    PaymentTransaction reversal; batch→void (mở lại file_sha256 để re-import). Gate
    manager/admin (CAO HƠN finance staff — accountant KHÔNG được). Lô chưa committed
    → 409.
    """
    unit_id = finance_scope_unit_id(current_user)
    try:
        result, callback = await payment_import_service.void_batch(
            db,
            batch_id=batch_id,
            user_id=current_user.id,
            unit_id=unit_id,
            reason=reason,
        )
        await db.commit()
        if callback:
            await callback()
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (BusinessRuleViolation, BadRequest) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    log.info(
        "payment_import_void",
        batch_id=batch_id,
        reversed=result.reversed_count,
        amount=str(result.reversed_amount),
        user_id=current_user.id,
    )
    return finance_schemas.PaymentImportVoidOut(
        batch_id=result.batch_id,
        status="void",
        reversed_count=result.reversed_count,
        reversed_amount=result.reversed_amount,
        void_reason=reason,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/import/batches",
    response_model=finance_schemas.PaymentImportBatchListOut,
    summary="Lịch sử lô import thu học phí (phân trang)",
)
async def list_payment_import_batches(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """Lịch sử lô import (mới nhất trước). Org-level finance info; tiền ghi ở mức
    dòng đã unit-scope."""
    unit_id = finance_scope_unit_id(current_user)
    skip = (page - 1) * page_size
    items, total = await payment_import_service.list_batches(
        db, unit_id=unit_id, skip=skip, limit=page_size
    )
    # can_void = quyền THẬT của người xem (khớp gate require_admin_or_manager của route
    # void) → FE đọc flag, KHÔNG tự check role. Chỉ lô 'committed' mới đảo được.
    items_out = []
    for b in items:
        summary = finance_schemas.PaymentImportBatchSummaryOut.model_validate(b)
        summary.can_void = _can_void_for(current_user, b.status)
        items_out.append(summary)
    return finance_schemas.PaymentImportBatchListOut(
        items=items_out,
        total=total,
        page=page,
        page_size=page_size,
    )


# Route-order: ĐẶT SAU "/import/batches" (tĩnh) + dùng đường con "/batches/{id}" để
# KHÔNG nuốt route danh sách. (Bare "/import/{batch_id}" sẽ khớp "batches"→ép int→422.)
@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/import/batches/{batch_id}",
    response_model=finance_schemas.PaymentImportBatchDetailOut,
    summary="Chi tiết lô import — xem lại từng dòng sau commit (BV-5 R2)",
)
async def get_payment_import_batch_detail(
    request: Request,
    batch_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """Lô + per-row (status / lý do / payment_ids) để truy vết. IDOR unit-scope → 404."""
    unit_id = finance_scope_unit_id(current_user)
    try:
        batch, rows = await payment_import_service.get_batch_detail_scoped(
            db, batch_id, unit_id
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    # KHÔNG model_validate(batch) trực tiếp vào DetailOut: field `rows` + from_attributes
    # → Pydantic đọc batch.rows (relationship LAZY, chưa load) → MissingGreenlet (async IO
    # ngoài greenlet) → 500. Build từ summary (chỉ cột) + rows đã nạp riêng.
    summary = finance_schemas.PaymentImportBatchSummaryOut.model_validate(batch)
    summary.can_void = _can_void_for(current_user, batch.status)
    return finance_schemas.PaymentImportBatchDetailOut(
        **summary.model_dump(),
        rows=[_payment_import_row_out(r) for r in rows],
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/import/batches/{batch_id}/result",
    summary="Tải file kết quả import (nguyên dòng gốc + Trạng thái/Lý do) (BV-5 R1)",
)
async def download_payment_import_result(
    request: Request,
    batch_id: int,
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """File kết quả = nguyên dòng gốc + cột kết quả (sanitize chống formula injection).
    IDOR unit-scope. Sinh ở service; router chỉ stream (CLAUDE.md rule 1)."""
    unit_id = finance_scope_unit_id(current_user)
    try:
        content, media_type, filename = await payment_import_service.build_result_file(
            db, batch_id, format, unit_id
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return StreamingResponse(
        io.BytesIO(content),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _can_void_for(user: models.User, batch_status: str) -> bool:
    """Quyền đảo lô của user xem: manager/admin & lô 'committed' (khớp gate route void).
    Dùng chung list + detail (1 nguồn — tránh lệch nếu đổi điều kiện)."""
    return user.role in (UserRole.MANAGER, UserRole.ADMIN) and batch_status == "committed"


def _payment_import_row_out(r) -> finance_schemas.PaymentImportRowOut:
    """Map 1 ``PaymentImportRow`` ORM → schema (dùng chung commit + detail BV-5)."""
    return finance_schemas.PaymentImportRowOut(
        row_no=r.row_no,
        validation_status=r.validation_status,
        commit_status=r.commit_status,
        # Phiếu chỉ đi ra khi dòng THẬT SỰ đang chờ xác nhận. Trả kèm ở mọi
        # trạng thái khác là phát ra một thứ trông như quyền nhưng không mở
        # được gì — và rồi ai đó sẽ thử.
        review_token=(
            r.duplicate_review_token
            if r.commit_status == "duplicate_review_required"
            else None
        ),
        message=r.message,
        citizen_id=r.citizen_id,
        profile_id=r.resolved_profile_id,
        fee_id=r.resolved_fee_id,
        amount=r.amount,
        payment_ids=r.payment_ids,
    )


def _build_payment_import_commit(
    result, batch, rows
) -> finance_schemas.PaymentImportCommitOut:
    """Map ``(CommitResult, batch, rows ORM)`` → schema response pha commit."""
    return finance_schemas.PaymentImportCommitOut(
        batch_id=result.batch_id,
        status=batch.status if batch is not None else "committed",
        committed_count=result.committed_count,
        failed_count=result.failed_count,
        review_required_count=result.review_required_count,
        payment_count=result.payment_count,
        total_amount=result.total_amount,
        rows=[_payment_import_row_out(r) for r in rows],
    )


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
                validation_status=r.validation_status,
                # Bước xem trước KHÔNG ghi tiền, nên trục GHI ở đây luôn là
                # "chưa ghi" — trừ dòng hỏng từ khâu đọc, thứ không có gì để ghi.
                commit_status=(
                    "not_applicable"
                    if r.validation_status == "error"
                    else "pending"
                ),
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
    imported_payment_ids: Optional[set] = None,
) -> finance_schemas.PaymentListItem:
    """Build an enriched ``PaymentListItem`` from a Payment model.

    SINGLE builder for the payment list, the manual-pending maker-checker queue
    (``pending_manual_only``) AND the profile-collection drawer so every surface
    shows the same enriched columns (``reference_code`` / ``payer_name`` for
    reconciliation, ``is_online`` to tell gateway payments apart) and the same
    role-aware can_verify/can_reject.

    Requires ``payment.invoice.fee.admission_profile.lead`` (profile_name),
    ``payment.method``, ``payment.created_by`` (and ``verified_by`` for the
    drawer) eager-loaded — all relationship access happens HERE in async
    context, never during Pydantic serialization.

    ``source`` (BE-owned): ``online`` khi ``intent_id`` có; ``import`` khi
    ``payment.id`` nằm trong ``imported_payment_ids`` (prefetch từ
    ``PaymentImportRow.payment_ids`` — chỉ drawer truyền vào); else ``manual``.
    Caller không truyền set → import-payment hiện "manual" (chấp nhận ở list/
    queue; drawer là nơi cần chi tiết nguồn).
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
    # verified_by may not be eager-loaded in list/queue callers → __dict__.get
    # avoids a lazy-load (MissingGreenlet); drawer eager-loads it.
    verified_by = payment.__dict__.get("verified_by")
    verified_by_name = None
    if verified_by:
        verified_by_name = verified_by.full_name or verified_by.email

    if payment.intent_id is not None:
        source = "online"
    elif imported_payment_ids and payment.id in imported_payment_ids:
        source = "import"
    else:
        source = "manual"

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
        verified_by_name=verified_by_name,
        verified_at=payment.verified_at,
        source=source,
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
