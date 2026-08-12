"""Overpayment resolution service for finance workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdmissionProfile
from app.models.finance import (
    FeeStatusEnum,
    InvoiceStatusEnum,
    OverpaymentRecord,
    OverpaymentStatusEnum,
    PAYABLE_INVOICE_STATUSES,
    PaymentTransaction,
    RefundRequest,
    RefundSourceEnum,
    RefundStatusEnum,
    ResolutionTypeEnum,
    TransactionTypeEnum,
)
from app.repositories.fee_repository import FeeRepository, InvoiceRepository
from app.repositories.payment_repository import OverpaymentRepository
from app.services.payment_service import RefundService, assert_payable_target
from app.utils.exceptions import (
    BadRequest,
    BusinessRuleViolation,
    ResourceNotFoundError,
)


class OverpaymentService:
    """Business logic for resolving tracked overpayment liabilities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.overpayment_repo = OverpaymentRepository(db)
        self.invoice_repo = InvoiceRepository(db)
        self.fee_repo = FeeRepository(db)
        self.refund_service = RefundService(db)

    async def get_overpayment(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None,
    ) -> OverpaymentRecord:
        overpayment = await self.overpayment_repo.get_by_id_with_relations(
            overpayment_id,
            unit_id,
        )
        if not overpayment:
            raise ResourceNotFoundError("Overpayment not found")
        return overpayment

    async def _get_overpayment_locked(
        self,
        overpayment_id: int,
        unit_id: Optional[int] = None,
    ) -> OverpaymentRecord:
        """Fetch an overpayment with a row lock for a resolution mutation (F6)."""
        overpayment = await self.overpayment_repo.get_for_update(
            overpayment_id,
            unit_id,
        )
        if not overpayment:
            raise ResourceNotFoundError("Overpayment not found")
        return overpayment

    async def list_overpayments(
        self,
        skip: int = 0,
        limit: int = 50,
        unit_id: Optional[int] = None,
        statuses: Optional[List[str]] = None,
        profile_id: Optional[int] = None,
    ) -> Tuple[List[OverpaymentRecord], int]:
        return await self.overpayment_repo.get_filtered_with_count(
            skip=skip,
            limit=limit,
            unit_id=unit_id,
            statuses=statuses,
            profile_id=profile_id,
        )

    async def apply_to_invoice(
        self,
        overpayment_id: int,
        target_invoice_id: int,
        user_id: int,
        amount: Optional[Decimal] = None,
        notes: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[OverpaymentRecord, None]:
        overpayment = await self._get_overpayment_locked(overpayment_id, unit_id)
        await self._ensure_resolvable(overpayment)

        # ── PHA KHOÁ 1/2: MỌI invoice liên quan, theo id tăng dần ───────────
        #
        # Quy ước thứ tự khoá toàn cục (#541): **invoice trước — id tăng dần —
        # rồi mới tới fee**, và sau khi đã cầm Fee thì tuyệt đối không xin thêm
        # khoá Invoice nào.
        #
        # Bản trước ở đây khoá target_invoice → target_fee → SOURCE_invoice:
        # xin Invoice sau khi đã cầm Fee, đúng thứ quy ước cấm. Hai lượt áp
        # khoản dư ngược chiều trên cùng hồ sơ (X→Y và Y→X) khi ấy ôm chéo và
        # Postgres bắn 40P01 — comment cũ tuyên bố đã tránh ABBA nhưng code thì
        # chưa. `get_for_update` KHÔNG dùng được ở pha này: nó `FOR UPDATE`
        # trần nên kéo luôn fee/profile/lead vào theo thứ tự của invoice.
        invoice_da_khoa = {
            inv.id: inv
            for inv in await self.invoice_repo.khoa_invoice_theo_id(
                [target_invoice_id, overpayment.invoice_id],
                unit_id,
            )
        }
        target_invoice = invoice_da_khoa.get(target_invoice_id)
        source_invoice = invoice_da_khoa.get(overpayment.invoice_id)

        if not target_invoice:
            raise ResourceNotFoundError("Target invoice not found")

        if target_invoice.status not in PAYABLE_INVOICE_STATUSES:
            raise BusinessRuleViolation(
                f"Cannot apply overpayment to invoice with status "
                f"'{target_invoice.status}'. Allowed: "
                f"{list(PAYABLE_INVOICE_STATUSES)}"
            )

        # ── PHA KHOÁ 2/2: fee theo id tăng dần, sau khi đã cầm trọn invoice ──
        fee_da_khoa = {}
        for _fee_id in sorted(
            {target_invoice.fee_id}
            | ({source_invoice.fee_id} if source_invoice else set())
        ):
            _fee = await self.fee_repo.get_for_update(_fee_id, unit_id)
            if _fee:
                fee_da_khoa[_fee_id] = _fee

        target_fee = fee_da_khoa.get(target_invoice.fee_id)
        if not target_fee:
            raise ResourceNotFoundError("Target fee not found")

        if target_fee.admission_profile_id != overpayment.admission_profile_id:
            raise BusinessRuleViolation(
                "Overpayment can only be applied to an invoice on the same profile"
            )

        # P0: applying an overpayment writes money onto the target fee/invoice.
        # Route through the shared money-write guard (target_fee + target_invoice
        # already locked above) so credit can't land on a cancelled fee/invoice
        # OR a withdrawn/rejected/refund-pending profile — one invariant. This
        # also closes the pre-existing gap where a cancelled target_fee with an
        # `issued` invoice slipped past the invoice-status check above.
        target_profile = (
            await self.db.execute(
                select(AdmissionProfile).where(
                    AdmissionProfile.id == target_fee.admission_profile_id
                )
            )
        ).scalar_one_or_none()
        assert_payable_target(
            target_fee, target_invoice, target_profile, action="áp khoản dư"
        )

        # Use `is not None` (not `or`): Decimal('0') is falsy, so `amount or ...`
        # would silently fall through to the full amount instead of being
        # rejected by the `<= 0` guard below.
        apply_amount = amount if amount is not None else overpayment.overpayment_amount
        if apply_amount <= 0:
            raise BadRequest("Applied amount must be positive")
        if apply_amount != overpayment.overpayment_amount:
            raise BusinessRuleViolation(
                "Partial overpayment application is not supported; "
                "apply the full amount"
            )
        if apply_amount > target_invoice.remaining_amount:
            raise BusinessRuleViolation(
                "Overpayment amount exceeds target invoice remaining balance"
            )

        # ── CHUYỂN, KHÔNG PHẢI CỘNG THÊM ────────────────────────────────────
        #
        # `paid_amount` phản ánh TOÀN BỘ tiền thật đã nhận, kể cả phần vượt —
        # `OverpaymentRecord` chỉ là nghĩa vụ chưa phân bổ, không phải nơi giữ
        # tiền ngoài sổ. Nên áp khoản dư là DI CHUYỂN tiền: rời hoá đơn nguồn
        # rồi mới vào hoá đơn đích.
        #
        # Thiếu vế trừ nguồn thì cùng một khoản được ghi nhận hai lần: thu
        # 8.070.000 cho hoá đơn 8.000.000 rồi áp 70.000 sang đợt sau ⇒ hệ thống
        # phân bổ 8.140.000 trong khi tiền thật chỉ có 8.070.000. Đã đo được.
        #
        # Nguồn đã được khoá ở hai pha trên (invoice trước, fee sau) — ở đây
        # chỉ tra cứu, KHÔNG xin thêm khoá nào nữa.
        if not source_invoice:
            raise ResourceNotFoundError("Source invoice not found")

        source_fee = fee_da_khoa.get(source_invoice.fee_id)
        if not source_fee:
            raise ResourceNotFoundError("Source fee not found")

        source_fee_balance_before = (
            source_fee.final_amount - source_fee.paid_amount - source_fee.waived_amount
        )

        # Rời nguồn.
        source_invoice.paid_amount -= apply_amount
        if source_invoice.is_fully_paid:
            source_invoice.status = InvoiceStatusEnum.paid.value
        elif source_invoice.paid_amount > 0:
            source_invoice.status = InvoiceStatusEnum.partial.value
        else:
            source_invoice.status = InvoiceStatusEnum.issued.value

        if source_fee.id != target_fee.id:
            # Khác Fee: nguồn giảm, đích tăng — tổng hai Fee không đổi.
            source_fee.paid_amount -= apply_amount
            source_fee.version += 1
            _sf_remaining = (
                source_fee.final_amount
                - source_fee.paid_amount
                - source_fee.waived_amount
            )
            if _sf_remaining <= 0:
                source_fee.status = FeeStatusEnum.paid.value
            elif source_fee.paid_amount > 0:
                source_fee.status = FeeStatusEnum.partial.value
            else:
                source_fee.status = FeeStatusEnum.invoiced.value
        # Cùng Fee: tiền chỉ đổi chỗ giữa hai đợt của chính nó, nên
        # `fee.paid_amount` KHÔNG đổi — trừ rồi cộng lại đúng bằng nhau.

        fee_balance_before = (
            target_fee.final_amount - target_fee.paid_amount - target_fee.waived_amount
        )

        target_invoice.paid_amount += apply_amount
        if target_invoice.is_fully_paid:
            target_invoice.status = InvoiceStatusEnum.paid.value
            target_invoice.paid_at = datetime.now(timezone.utc)
        elif target_invoice.paid_amount > 0:
            target_invoice.status = InvoiceStatusEnum.partial.value

        if source_fee.id != target_fee.id:
            target_fee.paid_amount += apply_amount
        # Cùng Fee thì KHÔNG cộng: tiền chỉ đổi chỗ giữa hai đợt của chính Fee
        # ấy. Cộng ở đây (mà không trừ ở nhánh nguồn) chính là chỗ tổng tiền
        # phân bổ phình ra so với tiền thật đã nhận.
        target_fee.last_payment_at = datetime.now(timezone.utc)
        target_fee.version += 1

        fee_remaining = (
            target_fee.final_amount - target_fee.paid_amount - target_fee.waived_amount
        )
        if fee_remaining <= 0:
            target_fee.status = FeeStatusEnum.paid.value
        elif target_fee.paid_amount > 0:
            target_fee.status = FeeStatusEnum.partial.value

        overpayment.status = OverpaymentStatusEnum.applied.value
        overpayment.resolution_type = ResolutionTypeEnum.apply_to_next.value
        overpayment.resolved_at = datetime.now(timezone.utc)
        overpayment.resolved_by_id = user_id
        overpayment.resolution_notes = notes
        overpayment.applied_to_invoice_id = target_invoice_id
        overpayment.applied_amount = apply_amount

        default_note = (
            f"Applied overpayment {overpayment.id} "
            f"to invoice {target_invoice.invoice_number}"
        )
        # Audit: một phép CHUYỂN phải để lại hai vế mang cùng mã, nếu không sổ
        # chỉ kể một nửa câu chuyện — người đọc thấy đích được cộng mà không
        # biết tiền đến từ đâu.
        ma_chuyen = f"OVERPAY-{overpayment.id}"

        # HAI VẾ, KHÔNG ĐIỀU KIỆN. Bản trước chỉ ghi vế âm khi hai Fee khác
        # nhau, nên lượt chuyển giữa hai đợt của CÙNG một khoản phí để lại đúng
        # một dòng `+apply_amount` với `balance_before == balance_after`: sổ nói
        # có 70.000 chảy vào mà số dư không nhúc nhích. Mọi báo cáo cộng cột
        # `amount` của `adjustment` đều lệch đúng chừng ấy.
        #
        # Bất biến giữ trên MỌI dòng: ``balance_after == balance_before -
        # amount``. Ở ca cùng Fee, tiền rời đợt nguồn rồi mới vào đợt đích, nên
        # số dư đi B → B + apply → B; ghi B → B cho cả hai vế sẽ phá bất biến ấy.
        cung_fee = source_fee.id == target_fee.id
        source_balance_after = (
            source_fee_balance_before + apply_amount
            if cung_fee
            else (
                source_fee.final_amount
                - source_fee.paid_amount
                - source_fee.waived_amount
            )
        )
        self.db.add(
            PaymentTransaction(
                payment_id=overpayment.payment_id,
                fee_id=source_fee.id,
                transaction_type=TransactionTypeEnum.adjustment.value,
                amount=-apply_amount,  # vế NỢ: tiền rời đợt nguồn
                balance_before=source_fee_balance_before,
                balance_after=source_balance_after,
                external_reference=ma_chuyen,
                performed_by_id=user_id,
                notes=(
                    f"Chuyển khoản dư #{overpayment.id} sang hóa đơn "
                    f"#{target_invoice_id} "
                    + ("(cùng khoản phí, khác đợt)" if cung_fee else "(khoản phí khác)")
                ),
            )
        )

        transaction = PaymentTransaction(
            payment_id=overpayment.payment_id,
            fee_id=target_fee.id,
            transaction_type=TransactionTypeEnum.adjustment.value,
            amount=apply_amount,  # vế CÓ
            balance_before=(
                fee_balance_before + apply_amount if cung_fee else fee_balance_before
            ),
            balance_after=fee_remaining,
            external_reference=ma_chuyen,
            performed_by_id=user_id,
            notes=notes or default_note,
        )
        self.db.add(transaction)

        await self.db.flush()
        return overpayment, None

    async def refund_overpayment(
        self,
        overpayment_id: int,
        user_id: int,
        notes: Optional[str] = None,
        unit_id: Optional[int] = None,
    ) -> Tuple[OverpaymentRecord, None]:
        overpayment = await self._get_overpayment_locked(overpayment_id, unit_id)
        await self._ensure_resolvable(overpayment)

        refund, _ = await self.refund_service.request_refund(
            payment_id=overpayment.payment_id,
            amount=overpayment.overpayment_amount,
            reason=notes or f"Refund overpayment {overpayment.id}",
            user_id=user_id,
            unit_id=unit_id,
            source=RefundSourceEnum.overpayment.value,
        )

        # F4: the overpayment liability stays *pending* and is only linked to the
        # refund request. It is closed to 'refunded' when that request is actually
        # processed (RefundService.process_approved_refund). If the refund is
        # rejected, the link clears and the overpayment remains re-resolvable.
        overpayment.refund_request_id = refund.id

        await self.db.flush()
        return overpayment, None

    async def write_off(
        self,
        overpayment_id: int,
        reason: str,
        user_id: int,
        unit_id: Optional[int] = None,
    ) -> Tuple[OverpaymentRecord, None]:
        overpayment = await self._get_overpayment_locked(overpayment_id, unit_id)
        await self._ensure_resolvable(overpayment)

        if not reason or not reason.strip():
            raise BadRequest("Write-off reason is required")

        overpayment.status = OverpaymentStatusEnum.cancelled.value
        overpayment.resolution_type = ResolutionTypeEnum.write_off.value
        overpayment.resolved_at = datetime.now(timezone.utc)
        overpayment.resolved_by_id = user_id
        overpayment.resolution_notes = reason

        await self.db.flush()
        return overpayment, None

    async def _ensure_resolvable(self, overpayment: OverpaymentRecord) -> None:
        """Guard a resolution: must be pending AND have no open linked refund.

        Blocking on an open (pending/approved) linked refund prevents a second
        resolution (apply/refund/write-off) from running while a refund created
        via :meth:`refund_overpayment` is still in flight (F4 double-resolution).
        """
        if overpayment.status != OverpaymentStatusEnum.pending.value:
            raise BusinessRuleViolation(
                "Can only resolve pending overpayments. "
                f"Current status: {overpayment.status}"
            )
        if overpayment.refund_request_id is not None:
            refund = await self.db.get(RefundRequest, overpayment.refund_request_id)
            if refund and refund.status in (
                RefundStatusEnum.pending.value,
                RefundStatusEnum.approved.value,
            ):
                raise BusinessRuleViolation(
                    f"Overpayment has an open refund request (#{refund.id}, "
                    f"{refund.status}); resolve that refund first"
                )
