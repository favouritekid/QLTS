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
from app.models.finance import (
    Fee, Invoice, PaymentIntent, PaymentMethod,
    FeeTypeEnum, FeeStatusEnum, InvoiceStatusEnum,
    PaymentIntentStatusEnum,
)
from app.services.fee_calculation_service import FeeCalculationService
from app.services.invoice_service import InvoiceService
from app.services.payment_intent_service import PaymentIntentService
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
)

pytestmark = pytest.mark.asyncio


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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
            unit_id=intent_fixtures["unit_id"],
        )
        await db.commit()

        intent2, _ = await service.create_intent(
            invoice_id=invoice.id,
            method_id=method.id,
            amount=Decimal("1000000"),
            idempotency_key=key,
            return_url="https://example.com/return",
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
                return_url="https://example.com/return",
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
                return_url="https://example.com/return",
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
                return_url="https://example.com/return",
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
                return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
            return_url="https://example.com/return",
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
                return_url="https://example.com/return",
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
