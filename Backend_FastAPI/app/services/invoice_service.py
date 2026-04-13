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

from sqlalchemy import select, func, text
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
        existing = await self.invoice_repo.get_by_fee_id(fee_id, unit_id)
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
            if fee.admission_profile_id:
                from sqlalchemy.orm import selectinload as _sil
                _prof_result = await self.db.execute(
                    select(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == fee.admission_profile_id)
                    .options(_sil(models.AdmissionProfile.lead))
                )
                _prof = _prof_result.scalar_one_or_none()
                if _prof:
                    _lead_id = _prof.lead_id
                    if getattr(_prof, "lead", None):
                        _officer_id = _prof.lead.assigned_officer_id

            _issued_payloads = []
            for inv in invoices:
                _issued_payloads.append({
                    "invoice_id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "fee_id": inv.fee_id,
                    "amount": str(inv.amount),
                    "due_date": inv.due_date.isoformat() if inv.due_date else None,
                    "admission_profile_id": fee.admission_profile_id,
                    "lead_id": _lead_id,
                    "unit_id": unit_id,
                    "user_id": _officer_id,
                })
            _db = self.db

            async def _post_commit_cb_fn():
                from app.services.notification_dispatcher import safe_dispatch
                from app.core.events import SystemEvents
                for payload in _issued_payloads:
                    if payload.get("user_id"):
                        await safe_dispatch(
                            db=_db,
                            event=SystemEvents.INVOICE_ISSUED,
                            payload=payload,
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
        fee = await self.fee_repo.get_by_id_with_relations(fee_id, unit_id)
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
        existing = await self.invoice_repo.get_by_fee_id(fee_id, unit_id)
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

        # Generate invoice number
        invoice_number = await self._generate_invoice_number()

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
        await self.db.flush()
        await self.db.refresh(invoice)

        # Update fee status if not already invoiced
        if fee.status == FeeStatusEnum.calculated.value:
            fee.status = FeeStatusEnum.invoiced.value
            await self.db.flush()

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
        fee = await self.fee_repo.get_by_id_with_relations(invoice.fee_id, unit_id) if invoice.fee_id else None
        if fee:
            from sqlalchemy.orm import selectinload
            result = await self.db.execute(
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == fee.admission_profile_id)
                .options(selectinload(models.AdmissionProfile.lead))
            )
            _profile = result.scalar_one_or_none()
            if _profile:
                _lead_id = _profile.lead_id
                if hasattr(_profile, "lead") and _profile.lead:
                    _officer_id = _profile.lead.assigned_officer_id

        _invoice_payload = {
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "fee_id": invoice.fee_id,
            "amount": str(invoice.amount),
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            "admission_profile_id": fee.admission_profile_id if fee else None,
            "lead_id": _lead_id,
            "unit_id": unit_id,
            "user_id": _officer_id,
        }
        _db = self.db

        async def post_commit():
            if not _invoice_payload.get("user_id"):
                return
            from app.services.notification_dispatcher import safe_dispatch
            from app.core.events import SystemEvents
            await safe_dispatch(
                db=_db,
                event=SystemEvents.INVOICE_ISSUED,
                payload=_invoice_payload,
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

        log.info(
            "invoice_cancelled",
            invoice_id=invoice_id,
            invoice_number=invoice.invoice_number,
            reason=reason,
            user_id=user_id,
        )

        return invoice, None

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

        if invoice.status in [InvoiceStatusEnum.paid.value, InvoiceStatusEnum.cancelled.value]:
            raise BusinessRuleViolation(
                f"Cannot apply penalty to {invoice.status} invoice"
            )

        if penalty_amount <= 0:
            raise BadRequest("Penalty amount must be positive")

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

        marked = []
        overdue_payloads = []

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
            for payload in overdue_payloads:
                if payload.get("user_id"):
                    await safe_dispatch(
                        db=_db,
                        event=SystemEvents.PAYMENT_OVERDUE,
                        payload=payload,
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

    async def _generate_invoice_number(self) -> str:
        """
        Generate unique invoice number using database sequence.

        Format: INV-YYYY-XXXXXX
        Example: INV-2026-000001

        Returns:
            Unique invoice number string
        """
        year = datetime.now(timezone.utc).year

        # Use PostgreSQL sequence for atomic counter
        # First try to get existing sequence, or use a fallback
        seq_num = None
        try:
            # Use savepoint so failure doesn't abort the whole transaction
            async with self.db.begin_nested():
                result = await self.db.execute(
                    text("SELECT nextval('invoice_number_seq')")
                )
                seq_num = result.scalar()
        except Exception:
            # Sequence doesn't exist - fallback to count-based generation
            pass

        if seq_num is None:
            # Fallback: count existing invoices + 1
            result = await self.db.execute(
                select(func.count(Invoice.id))
            )
            seq_num = (result.scalar() or 0) + 1

        invoice_number = f"INV-{year}-{seq_num:06d}"

        # Verify uniqueness (should not happen with sequence)
        existing = await self.invoice_repo.get_by_invoice_number(invoice_number)
        if existing:
            # Collision - append timestamp
            ts = int(datetime.now(timezone.utc).timestamp())
            invoice_number = f"INV-{year}-{seq_num:06d}-{ts}"

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
