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
- POST /api/invoices - Create a supplemental/replacement invoice for a fee
- GET /api/invoices/{invoice_id} - Get invoice details with payments
- GET /api/invoices/by-fee/{fee_id} - Get all invoices for a fee
- PUT /api/invoices/{invoice_id}/issue - Issue invoice
- PUT /api/invoices/{invoice_id}/cancel - Cancel invoice
- POST /api/invoices/{invoice_id}/apply-penalty - Apply late payment penalty
"""

import base64
from datetime import date
from decimal import Decimal
from typing import List, Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app import database, models
from app.core.constants import UserRole
from app.core.deps import (
    CasbinAuth,
    RequireManager,
    finance_scope_unit_id,
    require_finance_staff,
)
from app.core.rate_limits import get_user_id_key, limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.models.finance import (
    PAYABLE_INVOICE_STATUSES,
    OVERDUE_DERIVED_STATUSES,
)
from app.constants.fee_labels import FEE_TYPE_LABELS
from app.services.invoice_service import InvoiceService
from app.services.tuition_export_service import build_tuition_export
from app.services.system_config_service import SystemConfigService
from app.repositories.fee_repository import InvoiceRepository
from app.utils.id_helpers import format_profile_code
from app.utils.text_helpers import to_bank_transfer_note
from app.utils.vietqr import build_vietqr_payload, render_qr_png
from app.utils.bank_names import bank_name_from_bin
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    DuplicateResourceError,
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
    profile_id: Optional[int] = Query(None, description="Filter by profile ID"),
    fee_type: Optional[str] = Query(None, description="Filter by fee type"),
    overdue_only: Optional[bool] = Query(
        None,
        description="Only derived-overdue invoices (issued/partial/overdue past due)",
    ),
    search: Optional[str] = Query(
        None,
        description="Search by student name, profile code (HS-…) or invoice number",
    ),
    sort_by: Optional[str] = Query(
        None,
        description=(
            "priority (default) | due_date | amount | paid | remaining | "
            "status | created_at"
        ),
    ),
    sort_order: Optional[str] = Query(
        None, description="asc | desc (ignored for the default 'priority' sort)"
    ),
    major_id: Optional[int] = Query(None, description="Filter theo ngành (MajorProgram.id)"),
    degree_level: Optional[str] = Query(
        None, description="Filter theo trình độ (TEXT name, vd 'Cao đẳng')"
    ),
    academic_year: Optional[int] = Query(None, description="Filter theo năm học"),
    semester_no: Optional[int] = Query(None, description="Filter theo học kỳ (1=HK1...)"),
    officer_id: Optional[int] = Query(None, description="Filter theo TVV phụ trách"),
    unit_id: Optional[int] = Query(
        None, description="Filter theo đơn vị (INTERSECT với scope IDOR)"
    ),
    awaiting_major_change: Optional[bool] = Query(
        None,
        description=(
            "Lens 'Chờ xác nhận đổi ngành': chỉ hoá đơn có khoản phí cha đang chờ "
            "kế toán xác nhận đổi ngành. ORTHOGONAL với trạng thái hoá đơn (giống "
            "lens 'Quá hạn') — nguồn của tab worklist kế toán."
        ),
    ),
    due_window: Optional[str] = Query(
        None, description="Hạn: due_soon_7d (đến hạn ≤7 ngày, chưa thu) | overdue"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List invoices for the "Thu học phí" collection workspace.

    **Security:**
    - IDOR protection: unit-scoped via finance_scope_unit_id
    - Requires 'invoices:read' permission
    """
    invoice_repo = InvoiceRepository(db)
    scope_unit_id = finance_scope_unit_id(current_user)

    # Convert page/page_size to skip/limit
    skip = (page - 1) * page_size
    limit = min(page_size, 100)

    # Parse comma-separated status values
    statuses: Optional[List[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    # One "today" per request → the SQL overdue predicate/sort and the Python
    # row-level is_overdue can't disagree across a midnight tick.
    today = date.today()
    invoices, total = await invoice_repo.get_filtered_with_count(
        skip=skip,
        limit=limit,
        unit_id=scope_unit_id,
        statuses=statuses,
        fee_id=fee_id,
        profile_id=profile_id,
        fee_type=fee_type,
        overdue_only=overdue_only,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        today=today,
        major_id=major_id,
        degree_level=degree_level,
        academic_year=academic_year,
        semester_no=semester_no,
        officer_id=officer_id,
        unit_id_filter=unit_id,
        due_window=due_window,
        awaiting_major_change=awaiting_major_change,
    )

    # Build enriched list rows (identity + derived urgency + role-aware flags).
    # All relationship access happens here in async context (see builder).
    items = [
        _build_invoice_list_item(invoice, current_user.role, today)
        for invoice in invoices
    ]

    return finance_schemas.InvoicesPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/status-counts",
    response_model=finance_schemas.InvoiceStatusCounts,
    summary="Invoice counts per status (+ derived overdue) for workspace tabs",
)
async def get_invoice_status_counts(
    request: Request,
    fee_id: Optional[int] = Query(None, description="Filter by fee ID"),
    profile_id: Optional[int] = Query(None, description="Filter by profile ID"),
    fee_type: Optional[str] = Query(None, description="Filter by fee type"),
    search: Optional[str] = Query(
        None,
        description="Search by student name, profile code (HS-…) or invoice number",
    ),
    major_id: Optional[int] = Query(None, description="Filter theo ngành (MajorProgram.id)"),
    degree_level: Optional[str] = Query(
        None, description="Filter theo trình độ (TEXT name, vd 'Cao đẳng')"
    ),
    academic_year: Optional[int] = Query(None, description="Filter theo năm học"),
    semester_no: Optional[int] = Query(None, description="Filter theo học kỳ (1=HK1...)"),
    officer_id: Optional[int] = Query(None, description="Filter theo TVV phụ trách"),
    unit_id: Optional[int] = Query(
        None, description="Filter theo đơn vị (INTERSECT với scope IDOR)"
    ),
    awaiting_major_change: Optional[bool] = Query(
        None,
        description=(
            "Lens 'Chờ xác nhận đổi ngành': chỉ hoá đơn có khoản phí cha đang chờ "
            "kế toán xác nhận đổi ngành. ORTHOGONAL với trạng thái hoá đơn (giống "
            "lens 'Quá hạn') — nguồn của tab worklist kế toán."
        ),
    ),
    due_window: Optional[str] = Query(
        None, description="Hạn: due_soon_7d (đến hạn ≤7 ngày, chưa thu) | overdue"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
):
    """
    Counts for the status tabs/chips of the collection workspace.

    Same filters as the list (minus status/overdue) so a tab's count equals the
    rows clicking it returns. ``overdue_derived`` uses the derived predicate
    (issued/partial/overdue past due), NOT the lagging enum 'overdue' bucket.

    PARITY (P1): mọi filter mới (ngành/trình độ/năm-HK/TVV/đơn vị/hạn) phải y hệt
    list_invoices, nếu không badge tab đếm lệch so với danh sách.

    NOTE: declared BEFORE ``/{invoice_id}`` so this literal path is not
    captured as an invoice id.

    **Security:** ``require_finance_staff`` is a HARD role gate (admin/manager/
    accountant) — needed because this literal path collides with the
    ``/api/invoices/{id}`` policy under keyMatch4, which would otherwise leak
    counts to an officer that only has the per-invoice read. Plus IDOR via
    finance_scope_unit_id.
    """
    invoice_repo = InvoiceRepository(db)
    scope_unit_id = finance_scope_unit_id(current_user)
    counts = await invoice_repo.get_status_counts(
        unit_id=scope_unit_id,
        fee_id=fee_id,
        profile_id=profile_id,
        fee_type=fee_type,
        search=search,
        major_id=major_id,
        degree_level=degree_level,
        academic_year=academic_year,
        semester_no=semester_no,
        officer_id=officer_id,
        unit_id_filter=unit_id,
        due_window=due_window,
        awaiting_major_change=awaiting_major_change,
    )
    return finance_schemas.InvoiceStatusCounts(**counts)



# =============================================================================
# EXPORT — nhãn bộ lọc cho sheet "Thong tin xuat"
# =============================================================================

_FEE_TYPE_FILTER_LABELS = FEE_TYPE_LABELS
_INVOICE_STATUS_FILTER_LABELS = {
    "draft": "Nháp",
    "issued": "Chờ thu",
    "partial": "Một phần",
    "paid": "Đã thu",
    "overdue": "Quá hạn",
    "cancelled": "Đã hủy",
}
_DUE_WINDOW_LABELS = {
    "due_soon_7d": "Đến hạn ≤7 ngày",
    "overdue": "Đã quá hạn",
}


async def _build_export_filter_labels(
    db: AsyncSession,
    *,
    scope_unit_id: Optional[int],
    status: Optional[str],
    fee_type: Optional[str],
    overdue_only: Optional[bool],
    search: Optional[str],
    major_id: Optional[int],
    degree_level: Optional[str],
    academic_year: Optional[int],
    semester_no: Optional[int],
    officer_id: Optional[int],
    unit_id: Optional[int],
    awaiting_major_change: Optional[bool],
    due_window: Optional[str],
) -> dict:
    """Dựng bảng "Bộ lọc đã áp dụng" cho tệp xuất — TÊN thật, không phải ID.

    Ghi cả phạm vi quyền hiệu lực: người đọc tệp sau này phải biết số liệu bao
    trọn hệ hay chỉ một đơn vị, kể cả khi người xuất không tự gõ bộ lọc nào.
    """
    labels: dict = {}

    async def _unit_name_in_scope(target_id: int) -> str:
        """Tên đơn vị — CHỈ khi nằm trong phạm vi quyền của người xuất.

        🔴 Không ``db.get`` tuỳ ý: manager phạm vi đơn vị A truyền
        ``unit_id`` của B thì dữ liệu ra rỗng (điều kiện lọc AND cả hai) nhưng
        tệp vẫn in TÊN của B — rò rỉ danh mục đơn vị qua chính tệp xuất.
        """
        if scope_unit_id is not None and target_id != scope_unit_id:
            return f"đơn vị #{target_id} (ngoài phạm vi)"
        unit = await db.get(models.OrganizationUnit, target_id)
        return unit.name if unit else f"đơn vị #{target_id}"

    # Hai khái niệm KHÁC NHAU, phải ghi tách:
    #  * "Phạm vi quyền" = giới hạn do vai trò áp, người dùng không đổi được;
    #  * "Bộ lọc đơn vị" = thứ người dùng tự chọn (giao với phạm vi trên).
    # Gộp chúng như bản đầu thì tệp ghi sai phạm vi thật khi hai bên khác nhau.
    if scope_unit_id is None:
        labels["Phạm vi quyền"] = "Toàn hệ thống"
    else:
        labels["Phạm vi quyền"] = await _unit_name_in_scope(scope_unit_id)

    if unit_id is not None:
        labels["Bộ lọc đơn vị"] = await _unit_name_in_scope(unit_id)

    if status:
        labels["Trạng thái hoá đơn"] = ", ".join(
            _INVOICE_STATUS_FILTER_LABELS.get(s.strip(), s.strip())
            for s in status.split(",")
            if s.strip()
        )
    if fee_type:
        labels["Loại phí"] = _FEE_TYPE_FILTER_LABELS.get(fee_type, fee_type)
    if overdue_only:
        labels["Chỉ quá hạn"] = "Có"
    if search:
        labels["Từ khoá tìm kiếm"] = search
    if major_id is not None:
        major = await db.get(models.MajorProgram, major_id)
        labels["Ngành"] = major.name if major else f"ngành #{major_id}"
    if degree_level:
        labels["Trình độ"] = degree_level
    if academic_year is not None:
        labels["Năm học"] = f"{academic_year}-{academic_year + 1}"
    if semester_no is not None:
        labels["Học kỳ"] = f"HK{semester_no}"
    if officer_id is not None:
        # Cùng lý do với đơn vị: không lộ tên người ngoài phạm vi quyền.
        officer = await db.get(models.User, officer_id)
        if officer is None:
            labels["TVV phụ trách"] = f"người dùng #{officer_id}"
        elif scope_unit_id is not None and officer.unit_id != scope_unit_id:
            labels["TVV phụ trách"] = f"người dùng #{officer_id} (ngoài phạm vi)"
        else:
            labels["TVV phụ trách"] = officer.full_name or officer.username
    if awaiting_major_change:
        labels["Chờ xác nhận đổi ngành"] = "Có"
    if due_window:
        labels["Hạn"] = _DUE_WINDOW_LABELS.get(due_window, due_window)

    return labels


# ==============================================================================
# EXPORT
# ==============================================================================
# 🔴 Route-order: khai /export TRƯỚC /{invoice_id}. Nếu đặt sau, FastAPI khớp
# "/export" vào /{invoice_id} rồi ép "export" thành int → 422 khó đoán (không
# phải 404). Cùng bẫy đã gặp ở payments.py với /import/batches.

@router.get(
    "/export",
    summary="Xuất danh sách khoản phí theo bộ lọc màn hình Thu học phí",
)
# 🔴 Thứ tự BẮT BUỘC: @router.* ở TRÊN, @limiter.limit ở DƯỚI (limiter trong
# cùng). Python áp decorator từ dưới lên; đảo lại là @router đăng ký hàm CHƯA
# bọc và hạn mức im lặng không chạy — xem tests/security/test_ratelimit_order_guard.py.
#
# key_func per-user: hạn mức mặc định khoá theo IP, mà cả trường đi chung một
# IP NAT nên 20 lượt/giờ sẽ là quota DÙNG CHUNG — đúng hình dạng sự cố
# /auth/refresh đã gặp trên prod. Route này đã xác thực nên khoá theo người.
@limiter.limit(RateLimits.DATA_EXPORT, key_func=get_user_id_key)
async def export_tuition_list(
    request: Request,
    format: str = Query(
        "xlsx", pattern="^(xlsx|csv)$", description="xlsx (mặc định) | csv"
    ),
    status: Optional[str] = Query(
        None, description="Filter by status (comma-separated)"
    ),
    fee_id: Optional[int] = Query(None, description="Filter by fee ID"),
    profile_id: Optional[int] = Query(None, description="Filter by profile ID"),
    fee_type: Optional[str] = Query(None, description="Filter by fee type"),
    overdue_only: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    major_id: Optional[int] = Query(None),
    degree_level: Optional[str] = Query(None),
    academic_year: Optional[int] = Query(None),
    semester_no: Optional[int] = Query(None),
    officer_id: Optional[int] = Query(None),
    unit_id: Optional[int] = Query(None),
    awaiting_major_change: Optional[bool] = Query(None),
    due_window: Optional[str] = Query(None),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
) -> Response:
    """Xuất danh sách khoản phí (xlsx/csv) theo ĐÚNG bộ lọc đang xem.

    Nhận cùng bộ tham số lọc với ``GET /api/invoices``, TRỪ phân trang và sắp
    xếp: file xuất trọn kết quả lọc và tự sắp theo mã hồ sơ.

    **Grain**: mỗi dòng là MỘT KHOẢN PHÍ (không phải một hoá đơn) — xem
    docstring ``tuition_export_service``.

    **Security**: dual-gate (Casbin + require_finance_staff); IDOR qua
    ``finance_scope_unit_id``.
    """
    scope_unit_id = finance_scope_unit_id(current_user)

    statuses: Optional[List[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]

    # Sheet "Thong tin xuat" phải đọc được sau vài tuần, nên:
    #  * ghi PHẠM VI QUYỀN hiệu lực, không chỉ tham số người dùng gõ — admin
    #    lọc unit_id=14 mà sheet ghi "(không lọc)" là nói sai phạm vi;
    #  * resolve ID sang TÊN (ngành / TVV / đơn vị) và map enum sang nhãn UI —
    #    "Ngành | 37" thì không ai dựng lại được bối cảnh.
    applied_filters = await _build_export_filter_labels(
        db,
        scope_unit_id=scope_unit_id,
        status=status,
        fee_type=fee_type,
        overdue_only=overdue_only,
        search=search,
        major_id=major_id,
        degree_level=degree_level,
        academic_year=academic_year,
        semester_no=semester_no,
        officer_id=officer_id,
        unit_id=unit_id,
        awaiting_major_change=awaiting_major_change,
        due_window=due_window,
    )

    try:
        content, media_type, filename = await build_tuition_export(
            db,
            fmt=format,
            unit_id=scope_unit_id,
            exporter_name=current_user.full_name or current_user.username,
            applied_filters=applied_filters,
            statuses=statuses,
            fee_id=fee_id,
            profile_id=profile_id,
            fee_type=fee_type,
            overdue_only=overdue_only,
            search=search,
            major_id=major_id,
            degree_level=degree_level,
            academic_year=academic_year,
            semester_no=semester_no,
            officer_id=officer_id,
            unit_id_filter=unit_id,
            due_window=due_window,
            awaiting_major_change=awaiting_major_change,
        )
    except BadRequest as exc:
        raise HTTPException(status_code=400, detail=exc.detail)

    # Plain Response (không StreamingResponse) để có Content-Length — trình
    # duyệt hiện được tiến độ tải.
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Tệp chứa họ tên + CCCD hàng trăm thí sinh. Không có Cache-Control
            # thì RFC 7234 §4.2.2 cho phép cache theo suy nghiệm, mà hệ này xác
            # thực bằng cookie nên cache dùng chung không bị cấm lưu — trên máy
            # dùng chung ở quầy, người sau mở lại từ lịch sử là có tệp.
            # Cùng quy ước với sms_export / enrollment_letters / admissions.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

    invoices = await invoice_repo.get_by_fee_id(fee_id, unit_id)

    return [
        finance_schemas.InvoiceSummaryResponse(
            id=inv.id,
            invoice_number=inv.invoice_number,
            installment_no=inv.installment_no,
            amount=inv.amount,
            paid_amount=inv.paid_amount,
            # Dùng property remaining_amount (= amount + penalty − paid, GỒM
            # penalty) — KHÔNG phải amount−paid. Khớp cờ has_payable_invoice
            # (_invoice_is_payable cũng dùng property): ca penalty-only (principal
            # đã trả, còn dư nợ phạt) vẫn ra remaining > 0 nên FeeQRTransferDialog
            # không lọc nhầm → tránh "nút hiện nhưng dialog rỗng".
            remaining_amount=inv.remaining_amount,
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
                bank_name=bank_name_from_bin(bank_bin),
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
    unit_id = finance_scope_unit_id(current_user)

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
    unit_id = finance_scope_unit_id(current_user)

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
    "",
    response_model=finance_schemas.InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a supplemental/replacement invoice for a fee",
)
async def create_invoice(
    request: Request,
    data: finance_schemas.InvoiceCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireManager,
):
    """
    Create a single invoice (installment) for a fee.

    Primary use: re-create an installment after the original was cancelled.
    PR-A made cancelled invoices stop reserving the (fee_id, installment_no)
    slot, so a manager can issue a fresh invoice for that installment. Also
    serves manual / supplemental installments.

    **Business Rules:**
    - Fee status must be calculated / invoiced / partial
    - installment_no must not collide with an ACTIVE (non-cancelled) invoice
    - amount must not exceed the fee's remaining-to-invoice
    - Requires manager or admin role

    **Security:**
    - IDOR protection: scoped to the caller's unit
    - Role enforced via RequireManager dependency
    """
    invoice_service = InvoiceService(db)
    unit_id = finance_scope_unit_id(current_user)

    try:
        invoice, _ = await invoice_service.create_single_invoice(
            fee_id=data.fee_id,
            amount=data.amount,
            due_date=data.due_date,
            installment_no=data.installment_no,
            user_id=current_user.id,
            unit_id=unit_id,
        )

        await db.commit()

        log.info(
            "invoice_created_via_api",
            invoice_id=invoice.id,
            fee_id=data.fee_id,
            installment_no=data.installment_no,
            user_id=current_user.id,
        )

        await db.refresh(invoice)
        return _build_invoice_response(invoice, current_user_role=current_user.role)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DuplicateResourceError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except (BadRequest, BusinessRuleViolation) as e:
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
    penalty_amount: Decimal = Query(
        ..., gt=0, le=finance_schemas.MAX_AMOUNT, description="Số tiền phạt (VND, bắt buộc)"
    ),
    reason: str = Query(..., min_length=1, max_length=500, description="Lý do áp phạt"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = RequireManager,
):
    """
    Apply late payment penalty to an overdue invoice.

    **Business Rules:**
    - ``penalty_amount`` bắt buộc (> 0); tổng phạt không vượt số tiền hóa đơn.
    - Không áp phạt cho hóa đơn đã thanh toán / đã hủy.
    - Requires manager or admin role

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Role enforced via RequireManager dependency
    """
    invoice_service = InvoiceService(db)
    unit_id = finance_scope_unit_id(current_user)

    try:
        invoice, _ = await invoice_service.apply_penalty(
            invoice_id=invoice_id,
            penalty_amount=penalty_amount,
            reason=reason,
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

def _compute_invoice_permissions(
    invoice, current_user_role: str = None
) -> dict:
    """Role-aware ``can_*`` flags for an invoice.

    SINGLE SOURCE for both the detail response (``_build_invoice_response``)
    and the list item (``list_invoices``) so a button shown in the list is
    never one the detail/route would 403.

    Every flag is gated by the SAME roles that hold the underlying route, so a
    button shown is never one the route would 403 (critical now that managers can
    load the workspace list but do NOT hold the accountant write routes):
    - can_issue: status == 'draft' AND role in [admin, accountant]
      (PUT /api/invoices/{id}/issue → ACCOUNTANT_TEMPLATE; manager lacks it)
    - can_record_payment: status in PAYABLE (issued/partial/overdue) AND
      remaining > 0 AND role in [admin, accountant]
      (POST /api/payments → ACCOUNTANT_TEMPLATE; manager lacks it)
    - can_cancel: status not terminal AND paid == 0 AND role in [admin, manager]
      (PUT /api/invoices/{id}/cancel → RequireManager; accountant excluded)
    - can_apply_penalty: derived-overdue (issued/partial/overdue đã quá due_date)
      AND role in [admin, manager]
      (POST /api/invoices/{id}/apply-penalty → RequireManager; accountant excluded)
    """
    status_value = (
        invoice.status.value if hasattr(invoice.status, "value") else invoice.status
    )
    is_manager_or_admin = current_user_role in [UserRole.ADMIN, UserRole.MANAGER]
    is_accountant_or_admin = current_user_role in [UserRole.ADMIN, UserRole.ACCOUNTANT]
    # Đổi ngành: fee cha đang chờ kế toán xác nhận → ``cancel_invoice`` bị service
    # chặn (huỷ hoá đơn làm chu kỳ không thể chốt: confirm đòi ĐÚNG 1 invoice
    # active). Hoá đơn 0đ của hồ sơ đổi ngành lọt hết guard cũ nên đây đúng là ca
    # nút hiện rồi bấm ra 400.
    # ``__dict__.get`` để KHÔNG trigger lazy-load (MissingGreenlet trong async);
    # đường nào chưa eager-load ``fee`` thì cờ giữ nguyên như trước — service vẫn
    # là hàng rào thật, đây chỉ là lớp làm nút không chết.
    _parent_fee = invoice.__dict__.get("fee")
    _fee_awaiting_major_change = bool(
        _parent_fee is not None
        and getattr(_parent_fee, "awaiting_accountant_confirmation", False)
    )
    return {
        "can_issue": status_value == "draft" and is_accountant_or_admin,
        "can_cancel": (
            status_value not in ["paid", "cancelled"]
            and invoice.paid_amount == 0
            and is_manager_or_admin
            and not _fee_awaiting_major_change
        ),
        "can_record_payment": (
            status_value in PAYABLE_INVOICE_STATUSES
            and invoice.remaining_amount > 0
            and is_accountant_or_admin
        ),
        # Derived-overdue (issued/partial/overdue ĐÃ quá due_date), KHÔNG dùng enum
        # 'overdue' (lag theo beat job) → nút hiện đúng khi service apply_penalty
        # chấp nhận (service cũng gate ``invoice.is_overdue``).
        "can_apply_penalty": _invoice_is_overdue(invoice) and is_manager_or_admin,
    }


def _invoice_is_overdue(invoice, today: Optional[date] = None) -> bool:
    """Derived overdue for a single invoice (Python mirror of
    ``InvoiceRepository._overdue_predicate``): a billed/partial/overdue invoice
    past its due date. SUPERSET of the lagging enum 'overdue'. Single source for
    both the list row and the detail response so the detail page never goes
    silent on a row the list paints red.
    """
    today = today or date.today()
    status_value = (
        invoice.status.value if hasattr(invoice.status, "value") else invoice.status
    )
    return status_value in OVERDUE_DERIVED_STATUSES and invoice.due_date < today


def _build_invoice_list_item(
    invoice, current_user_role: str = None, today: Optional[date] = None
) -> finance_schemas.InvoiceListItem:
    """Build an ``InvoiceListItem`` (collection-workspace row) from an Invoice.

    Requires ``invoice.fee.admission_profile.lead`` with ``assigned_officer`` +
    ``offering.program`` eager-loaded (see
    ``InvoiceRepository.get_filtered_with_count``). All relationship access
    happens HERE in async context — never during Pydantic serialization — to
    avoid MissingGreenlet. Reused by PR2's profile-collection endpoint.
    """
    today = today or date.today()
    fee = invoice.fee
    profile = fee.admission_profile if fee else None
    lead = profile.lead if profile else None
    officer = lead.assigned_officer if lead else None
    # Ngành/trình độ đọc TỪ snapshot Fee.resolved_* (single source khớp filter),
    # KHÔNG dùng lead.offering.program (NV gốc — sai với multi-NV admitted).
    # __dict__.get tránh lazy-load (MissingGreenlet) nếu chưa eager-load; NULL
    # snapshot → program_name None → FE hiển thị "(chưa chốt ngành)".
    resolved_major = fee.__dict__.get("resolved_major") if fee else None

    return finance_schemas.InvoiceListItem(
        id=invoice.id,
        fee_id=invoice.fee_id,
        invoice_number=invoice.invoice_number,
        installment_no=invoice.installment_no,
        amount=invoice.amount,
        paid_amount=invoice.paid_amount,
        remaining_amount=invoice.remaining_amount,
        penalty_amount=invoice.penalty_amount,
        total_due=invoice.total_due,
        due_date=invoice.due_date,
        status=invoice.status,
        profile_id=profile.id if profile else None,
        profile_name=lead.full_name if lead else None,
        profile_code=format_profile_code(profile.id) if profile else None,
        program_name=resolved_major.name if resolved_major else None,
        degree_level=fee.resolved_degree_level if fee else None,
        officer_name=officer.full_name if officer else None,
        fee_type=fee.fee_type if fee else None,
        semester_no=fee.semester_no if fee else None,
        is_overdue=_invoice_is_overdue(invoice, today),
        **_compute_invoice_permissions(invoice, current_user_role),
    )


def _build_invoice_response(
    invoice, current_user_role: str = None, today: Optional[date] = None
) -> finance_schemas.InvoiceResponse:
    """Build InvoiceResponse from Invoice model (detail view)."""
    # QW-B fix #1: use the model's remaining_amount property (= amount +
    # penalty_amount - paid_amount) so the response is internally consistent
    # with total_due (= amount + penalty).
    remaining_amount = invoice.remaining_amount
    perms = _compute_invoice_permissions(invoice, current_user_role)

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
        # QW-B fix #1: these are REQUIRED on InvoiceResponse. This builder
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
        # P1: Permission flags (role-aware, shared with the list)
        **perms,
        # Derived overdue — same source as the list row so the detail page paints
        # the same urgency the list shows (no enum-lag silence).
        is_overdue=_invoice_is_overdue(invoice, today),
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
