# tests/services/test_payment_intent_service.py
"""
Tests for PaymentIntentService.

Covers:
- Intent creation with idempotency
- Invoice status validation
- Online-only method enforcement
- Amount exceeds remaining guard
- Gateway callback processing (mock, no adapter)
- Amount mismatch detection (C1)
- Expired intent guard
- Cancel intent lifecycle
- Auto-expire on get
- Batch expire old intents
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from sqlalchemy import func, select

from app.models.finance import (
    Fee, Invoice, PaymentIntent, PaymentMethod,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum,
    PaymentIntentStatusEnum, OverpaymentRecord, PaymentTransaction, Payment,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.services.payment_intent_service import PaymentIntentService
from app.config import settings
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
)

pytestmark = pytest.mark.asyncio

# PR1 Commit 5: create_intent now allowlists return_url against FRONTEND_URL.
# Use a same-origin URL so these fixtures pass the new guard.
VALID_RETURN_URL = (
    f"{settings.FRONTEND_URL.rstrip('/')}/finance/payments/return"
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def intent_fixtures(db: AsyncSession, seeded_dependencies: dict, admin_user):
    """Create fixtures: fee -> issued invoice + online payment method."""
    online_method = PaymentMethod(
        code="intent_test_vnpay",
        name="VNPay Test",
        is_online=True,
        is_active=True,
    )
    db.add(online_method)

    offline_method = PaymentMethod(
        code="intent_test_cash",
        name="Cash",
        is_online=False,
        is_active=True,
    )
    db.add(offline_method)

    inactive_online = PaymentMethod(
        code="intent_test_inactive",
        name="Inactive Online",
        is_online=True,
        is_active=False,
    )
    db.add(inactive_online)

    await db.flush()

    lead = models.Lead(
        full_name="Intent Test Student",
        phone="0901330001",
        source="test",
        unit_id=seeded_dependencies["unit_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
    )
    db.add(lead)
    await db.flush()

    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        academic_year=2025,
        applied_rules={},
    )
    db.add(profile)
    await db.flush()
    await db.refresh(profile)

    # Create fee via service
    fee_service = FeeCalculationService(db)
    fee, _ = await fee_service.calculate_fee(
        admission_profile_id=profile.id,
        fee_type=FeeTypeEnum.enrollment,
        base_amount=Decimal("5000000"),
        academic_year=2025,
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
    )
    await db.commit()

    # Generate and issue invoice
    inv_service = InvoiceService(db)
    invoices, _ = await inv_service.generate_invoices_for_fee(
        fee_id=fee.id,
        due_date_base=date.today() + timedelta(days=30),
        user_id=admin_user.id,
        unit_id=seeded_dependencies["unit_id"],
        auto_issue=True,
    )
    await db.commit()

    return {
        "fee": fee,
        "invoice": invoices[0],
        "online_method": online_method,
        "offline_method": offline_method,
        "inactive_online": inactive_online,
        "profile": profile,
        "unit_id": seeded_dependencies["unit_id"],
    }


# =============================================================================
# CREATE INTENT TESTS
# =============================================================================

class TestCreateIntent:
    """Tests for intent creation."""

    async def test_create_intent_success(self, db, intent_fixtures, admin_user):
        """Intent created with pay_url and gateway_ref (mock, no adapter)."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]
        key = str(uuid.uuid4())

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=key,
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        assert intent.id is not None
        assert intent.amount == Decimal("1000000")
        assert intent.invoice_id == invoice.id
        assert intent.method_id == method.id
        assert intent.idempotency_key == key
        assert intent.gateway_ref is not None
        assert intent.pay_url is not None
        assert intent.expires_at is not None

    async def test_create_intent_blocked_when_fee_cancelled(
        self, db, intent_fixtures, admin_user
    ):
        """Race guard: a cancelled fee cannot get a NEW intent (which would let
        the gateway collect money the callback must later refuse). Invoice is
        still 'issued' (payable) here — only the fee is cancelled."""
        service = PaymentIntentService(db)
        intent_fixtures["fee"].status = FeeStatusEnum.cancelled.value
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc:
            await service.create_intent(
                invoice_id=intent_fixtures["invoice"].id,
                method_id=intent_fixtures["online_method"].id,
                amount=Decimal("1000000"),
                idempotency_key=str(uuid.uuid4()),
                return_url=VALID_RETURN_URL,
                unit_id=intent_fixtures["unit_id"],
            )
        assert "đã bị huỷ" in str(exc.value)

    async def test_create_intent_rejects_foreign_return_url(
        self, db, intent_fixtures, admin_user
    ):
        """PR1 Commit 5: a return_url whose origin differs from FRONTEND_URL is
        rejected (open-redirect guard) → BusinessRuleViolation (mapped to HTTP
        400 by the payments router). Proves the guard is wired into
        create_intent, not just the standalone helper."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]
        with pytest.raises(BusinessRuleViolation):
            await service.create_intent(
                invoice_id=invoice.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                idempotency_key=str(uuid.uuid4()),
                return_url="https://attacker.evil/finance/payments/return",
                unit_id=intent_fixtures["unit_id"],
            )

    async def test_create_intent_idempotency_same_key(self, db, intent_fixtures, admin_user):
        """Same idempotency key + invoice returns existing non-terminal intent."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]
        key = str(uuid.uuid4())

        intent1, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=key,
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        intent2, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=key,
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )

        assert intent2.id == intent1.id

    async def test_create_intent_invalid_invoice_status(self, db, intent_fixtures, admin_user):
        """Cannot create intent for draft invoice."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        # Force draft status
        invoice.status = InvoiceStatusEnum.draft.value
        await db.commit()

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.create_intent(
                invoice_id=invoice.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                idempotency_key=str(uuid.uuid4()),
                return_url=VALID_RETURN_URL,
                unit_id=intent_fixtures["unit_id"],
            )

        assert "status" in str(exc_info.value).lower()

    async def test_create_intent_offline_method(self, db, intent_fixtures, admin_user):
        """Cannot create intent with offline payment method."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["offline_method"]

        with pytest.raises(BadRequest) as exc_info:
            await service.create_intent(
                invoice_id=invoice.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                idempotency_key=str(uuid.uuid4()),
                return_url=VALID_RETURN_URL,
                unit_id=intent_fixtures["unit_id"],
            )

        assert "online" in str(exc_info.value).lower()

    async def test_create_intent_exceeds_remaining(self, db, intent_fixtures, admin_user):
        """Amount exceeding invoice remaining raises BusinessRuleViolation."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.create_intent(
                invoice_id=invoice.id,
                method_id=method.id,
                amount=Decimal("999999999"),
                idempotency_key=str(uuid.uuid4()),
                return_url=VALID_RETURN_URL,
                unit_id=intent_fixtures["unit_id"],
            )

        assert "exceeds" in str(exc_info.value).lower()

    async def test_create_intent_inactive_method(self, db, intent_fixtures, admin_user):
        """Inactive online method raises BadRequest."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["inactive_online"]

        with pytest.raises(BadRequest) as exc_info:
            await service.create_intent(
                invoice_id=invoice.id,
                method_id=method.id,
                amount=Decimal("1000000"),
                idempotency_key=str(uuid.uuid4()),
                return_url=VALID_RETURN_URL,
                unit_id=intent_fixtures["unit_id"],
            )

        assert "not active" in str(exc_info.value).lower()


# =============================================================================
# PROCESS CALLBACK TESTS (mock, no adapter registered)
# =============================================================================

class TestProcessCallback:
    """Tests for gateway callback processing without adapter (mock path)."""

    async def test_process_callback_success(self, db, intent_fixtures, admin_user):
        """Successful callback creates payment and updates invoice."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]
        amount = Decimal("5000000")

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=amount,
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        # Mock callback data (no adapter → mock parsing path)
        callback_data = {
            "gateway_ref": intent.gateway_ref,
            "status": "success",
            "amount": str(amount),
        }

        result_intent, payment, _ = await service.process_callback(
            gateway_code=method.code,
            callback_data=callback_data,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        assert result_intent.status == PaymentIntentStatusEnum.completed.value
        assert payment is not None
        assert payment.amount == amount

    async def test_process_callback_refused_on_cancelled_fee(
        self, db, intent_fixtures, admin_user
    ):
        """2b-bis (money-critical): a SUCCESS callback whose fee was cancelled
        AFTER the intent was created is REFUSED — never write money onto a
        cancelled target. paid_amount stays 0 (no half-applied payment)."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]
        amount = Decimal("5000000")

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=amount,
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        # Fee cancelled out-of-band AFTER the intent exists (race / reissue).
        intent_fixtures["fee"].status = FeeStatusEnum.cancelled.value
        await db.commit()

        callback_data = {
            "gateway_ref": intent.gateway_ref,
            "status": "success",
            "amount": str(amount),
        }
        with pytest.raises(BusinessRuleViolation) as exc:
            await service.process_callback(
                gateway_code=method.code,
                callback_data=callback_data,
                unit_id=intent_fixtures["unit_id"],
            )
        assert "đã bị huỷ" in str(exc.value)

        await db.refresh(invoice)
        assert invoice.paid_amount == Decimal("0")

    async def test_process_callback_amount_mismatch(self, db, intent_fixtures, admin_user):
        """Amount mismatch in callback marks intent as failed (C1)."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        callback_data = {
            "gateway_ref": intent.gateway_ref,
            "status": "success",
            "amount": "999999",  # Mismatch
        }

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.process_callback(
                gateway_code=method.code,
                callback_data=callback_data,
            )

        assert "mismatch" in str(exc_info.value).lower()

        # Intent should be marked failed
        await db.refresh(intent)
        assert intent.status == PaymentIntentStatusEnum.failed.value

    async def test_process_callback_expired_intent(self, db, intent_fixtures, admin_user):
        """Cannot process callback for expired intent."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
            expiration_minutes=0,  # Already expired
        )
        await db.commit()

        # Force past expiration by setting expires_at in the past
        intent.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

        callback_data = {
            "gateway_ref": intent.gateway_ref,
            "status": "success",
            "amount": "1000000",
        }

        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.process_callback(
                gateway_code=method.code,
                callback_data=callback_data,
            )

        assert "expired" in str(exc_info.value).lower() or "cannot" in str(exc_info.value).lower()

    async def test_process_callback_failed_status(self, db, intent_fixtures, admin_user):
        """Failed gateway status marks intent as failed, no payment created."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]
        amount = Decimal("1000000")

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=amount,
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        callback_data = {
            "gateway_ref": intent.gateway_ref,
            "status": "failed",
            "amount": str(amount),
        }

        result_intent, payment, _ = await service.process_callback(
            gateway_code=method.code,
            callback_data=callback_data,
        )
        await db.commit()

        assert result_intent.status == PaymentIntentStatusEnum.failed.value
        assert payment is None


# =============================================================================
# INTENT LIFECYCLE TESTS
# =============================================================================

class TestIntentLifecycle:
    """Tests for cancel, expire, and get intent."""

    async def test_cancel_intent_success(self, db, intent_fixtures, admin_user):
        """Cancel non-terminal intent succeeds."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        cancelled, _ = await service.cancel_intent(
            intent_id=intent.id,
            reason="User cancelled",
            user_id=admin_user.id,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        assert cancelled.status == PaymentIntentStatusEnum.cancelled.value

    async def test_cancel_intent_terminal(self, db, intent_fixtures, admin_user):
        """Cannot cancel terminal intent."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        # Cancel first
        await service.cancel_intent(
            intent_id=intent.id,
            reason="First cancel",
            user_id=admin_user.id,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        # Try cancel again (already terminal)
        with pytest.raises(BusinessRuleViolation) as exc_info:
            await service.cancel_intent(
                intent_id=intent.id,
                reason="Second cancel",
                user_id=admin_user.id,
                unit_id=intent_fixtures["unit_id"],
            )

        assert "terminal" in str(exc_info.value).lower() or "cannot cancel" in str(exc_info.value).lower()

    async def test_get_intent_auto_expire(self, db, intent_fixtures, admin_user):
        """Getting a stale intent auto-expires it."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        intent, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        # Force past expiration
        intent.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()

        fetched = await service.get_intent(
            intent_id=intent.id,
            unit_id=intent_fixtures["unit_id"],
        )

        assert fetched.status == PaymentIntentStatusEnum.expired.value

    async def test_expire_old_intents_batch(self, db, intent_fixtures, admin_user):
        """Batch expire expires all stale intents."""
        service = PaymentIntentService(db)
        invoice = intent_fixtures["invoice"]
        method = intent_fixtures["online_method"]

        # Create multiple intents with past expiration
        intent_ids = []
        for i in range(3):
            intent, _ = await service.create_intent(
                invoice_id=invoice.id,
                method_id=method.id,
                amount=Decimal("100000"),
                idempotency_key=str(uuid.uuid4()),
                return_url=VALID_RETURN_URL,
                unit_id=intent_fixtures["unit_id"],
            )
            intent.expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)
            intent_ids.append(intent.id)

        await db.commit()

        expired = await service.expire_old_intents()
        await db.commit()

        assert len(expired) >= 3
        for e in expired:
            assert e.status == PaymentIntentStatusEnum.expired.value


# =============================================================================
# SỔ TIỀN THỪA Ở ĐƯỜNG CALLBACK ONLINE
# =============================================================================
# Callback online từng CHÉP TAY toàn bộ money-math (invoice.paid_amount,
# fee.paid_amount, hai nhánh status, fee.version) thay vì gọi hàm dùng chung với
# ghi tay và nhập lô. Bản sao ấy im lặng đúng vào lúc hàm chung học được cách mở
# sổ tiền thừa — nghĩa là callback trả dư vẫn đẩy số dư xuống âm mà không ai ghi
# nợ.
#
# 🔴 Ca parity KHÔNG dừng ở "HTTP 200" hay "payment tồn tại": nó so từng trường
# mà một bản chép tay có thể làm lệch — invoice.status/paid_amount,
# fee.status/paid_amount/version, và PaymentTransaction.balance_before/after.


#: Số tiền hoá đơn mà `intent_fixtures` dựng (fee 5.000.000, một đợt).
_HOA_DON = Decimal("5000000")


async def _dem_so(db, invoice_id: int) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(OverpaymentRecord)
            .where(OverpaymentRecord.invoice_id == invoice_id)
        )
    ).scalar_one()


async def _tao_intent(db, ctx: dict, amount: Decimal):
    """Chỉ TẠO intent, chưa cho gateway báo gì.

    Tách khỏi bước callback là điều kiện để dựng được race thật: cửa "không
    vượt quá còn nợ" của `create_intent` tính trên phần ĐÃ ghi, nên hai intent
    tạo trước khi bất kỳ callback nào chạy đều lọt qua — y hệt hai payment
    pending ở đường ghi tay.
    """
    service = PaymentIntentService(db)
    intent, _ = await service.create_intent(
        invoice_id=ctx["invoice"].id,
        method_id=ctx["online_method"].id,
        amount=amount,
        idempotency_key=str(uuid.uuid4()),
        return_url=VALID_RETURN_URL,
        unit_id=ctx["unit_id"],
    )
    await db.commit()
    return intent


async def _goi_callback(db, ctx: dict, intent, amount: Decimal):
    """Gateway báo thành công cho một intent đã tạo."""
    service = PaymentIntentService(db)
    result_intent, payment, _ = await service.process_callback(
        gateway_code=ctx["online_method"].code,
        callback_data={
            "gateway_ref": intent.gateway_ref,
            "status": "success",
            "amount": str(amount),
        },
        unit_id=ctx["unit_id"],
    )
    await db.commit()
    return result_intent, payment


async def _callback(db, ctx: dict, amount: Decimal):
    """Đường thẳng: tạo intent rồi callback ngay."""
    intent = await _tao_intent(db, ctx, amount)
    return await _goi_callback(db, ctx, intent, amount)


# ---------------------------------------------------------------------------
# CALLBACK — parity với đường ghi tay khi KHÔNG có phần thừa
# ---------------------------------------------------------------------------

async def test_callback_khong_thua_khop_tung_truong_va_khong_mo_so(
    db, intent_fixtures, admin_user
):
    """Trả đúng số còn nợ: sổ sách phải giống hệt đường ghi tay, và KHÔNG có
    khoản thừa nào.

    So từng trường thay vì chỉ so "đã thanh toán" — xem docstring đầu tệp.
    """
    ctx = intent_fixtures
    invoice_id = ctx["invoice"].id
    fee = ctx["fee"]

    version_truoc = fee.version
    fee_paid_truoc = fee.paid_amount

    result_intent, payment = await _callback(db, ctx, _HOA_DON)

    assert result_intent.status == PaymentIntentStatusEnum.completed.value
    assert payment is not None

    inv = (
        await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    await db.refresh(fee)

    # invoice: đủ tiền → paid, và paid_amount đúng bằng số đã trả
    assert inv.paid_amount == _HOA_DON
    assert inv.status == InvoiceStatusEnum.paid.value
    assert inv.remaining_amount == Decimal("0")
    assert inv.paid_at is not None

    # fee: cộng đúng, version bump ĐÚNG MỘT lần, status theo số còn lại
    assert fee.paid_amount == fee_paid_truoc + _HOA_DON
    assert fee.version == version_truoc + 1
    assert fee.status == "paid"
    assert fee.last_payment_at is not None

    # audit: balance_before/after phải kể đúng câu chuyện số dư
    tx = (
        await db.execute(
            select(PaymentTransaction).where(
                PaymentTransaction.payment_id == payment.id
            )
        )
    ).scalar_one()
    assert tx.amount == _HOA_DON
    assert tx.balance_before == fee.final_amount - fee_paid_truoc - fee.waived_amount
    assert tx.balance_after == Decimal("0")

    # và KHÔNG có sổ thừa nào — đây là luồng thường
    assert await _dem_so(db, invoice_id) == 0


# ---------------------------------------------------------------------------
# CALLBACK — có phần thừa
# ---------------------------------------------------------------------------

async def test_callback_tra_du_thi_mo_dung_mot_so(db, intent_fixtures, admin_user):
    """Gateway trả nhiều hơn số còn nợ.

    Ở đường online KHÔNG có maker-checker chặn trước, nên sổ thừa là chỗ duy
    nhất giữ dấu vết số tiền dôi ra.
    """
    ctx = intent_fixtures
    invoice_id = ctx["invoice"].id

    # 🔴 Hai intent tạo TRƯỚC khi callback nào chạy. `create_intent` chặn số
    # tiền vượt phần CÒN NỢ, nhưng phần còn nợ ấy tính trên tiền ĐÃ ghi — nên
    # lúc này cả hai đều hợp lệ. Chính khe đó, không phải "gateway trả sai số",
    # là đường duy nhất khiến online sinh khoản thừa.
    i1 = await _tao_intent(db, ctx, _HOA_DON - Decimal("100000"))
    i2 = await _tao_intent(db, ctx, Decimal("300000"))

    await _goi_callback(db, ctx, i1, _HOA_DON - Decimal("100000"))
    assert await _dem_so(db, invoice_id) == 0

    _, payment2 = await _goi_callback(db, ctx, i2, Decimal("300000"))

    so = (
        await db.execute(
            select(OverpaymentRecord).where(
                OverpaymentRecord.invoice_id == invoice_id
            )
        )
    ).scalars().all()
    assert len(so) == 1, f"phải mở đúng một sổ, đang có {len(so)}"
    assert so[0].overpayment_amount == Decimal("200000")
    assert so[0].payment_id == payment2.id
    assert so[0].source_type == "payment_settlement"
    assert so[0].status == "pending"

    inv = (
        await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert inv.remaining_amount == Decimal("-200000")
    assert -inv.remaining_amount == so[0].overpayment_amount, (
        "số dư âm và sổ thừa phải khớp từng đồng"
    )


async def test_callback_lap_lai_khong_nhan_ban_so(db, intent_fixtures, admin_user):
    """Gateway gọi lại cùng ``gateway_ref`` không được đẻ nghĩa vụ thứ hai.

    Callback lặp là chuyện bình thường của mọi cổng thanh toán (retry khi
    timeout, người dùng bấm lại). Nếu mỗi lần lặp mở thêm một sổ thì hệ thống tự
    tạo ra nợ không có thật.
    """
    ctx = intent_fixtures
    invoice_id = ctx["invoice"].id

    i1 = await _tao_intent(db, ctx, _HOA_DON - Decimal("100000"))
    intent = await _tao_intent(db, ctx, Decimal("300000"))
    await _goi_callback(db, ctx, i1, _HOA_DON - Decimal("100000"))

    service = PaymentIntentService(db)
    du_lieu = {
        "gateway_ref": intent.gateway_ref,
        "status": "success",
        "amount": "300000",
    }
    await service.process_callback(
        gateway_code=ctx["online_method"].code,
        callback_data=du_lieu,
        unit_id=ctx["unit_id"],
    )
    await db.commit()
    assert await _dem_so(db, invoice_id) == 1

    paid_truoc_replay = (
        await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one().paid_amount
    # Giữ id NGUYÊN THUỶ: sau `rollback()` mọi ORM object bị expire, và chạm
    # vào thuộc tính của chúng là một lượt IO lazy-load ngoài greenlet
    # (MissingGreenlet), không phải lỗi nghiệp vụ.
    intent_id = intent.id

    # Lượt lặp: cùng gateway_ref, cùng số tiền.
    #
    # 🔴 Khẳng định ĐÚNG lỗi mong đợi, không bắt `Exception` chung. Bản đầu của
    # ca này nuốt cả IntegrityError, lỗi lập trình lẫn lỗi kết nối — nó xanh dù
    # callback lặp được xử lý theo bất kỳ cách nào, kể cả cách sai.
    with pytest.raises(BusinessRuleViolation, match="Intent cannot process callback"):
        await service.process_callback(
            gateway_code=ctx["online_method"].code,
            callback_data=du_lieu,
            unit_id=ctx["unit_id"],
        )
    await db.rollback()

    # Hậu quả: mọi thứ đứng yên.
    intent_sau = (
        await db.execute(
            select(PaymentIntent).where(PaymentIntent.id == intent_id)
        )
    ).scalar_one()
    assert intent_sau.status == PaymentIntentStatusEnum.completed.value

    so_payment = (
        await db.execute(
            select(func.count())
            .select_from(Payment)
            .where(Payment.intent_id == intent_id)
        )
    ).scalar_one()
    assert so_payment == 1, "callback lặp đã tạo phiếu thu thứ hai"

    assert await _dem_so(db, invoice_id) == 1, (
        "callback lặp đã nhân bản sổ tiền thừa — mỗi lần retry của gateway là "
        "một khoản nợ mới không có thật"
    )

    inv_sau = (
        await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    ).scalar_one()
    assert inv_sau.paid_amount == paid_truoc_replay, (
        "callback lặp đã cộng tiền lần hai vào hóa đơn"
    )

    # Ca này là REPLAY TUẦN TỰ. Nó KHÔNG chứng minh gì về hai callback chạy
    # song song — khe đó cần hai giao dịch thật, và `uq_overpayment_payment` là
    # hàng rào cuối cho nó.
