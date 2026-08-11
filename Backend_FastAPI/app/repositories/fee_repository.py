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

import re
import unicodedata
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Tuple, Union

from sqlalchemy import select, and_, or_, func, desc, asc, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, noload, selectinload

from app import models
from app.models.finance import (
    Fee, FeeAppliedDiscount, Invoice, FeeStatusEnum, InvoiceStatusEnum,
    InstallmentPlan, OVERDUE_DERIVED_STATUSES,
)
from app.repositories.base import BaseRepository
from app.utils.text_helpers import escape_like_pattern, LIKE_ESCAPE_CHAR


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
        fee_type: Optional[str] = None,
        semester_no: Optional[int] = None,
    ) -> List[Fee]:
        """
        Get all fees for an admission profile.

        Args:
            profile_id: Admission profile ID
            unit_id: Filter by lead.unit_id (for IDOR protection)
            fee_type: Optional filter by fee type
            semester_no: Optional filter by semester number (PR 4)

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

        if semester_no is not None:
            query = query.where(Fee.semester_no == semester_no)

        query = query.order_by(Fee.created_at.desc())

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def has_active_tuition_fee(self, profile_id: int) -> bool:
        """True if a NON-cancelled tuition fee exists for the profile.

        Used by the choice-mutation finance lock. Excludes ``cancelled`` — a
        cancelled fee no longer commits the profile to a ngành, so it must not
        freeze NV edits (otherwise a prepay→cancel→rollback profile is locked
        out of editing its own NVs forever). EXISTS-style (``LIMIT 1``, id only)
        so it does not hydrate fee children / discounts / invoices.
        """
        result = await self.db.execute(
            select(Fee.id)
            .where(
                Fee.admission_profile_id == profile_id,
                Fee.fee_type == "tuition",
                Fee.status != "cancelled",
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def sum_paid_amount_by_profile(self, profile_id: int) -> Decimal:
        """Sum of ``paid_amount`` across all fees of an admission profile.

        Because a processed refund DECREMENTS ``fee.paid_amount``
        (``payment_service.process_approved_refund``), this sum is exactly the
        money currently HELD against the profile (i.e. collected and NOT yet
        refunded). Used to flag "đã thu học phí nhưng chưa hoàn" on a
        rejected/withdrawn profile (no IDOR filter needed — the caller has
        already authorized access to the profile).

        Returns ``Decimal("0")`` when the profile has no fees.
        """
        result = await self.db.execute(
            select(func.coalesce(func.sum(Fee.paid_amount), 0)).where(
                Fee.admission_profile_id == profile_id
            )
        )
        return Decimal(str(result.scalar() or 0))

    async def sum_unrefunded_refundable_paid(self, profile_id: int) -> Decimal:
        """Sum of ``paid_amount`` across REFUNDABLE fees still unrefunded.

        Identical to ``sum_paid_amount_by_profile`` but EXCLUDES the
        ``application`` fee (lệ phí xét tuyển) which is non-refundable and
        therefore keeps ``paid_amount > 0`` forever. This is the amount that
        determines whether a withdraw must wait in ``withdrawal_pending``
        (PR-B): using the all-fees total instead would trap the profile in
        ``withdrawal_pending`` permanently whenever an application fee was paid.

        A processed refund DECREMENTS ``fee.paid_amount``, so this sum is exactly
        the refundable money currently HELD (collected and NOT yet refunded).
        Returns ``Decimal("0")`` when there is no unrefunded refundable balance.
        """
        result = await self.db.execute(
            select(func.coalesce(func.sum(Fee.paid_amount), 0)).where(
                Fee.admission_profile_id == profile_id,
                Fee.fee_type != "application",
            )
        )
        return Decimal(str(result.scalar() or 0))

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

        # Đổi ngành: lọc "đang chờ kế toán xác nhận" — nguồn của tab worklist kế
        # toán. Không có bộ lọc này thì đường DUY NHẤT tới nút xác nhận là
        # notification; prod chỉ 1 kế toán nên bỏ lỡ thông báo là hồ sơ đứng im
        # (mọi hành động approve/publish/enroll/xuất-giấy đang bị chặn chờ họ).
        if filters.get("awaiting_major_change") is True:
            base_conditions.append(
                Fee.awaiting_accountant_confirmation.is_(True)
            )

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

    async def get_many_for_export(self, fee_ids: List[int]) -> List[Fee]:
        """Nạp khoản phí theo id, eager-load đủ mọi thứ file xuất cần đọc.

        Eager-load là BẮT BUỘC, không phải tối ưu: file xuất đọc tên officer,
        tên thí sinh, tên ngành và tên đơn vị cho TỪNG dòng — lazy-load sẽ thành
        4 truy vấn mỗi dòng (và ``MissingGreenlet`` ngoài session async).

        ⚠️ Sắp xếp theo ``Fee.admission_profile_id`` (cột FK có sẵn trên Fee),
        KHÔNG phải ``AdmissionProfile.id``: bảng đó chỉ xuất hiện qua eager-load
        nên không nằm trong FROM của câu SELECT này.
        """
        if not fee_ids:
            return []

        query = (
            select(Fee)
            .where(Fee.id.in_(fee_ids))
            .options(
                joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead)
                .joinedload(models.Lead.assigned_officer),
                joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead)
                .joinedload(models.Lead.unit),
                joinedload(Fee.resolved_major),
                # 🔴 Chặn các quan hệ khai ``lazy="selectin"`` — chúng tự bắn
                # truy vấn dù KHÔNG có trong options() và tệp xuất không đọc ô
                # nào của chúng. Đo trên dev: 3 khoản phí → 9 SELECT (invoice,
                # fee_applied_discount, payment, payment_intent,
                # payment_transaction…). Ở mức trần 10.000 dòng, phần thừa này
                # còn kéo theo mọi hoá đơn/giao dịch của chúng.
                noload(Fee.invoices),
                noload(Fee.applied_discounts),
            )
            .order_by(Fee.admission_profile_id.asc(), Fee.id.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

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
        # Exclude cancelled fees: they no longer occupy the partial unique
        # index (uq_fee_*_active, status <> 'cancelled'), so a fee that was
        # cancelled (e.g. tính nhầm) must NOT block re-calculating a correct
        # one. Keep this predicate in lock-step with those partial indexes.
        not_cancelled = Fee.status != FeeStatusEnum.cancelled.value
        if fee_type == "tuition" and semester_no is not None:
            query = (
                select(func.count(Fee.id))
                .where(
                    and_(
                        Fee.admission_profile_id == profile_id,
                        Fee.fee_type == fee_type,
                        Fee.semester_no == semester_no,
                        not_cancelled,
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
                        not_cancelled,
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

    async def get_major_name_by_academic_info(
        self, academic_info_id: Optional[int]
    ) -> Optional[str]:
        """F12 — tên ngành (MajorProgram.name) từ ``offering_academic_info_id``
        qua join ai → offering → major. Dùng bởi enrich dialog đổi ngành (chuyển
        SQL khỏi router theo CLAUDE.md 'No direct SQL in Routers')."""
        if academic_info_id is None:
            return None
        return (
            await self.db.execute(
                select(models.MajorProgram.name)
                .select_from(models.OfferingAcademicInfo)
                .join(
                    models.ProgramOffering,
                    models.ProgramOffering.id
                    == models.OfferingAcademicInfo.offering_id,
                )
                .join(
                    models.MajorProgram,
                    models.MajorProgram.id == models.ProgramOffering.program_id,
                )
                .where(models.OfferingAcademicInfo.id == academic_info_id)
            )
        ).scalar_one_or_none()

    async def get_major_name_by_id(
        self, major_id: Optional[int]
    ) -> Optional[str]:
        """F12 — tên ngành trực tiếp theo ``MajorProgram.id``."""
        if major_id is None:
            return None
        return (
            await self.db.execute(
                select(models.MajorProgram.name).where(
                    models.MajorProgram.id == major_id
                )
            )
        ).scalar_one_or_none()


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
                joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead),
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
        unit_id: Optional[int] = None,
        active_only: bool = False,
    ) -> List[Invoice]:
        """
        Get all invoices for a fee.

        Args:
            fee_id: Fee ID
            unit_id: Filter by lead.unit_id (for IDOR protection)
            active_only: When True, exclude cancelled invoices. Default False
                keeps the legacy behaviour — display/audit callers must still
                see cancelled rows. Only the duplicate-guard callers in
                InvoiceService pass True so a cancelled installment no longer
                blocks re-creating that installment (PR-A).

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

        if active_only:
            # 'cancelled' is the only non-active invoice state today; the partial
            # unique index uq_invoice_fee_installment_active uses the same
            # predicate so this guard and the DB constraint stay in agreement.
            query = query.where(Invoice.status != 'cancelled')

        # IDOR Filter
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        query = query.order_by(Invoice.installment_no)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_active_for_fee(
        self,
        fee_id: int,
        unit_id: Optional[int] = None,
    ) -> int:
        """Count non-cancelled invoices for a fee (IDOR-scoped).

        Cheap aggregate for the Fee.status recompute (PR-B) — a single COUNT, no
        payment hydration (unlike ``get_by_fee_id`` which selectinloads payments).
        """
        query = (
            select(func.count(Invoice.id))
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(
                Invoice.fee_id == fee_id,
                Invoice.status != 'cancelled',
            )
        )
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)
        result = await self.db.execute(query)
        return int(result.scalar() or 0)

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

    async def khoa_moi_invoice_cua_fee(
        self,
        fee_ids: List[int],
        unit_id: Optional[int] = None,
    ) -> List[Invoice]:
        """Khoá MỌI hàng invoice thuộc các khoản phí — và CHỈ hàng invoice.

        Dành riêng cho đường nhập lô. Khác ``get_for_update`` ở đúng một điểm,
        nhưng điểm đó là cả lý do hàm này tồn tại: ``FOR UPDATE`` **OF invoice**
        thay vì ``FOR UPDATE`` trần. Câu trần khoá hàng của mọi bảng trong
        ``FROM`` — gồm cả ``fee`` — nên dùng nó ở pha khoá đầu sẽ kéo ``fee``
        vào theo thứ tự của ``invoice``, đúng thứ mà bản vá thứ tự khoá đang
        gỡ bỏ.

        ⚠️ **Đừng "hợp nhất" hàm này với ``get_for_update``.** Ngữ nghĩa khoá
        kèm ``fee`` của hàm kia là hàng rào mà đường ghi tay đang dựa vào (xem
        ``payment_service.record_manual_payment``): hai request ghi vào hai đợt
        khác nhau của cùng một khoản phí cần một điểm gặp chung. Đổi hàm kia
        sang ``OF invoice`` sẽ lặng lẽ tháo hàng rào ấy.

        Khoá **mọi** đợt, không lọc payable: đường ghi tay có thể chạm một đợt
        đã thu đủ, và invariant cần giữ là "sau khi bắt đầu khoá Fee, nhập lô
        tuyệt đối không xin thêm khoá Invoice nào" — muốn vậy thì pha đầu phải
        cầm trọn tập, không cầm phần dự đoán sẽ dùng.

        ``ORDER BY (fee_id, id)`` cho thứ tự khoá xác định giữa hai lượt nhập
        lô bất kỳ. Nút ``LockRows`` nằm TRÊN nút sắp xếp, nên hàng được khoá
        theo đúng thứ tự này.
        """
        if not fee_ids:
            return []

        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(Invoice.fee_id.in_(list(fee_ids)))
            .order_by(Invoice.fee_id, Invoice.id)
            .with_for_update(of=Invoice)
        )

        # IDOR Filter — cùng đường với get_for_update.
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def khoa_invoice_theo_id(
        self,
        invoice_ids: List[int],
        unit_id: Optional[int] = None,
    ) -> List[Invoice]:
        """Khoá một TẬP hàng invoice theo id tăng dần — và CHỈ hàng invoice.

        Dành cho đường chạm HAI hoá đơn trong cùng một giao dịch (áp khoản dư:
        rời hoá đơn nguồn, vào hoá đơn đích). Khoá từng cái bằng
        ``get_for_update`` là đủ để kẹt chéo: hàm ấy ``FOR UPDATE`` trần nên
        kéo cả ``fee``/``profile``/``lead`` vào theo thứ tự của ``invoice``,
        và hai lượt áp khoản dư ngược chiều nhau (X→Y và Y→X) tạo đúng chu kỳ
        mà quy ước thứ tự khoá dựng lên để tránh.

        ``ORDER BY id`` + ``LockRows`` nằm trên nút sắp xếp ⇒ mọi luồng khoá
        cùng một thứ tự, nên hai luồng bất kỳ gặp nhau ở hàng nhỏ nhất thay vì
        ôm chéo. Cùng quy ước với ``khoa_moi_invoice_cua_fee`` của đường nhập
        lô: **invoice trước, fee sau**; sau khi bắt đầu khoá Fee thì tuyệt đối
        không xin thêm khoá Invoice nào.

        Trả về theo thứ tự đã khoá; caller tự map theo ``id`` và tự quyết định
        thiếu hàng nào thì lỗi gì — hàm này không đoán hộ.
        """
        if not invoice_ids:
            return []

        query = (
            select(Invoice)
            .join(Fee)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(Invoice.id.in_(sorted(set(invoice_ids))))
            .order_by(Invoice.id)
            .with_for_update(of=Invoice)
        )

        # IDOR Filter — cùng đường với get_for_update.
        if unit_id is not None:
            query = query.where(models.Lead.unit_id == unit_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

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

    # ------------------------------------------------------------------
    # Shared list/counts plumbing — list and status-counts MUST build the
    # same WHERE so a tab's count always equals the rows it returns.
    # ------------------------------------------------------------------
    @staticmethod
    def _overdue_predicate(today: date):
        """Derived "overdue": a billed-but-unsettled invoice that is past due.

        ``status IN OVERDUE_DERIVED_STATUSES (issued/partial/overdue) AND
        due_date < today`` — a SUPERSET of the enum ``overdue`` status set nightly
        by the beat job ``invoice_service.mark_overdue_invoices`` (the
        issued/partial legs catch rows not yet transitioned; the overdue leg keeps
        transitioned ones). Single source (model OVERDUE_DERIVED_STATUSES) for
        spine / "Quá hạn" tab / sort / rail / is_overdue. ``today`` is passed in
        (computed once per request) so predicate/sort/is_overdue never straddle
        midnight inconsistently.
        """
        return and_(
            Invoice.due_date < today,
            Invoice.status.in_(OVERDUE_DERIVED_STATUSES),
        )

    @staticmethod
    def _build_invoice_list_conditions(
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        fee_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        overdue_only: Optional[bool] = None,
        search: Optional[str] = None,
        fee_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        today: Optional[date] = None,
        major_id: Optional[int] = None,
        degree_level: Optional[str] = None,
        academic_year: Optional[int] = None,
        semester_no: Optional[int] = None,
        officer_id: Optional[int] = None,
        unit_id_filter: Optional[int] = None,
        due_window: Optional[str] = None,
        awaiting_major_change: Optional[bool] = None,
    ) -> list:
        """Build the shared WHERE for the invoice list + status-counts.

        Assumes the query joins Invoice -> Fee -> AdmissionProfile -> Lead.

        Filter ngành/trình độ đọc ``Fee.resolved_major_id`` /
        ``Fee.resolved_degree_level`` (snapshot denormalized — single source of
        truth, đúng admitted-choice cho multi-NV), KHÔNG join offering/program
        nên cả list + status-counts dùng chung không cần thêm join → parity.
        """
        today = today or date.today()
        conditions = []
        # IDOR (None = admin/accountant global scope)
        if unit_id is not None:
            conditions.append(models.Lead.unit_id == unit_id)
        # Unit filter (manager/admin chọn đơn vị cụ thể) — INTERSECT với IDOR
        # scope ở trên (ANDed): officer bị clamp unit_id của mình nên truyền
        # unit_id_filter khác cũng ra rỗng, KHÔNG nới quyền.
        if unit_id_filter is not None:
            conditions.append(models.Lead.unit_id == unit_id_filter)
        if statuses:
            conditions.append(Invoice.status.in_(statuses))
        if fee_id:
            conditions.append(Invoice.fee_id == fee_id)
        if profile_id:
            conditions.append(Fee.admission_profile_id == profile_id)
        if fee_type:
            conditions.append(Fee.fee_type == fee_type)
        if major_id is not None:
            conditions.append(Fee.resolved_major_id == major_id)
        if degree_level:
            conditions.append(Fee.resolved_degree_level == degree_level)
        if academic_year is not None:
            conditions.append(Fee.academic_year == academic_year)
        if semester_no is not None:
            conditions.append(Fee.semester_no == semester_no)
        if officer_id is not None:
            conditions.append(models.Lead.assigned_officer_id == officer_id)
        # Hạn thanh toán: "sắp đến hạn ≤7 ngày" = invoice chưa thu (issued/
        # partial/overdue-enum) due trong [today, today+7]; "overdue" = derived
        # predicate. Tự chứa trong builder → list + counts khớp.
        if due_window == "due_soon_7d":
            conditions.append(Invoice.due_date >= today)
            conditions.append(Invoice.due_date <= today + timedelta(days=7))
            conditions.append(Invoice.status.in_(OVERDUE_DERIVED_STATUSES))
        elif due_window == "overdue":
            conditions.append(InvoiceRepository._overdue_predicate(today))
        if overdue_only:
            conditions.append(InvoiceRepository._overdue_predicate(today))
        # Đổi ngành: lens "chờ kế toán xác nhận" — ORTHOGONAL với trạng thái hoá
        # đơn (một hoá đơn issued/partial vẫn có thể đang chờ), giống lens "Quá
        # hạn". Đọc cờ trên Fee cha (đã join sẵn) nên list + status-counts dùng
        # chung điều kiện này ⇒ số trên tab luôn khớp số dòng khi bấm vào.
        if awaiting_major_change:
            conditions.append(Fee.awaiting_accountant_confirmation.is_(True))
        if date_from:
            conditions.append(Invoice.due_date >= date_from)
        if date_to:
            conditions.append(Invoice.due_date <= date_to)
        if search and search.strip():
            # NFC + central LIKE escaping (shared helper used across repos).
            normalized = unicodedata.normalize("NFC", search.strip())
            term = f"%{escape_like_pattern(normalized)}%"
            search_or = [
                Invoice.invoice_number.ilike(term, escape=LIKE_ESCAPE_CHAR),
                func.f_unaccent(models.Lead.full_name).ilike(
                    func.f_unaccent(term), escape=LIKE_ESCAPE_CHAR
                ),
                # Accountants receiving a profile from an officer often look it up
                # by the parent's phone (plain ilike — digits, no diacritics).
                models.Lead.phone.ilike(term, escape=LIKE_ESCAPE_CHAR),
            ]
            # "HS-000131" or a bare profile id -> match AdmissionProfile.id.
            digits = re.sub(r"\D", "", normalized)
            if digits and (normalized.upper().startswith("HS") or normalized.isdigit()):
                # A profile id is a PostgreSQL int4. ``int(digits)`` NEVER raises
                # in Python (arbitrary precision), so the old try/except was a
                # no-op: a long numeric search (a pasted phone / mã ~11+ digits)
                # bound an out-of-int32 value into AdmissionProfile.id → asyncpg
                # DataError → 500 on BOTH list_invoices and get_status_counts
                # (observed 126×/72h on prod). Range-guard instead — out of int4
                # range means "no such profile", so just skip the id branch
                # (mirrors search_calculable_profiles in fee_calculation_service).
                pid_val = int(digits)
                if 1 <= pid_val <= 2147483647:
                    search_or.append(models.AdmissionProfile.id == pid_val)
            conditions.append(or_(*search_or))
        return conditions

    @staticmethod
    def _invoice_sort_clause(
        sort_by: Optional[str], sort_order: Optional[str], today: date
    ):
        """ORDER BY for the invoice list. Default = actionable-first priority.

        ``Invoice.id`` is appended as a UNIQUE tiebreaker on EVERY branch so
        pagination is deterministic — without it, rows sharing a status + due_date
        (e.g. a batch of same-day tuition invoices) order arbitrarily and a row
        can appear on two pages or be skipped across offset/limit.
        """
        descending = (sort_order or "asc").lower() == "desc"
        direction = desc if descending else asc
        if sort_by == "due_date":
            return [direction(Invoice.due_date), asc(Invoice.id)]
        if sort_by == "amount":
            return [direction(Invoice.amount), asc(Invoice.id)]
        if sort_by == "paid":
            return [direction(Invoice.paid_amount), asc(Invoice.id)]
        if sort_by == "remaining":
            # Khớp Invoice.remaining_amount = amount + penalty - paid (clamp ≥0).
            remaining_expr = func.greatest(
                Invoice.amount + Invoice.penalty_amount - Invoice.paid_amount, 0
            )
            return [direction(remaining_expr), asc(Invoice.id)]
        if sort_by == "status":
            return [direction(Invoice.status), asc(Invoice.due_date), asc(Invoice.id)]
        if sort_by == "created_at":
            return [direction(Invoice.created_at), asc(Invoice.id)]
        # Default "priority": overdue (derived) > issued > partial > draft >
        # paid > cancelled, then earliest due first, then id. Branch 0 reuses
        # _overdue_predicate so a beat-transitioned enum 'overdue' row stays at
        # the TOP (not dumped into else_ below cancelled).
        priority = case(
            (InvoiceRepository._overdue_predicate(today), 0),
            (Invoice.status == InvoiceStatusEnum.overdue.value, 1),
            (Invoice.status == InvoiceStatusEnum.issued.value, 2),
            (Invoice.status == InvoiceStatusEnum.partial.value, 3),
            (Invoice.status == InvoiceStatusEnum.draft.value, 4),
            (Invoice.status == InvoiceStatusEnum.paid.value, 5),
            (Invoice.status == InvoiceStatusEnum.cancelled.value, 6),
            else_=7,
        )
        return [asc(priority), asc(Invoice.due_date), asc(Invoice.id)]

    async def get_filtered_with_count(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        fee_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        overdue_only: Optional[bool] = None,
        search: Optional[str] = None,
        fee_type: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        today: Optional[date] = None,
        major_id: Optional[int] = None,
        degree_level: Optional[str] = None,
        academic_year: Optional[int] = None,
        semester_no: Optional[int] = None,
        officer_id: Optional[int] = None,
        unit_id_filter: Optional[int] = None,
        due_window: Optional[str] = None,
        awaiting_major_change: Optional[bool] = None,
    ) -> Tuple[List[Invoice], int]:
        """Filtered + paginated invoice list WITH total count (IDOR by unit)."""
        today = today or date.today()  # one "today" → predicate + sort agree
        conditions = self._build_invoice_list_conditions(
            unit_id=unit_id, statuses=statuses, fee_id=fee_id,
            profile_id=profile_id, overdue_only=overdue_only, search=search,
            fee_type=fee_type, date_from=date_from, date_to=date_to, today=today,
            major_id=major_id, degree_level=degree_level,
            academic_year=academic_year, semester_no=semester_no,
            officer_id=officer_id, unit_id_filter=unit_id_filter,
            due_window=due_window, awaiting_major_change=awaiting_major_change,
        )

        count_query = (
            select(func.count(Invoice.id))
            .join(Fee).join(models.AdmissionProfile).join(models.Lead)
        )
        if conditions:
            count_query = count_query.where(and_(*conditions))
        total = (await self.db.execute(count_query)).scalar() or 0

        data_query = (
            select(Invoice)
            .join(Fee).join(models.AdmissionProfile).join(models.Lead)
            .options(
                joinedload(Invoice.fee)
                .joinedload(Fee.admission_profile)
                .joinedload(models.AdmissionProfile.lead)
                .joinedload(models.Lead.assigned_officer),
                # Ngành/trình độ hiển thị đọc từ snapshot Fee.resolved_major
                # (single source khớp filter) — KHÔNG còn lead.offering.program.
                joinedload(Invoice.fee).joinedload(Fee.resolved_major),
            )
            .order_by(*self._invoice_sort_clause(sort_by, sort_order, today))
            .offset(skip)
            .limit(limit)
        )
        if conditions:
            data_query = data_query.where(and_(*conditions))

        result = await self.db.execute(data_query)
        invoices = list(result.scalars().all())
        return invoices, total

    async def get_status_counts(
        self,
        unit_id: Optional[int] = None,
        fee_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        search: Optional[str] = None,
        fee_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        today: Optional[date] = None,
        major_id: Optional[int] = None,
        degree_level: Optional[str] = None,
        academic_year: Optional[int] = None,
        semester_no: Optional[int] = None,
        officer_id: Optional[int] = None,
        unit_id_filter: Optional[int] = None,
        due_window: Optional[str] = None,
        awaiting_major_change: Optional[bool] = None,
    ) -> dict:
        """Per-status counts + derived overdue count for the workspace tabs.

        Uses the SAME conditions as the list (minus status/overdue) so each
        tab's count matches the rows clicking it would return. Mọi filter mới
        (ngành/trình độ/năm-HK/TVV/đơn vị/hạn) PHẢI truyền y hệt list để badge
        khớp (parity).
        """
        today = today or date.today()
        # ``awaiting_major_change`` được NHẬN nhưng CỐ Ý bỏ qua ở đây: counts phải
        # tính cho MỌI tab (kể cả tab đang chọn) nên không được lọc theo lens hiện
        # tại — giống cách ``overdue_only`` bị truyền None. Số của lens này nằm ở
        # khoá ``awaiting_major_change`` trong dict trả về.
        conditions = self._build_invoice_list_conditions(
            unit_id=unit_id, statuses=None, fee_id=fee_id, profile_id=profile_id,
            overdue_only=None, search=search, fee_type=fee_type,
            date_from=date_from, date_to=date_to, today=today,
            major_id=major_id, degree_level=degree_level,
            academic_year=academic_year, semester_no=semester_no,
            officer_id=officer_id, unit_id_filter=unit_id_filter,
            due_window=due_window,
        )

        group_query = (
            select(Invoice.status, func.count(Invoice.id))
            .join(Fee).join(models.AdmissionProfile).join(models.Lead)
        )
        if conditions:
            group_query = group_query.where(and_(*conditions))
        group_query = group_query.group_by(Invoice.status)
        rows = (await self.db.execute(group_query)).all()
        raw = {row[0]: row[1] for row in rows}
        counts = {s.value: int(raw.get(s.value, 0)) for s in InvoiceStatusEnum}
        total = sum(counts.values())

        overdue_query = (
            select(func.count(Invoice.id))
            .join(Fee).join(models.AdmissionProfile).join(models.Lead)
            .where(and_(*(conditions + [self._overdue_predicate(today)])))
        )
        overdue_derived = (await self.db.execute(overdue_query)).scalar() or 0

        # Đổi ngành: count cho lens "Chờ xác nhận đổi ngành" — cùng bộ điều kiện
        # với list (chỉ thêm predicate của lens) nên số trên tab khớp số dòng.
        awaiting_query = (
            select(func.count(Invoice.id))
            .join(Fee).join(models.AdmissionProfile).join(models.Lead)
            .where(
                and_(
                    *(
                        conditions
                        + [Fee.awaiting_accountant_confirmation.is_(True)]
                    )
                )
            )
        )
        awaiting_major_change = (
            await self.db.execute(awaiting_query)
        ).scalar() or 0

        return {
            "counts": counts,
            "overdue_derived": int(overdue_derived),
            "awaiting_major_change": int(awaiting_major_change),
            "total": int(total),
        }

    async def get_distinct_fee_ids_for_filter(
        self,
        limit: int,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        fee_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        overdue_only: Optional[bool] = None,
        search: Optional[str] = None,
        fee_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        today: Optional[date] = None,
        major_id: Optional[int] = None,
        degree_level: Optional[str] = None,
        academic_year: Optional[int] = None,
        semester_no: Optional[int] = None,
        officer_id: Optional[int] = None,
        unit_id_filter: Optional[int] = None,
        due_window: Optional[str] = None,
        awaiting_major_change: Optional[bool] = None,
    ) -> List[int]:
        """Tập ``fee_id`` DISTINCT khớp bộ lọc workspace — phục vụ EXPORT.

        Vì sao DISTINCT fee mà không phải danh sách hoá đơn: file xuất có 3 cột
        tiền ở mức KHOẢN PHÍ (học phí / đã đóng / còn lại). Một khoản phí nhiều
        đợt sẽ ra nhiều hoá đơn; xuất theo hoá đơn là lặp lại cùng số tiền, kế
        toán bôi đen cột cộng sẽ ra gấp đôi mà không có dấu hiệu gì trên màn hình.

        ⚠️ Ngữ nghĩa lọc là ANY-match: một khoản phí lọt vào nếu **ít nhất một**
        hoá đơn của nó khớp bộ lọc, nhưng số tiền xuất ra là của CẢ khoản phí.
        Sheet "Thong tin xuat" trong file phải nói rõ điều này.

        ``limit`` nên truyền ``MAX_EXPORT_ROWS + 1``: gọi một lần rồi đếm độ dài
        để biết có vượt trần không — không dùng cặp count-rồi-fetch (hai câu
        truy vấn có khe TOCTOU, và cắt im lặng thì file thiếu trông y hệt file đủ).

        Dùng CHUNG ``_build_invoice_list_conditions`` với list + status-counts nên
        tập hàng xuất ra luôn khớp tập hàng đang hiển thị.
        """
        today = today or date.today()
        conditions = self._build_invoice_list_conditions(
            unit_id=unit_id, statuses=statuses, fee_id=fee_id,
            profile_id=profile_id, overdue_only=overdue_only, search=search,
            fee_type=fee_type, date_from=date_from, date_to=date_to, today=today,
            major_id=major_id, degree_level=degree_level,
            academic_year=academic_year, semester_no=semester_no,
            officer_id=officer_id, unit_id_filter=unit_id_filter,
            due_window=due_window, awaiting_major_change=awaiting_major_change,
        )

        # Chuỗi join PHẢI khớp get_filtered_with_count — builder điều kiện ở trên
        # giả định query đã join Invoice → Fee → AdmissionProfile → Lead.
        query = (
            select(Invoice.fee_id)
            .join(Fee).join(models.AdmissionProfile).join(models.Lead)
            .distinct()
        )
        if conditions:
            query = query.where(and_(*conditions))
        query = query.limit(limit)

        result = await self.db.execute(query)
        return [row for row in result.scalars().all()]

    async def get_collection_money_totals(
        self,
        unit_id: Optional[int] = None,
        today: Optional[date] = None,
    ) -> dict:
        """Money aggregates for the workspace rail / finance dashboard.

        Keeps the SQL in the repository (Backend rule: no ``db.execute`` in
        routers). Per-row remaining = ``amount + penalty - paid`` clamped ≥ 0
        (mirrors Invoice.remaining_amount). ``outstanding_total`` sums every
        billed-but-unsettled invoice (OVERDUE_DERIVED_STATUSES); the overdue
        slice adds ``due_date < today`` so overdue ⊆ outstanding.
        """
        today = today or date.today()
        remaining_expr = func.greatest(
            Invoice.amount + Invoice.penalty_amount - Invoice.paid_amount, 0
        )

        def _scoped(query):
            query = query.join(Fee).join(models.AdmissionProfile).join(models.Lead)
            # F4: exclude withdrawn / awaiting-refund profiles — they owe nothing,
            # so their leftover invoices must not inflate outstanding / overdue.
            query = query.where(
                models.AdmissionProfile.status.notin_(
                    ("withdrawn", "withdrawal_pending")
                )
            )
            if unit_id is not None:
                query = query.where(models.Lead.unit_id == unit_id)
            return query

        outstanding = (await self.db.execute(
            _scoped(select(func.coalesce(func.sum(remaining_expr), 0)))
            .where(Invoice.status.in_(OVERDUE_DERIVED_STATUSES))
        )).scalar() or 0

        overdue_row = (await self.db.execute(
            _scoped(select(
                func.count(Invoice.id).label("count"),
                func.coalesce(func.sum(remaining_expr), 0).label("amount"),
            )).where(self._overdue_predicate(today))
        )).one()

        return {
            "outstanding_total": Decimal(str(outstanding)),
            "overdue_amount": Decimal(str(overdue_row.amount or 0)),
            "overdue_invoices_count": int(overdue_row.count or 0),
        }

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

        # Include overdue status so the beat task can revisit for
        # milestone re-notifications (7/14/30 day buckets). The service
        # layer handles dedup via bucket keys + skips already-notified
        # invoices at the current milestone.
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
                        InvoiceStatusEnum.issued.value,
                        InvoiceStatusEnum.overdue.value,
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
