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
        """Amount mismatch in callback is REFUSED — và KHÔNG ghi gì (C1).

        ⚠️ ĐỔI KỲ VỌNG CÓ CHỦ ĐÍCH. Bản trước khẳng định
        ``intent.status == failed`` — tức nó KHOÁ ĐÚNG hành vi hoá ra là lỗ
        hổng: nhánh lệch số tiền ghi bốn trường (gồm cả thân request thô) rồi
        ``flush()`` rồi mới ``raise``; ``process_gateway_callback`` nuốt ngoại
        lệ và router ``db.commit()`` vô điều kiện, nên phép ghi thành vĩnh
        viễn. ``failed`` là trạng thái terminal ⇒ callback THẬT sau đó bị từ
        chối.

        Kỳ vọng mới: vẫn từ chối, nhưng intent ĐỨNG YÊN. Xem
        ``TestCallbackFailClosed`` để có phép đo đi qua đúng chuỗi của router.
        """
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

        # Intent KHÔNG được đổi trạng thái: nhánh lỗi không ghi.
        await db.refresh(intent)
        assert intent.status == PaymentIntentStatusEnum.created.value
        assert intent.gateway_status is None
        assert intent.callback_data is None

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


# =============================================================================
# CỔNG FAIL-CLOSED CHO CALLBACK — mỗi ca vi phạm ĐÚNG MỘT bất biến
# =============================================================================
#
# `POST /api/payments/callback/{gateway_code}` là POST KHÔNG AUTH duy nhất của
# router thanh toán. Đường mã fail-OPEN ở ba chỗ độc lập:
#
#   1. `_gateway_adapters` RỖNG ở mọi request (`register_default_gateways` có
#      0 call-site sản xuất) ⇒ luôn rơi vào nhánh `else: # Mock parsing`, nơi
#      `gateway_ref`/`status`/`amount` lấy THẲNG từ thân request.
#   2. `if secret_key and not adapter.verify_signature(...)` — secret RỖNG thì
#      phép kiểm chữ ký bị BỎ QUA, không phải bị từ chối.
#   3. `gateway_code` của ROUTE không bao giờ được đối chiếu với phương thức
#      của intent.
#
# ---------------------------------------------------------------------------
# VÌ SAO GỌI QUA `process_gateway_callback` RỒI `commit`, CHỨ KHÔNG PHẢI
# `pytest.raises(...)` RỒI `rollback`
# ---------------------------------------------------------------------------
# Một bản nháp của chính bộ ca này đã XANH GIẢ vì viết theo lối đó. Thiệt hại
# thật KHÔNG nằm ở chỗ service ném ngoại lệ — nó nằm ở chỗ:
#
#     service gán + `flush()`  →  wrapper NUỐT ngoại lệ (không re-raise,
#     không rollback)  →  router `await db.commit()` VÔ ĐIỀU KIỆN.
#
# `pytest.raises` + `rollback` vứt bỏ đúng phép ghi cần đo, nên ca nào cũng
# xanh kể cả khi hàng `payment_intent` đã bị sửa. Vì thế bộ ca dưới đây dựng
# lại ĐÚNG chuỗi của router: gọi wrapper, rồi `commit`, rồi đọc lại hàng.
#
# Hệ quả: bất biến ở đây là "KHÔNG GHI", không phải "có ném". Một bản vá chỉ
# thêm `raise` mà vẫn gán trước khi ném sẽ VẪN ĐỎ — đúng như mong muốn.


@pytest.fixture(autouse=True)
def bat_mock_callback_cho_module(monkeypatch):
    """Nhánh mock phải TẮT mặc định; module này bật TƯỜNG MINH để test nó.

    Đặt thẳng trên object `settings` (không qua `os.environ`): `Settings` đã
    dựng xong lúc import, nên sửa biến môi trường lúc này không ai đọc — cùng
    lý do với `cho_phep_dong_ky`/`cho_phep_ap_phat` ở `tests/conftest.py`.
    """
    monkeypatch.setattr(settings, "PAYMENT_CALLBACK_MOCK_ENABLED", True)


class _AdapterGia:
    """Adapter tối thiểu — dựng ca "CÓ adapter nhưng chữ ký/secret hỏng".

    Không kế thừa `BaseGatewayAdapter`: lớp đó là ABC với nhiều abstractmethod
    không liên quan, mà `register_gateway` chỉ chú kiểu chứ không ép lúc chạy.
    """

    def __init__(self, *, gateway_ref: str, amount: Decimal, chu_ky_hop_le: bool):
        self._gateway_ref = gateway_ref
        self._amount = amount
        self._chu_ky_hop_le = chu_ky_hop_le
        self.so_lan_verify = 0

    def verify_signature(self, callback_data, secret_key) -> bool:
        self.so_lan_verify += 1
        return self._chu_ky_hop_le

    def parse_callback(self, callback_data):
        from app.gateways.base import GatewayResponse
        from app.gateways.base import GatewayStatusEnum as _GwStatus

        return GatewayResponse(
            gateway_ref=self._gateway_ref,
            status=_GwStatus(callback_data.get("status", "success")),
            amount=self._amount,
        )


async def _anh_chup_intent(db, intent_id: int) -> tuple:
    """Chụp hàng `payment_intent` bằng SELECT CỘT, không qua ORM.

    Chọn cột thay vì entity có chủ đích: identity map của ORM trả lại đối
    tượng đã nạp sẵn, nên một bản vá hỏng vẫn "xanh". Hàng cột luôn đọc lại
    từ CSDL.
    """
    return (
        await db.execute(
            select(
                PaymentIntent.status,
                PaymentIntent.gateway_status,
                PaymentIntent.callback_received_at,
                PaymentIntent.callback_data,
                PaymentIntent.gateway_response,
                PaymentIntent.completed_at,
            ).where(PaymentIntent.id == intent_id)
        )
    ).one()


async def _dem_payment(db) -> int:
    return (await db.execute(select(func.count()).select_from(Payment))).scalar_one()


async def _nhu_router(db, *, gateway_code: str, callback_data: dict) -> dict:
    """Chạy ĐÚNG chuỗi của `payments.py::payment_callback`.

    Gồm cả `commit` vô điều kiện — đó là thứ biến một phép `flush` trên nhánh
    lỗi thành thiệt hại vĩnh viễn.
    """
    service = PaymentIntentService(db)
    ket_qua, post_commit = await service.process_gateway_callback(
        gateway_code=gateway_code,
        callback_data=callback_data,
    )
    await db.commit()
    return ket_qua


class TestCallbackFailClosed:
    """Mỗi ca gỡ ĐÚNG MỘT hàng rào, để màu đỏ chỉ ra đúng thứ bị hỏng."""

    async def test_thieu_adapter_va_mock_tat_thi_khong_ghi_gi(
        self, db, intent_fixtures, monkeypatch
    ):
        """BẤT BIẾN 1 — không adapter + mock TẮT ⇒ từ chối, hàng intent đứng yên."""
        monkeypatch.setattr(settings, "PAYMENT_CALLBACK_MOCK_ENABLED", False)
        ma_cong = intent_fixtures["online_method"].code
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref
        truoc = await _anh_chup_intent(db, intent_id)

        ket_qua = await _nhu_router(
            db,
            gateway_code=ma_cong,
            callback_data={
                "gateway_ref": ref,
                "status": "success",
                "amount": str(_HOA_DON),
            },
        )

        assert ket_qua["success"] is False
        assert await _anh_chup_intent(db, intent_id) == truoc
        assert await _dem_payment(db) == 0

    async def test_mock_tat_thi_than_bao_failed_cung_khong_doi_intent(
        self, db, intent_fixtures, monkeypatch
    ):
        """BẤT BIẾN 1 — biến thể RẺ NHẤT của kẻ tấn công.

        Thân mang ĐÚNG số tiền nên KHÔNG chạm nhánh lệch số tiền; điều duy
        nhất nó nói là `status=failed`. Ở bản chưa vá nhánh này KHÔNG ném gì,
        chỉ đặt `intent.status = failed` rồi flush, router commit, API trả
        `200 {"status":"ok"}`. `failed` nằm trong `is_terminal` ⇒
        `can_process_callback` False VĨNH VIỄN ⇒ callback THẬT sau đó bị từ
        chối. Không mất đồng nào mà vẫn hỏng một intent còn hiệu lực.

        Bộ ca cũ mù đúng chỗ này vì nó chỉ hỏi `payment is None` — mà payment
        vốn dĩ là None trên nhánh đó.
        """
        monkeypatch.setattr(settings, "PAYMENT_CALLBACK_MOCK_ENABLED", False)
        ma_cong = intent_fixtures["online_method"].code
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref
        truoc = await _anh_chup_intent(db, intent_id)

        ket_qua = await _nhu_router(
            db,
            gateway_code=ma_cong,
            callback_data={
                "gateway_ref": ref,
                "status": "failed",
                "amount": str(_HOA_DON),
            },
        )

        assert ket_qua["success"] is False
        assert await _anh_chup_intent(db, intent_id) == truoc
        assert await _dem_payment(db) == 0

    async def test_secret_rong_khong_duoc_BO_QUA_phep_kiem_chu_ky(
        self, db, intent_fixtures
    ):
        """BẤT BIẾN 2 — secret rỗng bị TỪ CHỐI **TRƯỚC KHI** gọi adapter.

        Fixture dùng `code='intent_test_vnpay'` nên `secret_key` rơi về
        `getattr(settings, 'GATEWAY_INTENT_TEST_VNPAY_SECRET', '')` = rỗng.

        ⚠️ Chữ ký giả lập **HỢP LỆ** (`chu_ky_hop_le=True`) là chủ ý, và đó là
        điểm mấu chốt. Bản trước dựng adapter trả False, nên khi gỡ cổng
        `if not secret_key` thì luồng vẫn rơi xuống `verify_signature`, adapter
        vẫn từ chối, và cả ba assert cũ VẪN XANH — ca kiểm không chứng minh
        được "secret rỗng tự thân là lý do từ chối". Đo 20-09: đột biến vô hiệu
        riêng cổng ấy SỐNG SÓT 28/28.

        Với adapter trả True, chỉ còn đúng một thứ có thể từ chối callback này,
        nên cả hai đột biến đều phải ĐỎ:
          - gỡ hẳn khối `if not secret_key` ⇒ chữ ký "hợp lệ" ⇒ callback được
            CHẤP NHẬN ⇒ `success` True và sinh `payment` ⇒ đỏ;
          - lỗi lịch sử `if secret_key and not adapter.verify_signature(...)`
            ⇒ ngắn mạch, bỏ luôn phép kiểm ⇒ cũng được chấp nhận ⇒ đỏ.

        `so_lan_verify == 0` là bất biến về THỨ TỰ, không phải về kết quả: nó
        khoá "từ chối TRƯỚC adapter", nên một bản vá dời phép kiểm xuống sau
        `verify_signature` vẫn bị bắt dù kết quả cuối giống nhau.

        Mock vẫn BẬT: adapter CÓ mặt nên nhánh mock không dính dáng.
        """
        ma_cong = intent_fixtures["online_method"].code
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref
        truoc = await _anh_chup_intent(db, intent_id)

        service = PaymentIntentService(db)
        adapter = _AdapterGia(gateway_ref=ref, amount=_HOA_DON, chu_ky_hop_le=True)
        service.register_gateway(ma_cong, adapter)
        ket_qua, _ = await service.process_gateway_callback(
            gateway_code=ma_cong,
            callback_data={
                "gateway_ref": ref,
                "status": "success",
                "amount": str(_HOA_DON),
            },
        )
        await db.commit()

        # Bất biến THỨ TỰ: secret rỗng chặn trước, adapter không được đụng tới.
        assert adapter.so_lan_verify == 0
        assert ket_qua["success"] is False
        assert await _anh_chup_intent(db, intent_id) == truoc
        assert await _dem_payment(db) == 0

    async def test_cong_cua_route_phai_khop_phuong_thuc_cua_intent(
        self, db, intent_fixtures
    ):
        """BẤT BIẾN 3 — `gateway_code` của ROUTE khác `method.code` của intent ⇒ từ chối.

        Mock vẫn BẬT (fixture autouse) để màu đỏ chỉ đúng vào phép đối chiếu
        chứ không lẫn sang cổng mock.

        Phải so với `PaymentMethod.code` — KHÔNG phải `PaymentMethod.gateway_code`.
        `create_intent` dùng `gateway_code = method.code` để tra adapter; cột
        `gateway_code` tồn tại riêng và không nằm trên đường này. So nhầm cột
        là một phép kiểm xanh mà không canh gì.
        """
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref
        truoc = await _anh_chup_intent(db, intent_id)

        ket_qua = await _nhu_router(
            db,
            gateway_code="mot_cong_hoan_toan_khac",
            callback_data={
                "gateway_ref": ref,
                "status": "success",
                "amount": str(_HOA_DON),
            },
        )

        assert ket_qua["success"] is False
        assert await _anh_chup_intent(db, intent_id) == truoc
        assert await _dem_payment(db) == 0

    async def test_lech_so_tien_khong_duoc_GHI_truoc_khi_nem(
        self, db, intent_fixtures
    ):
        """BẤT BIẾN 4 — nhánh lệch số tiền phải KHÔNG ghi gì trước khi từ chối.

        Đây là ca người dùng chỉ ra. Ở bản chưa vá: `status=failed`,
        `gateway_status='amount_mismatch'`, `callback_received_at`,
        `callback_data = THÂN REQUEST THÔ`, rồi `flush()`, rồi mới `raise`.
        Wrapper nuốt, router commit ⇒ intent hỏng vĩnh viễn và thân request
        chưa xác thực nằm lại trong CSDL.

        ⚠️ Ca này KHÔNG phán xử chuyện "gateway ĐÃ xác thực báo sai số tiền
        thì có nên đánh dấu failed không" — đó là quyết định nghiệp vụ. Ở đây
        callback CHƯA hề được xác thực (không adapter, mock đang bật), nên nó
        không được phép ghi bất cứ thứ gì.
        """
        ma_cong = intent_fixtures["online_method"].code
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref
        truoc = await _anh_chup_intent(db, intent_id)

        ket_qua = await _nhu_router(
            db,
            gateway_code=ma_cong,
            callback_data={"gateway_ref": ref, "status": "success", "amount": "1"},
        )

        assert ket_qua["success"] is False
        assert await _anh_chup_intent(db, intent_id) == truoc
        assert await _dem_payment(db) == 0

    async def test_tao_payment_that_bai_thi_khong_de_lai_dau_vet_tren_intent(
        self, db, intent_fixtures
    ):
        """BẤT BIẾN 5 — chỉ được gán SAU khi mọi phép có thể ném đã đi qua.

        Dựng đúng hình dạng của `test_process_callback_refused_on_cancelled_fee`:
        fee bị huỷ SAU khi intent đã tạo, nên `_create_payment_from_intent` ném
        `BusinessRuleViolation`.

        Bản trước gán bốn trường — gồm `gateway_response = THÂN REQUEST THÔ` —
        TRƯỚC lời gọi đó. Wrapper nuốt ngoại lệ, router commit, và thân request
        chưa xác thực nằm lại trên một intent VẪN CÒN SỐNG (`created`, chưa hết
        hạn), sẵn sàng nhận callback thật sau này.

        Khe này KHÔNG có ca nào canh trước khi thêm: đẩy khối gán lên trước
        `_create_payment_from_intent` vẫn cho 25/25 xanh.
        """
        ma_cong = intent_fixtures["online_method"].code
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref

        # Huỷ fee NGOÀI luồng, sau khi intent đã tồn tại (race / phát hành lại).
        intent_fixtures["fee"].status = FeeStatusEnum.cancelled.value
        await db.commit()

        truoc = await _anh_chup_intent(db, intent_id)

        ket_qua = await _nhu_router(
            db,
            gateway_code=ma_cong,
            callback_data={
                "gateway_ref": ref,
                "status": "success",
                "amount": str(_HOA_DON),
            },
        )

        assert ket_qua["success"] is False
        assert await _anh_chup_intent(db, intent_id) == truoc
        assert await _dem_payment(db) == 0

    async def test_giao_dich_va_intent_giu_CUNG_mot_snapshot_gateway(
        self, db, intent_fixtures, monkeypatch
    ):
        """ĐỐI SOÁT — `PaymentTransaction.gateway_response` phải khớp `intent.gateway_response`.

        Hồi quy do CHÍNH đợt vá này đẻ ra: khi dời phép gán
        `intent.gateway_response` xuống SAU `_create_payment_from_intent`, mà
        bản ghi kiểm toán bên trong hàm đó lại ĐỌC `intent.gateway_response`,
        thì một giao dịch THÀNH CÔNG lưu snapshot RỖNG trong khi intent lại có
        dữ liệu — hai nguồn lệch nhau đúng ở bản ghi dùng để đối soát. Không ca
        nào trước đó đọc trường này, nên hồi quy lọt qua 26/26 xanh.

        Đây cũng là ca DUY NHẤT đi hết đường thành công với CHỮ KÝ HỢP LỆ. Phải
        dựng một `PaymentMethod` mã `vnpay` để `secret_key` rơi vào trường đã
        khai `settings.VNPAY_HASH_SECRET` — pydantic không cho đặt trường lạ,
        nên `GATEWAY_<MÃ>_SECRET` của mã tuỳ ý là không monkeypatch được.
        """
        monkeypatch.setattr(settings, "VNPAY_HASH_SECRET", "bi-mat-that")

        cong = PaymentMethod(
            code="vnpay", name="VNPay", is_online=True, is_active=True
        )
        db.add(cong)
        await db.flush()

        service = PaymentIntentService(db)
        intent, _ = await service.create_intent(
            invoice_id=intent_fixtures["invoice"].id,
            method_id=cong.id,
            amount=_HOA_DON,
            idempotency_key=str(uuid.uuid4()),
            return_url=VALID_RETURN_URL,
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()
        intent_id, ref = intent.id, intent.gateway_ref

        than = {"gateway_ref": ref, "status": "success", "amount": str(_HOA_DON)}

        service = PaymentIntentService(db)
        service.register_gateway(
            "vnpay",
            _AdapterGia(gateway_ref=ref, amount=_HOA_DON, chu_ky_hop_le=True),
        )
        ket_qua, _ = await service.process_gateway_callback(
            gateway_code="vnpay", callback_data=than
        )
        await db.commit()

        assert ket_qua["success"] is True
        assert await _dem_payment(db) == 1

        # `_anh_chup_intent` trả về theo thứ tự cột: status, gateway_status,
        # callback_received_at, callback_data, gateway_response, completed_at.
        sau = await _anh_chup_intent(db, intent_id)
        assert sau[4] == than, "intent phải giữ phản hồi gateway đã xác thực"

        snapshot_giao_dich = (
            (await db.execute(select(PaymentTransaction.gateway_response)))
            .scalars()
            .all()
        )
        assert snapshot_giao_dich == [than], (
            "PaymentTransaction phải giữ CÙNG snapshot với intent — lệch ở đây "
            "là lệch đúng bản ghi dùng để đối soát"
        )

    async def test_loi_SAU_mot_buoc_ghi_trung_gian_khong_de_lai_gi(
        self, db, intent_fixtures, monkeypatch
    ):
        """BẤT BIẾN 6 — NGUYÊN TỬ: lỗi sau một phép ghi trung gian không để lại gì.

        Ca `refused_on_cancelled_fee` chỉ phủ trường hợp ném TRƯỚC mọi phép
        ghi (`assert_payable_target`), nên nó không chứng minh được tính
        nguyên tử.

        Điểm bơm: `mo_so_tien_thua` — nằm SAU `db.add(payment)` + `flush()`
        VÀ sau khi `apply_verified_payment_balances` đã sửa
        `invoice.paid_amount`, `fee.paid_amount`, `fee.status`, `fee.version`.
        Bơm vì không có đường DỮ LIỆU THUẦN nào tới đó: ràng buộc bảng
        (`chk_payment_intent_amount_positive`, FK `resolved_major_id`) chặn hết
        các cách làm hỏng dữ liệu từ ngoài.

        ⚠️ Phải ném đúng `BusinessRuleViolation`: đó là một trong HAI lớp mà
        `process_gateway_callback` nuốt. Mọi lớp khác thoát ra và đã được
        router `except Exception` → `db.rollback()` xử lý, nên bơm lớp khác sẽ
        cho một ca xanh vô nghĩa.
        """
        from app.services import payment_intent_service as _module

        ma_cong = intent_fixtures["online_method"].code
        hoa_don_id = intent_fixtures["invoice"].id
        fee_id = intent_fixtures["fee"].id
        intent = await _tao_intent(db, intent_fixtures, _HOA_DON)
        intent_id, ref = intent.id, intent.gateway_ref

        truoc_intent = await _anh_chup_intent(db, intent_id)
        truoc_so_sach = (
            await db.execute(
                select(Invoice.paid_amount, Invoice.status).where(
                    Invoice.id == hoa_don_id
                )
            )
        ).one()
        truoc_fee = (
            await db.execute(
                select(Fee.paid_amount, Fee.status, Fee.version).where(Fee.id == fee_id)
            )
        ).one()

        def _no_giua_chung(*args, **kwargs):
            raise BusinessRuleViolation("lỗi bơm vào SAU một bước ghi trung gian")

        monkeypatch.setattr(_module, "mo_so_tien_thua", _no_giua_chung)

        ket_qua = await _nhu_router(
            db,
            gateway_code=ma_cong,
            callback_data={
                "gateway_ref": ref,
                "status": "success",
                "amount": str(_HOA_DON),
            },
        )

        assert ket_qua["success"] is False
        assert await _dem_payment(db) == 0, "payment dang dở phải bị cuộn lại"
        assert await _anh_chup_intent(db, intent_id) == truoc_intent
        assert (
            await db.execute(
                select(Invoice.paid_amount, Invoice.status).where(
                    Invoice.id == hoa_don_id
                )
            )
        ).one() == truoc_so_sach, "số dư hoá đơn phải đứng yên"
        assert (
            await db.execute(
                select(Fee.paid_amount, Fee.status, Fee.version).where(Fee.id == fee_id)
            )
        ).one() == truoc_fee, "số dư fee phải đứng yên"
        assert (
            await db.execute(select(func.count()).select_from(PaymentTransaction))
        ).scalar_one() == 0
        assert (
            await db.execute(select(func.count()).select_from(OverpaymentRecord))
        ).scalar_one() == 0
