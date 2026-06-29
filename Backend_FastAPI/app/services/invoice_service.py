# app/services/invoice_service.py
"""
Invoice Service - Business logic for invoice lifecycle management.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: IDOR checks via repository (unit_id filtering)
- Transactions: Services use db.add()/db.flush(), Router commits
- Error Handling: Raise custom exceptions (ResourceNotFoundError, etc.)

Invoice Lifecycle:
    draft → issued → partial → paid
                      ↓
                   overdue (scheduled job)
                      ↓
                  cancelled

Business Rules (Section 3.9):
- H8: Can only create invoice if fee.status in ('calculated', 'invoiced', 'partial')
- Invoice amount cannot exceed fee remaining balance
- Invoice number format: INV-YYYY-XXXXXX (generated via DB sequence)
- Due dates calculated from installment plan schedule
"""

from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional, Tuple, Callable
import structlog

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import models
from app.models.finance import (
    Fee, Invoice, InstallmentPlan,
    FeeStatusEnum, InvoiceStatusEnum,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    DuplicateResourceError,
)
from app.config import settings

log = structlog.get_logger(__name__)


class InvoiceService:
    """
    Service for invoice lifecycle management.

    Responsibilities:
    - Generate invoices for fees (single or installment-based)
    - Issue invoices to students
    - Cancel invoices
    - Mark overdue invoices
    - Apply late payment penalties
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        self.fee_repo = FeeRepository(db)
        self.invoice_repo = InvoiceRepository(db)

    # ==========================================================================
    # INVOICE GENERATION
    # ==========================================================================

    async def generate_invoices_for_fee(
        self,
        fee_id: int,
        due_date_base: date,
        user_id: int,
        unit_id: Optional[int] = None,
        auto_issue: bool = False,
        anchor_date: Optional[date] = None,
    ) -> Tuple[List[Invoice], Optional[Callable]]:
        """
        Generate all invoices for a fee based on its installment plan.

        Creates one invoice for single payment, or multiple invoices
        for installment plans with proper amount distribution.

        Args:
            fee_id: Fee to generate invoices for
            due_date_base: Base due date (first installment)
            user_id: User generating invoices (for audit)
            unit_id: Unit ID for IDOR protection
            auto_issue: If True, immediately issue invoices (skip draft)

        Returns:
            Tuple of (List[Invoice], post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If fee status doesn't allow invoicing (H8)
            BadRequest: If invoices already exist for this fee
        """
        # Get fee with installment plan
        fee = await self.fee_repo.get_by_id_with_relations(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # H8: Check fee status allows invoicing
        allowed_statuses = [
            FeeStatusEnum.calculated.value,
            FeeStatusEnum.invoiced.value,
            FeeStatusEnum.partial.value,
        ]
        if fee.status not in allowed_statuses:
            raise BusinessRuleViolation(
                f"Cannot create invoice for fee with status '{fee.status}'. "
                f"Allowed: {allowed_statuses}"
            )

        # Check if invoices already exist
        existing = await self.invoice_repo.get_by_fee_id(
            fee_id, unit_id, active_only=True
        )
        if existing:
            raise BadRequest(
                f"Invoices already exist for this fee. "
                f"Found {len(existing)} invoice(s)."
            )

        # Calculate remaining to invoice (final - waived)
        amount_to_invoice = fee.final_amount - fee.waived_amount
        if amount_to_invoice <= 0:
            raise BadRequest("No amount to invoice (fee fully waived)")

        # Get installment schedule
        if fee.installment_plan:
            # Chặn dùng plan đã NGỪNG hoạt động: lúc gắn plan đã lọc is_active
            # (fee_calculation_service), nhưng admin có thể tắt plan SAU đó →
            # không được tiếp tục sinh hóa đơn theo schedule của plan đã tắt.
            if not getattr(fee.installment_plan, "is_active", True):
                raise BusinessRuleViolation(
                    f"Kế hoạch thanh toán '{fee.installment_plan.code}' đã ngừng "
                    "hoạt động — không thể sinh hóa đơn."
                )
            # Use plan's schedule with proper due_days_offset per installment
            installment_schedule = fee.installment_plan.get_installment_schedule(
                amount_to_invoice, anchor_date=anchor_date
            )
        else:
            # Single payment fallback. When anchor_date is provided
            # (tuition HK1 anchored to approval date), set due_date so
            # the invoice loop picks it up instead of falling back to
            # due_date_base + offset.
            entry: dict = {
                "installment_no": 1,
                "amount": amount_to_invoice,
                "due_days_offset": 0,
                "percent": Decimal("100.0"),
                "description": "Thanh toán một lần",
            }
            if anchor_date is not None:
                entry["due_date"] = anchor_date.isoformat()
            installment_schedule = [entry]

        # Generate invoices
        invoices = []
        for item in installment_schedule:
            installment_no = item["installment_no"]
            amount = item["amount"]
            due_days_offset = item.get("due_days_offset", 0)

            # Due date: prefer pre-computed date from anchor_date path
            # (when get_installment_schedule was called with anchor_date).
            # Fall back to due_date_base + offset (legacy path).
            if "due_date" in item and item["due_date"] is not None:
                installment_due = date.fromisoformat(item["due_date"])
            else:
                installment_due = due_date_base + timedelta(days=due_days_offset)

            # Generate unique invoice number
            invoice_number = await self._generate_invoice_number()

            invoice = Invoice(
                fee_id=fee_id,
                invoice_number=invoice_number,
                installment_no=installment_no,
                amount=amount,
                paid_amount=Decimal("0"),
                penalty_amount=Decimal("0"),
                status=InvoiceStatusEnum.draft.value,
                due_date=installment_due,
            )

            self.db.add(invoice)
            invoices.append(invoice)

        await self.db.flush()

        # Refresh to get IDs
        for invoice in invoices:
            await self.db.refresh(invoice)

        # Update fee status to invoiced
        fee.status = FeeStatusEnum.invoiced.value
        await self.db.flush()

        # Auto-issue if requested
        if auto_issue:
            for invoice in invoices:
                invoice.status = InvoiceStatusEnum.issued.value
                invoice.issued_at = datetime.now(timezone.utc)
                invoice.issued_by_id = user_id

            await self.db.flush()

        log.info(
            "invoices_generated",
            fee_id=fee_id,
            invoice_count=len(invoices),
            total_amount=str(amount_to_invoice),
            installment_count=len(installment_schedule),
            auto_issued=auto_issue,
            user_id=user_id,
        )

        # Build post_commit for auto-issued invoices (INVOICE_ISSUED dispatch).
        # Resolve profile/lead/officer once for all invoices in this fee.
        _post_commit_cb = None
        if auto_issue and invoices:
            _lead_id = None
            _officer_id = None
            _lead_full_name = None
            _major_name = None
            _degree_level = None
            if fee.admission_profile_id:
                from sqlalchemy.orm import selectinload as _sil
                _prof_result = await self.db.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == fee.admission_profile_id)
                    .options(
                        _sil(models.AdmissionProfile.lead)
                        .selectinload(models.Lead.offering)
                        .selectinload(models.ProgramOffering.program),
                    )
                )
                _prof = _prof_result.scalar_one_or_none()
                if _prof:
                    _lead_id = _prof.lead_id
                    _lead_obj = getattr(_prof, "lead", None)
                    if _lead_obj is not None:
                        _officer_id = _lead_obj.assigned_officer_id
                        _lead_full_name = _lead_obj.full_name
                        _offering = getattr(_lead_obj, "offering", None)
                        if _offering is not None:
                            _program = getattr(_offering, "program", None)
                            if _program is not None:
                                _major_name = _program.name
                                _degree_level = _program.degree_level

            from app.services.notification_payloads import EventPayload
            _issued_payloads = [
                EventPayload.for_invoice_issued(
                    inv,
                    admission_profile_id=fee.admission_profile_id,
                    lead_id=_lead_id,
                    unit_id=unit_id,
                    officer_id=_officer_id,
                    lead_full_name=_lead_full_name,
                    major_name=_major_name,
                    degree_level=_degree_level,
                )
                for inv in invoices
            ]
            _db = self.db
            # Snapshot rooms pre-commit so post-commit callback doesn't lazy-fetch
            from app.services.notification_dispatcher import rooms_for_admission
            _issued_rooms = rooms_for_admission(_prof) if _prof is not None else ["role_admin"]

            async def _post_commit_cb_fn():
                from app.services.notification_dispatcher import safe_dispatch
                from app.core.events import SystemEvents
                for payload in _issued_payloads:
                    if payload.get("user_id"):
                        await safe_dispatch(
                            db=_db,
                            event=SystemEvents.INVOICE_ISSUED,
                            payload=payload,
                            rooms=_issued_rooms,
                        )

            _post_commit_cb = _post_commit_cb_fn

        return invoices, _post_commit_cb

    async def create_single_invoice(
        self,
        fee_id: int,
        amount: Decimal,
        due_date: date,
        installment_no: int,
        user_id: int,
        unit_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> Tuple[Invoice, Optional[Callable]]:
        """
        Create a single invoice for a fee.

        Use this for manual invoice creation or supplementary invoices.

        Args:
            fee_id: Fee to create invoice for
            amount: Invoice amount
            due_date: Due date
            installment_no: Installment number
            user_id: User creating invoice
            unit_id: Unit ID for IDOR protection
            notes: Optional notes

        Returns:
            Tuple of (Invoice, post_commit_callback)

        Raises:
            ResourceNotFoundError: If fee not found
            BusinessRuleViolation: If amount exceeds remaining balance
            BadRequest: If duplicate installment number
        """
        # Global lock order (review v8): advisory(invoice-number) -> fee-row ->
        # invoice — the SAME order generate_invoices_for_fee uses. Acquire the
        # invoice-number advisory FIRST; v7 took the fee row first, which let
        # create×generate on one fee ABBA-deadlock on (fee-row ↔ number-advisory).
        invoice_number = await self._generate_invoice_number()

        # LOCK the fee row up-front (not get_by_id_with_relations) so the checks
        # below + recompute act on a FRESH fee under the lock (recompute calls
        # db.refresh — get_for_update alone does NOT repopulate an instance already
        # in the session), and FOR UPDATE is taken before the INSERT (no
        # KEY-SHARE→FOR UPDATE upgrade that two concurrent creates would deadlock
        # on). Shares only the fee row with cancel (invoice→fee), so no cycle.
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")

        # H8: Check fee status
        allowed_statuses = [
            FeeStatusEnum.calculated.value,
            FeeStatusEnum.invoiced.value,
            FeeStatusEnum.partial.value,
        ]
        if fee.status not in allowed_statuses:
            raise BusinessRuleViolation(
                f"Cannot create invoice for fee with status '{fee.status}'"
            )

        # Check for duplicate installment
        existing = await self.invoice_repo.get_by_fee_id(
            fee_id, unit_id, active_only=True
        )
        for inv in existing:
            if inv.installment_no == installment_no:
                raise BadRequest(
                    f"Invoice for installment #{installment_no} already exists"
                )

        # Validate amount doesn't exceed remaining
        total_invoiced = sum(inv.amount for inv in existing)
        remaining_to_invoice = fee.final_amount - fee.waived_amount - total_invoiced
        if amount > remaining_to_invoice:
            raise BusinessRuleViolation(
                f"Invoice amount ({amount}) exceeds remaining balance ({remaining_to_invoice})"
            )

        invoice = Invoice(
            fee_id=fee_id,
            invoice_number=invoice_number,
            installment_no=installment_no,
            amount=amount,
            paid_amount=Decimal("0"),
            penalty_amount=Decimal("0"),
            status=InvoiceStatusEnum.draft.value,
            due_date=due_date,
            notes=notes,
        )

        self.db.add(invoice)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # Race: a concurrent create for the same (fee_id, installment_no)
            # slipped past the active_only pre-check and won the INSERT; the
            # partial unique index uq_invoice_fee_installment_active rejects
            # this one. Map the raw DB error to a domain 409, not a 500.
            await self.db.rollback()
            raise DuplicateResourceError(
                f"Invoice for installment #{installment_no} already exists"
            ) from exc
        await self.db.refresh(invoice)

        # Keep Fee.status consistent (PR-B): recompute re-reads the locked fee
        # (db.refresh inside) and updates status from the active-invoice set.
        await self.recompute_fee_from_invoices(fee_id, unit_id)

        log.info(
            "invoice_created",
            invoice_id=invoice.id,
            fee_id=fee_id,
            amount=str(amount),
            installment_no=installment_no,
            user_id=user_id,
        )

        return invoice, None

    # ==========================================================================
    # INVOICE LIFECYCLE
    # ==========================================================================

    async def issue_invoice(
        self,
        invoice_id: int,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Invoice, Optional[Callable]]:
        """
        Issue a draft invoice to the student.

        Args:
            invoice_id: Invoice to issue
            user_id: User issuing invoice
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Invoice, post_commit_callback)

        Raises:
            ResourceNotFoundError: If invoice not found
            BusinessRuleViolation: If invoice not in draft status
        """
        invoice = await self.invoice_repo.get_for_update(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        if invoice.status != InvoiceStatusEnum.draft.value:
            raise BusinessRuleViolation(
                f"Can only issue draft invoices. Current status: {invoice.status}"
            )

        invoice.status = InvoiceStatusEnum.issued.value
        invoice.issued_at = datetime.now(timezone.utc)
        invoice.issued_by_id = user_id

        await self.db.flush()

        log.info(
            "invoice_issued",
            invoice_id=invoice_id,
            invoice_number=invoice.invoice_number,
            user_id=user_id,
        )

        # Resolve profile + lead for notification payload
        _profile = None
        _lead_id = None
        _officer_id = None
        _lead_full_name = None
        _major_name = None
        _degree_level = None
        fee = await self.fee_repo.get_by_id_with_relations(invoice.fee_id, unit_id) if invoice.fee_id else None
        if fee:
            from sqlalchemy.orm import selectinload
            result = await self.db.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == fee.admission_profile_id)
                .options(
                    selectinload(models.AdmissionProfile.lead)
                    .selectinload(models.Lead.offering)
                    .selectinload(models.ProgramOffering.program),
                )
            )
            _profile = result.scalar_one_or_none()
            if _profile:
                _lead_id = _profile.lead_id
                _lead_obj = getattr(_profile, "lead", None)
                if _lead_obj is not None:
                    _officer_id = _lead_obj.assigned_officer_id
                    _lead_full_name = _lead_obj.full_name
                    _offering = getattr(_lead_obj, "offering", None)
                    if _offering is not None:
                        _program = getattr(_offering, "program", None)
                        if _program is not None:
                            _major_name = _program.name
                            _degree_level = _program.degree_level

        from app.services.notification_payloads import EventPayload
        _invoice_payload = EventPayload.for_invoice_issued(
            invoice,
            admission_profile_id=fee.admission_profile_id if fee else None,
            lead_id=_lead_id,
            unit_id=unit_id,
            officer_id=_officer_id,
            lead_full_name=_lead_full_name,
            major_name=_major_name,
            degree_level=_degree_level,
        )
        _db = self.db
        from app.services.notification_dispatcher import rooms_for_admission
        _invoice_rooms = rooms_for_admission(_profile) if _profile is not None else ["role_admin"]

        async def post_commit():
            if not _invoice_payload.get("user_id"):
                return
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents
            await safe_dispatch(
                db=_db,
                event=SystemEvents.INVOICE_ISSUED,
                payload=_invoice_payload,
                rooms=_invoice_rooms,
            )

        return invoice, post_commit

    async def cancel_invoice(
        self,
        invoice_id: int,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Invoice, Optional[Callable]]:
        """
        Cancel an invoice.

        Can only cancel if no payments have been made.

        Args:
            invoice_id: Invoice to cancel
            reason: Cancellation reason (required)
            user_id: User cancelling invoice
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Invoice, post_commit_callback)

        Raises:
            ResourceNotFoundError: If invoice not found
            BusinessRuleViolation: If invoice has payments
        """
        invoice = await self.invoice_repo.get_for_update(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        # Cannot cancel if paid
        if invoice.paid_amount > 0:
            raise BusinessRuleViolation(
                f"Cannot cancel invoice with payments. Paid amount: {invoice.paid_amount}"
            )

        # Cannot cancel already cancelled
        if invoice.status == InvoiceStatusEnum.cancelled.value:
            raise BusinessRuleViolation("Invoice is already cancelled")

        invoice.status = InvoiceStatusEnum.cancelled.value
        invoice.cancelled_at = datetime.now(timezone.utc)
        invoice.cancelled_by_id = user_id
        invoice.cancelled_reason = reason

        await self.db.flush()

        # Nhóm A (PR-B): cancelling an invoice must not leave the parent Fee
        # stranded ('invoiced' while fewer invoices remain billed). Recompute
        # Fee.status from the remaining active invoices in the SAME transaction.
        await self.recompute_fee_from_invoices(invoice.fee_id, unit_id)

        log.info(
            "invoice_cancelled",
            invoice_id=invoice_id,
            invoice_number=invoice.invoice_number,
            reason=reason,
            user_id=user_id,
        )

        return invoice, None

    async def recompute_fee_from_invoices(
        self,
        fee_id: int,
        unit_id: Optional[int] = None,
    ) -> Fee:
        """Recompute ``Fee.status`` from settlement (paid + waived) and whether
        any ACTIVE (non-cancelled) invoice remains.

        Nhóm A balance fix (PR-B): paths that change the active-invoice set
        (cancel, supplemental create) must keep ``Fee.status`` consistent in the
        SAME transaction, else the Fee drifts (status stuck at 'invoiced' with
        fewer invoices than billed).

        Status rules (no 'partially invoiced' enum — don't overload 'partial' =
        "đã thu một phần"):
        - fully settled (``final - waived - paid <= 0``) -> 'paid'. Catches a FULL
          WAIVER too (``waive_fee`` sets 'paid' with ``paid_amount == 0``).
        - else ``paid_amount > 0`` -> 'partial'
        - else any active invoice -> 'invoiced'
        - else -> 'calculated'

        Terminal statuses ('waived', 'cancelled') are deliberate and left as-is.
        Does NOT touch final/waived/paid amounts — a real reduction is a separate
        audited flow. NO over-bill guard here: recompute runs on REDUCTIONS
        (cancel) and must never block clearing an already over-billed fee — a
        post-issue waiver can legitimately make Σ active > (final - waived). The
        over-bill guard lives at invoice CREATION (``create_single_invoice``).
        """
        fee = await self.fee_repo.get_for_update(fee_id, unit_id)
        if not fee:
            raise ResourceNotFoundError("Fee not found")
        # get_for_update does NOT repopulate an instance already in this session
        # (no populate_existing), so force a fresh read under the lock before
        # branching on fee.status/paid/waived — a fee loaded earlier in the same
        # session (e.g. by create_single_invoice) would otherwise be a stale
        # snapshot and we could skip a needed status UPDATE.
        await self.db.refresh(fee)

        # Terminal statuses first: a stale over-billed waived/cancelled fee stays
        # a no-op rather than being recomputed.
        if fee.status in (
            FeeStatusEnum.waived.value,
            FeeStatusEnum.cancelled.value,
        ):
            return fee

        active_count = await self.invoice_repo.count_active_for_fee(fee_id, unit_id)

        # Settled by EITHER payment OR waiver.
        remaining = fee.final_amount - fee.waived_amount - fee.paid_amount
        if remaining <= 0:
            new_status = FeeStatusEnum.paid.value
        elif fee.paid_amount > 0:
            new_status = FeeStatusEnum.partial.value
        elif active_count > 0:
            new_status = FeeStatusEnum.invoiced.value
        else:
            new_status = FeeStatusEnum.calculated.value

        if new_status != fee.status:
            fee.status = new_status
            fee.version += 1  # optimistic-lock token, like every Fee mutator
            await self.db.flush()
        return fee

    async def apply_penalty(
        self,
        invoice_id: int,
        penalty_amount: Decimal,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[Invoice, Optional[Callable]]:
        """
        Apply late payment penalty to an invoice.

        Args:
            invoice_id: Invoice to apply penalty to
            penalty_amount: Penalty amount to add
            reason: Reason for penalty
            user_id: User applying penalty
            unit_id: Unit ID for IDOR protection

        Returns:
            Tuple of (Invoice, post_commit_callback)

        Raises:
            ResourceNotFoundError: If invoice not found
            BusinessRuleViolation: If invoice is paid or cancelled
        """
        invoice = await self.invoice_repo.get_for_update(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")

        # (1) Input: ``is None`` guard cho direct caller (route đã ép required gt=0;
        # HTTP không gửi None được nữa, nhưng service là business boundary → tự bảo
        # vệ khỏi None→TypeError).
        if penalty_amount is None or penalty_amount <= 0:
            raise BadRequest("Penalty amount must be positive")

        # (2) Trạng thái: không áp phạt hóa đơn đã thanh toán / đã hủy.
        if invoice.status in [InvoiceStatusEnum.paid.value, InvoiceStatusEnum.cancelled.value]:
            raise BusinessRuleViolation(
                f"Cannot apply penalty to {invoice.status} invoice"
            )

        # (3) CHỈ áp phạt khi ĐÃ QUÁ HẠN (phí TRỄ hạn): quá ngày đến hạn + chưa thu
        # đủ. Dùng ``is_overdue`` (derived: today > due_date) nên bắt cả HĐ quá hạn
        # mà beat job chưa kịp lật status='overdue'; đồng thời CHẶN áp phạt HĐ chưa
        # tới hạn (issued, due tương lai) — khớp cờ FE can_apply_penalty.
        if not invoice.is_overdue:
            raise BusinessRuleViolation(
                "Chỉ áp phạt cho hóa đơn ĐÃ QUÁ HẠN (quá ngày đến hạn, chưa thu đủ)."
            )

        # (4) Trần: tổng phạt cộng dồn không vượt số tiền hóa đơn (chống áp phạt lặp
        # nhiều lần đẩy nợ vô lý).
        if invoice.penalty_amount + penalty_amount > invoice.amount:
            raise BusinessRuleViolation(
                f"Tổng phạt ({invoice.penalty_amount + penalty_amount}) vượt số "
                f"tiền hóa đơn ({invoice.amount})."
            )

        old_penalty = invoice.penalty_amount
        invoice.penalty_amount = invoice.penalty_amount + penalty_amount
        invoice.notes = f"{invoice.notes or ''}\n[{datetime.now(timezone.utc).isoformat()}] " \
                        f"Penalty +{penalty_amount} VND by user {user_id}. Reason: {reason}"

        await self.db.flush()

        log.info(
            "invoice_penalty_applied",
            invoice_id=invoice_id,
            old_penalty=str(old_penalty),
            new_penalty=str(invoice.penalty_amount),
            added=str(penalty_amount),
            user_id=user_id,
        )

        return invoice, None

    # ==========================================================================
    # OVERDUE PROCESSING
    # ==========================================================================

    @staticmethod
    def _overdue_bucket(days: int) -> str:
        """Compute window bucket for overdue dedup key.

        Groups overdue days into windows: 1, 2-7, 8-14, 15-30, 30+.
        One notification fires per window (not per exact milestone day).
        The dedup key ``overdue:{invoice_id}:{bucket}`` prevents daily
        spam within each window while allowing re-notification when the
        invoice crosses into a new window.
        """
        for threshold in (1, 7, 14, 30):
            if days <= threshold:
                return str(threshold)
        return "30+"

    async def mark_overdue_invoices(
        self,
        unit_id: Optional[int] = None,
        as_of_date: Optional[date] = None,
    ) -> Tuple[List[Invoice], Optional[Callable]]:
        """
        Mark all overdue invoices as overdue + dispatch PAYMENT_OVERDUE.

        Called by a scheduled Celery beat task (daily).

        Returns:
            Tuple of (marked_invoices, post_commit_callback)
        """
        from app.config import settings
        from sqlalchemy.orm import selectinload as _sil

        check_date = as_of_date or date.today()

        # OVERDUE_NOTIFY_SINCE gate: only dispatch for invoices whose
        # due_date >= this threshold to prevent first-run burst.
        notify_since = None
        if settings.OVERDUE_NOTIFY_SINCE:
            notify_since = date.fromisoformat(settings.OVERDUE_NOTIFY_SINCE)

        overdue_invoices = await self.invoice_repo.get_overdue_invoices(
            unit_id=unit_id,
            as_of_date=check_date,
        )

        from app.services.notification_dispatcher import rooms_for_admission

        marked = []
        overdue_payloads = []
        overdue_rooms_list: List[List[str]] = []  # parallel to overdue_payloads

        for invoice in overdue_invoices:
            newly_overdue = invoice.status != InvoiceStatusEnum.overdue.value
            if newly_overdue:
                invoice.status = InvoiceStatusEnum.overdue.value
                marked.append(invoice)

            # Build notification payload if within rollout window
            if notify_since and invoice.due_date and invoice.due_date < notify_since:
                continue  # Pre-rollout invoice, skip notification

            days = (check_date - invoice.due_date).days if invoice.due_date else 0
            bucket = self._overdue_bucket(days)

            # Resolve fee + profile + lead for payload
            fee = await self.db.get(Fee, invoice.fee_id) if invoice.fee_id else None
            _officer_id = None
            _lead_id = None
            _profile_id = None
            _rooms_this: List[str] = ["role_admin"]
            if fee and fee.admission_profile_id:
                _profile_id = fee.admission_profile_id
                prof_result = await self.db.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == fee.admission_profile_id)
                    .options(_sil(models.AdmissionProfile.lead))
                )
                _prof = prof_result.scalar_one_or_none()
                if _prof:
                    _lead_id = _prof.lead_id
                    if getattr(_prof, "lead", None):
                        _officer_id = _prof.lead.assigned_officer_id
                    _rooms_this = rooms_for_admission(_prof)

            overdue_payloads.append({
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "fee_id": invoice.fee_id,
                "fee_type": fee.fee_type if fee else None,
                "semester_no": fee.semester_no if fee else None,
                "amount": str(invoice.amount - invoice.paid_amount),
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                "days_overdue": days,
                "days_overdue_bucket": bucket,
                "installment_no": invoice.installment_no,
                "admission_profile_id": _profile_id,
                "lead_id": _lead_id,
                "unit_id": unit_id,
                "user_id": _officer_id,
            })
            overdue_rooms_list.append(_rooms_this)

        await self.db.flush()

        if marked:
            log.info(
                "invoices_marked_overdue",
                count=len(marked),
                notify_count=len(overdue_payloads),
                as_of_date=str(check_date),
                unit_id=unit_id,
            )

        _db = self.db

        async def _post_commit():
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents
            for payload, rooms_this in zip(overdue_payloads, overdue_rooms_list):
                if payload.get("user_id"):
                    await safe_dispatch(
                        db=_db,
                        event=SystemEvents.PAYMENT_OVERDUE,
                        payload=payload,
                        rooms=rooms_this,
                    )

        return marked, _post_commit

    # ==========================================================================
    # INVOICE RETRIEVAL
    # ==========================================================================

    async def get_invoice(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None,
    ) -> Invoice:
        """Get invoice by ID with all relations."""
        invoice = await self.invoice_repo.get_by_id_with_relations(invoice_id, unit_id)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")
        return invoice

    async def get_invoice_by_number(
        self,
        invoice_number: str,
    ) -> Invoice:
        """Get invoice by invoice number."""
        invoice = await self.invoice_repo.get_by_invoice_number(invoice_number)
        if not invoice:
            raise ResourceNotFoundError("Invoice not found")
        return invoice

    async def get_invoices_for_fee(
        self,
        fee_id: int,
        unit_id: Optional[int] = None,
    ) -> List[Invoice]:
        """Get all invoices for a fee."""
        return await self.invoice_repo.get_by_fee_id(fee_id, unit_id)

    async def get_overdue_invoices(
        self,
        unit_id: Optional[int] = None,
    ) -> List[Invoice]:
        """Get all overdue invoices."""
        return await self.invoice_repo.get_overdue_invoices(unit_id)

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    # Tuition invoice number prefix. Application-fee invoices use a separate
    # ``APP-{fee.id}`` scheme (see admission_service) and never pass through
    # this helper, so the MAX scan below is naturally scoped to INV rows.
    _INVOICE_PREFIX = "INV"

    async def _generate_invoice_number(self) -> str:
        """
        Generate a unique tuition invoice number atomically.

        Format: ``INV-YYYY-NNNNNN`` (e.g. ``INV-2026-000001``).

        Concurrency: a transaction-scoped advisory lock keyed on
        ``(prefix, year)`` serialises allocation so two invoices issued at the
        same instant cannot read the same counter and collide on the
        ``invoice_number`` UNIQUE index (which previously surfaced as an HTTP
        500 under concurrent issue). The lock auto-releases when the
        surrounding transaction commits or rolls back.

        Counter: the next number is ``MAX(existing suffix) + 1`` scoped to
        ``INV-{year}-`` rows whose suffix is purely numeric — replacing the old
        ``COUNT(*) + 1`` over the whole table, which counted ``APP-*`` rows too
        (so INV suffixes jumped and never reset per year). The
        ``~ '^[0-9]{1,9}$'`` guard means a stray non-numeric OR oversized INV
        row can never make the ``CAST`` overflow int4 or throw.
        Note: ``invoice_number_seq`` was never created in prod, so the previous
        code always fell through to that fragile count-based path.

        Returns:
            Unique invoice number string.
        """
        year = datetime.now(timezone.utc).year
        prefix = self._INVOICE_PREFIX

        # Flush pending invoices first so the MAX() scan below sees rows added
        # earlier in the SAME transaction — e.g. sibling installment invoices in
        # one generate_invoices_for_fee batch. Raw text() queries do not trigger
        # the ORM autoflush that the old COUNT(*) select relied on, so make it
        # explicit; otherwise every invoice in a multi-installment batch reads
        # the same MAX and collides on the invoice_number UNIQUE index.
        await self.db.flush()

        # Serialise allocation for this (prefix, year). hashtext() is a stable
        # PostgreSQL hash → deterministic across workers (Python's hash() is
        # per-process salted and must NOT be used for a shared lock key).
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_ns), :year)"),
            {"lock_ns": f"invoice_number:{prefix}", "year": year},
        )

        # Highest suffix already issued for this prefix+year (NULL-safe → 0).
        # The ``split_part ~ '^[0-9]{1,9}$'`` predicate keeps the CAST safe: it
        # excludes any row whose 3rd segment is non-numeric (e.g. a manually
        # inserted ``INV-2026-FOO``) AND any suffix longer than 9 digits, so the
        # CAST can never overflow int4 (max 2,147,483,647) nor throw — one bad
        # row cannot poison generation for the whole year. The timestamped
        # collision fallback ``INV-2026-000001-<ts>`` IS still counted: its 3rd
        # dash-segment is the numeric seq ``000001`` (the ts is the 4th).
        result = await self.db.execute(
            text(
                "SELECT COALESCE(MAX(CAST(split_part(invoice_number, '-', 3) "
                "AS INTEGER)), 0) FROM invoice "
                "WHERE invoice_number LIKE :pattern "
                "AND split_part(invoice_number, '-', 3) ~ '^[0-9]{1,9}$'"
            ),
            {"pattern": f"{prefix}-{year}-%"},
        )
        seq_num = (result.scalar() or 0) + 1

        invoice_number = f"{prefix}-{year}-{seq_num:06d}"

        # Belt-and-suspenders: the advisory lock makes a collision impossible,
        # but verify once and fall back to a timestamped suffix if a row with a
        # non-standard format ever slipped past the MAX scan.
        existing = await self.invoice_repo.get_by_invoice_number(invoice_number)
        if existing:
            ts = int(datetime.now(timezone.utc).timestamp())
            invoice_number = f"{prefix}-{year}-{seq_num:06d}-{ts}"

        return invoice_number

    def _calculate_installment_amounts(
        self,
        total_amount: Decimal,
        installment_count: int,
    ) -> List[Decimal]:
        """
        Calculate installment amounts with proper rounding.

        Uses remainder-in-last strategy: base amount for first n-1 installments,
        remainder goes to last installment. Ensures sum equals total.

        Args:
            total_amount: Total fee amount
            installment_count: Number of installments

        Returns:
            List of amounts per installment
        """
        if installment_count <= 0:
            raise ValueError("Installment count must be positive")

        if installment_count == 1:
            return [total_amount]

        # Calculate base amount (floor division)
        base_amount = (total_amount / installment_count).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # First n-1 installments get base amount
        amounts = [base_amount] * (installment_count - 1)

        # Last installment gets remainder
        remainder = total_amount - (base_amount * (installment_count - 1))
        amounts.append(remainder)

        return amounts
