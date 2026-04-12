# app/repositories/fee_repository.py
"""
Fee Repository - Data access layer for Finance Module.

Security Features:
- IDOR Protection: All queries filter through lead.unit_id
- Pessimistic Locking: SELECT FOR UPDATE for concurrent payment handling
- Optimistic Locking: Version column for conflict detection

Architecture:
- Extends BaseRepository for common CRUD operations
- Implements custom queries for fee-specific operations
- Eager loading to prevent N+1 queries
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from typing import List, Optional, Tuple, Union

from sqlalchemy import select, and_, or_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app import models
from app.models.finance import (
    Fee, FeeAppliedDiscount, Invoice, FeeStatusEnum, InvoiceStatusEnum,
    InstallmentPlan,
)
from app.repositories.base import BaseRepository


class FeeRepository(BaseRepository[Fee]):
    """Repository for Fee model operations with IDOR protection."""

    def __init__(self, db: AsyncSession):
        """Initialize Fee repository."""
        super().__init__(db, Fee)

    async def get_by_id_with_relations(
        self,
        fee_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[Fee]:
        """
        Get fee by ID with all related data.

        Args:
            fee_id: Fee ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            Fee with relations or None
        """
        query = (
            select(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Fee.applied_discounts),
                selectinload(Fee.invoices),
                selectinload(Fee.installment_plan),
                joinedload(Fee.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
            )
            .where(Fee.id == fee_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_profile_id(
        self,
        profile_id: int,
        unit_id: Optional[int] = None,
        fee_type: Optional[str] = None
    ) -> List[Fee]:
        """
        Get all fees for an admission profile.

        Args:
            profile_id: Admission profile ID
            unit_id: Filter by lead.unit_id (for IDOR protection)
            fee_type: Optional filter by fee type

        Returns:
            List of fees
        """
        query = (
            select(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Fee.applied_discounts),
                selectinload(Fee.invoices),
            )
            .where(Fee.admission_profile_id == profile_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if fee_type is not None:
            query = query.where(Fee.fee_type == fee_type)

        query = query.order_by(Fee.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_for_update(
        self,
        fee_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[Fee]:
        """
        Get fee with pessimistic lock (SELECT FOR UPDATE).

        CRITICAL: Use this method when processing payments to prevent
        concurrent updates causing lost updates.

        Args:
            fee_id: Fee ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            Locked Fee or None
        """
        query = (
            select(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(Fee.id == fee_id)
            .with_for_update()  # Pessimistic locking
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[Fee]:
        """
        Get filtered list of fees with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, fee_type, profile_id)

        Returns:
            List of Fee instances
        """
        query = (
            select(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Fee.applied_discounts),
                joinedload(Fee.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(Fee.status == filters["status"])

        if filters.get("fee_type"):
            query = query.where(Fee.fee_type == filters["fee_type"])

        if filters.get("profile_id"):
            query = query.where(Fee.admission_profile_id == filters["profile_id"])

        if filters.get("academic_year"):
            query = query.where(Fee.academic_year == filters["academic_year"])

        query = query.order_by(Fee.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        fee_types: Optional[List[str]] = None,
        has_outstanding: Optional[bool] = None,
        **filters
    ) -> Tuple[List[Fee], int]:
        """
        Get filtered list of fees with pagination AND total count.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            statuses: List of statuses to filter
            fee_types: List of fee types to filter
            has_outstanding: Filter by outstanding balance > 0
            **filters: Additional filter parameters

        Returns:
            Tuple of (List of Fee instances, total_count)
        """
        base_conditions = []

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses and len(statuses) > 0:
            base_conditions.append(Fee.status.in_(statuses))

        if fee_types and len(fee_types) > 0:
            base_conditions.append(Fee.fee_type.in_(fee_types))

        if has_outstanding is True:
            # remaining = final_amount - paid_amount - waived_amount > 0
            base_conditions.append(
                (Fee.final_amount - Fee.paid_amount - Fee.waived_amount) > 0
            )

        if filters.get("profile_id"):
            base_conditions.append(Fee.admission_profile_id == filters["profile_id"])

        if filters.get("academic_year"):
            base_conditions.append(Fee.academic_year == filters["academic_year"])

        # Count query
        count_query = (
            select(func.count(Fee.id))
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Fee.applied_discounts),
                joinedload(Fee.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
            )
            .offset(skip)
            .limit(limit)
            .order_by(Fee.created_at.desc())
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        fees = list(result.scalars().all())

        return fees, total

    async def check_duplicate(
        self,
        profile_id: int,
        fee_type: str,
        academic_year: Union[str, int],
        semester_no: Optional[int] = None,
        exclude_id: Optional[int] = None,
    ) -> bool:
        """
        Check if a fee already exists.

        For tuition fees (when ``semester_no`` is provided), checks the
        semester-aware tuple ``(profile, fee_type, semester_no)`` which
        matches the partial unique index ``uq_fee_profile_type_semester_tuition``.

        For non-tuition fees (``semester_no=None``), keeps the legacy
        year-based tuple ``(profile, fee_type, academic_year)`` which
        matches ``uq_fee_profile_type_year_nontuition``.

        Args:
            profile_id: Admission profile ID
            fee_type: Fee type
            academic_year: Academic year (e.g., "2025" or 2025)
            semester_no: Semester number for tuition fees (None for non-tuition)
            exclude_id: Exclude this fee ID from check (for updates)

        Returns:
            True if duplicate exists
        """
        if fee_type == "tuition" and semester_no is not None:
            query = (
                select(func.count(Fee.id))
                .where(
                    and_(
                        Fee.admission_profile_id == profile_id,
                        Fee.fee_type == fee_type,
                        Fee.semester_no == semester_no,
                    )
                )
            )
        else:
            if isinstance(academic_year, str):
                academic_year_int = int(academic_year.split("-")[0])
            else:
                academic_year_int = academic_year

            query = (
                select(func.count(Fee.id))
                .where(
                    and_(
                        Fee.admission_profile_id == profile_id,
                        Fee.fee_type == fee_type,
                        Fee.academic_year == academic_year_int,
                    )
                )
            )

        if exclude_id is not None:
            query = query.where(Fee.id != exclude_id)

        result = await self.db.execute(query)
        count = result.scalar() or 0
        return count > 0

    async def update_paid_amount(
        self,
        fee_id: int,
        amount_to_add: Decimal,
        expected_version: int
    ) -> Optional[Fee]:
        """
        Update fee paid amount with optimistic locking.

        Args:
            fee_id: Fee ID
            amount_to_add: Amount to add to paid_amount
            expected_version: Expected version for optimistic lock check

        Returns:
            Updated Fee or None if version mismatch

        Raises:
            ConflictError: If version mismatch (optimistic lock failure)
        """
        fee = await self.get_for_update(fee_id)
        if not fee:
            return None

        # Optimistic lock check
        if fee.version != expected_version:
            from app.utils.exceptions import ConflictError
            raise ConflictError(
                f"Fee {fee_id} was modified by another transaction. "
                f"Expected version {expected_version}, found {fee.version}"
            )

        # Update paid amount
        fee.paid_amount = fee.paid_amount + amount_to_add
        fee.version += 1  # Increment version

        # Update status if fully paid
        remaining = fee.final_amount - fee.paid_amount - fee.waived_amount
        if remaining <= 0:
            fee.status = FeeStatusEnum.paid.value

        await self.db.flush()
        await self.db.refresh(fee)
        return fee


    async def get_installment_plan_by_code(
        self,
        code: str,
    ) -> Optional["InstallmentPlan"]:
        """
        Get installment plan by its unique code.

        Args:
            code: Plan code (e.g., "FULL", "TWO_TERM", "QUARTERLY")

        Returns:
            InstallmentPlan or None
        """
        query = select(InstallmentPlan).where(
            and_(InstallmentPlan.code == code, InstallmentPlan.is_active == True)
        )
        result = await self.db.execute(query)
        return result.scalars().first()


class InvoiceRepository(BaseRepository[Invoice]):
    """Repository for Invoice model operations with IDOR protection."""

    def __init__(self, db: AsyncSession):
        """Initialize Invoice repository."""
        super().__init__(db, Invoice)

    async def get_by_id_with_relations(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[Invoice]:
        """
        Get invoice by ID with all related data.

        Args:
            invoice_id: Invoice ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            Invoice with relations or None
        """
        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Invoice.payments),
                selectinload(Invoice.payment_intents),
                joinedload(Invoice.fee).joinedload(Fee.admission_profile),
            )
            .where(Invoice.id == invoice_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_by_fee_id(
        self,
        fee_id: int,
        unit_id: Optional[int] = None
    ) -> List[Invoice]:
        """
        Get all invoices for a fee.

        Args:
            fee_id: Fee ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            List of invoices
        """
        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                selectinload(Invoice.payments),
            )
            .where(Invoice.fee_id == fee_id)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        query = query.order_by(Invoice.installment_no)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_for_update(
        self,
        invoice_id: int,
        unit_id: Optional[int] = None
    ) -> Optional[Invoice]:
        """
        Get invoice with pessimistic lock (SELECT FOR UPDATE).

        Args:
            invoice_id: Invoice ID
            unit_id: Filter by lead.unit_id (for IDOR protection)

        Returns:
            Locked Invoice or None
        """
        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(Invoice.id == invoice_id)
            .with_for_update()
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_filtered(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        **filters
    ) -> List[Invoice]:
        """
        Get filtered list of invoices with pagination.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            **filters: Filter parameters (status, fee_id, overdue)

        Returns:
            List of Invoice instances
        """
        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Invoice.fee),
            )
            .offset(skip)
            .limit(limit)
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        if filters.get("status"):
            query = query.where(Invoice.status == filters["status"])

        if filters.get("fee_id"):
            query = query.where(Invoice.fee_id == filters["fee_id"])

        if filters.get("overdue"):
            # Overdue = due_date < today AND status in (draft, issued)
            today = date.today()
            query = query.where(
                and_(
                    Invoice.due_date < today,
                    Invoice.status.in_([
                        InvoiceStatusEnum.draft.value,
                        InvoiceStatusEnum.issued.value
                    ])
                )
            )

        query = query.order_by(Invoice.due_date)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        fee_id: Optional[int] = None,
        overdue_only: Optional[bool] = None,
    ) -> Tuple[List[Invoice], int]:
        """
        Get filtered list of invoices with pagination AND total count.

        Args:
            skip: Number of records to skip
            limit: Maximum records to return
            unit_id: Filter by lead.unit_id (for IDOR protection)
            statuses: List of statuses to filter
            fee_id: Filter by fee ID
            overdue_only: Filter only overdue invoices

        Returns:
            Tuple of (List of Invoice instances, total_count)
        """
        base_conditions = []

        # IDOR Filter
        if unit_id is not None:
            base_conditions.append(models.Lead.unit_id == unit_id)

        if statuses and len(statuses) > 0:
            base_conditions.append(Invoice.status.in_(statuses))

        if fee_id:
            base_conditions.append(Invoice.fee_id == fee_id)

        if overdue_only:
            today = date.today()
            base_conditions.append(
                and_(
                    Invoice.due_date < today,
                    Invoice.status.in_([
                        InvoiceStatusEnum.draft.value,
                        InvoiceStatusEnum.issued.value
                    ])
                )
            )

        # Count query
        count_query = (
            select(func.count(Invoice.id))
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
        )
        if base_conditions:
            count_query = count_query.where(and_(*base_conditions))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Data query
        data_query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Invoice.fee).joinedload(Fee.admission_profile).joinedload(
                    models.AdmissionProfile.lead
                ),
            )
            .offset(skip)
            .limit(limit)
            .order_by(Invoice.due_date)
        )
        if base_conditions:
            data_query = data_query.where(and_(*base_conditions))

        result = await self.db.execute(data_query)
        invoices = list(result.scalars().all())

        return invoices, total

    async def get_overdue_invoices(
        self,
        unit_id: Optional[int] = None,
        as_of_date: Optional[date] = None
    ) -> List[Invoice]:
        """
        Get all overdue invoices.

        Args:
            unit_id: Filter by lead.unit_id (for IDOR protection)
            as_of_date: Date to check overdue against (default: today)

        Returns:
            List of overdue invoices
        """
        check_date = as_of_date or date.today()

        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .options(
                joinedload(Invoice.fee).joinedload(Fee.admission_profile),
            )
            .where(
                and_(
                    Invoice.due_date < check_date,
                    Invoice.status.in_([
                        InvoiceStatusEnum.draft.value,
                        InvoiceStatusEnum.issued.value
                    ])
                )
            )
        )

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        query = query.order_by(Invoice.due_date)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_invoice_number(
        self,
        invoice_number: str
    ) -> Optional[Invoice]:
        """
        Get invoice by invoice number.

        Args:
            invoice_number: Unique invoice number

        Returns:
            Invoice or None
        """
        query = (
            select(Invoice)
            .options(
                selectinload(Invoice.payments),
                joinedload(Invoice.fee),
            )
            .where(Invoice.invoice_number == invoice_number)
        )

        result = await self.db.execute(query)
        return result.scalars().first()

    async def update_paid_amount(
        self,
        invoice_id: int,
        amount_to_add: Decimal
    ) -> Optional[Invoice]:
        """
        Update invoice paid amount.

        Args:
            invoice_id: Invoice ID
            amount_to_add: Amount to add to paid_amount

        Returns:
            Updated Invoice or None
        """
        invoice = await self.get_for_update(invoice_id)
        if not invoice:
            return None

        invoice.paid_amount = invoice.paid_amount + amount_to_add

        # Update status if fully paid
        remaining = invoice.amount - invoice.paid_amount
        if remaining <= 0:
            invoice.status = InvoiceStatusEnum.paid.value
            invoice.paid_at = datetime.now(timezone.utc)

        await self.db.flush()
        await self.db.refresh(invoice)
        return invoice
