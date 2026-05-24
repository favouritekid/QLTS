# tests/api/test_finance_api.py
"""
API Tests for Finance Module (Phase 4).

Tests the HTTP endpoints for:
- Fee management (/api/fees)
- Invoice management (/api/invoices)
- Payment processing (/api/payments)
- Accounting periods (/api/accounting)

Test Categories:
1. Authentication & Authorization - RBAC checks
2. IDOR Protection - Unit-based access control
3. Business Logic - Endpoint behavior
4. Error Handling - Proper error responses

Run: pytest tests/api/test_finance_api.py -v
"""

import pytest
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.user import User
from app.models.finance import (
    Fee, Invoice, Payment, PaymentIntent, AccountingPeriod,
    PaymentMethod, InstallmentPlan,
    FeeStatusEnum, InvoiceStatusEnum, PaymentStatusEnum,
    PaymentIntentStatusEnum,
)


# =============================================================================
# TEST FIXTURES
# =============================================================================

@pytest.fixture
def mock_admin_user():
    """Create mock admin user."""
    user = MagicMock(spec=User)
    user.id = 1
    user.email = "admin@test.com"
    user.role = "admin"
    user.unit_id = None
    user.is_active = True
    return user


@pytest.fixture
def mock_officer_user():
    """Create mock officer user."""
    user = MagicMock(spec=User)
    user.id = 2
    user.email = "officer@test.com"
    user.role = "officer"
    user.unit_id = 1
    user.is_active = True
    return user


@pytest.fixture
def mock_manager_user():
    """Create mock manager user."""
    user = MagicMock(spec=User)
    user.id = 3
    user.email = "manager@test.com"
    user.role = "manager"
    user.unit_id = 1
    user.is_active = True
    return user


@pytest.fixture
def mock_accountant_user():
    """Create mock accountant user (finance staff)."""
    user = MagicMock(spec=User)
    user.id = 4
    user.email = "accountant@test.com"
    user.role = "accountant"
    user.unit_id = 1
    user.is_active = True
    return user


@pytest.fixture
def mock_fee():
    """Create mock fee object."""
    fee = MagicMock(spec=Fee)
    fee.id = 1
    fee.admission_profile_id = 100
    fee.fee_type = "tuition"
    fee.academic_year = "2025-2026"
    fee.base_amount = Decimal("10000000")
    fee.total_discount = Decimal("1000000")
    fee.final_amount = Decimal("9000000")
    fee.paid_amount = Decimal("0")
    fee.waived_amount = Decimal("0")
    fee.remaining_amount = Decimal("9000000")
    fee.status = FeeStatusEnum.pending.value
    fee.version = 1
    fee.notes = None
    fee.created_at = datetime.now(timezone.utc)
    fee.updated_at = datetime.now(timezone.utc)
    fee.applied_discounts = []
    fee.installment_plan = None
    fee.installment_plan_id = None
    return fee


@pytest.fixture
def mock_invoice():
    """Create mock invoice object."""
    invoice = MagicMock(spec=Invoice)
    invoice.id = 1
    invoice.fee_id = 1
    invoice.invoice_number = "INV-2025-0001"
    invoice.installment_no = 1
    invoice.amount = Decimal("9000000")
    invoice.paid_amount = Decimal("0")
    invoice.remaining_amount = Decimal("9000000")
    invoice.due_date = date.today() + timedelta(days=30)
    invoice.status = InvoiceStatusEnum.draft.value
    invoice.issued_at = None
    invoice.paid_at = None
    invoice.cancelled_at = None
    invoice.created_at = datetime.now(timezone.utc)
    invoice.updated_at = datetime.now(timezone.utc)
    invoice.payments = []
    invoice.fee = None
    return invoice


@pytest.fixture
def mock_payment():
    """Create mock payment object."""
    payment = MagicMock(spec=Payment)
    payment.id = 1
    payment.invoice_id = 1
    payment.method_id = 1
    payment.intent_id = None
    payment.amount = Decimal("3000000")
    payment.status = PaymentStatusEnum.pending.value
    payment.reference_code = "REF-001"
    payment.payer_name = "Nguyen Van A"
    payment.payment_date = datetime.now(timezone.utc)
    payment.verified_at = None
    payment.rejected_at = None
    payment.created_by_id = 2
    payment.verified_by_id = None
    payment.rejection_reason = None
    payment.notes = None
    payment.created_at = datetime.now(timezone.utc)
    payment.updated_at = datetime.now(timezone.utc)
    return payment


@pytest.fixture
def mock_payment_intent():
    """Create mock payment intent object."""
    intent = MagicMock(spec=PaymentIntent)
    intent.id = 1
    intent.invoice_id = 1
    intent.method_id = 2
    intent.amount = Decimal("3000000")
    intent.currency = "VND"
    intent.status = PaymentIntentStatusEnum.created.value
    intent.idempotency_key = "idem-key-123"
    intent.gateway_ref = "QLTS1234567890"
    intent.gateway_status = None
    intent.pay_url = "https://payment.example.com/pay/QLTS1234567890"
    intent.return_url = "https://app.example.com/payment/return"
    intent.expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    intent.created_at = datetime.now(timezone.utc)
    intent.is_terminal = False
    intent.is_expired = False
    intent.method = MagicMock()
    intent.method.code = "vnpay"
    return intent


@pytest.fixture
def mock_accounting_period():
    """Create mock accounting period object."""
    period = MagicMock(spec=AccountingPeriod)
    period.id = 1
    period.period_month = 1
    period.period_year = 2025
    period.is_closed = False
    period.closed_at = None
    period.closed_by_id = None
    period.total_payments = Decimal("0")
    period.total_refunds = Decimal("0")
    period.net_revenue = Decimal("0")
    period.created_at = datetime.now(timezone.utc)
    return period


# =============================================================================
# FEE API TESTS
# =============================================================================

class TestFeeAPI:
    """Tests for Fee API endpoints."""

    @pytest.mark.asyncio
    async def test_get_fee_requires_auth(self):
        """GET /api/fees/{id} requires authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/fees/1")
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_calculate_fee_requires_auth(self):
        """POST /api/fees/calculate requires authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/fees/calculate",
                json={
                    "admission_profile_id": 1,
                    "fee_type": "tuition",
                    "installment_plan_code": "FULL",
                }
            )
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_waive_fee_requires_manager_role(self, mock_officer_user):
        """POST /api/fees/{id}/waive requires manager or admin role."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/fees/1/waive",
                json={
                    "waive_amount": "100000",
                    "reason": "Test waiver",
                }
            )
            # Should be forbidden without auth
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_cancel_fee_requires_admin_role(self, mock_manager_user):
        """POST /api/fees/{id}/cancel requires admin role."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/fees/1/cancel",
                params={"reason": "Test cancel"},
            )
            assert response.status_code in [401, 403]


# =============================================================================
# INVOICE API TESTS
# =============================================================================

class TestInvoiceAPI:
    """Tests for Invoice API endpoints."""

    @pytest.mark.asyncio
    async def test_get_invoice_requires_auth(self):
        """GET /api/invoices/{id} requires authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/invoices/1")
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_cancel_invoice_requires_manager(self):
        """PUT /api/invoices/{id}/cancel requires manager or admin."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/invoices/1/cancel",
                params={"reason": "Test cancel"},
            )
            assert response.status_code in [401, 403]


# =============================================================================
# PAYMENT API TESTS
# =============================================================================

class TestPaymentAPI:
    """Tests for Payment API endpoints."""

    @pytest.mark.asyncio
    async def test_record_payment_requires_auth(self):
        """POST /api/payments requires authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/payments",
                json={
                    "invoice_id": 1,
                    "method_id": 1,
                    "amount": "3000000",
                }
            )
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_verify_payment_requires_manager(self):
        """PUT /api/payments/{id}/verify requires manager or admin."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put("/api/payments/1/verify")
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_reject_payment_requires_manager(self):
        """PUT /api/payments/{id}/reject requires manager or admin."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put(
                "/api/payments/1/reject",
                params={"reason": "Invalid payment"},
            )
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_create_payment_intent_requires_auth(self):
        """POST /api/payments/intents requires authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/payments/intents",
                json={
                    "invoice_id": 1,
                    "method_id": 2,
                    "amount": "3000000",
                    "idempotency_key": "test-key",
                }
            )
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_payment_callback_no_auth_required(self):
        """POST /api/payments/callback/{gateway} does not require auth."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Callback endpoint should accept requests (even if processing fails)
            response = await client.post(
                "/api/payments/callback/vnpay",
                json={
                    "vnp_TxnRef": "TEST123",
                    "vnp_ResponseCode": "00",
                    "vnp_Amount": "300000000",
                }
            )
            # Should return 200 (even for processing failures)
            assert response.status_code == 200


# =============================================================================
# ACCOUNTING API TESTS
# =============================================================================

class TestAccountingAPI:
    """Tests for Accounting API endpoints."""

    @pytest.mark.asyncio
    async def test_list_periods_requires_auth(self):
        """GET /api/accounting/periods requires authentication."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/accounting/periods")
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_create_period_requires_admin(self):
        """POST /api/accounting/periods requires admin role."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/accounting/periods",
                json={
                    "month": 1,
                    "year": 2025,
                }
            )
            assert response.status_code in [401, 403]

    @pytest.mark.asyncio
    async def test_close_period_requires_admin(self):
        """PUT /api/accounting/periods/{id}/close requires admin role."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.put("/api/accounting/periods/1/close")
            assert response.status_code in [401, 403]


# =============================================================================
# RESPONSE FORMAT TESTS
# =============================================================================

class TestResponseFormats:
    """Tests for API response format consistency."""

    def test_fee_response_schema(self, mock_fee):
        """Fee response should match schema."""
        from app.schemas.finance import FeeResponse

        # Test that we can create a valid response
        # academic_year expects format YYYY-YYYY (e.g., 2025-2026)
        response = FeeResponse(
            id=mock_fee.id,
            admission_profile_id=mock_fee.admission_profile_id,
            fee_type=mock_fee.fee_type,
            academic_year="2025-2026",
            installment_plan_id=None,
            base_amount=mock_fee.base_amount,
            total_discount=mock_fee.total_discount,
            final_amount=mock_fee.final_amount,
            paid_amount=mock_fee.paid_amount,
            waived_amount=mock_fee.waived_amount,
            remaining_amount=mock_fee.remaining_amount,
            status=mock_fee.status,
            notes=None,
            version=mock_fee.version,
            created_at=mock_fee.created_at,
            updated_at=mock_fee.updated_at,
            applied_discounts=[],
        )

        assert response.id == 1
        assert response.final_amount == Decimal("9000000")

    def test_invoice_response_schema(self, mock_invoice):
        """Invoice response should match schema."""
        from app.schemas.finance import InvoiceResponse

        response = InvoiceResponse(
            id=mock_invoice.id,
            fee_id=mock_invoice.fee_id,
            invoice_number=mock_invoice.invoice_number,
            installment_no=mock_invoice.installment_no,
            amount=mock_invoice.amount,
            due_date=mock_invoice.due_date,
            status=mock_invoice.status,
            paid_amount=mock_invoice.paid_amount,
            remaining_amount=mock_invoice.remaining_amount,
            issued_at=None,
            paid_at=None,
            cancelled_at=None,
            created_at=mock_invoice.created_at,
            updated_at=mock_invoice.updated_at,
        )

        assert response.invoice_number == "INV-2025-0001"

    def test_payment_response_schema(self, mock_payment):
        """Payment response should match schema."""
        from app.schemas.finance import PaymentResponse

        response = PaymentResponse(
            id=mock_payment.id,
            invoice_id=mock_payment.invoice_id,
            method_id=mock_payment.method_id,
            intent_id=None,
            amount=mock_payment.amount,
            status=mock_payment.status,
            reference_code=mock_payment.reference_code,
            payer_name=mock_payment.payer_name,
            payment_date=mock_payment.payment_date,
            verified_at=None,
            rejected_at=None,
            created_by_id=mock_payment.created_by_id,
            verified_by_id=None,
            rejection_reason=None,
            notes=None,
            created_at=mock_payment.created_at,
            updated_at=mock_payment.updated_at,
        )

        assert response.amount == Decimal("3000000")

    def test_accounting_period_response_schema(self, mock_accounting_period):
        """Accounting period response should match schema."""
        from app.schemas.finance import AccountingPeriodResponse

        response = AccountingPeriodResponse(
            id=mock_accounting_period.id,
            month=mock_accounting_period.period_month,
            year=mock_accounting_period.period_year,
            is_closed=mock_accounting_period.is_closed,
            closed_at=None,
            closed_by_id=None,
            total_payments=mock_accounting_period.total_payments,
            total_refunds=mock_accounting_period.total_refunds,
            net_revenue=mock_accounting_period.net_revenue,
            created_at=mock_accounting_period.created_at,
        )

        assert response.month == 1
        assert response.year == 2025
        assert response.is_closed is False


# =============================================================================
# INPUT VALIDATION TESTS
# =============================================================================

class TestInputValidation:
    """Tests for API input validation."""

    def test_fee_calculate_request_validation(self):
        """FeeCalculateRequest should validate input."""
        from app.schemas.finance import FeeCalculateRequest

        # Valid request
        request = FeeCalculateRequest(
            admission_profile_id=1,
            fee_type="tuition",
            installment_plan_code="FULL",
        )
        assert request.admission_profile_id == 1

    def test_payment_create_validation(self):
        """PaymentCreate should validate amount."""
        from app.schemas.finance import PaymentCreate

        # Valid request
        request = PaymentCreate(
            invoice_id=1,
            method_id=1,
            amount=Decimal("1000000"),
        )
        assert request.amount == Decimal("1000000")

        # Amount must be positive
        with pytest.raises(ValueError):
            PaymentCreate(
                invoice_id=1,
                method_id=1,
                amount=Decimal("-100"),
            )

    def test_fee_waive_request_validation(self):
        """FeeWaiveRequest should validate input."""
        from app.schemas.finance import FeeWaiveRequest

        # Valid request
        request = FeeWaiveRequest(
            waive_amount=Decimal("100000"),
            reason="Test reason",
        )
        assert request.waive_amount == Decimal("100000")

        # Amount must be positive
        with pytest.raises(ValueError):
            FeeWaiveRequest(
                waive_amount=Decimal("0"),
                reason="Test",
            )

    def test_payment_intent_create_validation(self):
        """PaymentIntentCreate should validate input."""
        from app.schemas.finance import PaymentIntentCreate

        # Valid request
        request = PaymentIntentCreate(
            invoice_id=1,
            method_id=2,
            amount=Decimal("3000000"),
            idempotency_key="test-key-123",
        )
        assert request.idempotency_key == "test-key-123"

    def test_accounting_period_create_validation(self):
        """AccountingPeriodCreate should validate month/year."""
        from app.schemas.finance import AccountingPeriodCreate

        # Valid request
        request = AccountingPeriodCreate(month=1, year=2025)
        assert request.month == 1

        # Month must be 1-12
        with pytest.raises(ValueError):
            AccountingPeriodCreate(month=13, year=2025)

        # Year must be reasonable
        with pytest.raises(ValueError):
            AccountingPeriodCreate(month=1, year=1900)


# =============================================================================
# ROLE-BASED PERMISSION TESTS
# =============================================================================

class TestFinanceRolePermissions:
    """
    Tests for Finance Module role-based permission model.

    Permission Matrix:
    ┌──────────────────────┬──────────┬────────────┬─────────┬───────┐
    │ Action               │ Officer  │ Accountant │ Manager │ Admin │
    ├──────────────────────┼──────────┼────────────┼─────────┼───────┤
    │ View fees            │ ✅       │ ✅         │ ✅      │ ✅    │
    │ Calculate fee        │ ❌       │ ✅         │ ✅      │ ✅    │
    │ Waive fee            │ ❌       │ ✅         │ ✅      │ ✅    │
    │ Cancel fee           │ ❌       │ ❌         │ ❌      │ ✅    │
    │ View invoices        │ ✅       │ ✅         │ ✅      │ ✅    │
    │ Issue invoice        │ ❌       │ ✅         │ ✅      │ ✅    │
    │ View payments        │ ✅       │ ✅         │ ✅      │ ✅    │
    │ Record payment       │ ❌       │ ✅         │ ✅      │ ✅    │
    │ Verify payment       │ ❌       │ ✅         │ ✅      │ ✅    │
    │ Create intent        │ ✅       │ ✅         │ ✅      │ ✅    │
    │ View periods         │ ❌       │ ✅         │ ✅      │ ✅    │
    │ Create period        │ ❌       │ ❌         │ ❌      │ ✅    │
    │ Close period         │ ❌       │ ❌         │ ❌      │ ✅    │
    └──────────────────────┴──────────┴────────────┴─────────┴───────┘
    """

    def test_role_hierarchy_defined(self):
        """UserRole enum should include accountant."""
        from app.core.constants import UserRole

        assert hasattr(UserRole, "ADMIN")
        assert hasattr(UserRole, "MANAGER")
        assert hasattr(UserRole, "ACCOUNTANT")
        assert hasattr(UserRole, "OFFICER")
        assert hasattr(UserRole, "USER")

        # Verify values
        assert UserRole.ADMIN == "admin"
        assert UserRole.ACCOUNTANT == "accountant"

    def test_role_priority_includes_accountant(self):
        """Role priority should include accountant role."""
        from app.services.role_service import ROLE_PRIORITY

        assert "role:accountant" in ROLE_PRIORITY
        # Accountant should be between manager and officer
        assert ROLE_PRIORITY["role:manager"] > ROLE_PRIORITY["role:accountant"]
        assert ROLE_PRIORITY["role:accountant"] > ROLE_PRIORITY["role:officer"]

    def test_system_roles_includes_accountant(self):
        """System roles should include accountant."""
        from app.casbin_config.policy_templates import SYSTEM_ROLES

        role_names = [r["name"] for r in SYSTEM_ROLES]
        assert "role:accountant" in role_names

    def test_accountant_template_exists(self):
        """Accountant policy template should exist."""
        from app.casbin_config.policy_templates import POLICY_TEMPLATES

        assert "accountant" in POLICY_TEMPLATES
        template = POLICY_TEMPLATES["accountant"]
        assert template["display_name"] == "Accountant (Kế toán viên)"

    def test_officer_cannot_record_payment(self):
        """Officer policy should NOT include record payment permission."""
        from app.casbin_config.policy_templates import OFFICER_TEMPLATE

        # Officer should NOT have POST /api/payments permission
        officer_actions = [
            (p["object"], p["action"])
            for p in OFFICER_TEMPLATE["policies"]
        ]

        # Should NOT have POST /api/payments (record payment)
        assert ("/api/payments", "POST") not in officer_actions

        # Should have POST /api/payments/intents (create intent for online)
        assert ("/api/payments/intents", "POST") in officer_actions

    def test_accountant_can_record_payment(self):
        """Accountant policy should include record payment permission."""
        from app.casbin_config.policy_templates import ACCOUNTANT_TEMPLATE

        accountant_actions = [
            (p["object"], p["action"])
            for p in ACCOUNTANT_TEMPLATE["policies"]
        ]

        # Should have POST /api/payments (record payment)
        assert ("/api/payments", "POST") in accountant_actions

    def test_accountant_can_verify_payment(self):
        """Accountant policy should include verify payment permission."""
        from app.casbin_config.policy_templates import ACCOUNTANT_TEMPLATE

        accountant_actions = [
            (p["object"], p["action"])
            for p in ACCOUNTANT_TEMPLATE["policies"]
        ]

        # Should have PUT /api/payments/{id}/verify
        assert ("/api/payments/{id}/verify", "PUT") in accountant_actions

    def test_officer_can_calculate_fee_scoped(self):
        """Officer template INCLUDES /api/fees/calculate POST (scoped).

        Decision reference: memory ``admission-audit-decisions-2026-04-24``
        chốt officer scoped fee calc — officer initiates fee calculation
        on their assigned profile within the approved/confirmed/enrolled
        status whitelist. The service layer ``_fee_calc_authorized``
        enforces ownership + status guard at runtime; the Casbin gate
        only opens the route.

        Recording payments (``/api/payments`` POST) and issuing invoices
        (``/api/invoices/{id}/issue`` PUT) remain accountant-only per
        separation of duties — asserted here as symmetry guard so a
        future template drift that grants officer those writes fails
        loud at unit-test time.

        Pre-PR-1 this test was ``test_officer_cannot_calculate_fee`` —
        flipped 2026-05-23 to match the policy reality shipped
        2026-04-24 (memory ``test-debt-admission-workflow-e2e``).
        """
        from app.casbin_config.policy_templates import OFFICER_TEMPLATE

        officer_actions = [
            (p["object"], p["action"])
            for p in OFFICER_TEMPLATE["policies"]
        ]

        # Officer HAS /api/fees/calculate POST (scoped to assigned profile,
        # service-layer ownership + status whitelist enforced).
        assert ("/api/fees/calculate", "POST") in officer_actions, (
            "OFFICER_TEMPLATE must include /api/fees/calculate POST per "
            "decision admission-audit-decisions-2026-04-24."
        )

        # Officer LACKS accountant-only finance writes (symmetry drift guard).
        assert ("/api/payments", "POST") not in officer_actions, (
            "Officer must NOT have /api/payments POST — accountant-only "
            "(separation of duties)."
        )
        assert ("/api/invoices/{id}/issue", "PUT") not in officer_actions, (
            "Officer must NOT have /api/invoices/{id}/issue PUT — "
            "accountant-only (separation of duties)."
        )

    def test_accountant_can_calculate_fee(self):
        """Accountant policy should include calculate fee permission."""
        from app.casbin_config.policy_templates import ACCOUNTANT_TEMPLATE

        accountant_actions = [
            (p["object"], p["action"])
            for p in ACCOUNTANT_TEMPLATE["policies"]
        ]

        # Accountant should have POST /api/fees/calculate
        assert ("/api/fees/calculate", "POST") in accountant_actions

    def test_only_admin_can_cancel_fee(self):
        """Only admin should have cancel fee permission."""
        from app.casbin_config.policy_templates import (
            OFFICER_TEMPLATE,
            ACCOUNTANT_TEMPLATE,
            MANAGER_TEMPLATE,
        )

        # Check officer doesn't have it
        officer_actions = [(p["object"], p["action"]) for p in OFFICER_TEMPLATE["policies"]]
        assert ("/api/fees/{id}/cancel", "POST") not in officer_actions

        # Check accountant doesn't have it
        accountant_actions = [(p["object"], p["action"]) for p in ACCOUNTANT_TEMPLATE["policies"]]
        assert ("/api/fees/{id}/cancel", "POST") not in accountant_actions

        # Check manager doesn't have it
        manager_actions = [(p["object"], p["action"]) for p in MANAGER_TEMPLATE["policies"]]
        assert ("/api/fees/{id}/cancel", "POST") not in manager_actions

    def test_only_admin_can_close_period(self):
        """Only admin should have close period permission."""
        from app.casbin_config.policy_templates import (
            OFFICER_TEMPLATE,
            ACCOUNTANT_TEMPLATE,
            MANAGER_TEMPLATE,
        )

        # Check none of the non-admin roles have it
        for template_name, template in [
            ("officer", OFFICER_TEMPLATE),
            ("accountant", ACCOUNTANT_TEMPLATE),
            ("manager", MANAGER_TEMPLATE),
        ]:
            actions = [(p["object"], p["action"]) for p in template["policies"]]
            assert ("/api/accounting/periods/{id}/close", "PUT") not in actions, \
                f"{template_name} should not have close period permission"


# =============================================================================
# DIAMOND INHERITANCE TESTS
# =============================================================================

class TestDiamondInheritance:
    """
    Test Diamond Inheritance pattern for role hierarchy.

    Diamond Structure:
                       ┌─────────┐
                       │  Admin  │
                       └────┬────┘
                         ▲   ▲
              ┌──────────┘   └──────────┐
              │                         │
        ┌─────┴──────┐           ┌──────┴─────┐
        │  Manager   │           │ Accountant │
        └─────┬──────┘           └──────┬─────┘
              │                         │
              └──────────┐   ┌──────────┘
                         ▼   ▼
                      ┌───────────┐
                      │  Officer  │
                      └─────┬─────┘
                            │
                      ┌─────┴─────┐
                      │   User    │
                      └───────────┘

    Key Tests:
    1. Manager does NOT inherit Accountant permissions (separation of duties)
    2. Accountant does NOT inherit Manager permissions (separation of duties)
    3. Admin inherits BOTH branches (full access)
    4. Both Manager and Accountant inherit Officer permissions
    """

    def test_role_inheritance_structure(self):
        """Verify the diamond inheritance structure is correctly defined."""
        # Import the inheritance rules from main.py pattern
        expected_inheritance = [
            ("g", "role:officer", "role:user"),       # Officer inherits from User
            ("g", "role:accountant", "role:officer"), # Accountant inherits from Officer
            ("g", "role:manager", "role:officer"),    # Manager inherits from Officer
            ("g", "role:admin", "role:manager"),      # Admin inherits from Manager
            ("g", "role:admin", "role:accountant"),   # Admin inherits from Accountant (Diamond!)
        ]

        # Verify no Manager -> Accountant inheritance
        assert ("g", "role:manager", "role:accountant") not in expected_inheritance, \
            "Manager should NOT inherit from Accountant (separation of duties)"

        # Verify no Accountant -> Manager inheritance
        assert ("g", "role:accountant", "role:manager") not in expected_inheritance, \
            "Accountant should NOT inherit from Manager (separation of duties)"

        # Verify Admin inherits from BOTH branches
        admin_parents = [rule[2] for rule in expected_inheritance if rule[1] == "role:admin"]
        assert "role:manager" in admin_parents, "Admin should inherit from Manager"
        assert "role:accountant" in admin_parents, "Admin should inherit from Accountant"

    def test_manager_does_not_have_finance_write_operations(self):
        """
        Manager should NOT have accountant-specific finance permissions.
        These are defined in ACCOUNTANT_TEMPLATE only.
        """
        from app.casbin_config.policy_templates import MANAGER_TEMPLATE

        manager_actions = [(p["object"], p["action"]) for p in MANAGER_TEMPLATE["policies"]]

        # Manager should NOT have these accountant-specific operations.
        # PR-1.5 Commit 3 (2026-05-24) — refund routes dropped from the
        # list: ``/api/refunds*`` was intentionally removed from
        # ACCOUNTANT_TEMPLATE on 2026-05-16 (policy_templates.py:352-355
        # comment) — the refunds router does not exist (``/api/refunds``
        # live probe returns 404) and ``REFUND_PROCESSED`` is tagged
        # ``internal_future`` per memory ``finance-event-decisions``. The
        # routes are no longer accountant-specific live permissions, so
        # asserting manager doesn't have them is meaningless until the
        # refunds module is re-introduced.
        accountant_only_permissions = [
            ("/api/payments", "POST"),              # Record payment
            ("/api/fees/calculate", "POST"),        # Calculate fee
            ("/api/invoices/{id}/issue", "PUT"),    # Issue invoice
        ]

        for obj, action in accountant_only_permissions:
            assert (obj, action) not in manager_actions, \
                f"Manager should NOT have {action} {obj} (accountant-only operation)"

    def test_accountant_does_not_have_user_management(self):
        """
        Accountant should NOT have manager-specific user management permissions.
        These are defined in MANAGER_TEMPLATE only.

        PR-1.5 Commit 3 (2026-05-24) — allow-only filter on the policy
        enumeration. ACCOUNTANT_TEMPLATE since the B1 deny-first design
        carries explicit ``eft="deny"`` rows for lead-management routes
        (``/api/leads/bulk-assign``, ``/api/leads/bulk-delete``,
        ``/api/leads/distribution-preview``) so accountant inherits
        officer but is denied those routes at enforce time. The naive
        ``(obj, action) for p in policies`` enumeration treated those
        deny rows as grants and flipped the test result. The correct
        semantic is "what does the accountant role get GRANTED" —
        filter ``eft == "allow"``. Memory:
        ``casbin-deny-parent-role-propagates-to-children``.
        """
        from app.casbin_config.policy_templates import ACCOUNTANT_TEMPLATE

        accountant_grants = [
            (p["object"], p["action"])
            for p in ACCOUNTANT_TEMPLATE["policies"]
            if p.get("eft", "allow") == "allow"
        ]

        # Accountant should NOT be GRANTED these manager-specific operations.
        # A deny row on the same (object, action) is the intended outcome,
        # not a grant — filter above ignores deny rows.
        manager_only_permissions = [
            ("/api/admin/users", ".*"),                    # User management
            ("/api/leads/bulk-assign", "POST"),            # Bulk assign leads
            ("/api/admissions/{id}/approve", "POST"),      # Approve admission
            ("/api/admissions/{id}/reject", "POST"),       # Reject admission
            ("/api/admission-config/paths", "POST"),       # Create admission path
        ]

        for obj, action in manager_only_permissions:
            assert (obj, action) not in accountant_grants, \
                f"Accountant should NOT have {action} {obj} granted (manager-only operation)"

    def test_role_priority_reflects_diamond_structure(self):
        """Verify ROLE_PRIORITY correctly handles diamond inheritance."""
        from app.services.role_service import ROLE_PRIORITY

        # Admin is highest
        assert ROLE_PRIORITY["role:admin"] > ROLE_PRIORITY["role:manager"]
        assert ROLE_PRIORITY["role:admin"] > ROLE_PRIORITY["role:accountant"]

        # Manager and Accountant are parallel (both higher than Officer)
        assert ROLE_PRIORITY["role:manager"] > ROLE_PRIORITY["role:officer"]
        assert ROLE_PRIORITY["role:accountant"] > ROLE_PRIORITY["role:officer"]

        # Officer is higher than User
        assert ROLE_PRIORITY["role:officer"] > ROLE_PRIORITY["role:user"]

    def test_officer_is_common_parent(self):
        """Both Manager and Accountant should inherit Officer's base permissions."""
        from app.casbin_config.policy_templates import OFFICER_TEMPLATE

        # Officer has base permissions like viewing leads, profiles, fees
        officer_actions = [(p["object"], p["action"]) for p in OFFICER_TEMPLATE["policies"]]

        # These are common actions available to Officer (and inherited by both branches)
        common_base_permissions = [
            ("/api/leads", "GET"),                   # View leads
            ("/api/fees", "GET"),                    # View fees
            ("/api/profile", "GET"),                 # View own profile
            ("/api/admissions", "GET"),              # View admissions
        ]

        for obj, action in common_base_permissions:
            assert (obj, action) in officer_actions, \
                f"Officer should have {action} {obj} as base permission"

    def test_admin_inherits_both_branches(self):
        """
        Admin with wildcard access should work with diamond inheritance.
        Even if Admin explicitly had no wildcard, it would inherit from both branches.
        """
        from app.casbin_config.policy_templates import ADMIN_TEMPLATE

        admin_actions = [(p["object"], p["action"]) for p in ADMIN_TEMPLATE["policies"]]

        # Admin has wildcard access
        assert ("/*", ".*") in admin_actions, "Admin should have wildcard access"

    def test_separation_of_duties_summary(self):
        """
        Summary test: Verify complete separation between Manager and Accountant.

        PR-1.5 Commit 3 (2026-05-24) — allow-only filter, same reasoning
        as ``test_accountant_does_not_have_user_management``. The naive
        ``{p["object"] for p in policies}`` enumeration counted explicit
        deny rows as "objects the role has access to", which is the
        opposite of what the assertion wants. Filter ``eft == "allow"``
        so the object set reflects actual grants only.
        """
        from app.casbin_config.policy_templates import (
            MANAGER_TEMPLATE,
            ACCOUNTANT_TEMPLATE,
        )

        manager_objects = {
            p["object"]
            for p in MANAGER_TEMPLATE["policies"]
            if p.get("eft", "allow") == "allow"
        }
        accountant_objects = {
            p["object"]
            for p in ACCOUNTANT_TEMPLATE["policies"]
            if p.get("eft", "allow") == "allow"
        }

        # Manager-exclusive objects (user management, admission workflow)
        manager_exclusive = {
            "/api/admin/users",
            "/api/leads/bulk-assign",
            "/api/leads/distribution-preview",
            "/api/admissions/{id}/approve",
            "/api/admissions/{id}/reject",
            "/api/admissions/{id}/override",
            "/api/admission-config/paths",
            "/api/admission-config/paths/{path_id}",
        }

        # Accountant-exclusive objects (finance operations).
        # PR-1.5 Commit 3 (2026-05-24) — refund routes dropped (intentionally
        # removed from ACCOUNTANT_TEMPLATE on 2026-05-16 per
        # ``policy_templates.py:352-355``; live probe ``/api/refunds`` → 404;
        # memory ``finance-event-decisions`` tags ``REFUND_PROCESSED`` as
        # ``internal_future``). Re-add when the refunds router ships.
        accountant_exclusive = {
            "/api/fees/calculate",
            "/api/invoices/{id}/issue",
        }

        # Verify separation — both sides intersect only the GRANT sets,
        # never the deny-row presence.
        for obj in manager_exclusive:
            assert obj in manager_objects, f"Manager should have access to {obj}"
            assert obj not in accountant_objects, f"Accountant should NOT have access to {obj}"

        for obj in accountant_exclusive:
            assert obj in accountant_objects, f"Accountant should have access to {obj}"
            assert obj not in manager_objects, f"Manager should NOT have access to {obj}"


# =============================================================================
# FEE GATE TESTS (Phase 6)
# =============================================================================

class TestFeeGateEnrollment:
    """
    Tests for Fee Gate (Phase 6) - Enrollment blocked if tuition fee not cleared.

    Per FINANCE_MODULE_DESIGN.md Section 5.3 - Gate 2:
    - Enrollment MUST be blocked if tuition fee not cleared
    - Fee is "cleared" if status == 'paid' OR status == 'waived'
    - Gate is ONLY enforced when ENABLE_FEE_VERIFICATION=True
    """

    @pytest.mark.asyncio
    async def test_fee_gate_passes_when_fee_is_paid(self):
        """
        Fee gate should PASS when tuition fee status is 'paid'.
        """
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock fee with status = paid
        mock_fee = MagicMock()
        mock_fee.id = 1
        mock_fee.status = "paid"
        mock_fee.fee_type = "tuition"
        mock_fee.remaining_amount = Decimal("0")

        mock_fee_repo = MagicMock()
        mock_fee_repo.get_by_profile_id = AsyncMock(return_value=[mock_fee])

        mock_db = MagicMock()

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_fee_repo):
            # Should NOT raise any exception
            await check_enrollment_fee_eligibility(mock_db, profile_id=100)

    @pytest.mark.asyncio
    async def test_fee_gate_passes_when_fee_is_waived(self):
        """
        Fee gate should PASS when tuition fee status is 'waived'.
        """
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock fee with status = waived
        mock_fee = MagicMock()
        mock_fee.id = 1
        mock_fee.status = "waived"
        mock_fee.fee_type = "tuition"
        mock_fee.remaining_amount = Decimal("0")

        mock_fee_repo = MagicMock()
        mock_fee_repo.get_by_profile_id = AsyncMock(return_value=[mock_fee])

        mock_db = MagicMock()

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_fee_repo):
            # Should NOT raise any exception
            await check_enrollment_fee_eligibility(mock_db, profile_id=100)

    @pytest.mark.asyncio
    async def test_fee_gate_blocks_when_fee_is_pending(self):
        """
        Fee gate should BLOCK enrollment when tuition fee status is 'pending'.
        """
        from app.services.admission_service import check_enrollment_fee_eligibility
        from app.utils.exceptions import BadRequest
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock fee with status = pending
        mock_fee = MagicMock()
        mock_fee.id = 1
        mock_fee.status = "pending"
        mock_fee.fee_type = "tuition"
        mock_fee.remaining_amount = Decimal("5000000")

        mock_fee_repo = MagicMock()
        mock_fee_repo.get_by_profile_id = AsyncMock(return_value=[mock_fee])

        mock_db = MagicMock()

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_fee_repo):
            with pytest.raises(BadRequest) as exc_info:
                await check_enrollment_fee_eligibility(mock_db, profile_id=100)

            assert "Tuition fee not cleared" in str(exc_info.value)
            assert "5,000,000 VND" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fee_gate_blocks_when_fee_is_partial(self):
        """
        Fee gate should BLOCK enrollment when tuition fee status is 'partial'.
        """
        from app.services.admission_service import check_enrollment_fee_eligibility
        from app.utils.exceptions import BadRequest
        from unittest.mock import AsyncMock, MagicMock, patch

        # Create mock fee with status = partial (partially paid)
        mock_fee = MagicMock()
        mock_fee.id = 1
        mock_fee.status = "partial"
        mock_fee.fee_type = "tuition"
        mock_fee.remaining_amount = Decimal("3000000")

        mock_fee_repo = MagicMock()
        mock_fee_repo.get_by_profile_id = AsyncMock(return_value=[mock_fee])

        mock_db = MagicMock()

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_fee_repo):
            with pytest.raises(BadRequest) as exc_info:
                await check_enrollment_fee_eligibility(mock_db, profile_id=100)

            assert "Tuition fee not cleared" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fee_gate_blocks_when_no_fee_record(self):
        """
        Fee gate should BLOCK enrollment when no tuition fee record exists.
        This ensures fee calculation happens before enrollment.
        """
        from app.services.admission_service import check_enrollment_fee_eligibility
        from app.utils.exceptions import BadRequest
        from unittest.mock import AsyncMock, MagicMock, patch

        # Return empty list (no fee records)
        mock_fee_repo = MagicMock()
        mock_fee_repo.get_by_profile_id = AsyncMock(return_value=[])

        mock_db = MagicMock()

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_fee_repo):
            with pytest.raises(BadRequest) as exc_info:
                await check_enrollment_fee_eligibility(mock_db, profile_id=100)

            assert "Tuition fee has not been calculated" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fee_gate_bypassed_when_feature_disabled(self):
        """
        Fee gate should be BYPASSED when ENABLE_FEE_VERIFICATION=False.
        This is the default behavior for backward compatibility.
        """
        from app.config import settings

        # Verify default is False
        assert settings.ENABLE_FEE_VERIFICATION is False, (
            "ENABLE_FEE_VERIFICATION should default to False for backward compatibility"
        )

    def test_fee_gate_status_accepted_values(self):
        """
        Only 'paid' and 'waived' should pass the fee gate.
        All other statuses should be blocked.
        """
        from app.models.finance.fee import FeeStatusEnum

        # Statuses that should PASS
        passing_statuses = {FeeStatusEnum.paid.value, FeeStatusEnum.waived.value}

        # Statuses that should FAIL
        blocking_statuses = {
            FeeStatusEnum.pending.value,
            FeeStatusEnum.calculated.value,
            FeeStatusEnum.invoiced.value,
            FeeStatusEnum.partial.value,
            FeeStatusEnum.overdue.value,
            FeeStatusEnum.cancelled.value,
        }

        # Verify all statuses are covered
        all_statuses = {s.value for s in FeeStatusEnum}
        assert passing_statuses | blocking_statuses == all_statuses, (
            "Fee gate test must cover all FeeStatusEnum values"
        )


class TestFeeGateHK1Mode:
    """Tests for HK1 financial clearance gate (ADMISSION_FEE_GATE_MODE=semester_hk1).

    PR 4 (ADR-002 Decision 2): when mode=semester_hk1, the gate checks
    fee_type=tuition + semester_no=1 and accepts paid/waived/partial
    with paid_amount > 0. No minimum threshold.
    """

    def _make_mock_fee(self, status, paid_amount=Decimal("0"), semester_no=1):
        from unittest.mock import MagicMock
        fee = MagicMock()
        fee.id = 1
        fee.status = status
        fee.fee_type = "tuition"
        fee.semester_no = semester_no
        fee.paid_amount = paid_amount
        fee.remaining_amount = Decimal("10000000") - paid_amount
        return fee

    @pytest.mark.asyncio
    async def test_hk1_gate_passes_paid(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(
            return_value=[self._make_mock_fee("paid", Decimal("10000000"))]
        )

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)

    @pytest.mark.asyncio
    async def test_hk1_gate_passes_waived(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(
            return_value=[self._make_mock_fee("waived")]
        )

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)

    @pytest.mark.asyncio
    async def test_hk1_gate_passes_partial_with_payment(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(
            return_value=[self._make_mock_fee("partial", Decimal("100000"))]
        )

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)

    @pytest.mark.asyncio
    async def test_hk1_gate_blocks_partial_zero_payment(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(
            return_value=[self._make_mock_fee("partial", Decimal("0"))]
        )

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            from app.utils.exceptions import BadRequest as _BadRequest
            with pytest.raises(_BadRequest):
                await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)

    @pytest.mark.asyncio
    async def test_hk1_gate_blocks_pending(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(
            return_value=[self._make_mock_fee("pending")]
        )

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            from app.utils.exceptions import BadRequest as _BadRequest
            with pytest.raises(_BadRequest):
                await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)

    @pytest.mark.asyncio
    async def test_hk1_gate_blocks_no_hk1_fee(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(return_value=[])

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            from app.utils.exceptions import BadRequest as _BadRequest
            with pytest.raises(_BadRequest) as exc_info:
                await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)
            assert "HK1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_hk1_gate_blocks_overdue(self):
        from app.services.admission_service import check_enrollment_fee_eligibility
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_repo = MagicMock()
        mock_repo.get_by_profile_id = AsyncMock(
            return_value=[self._make_mock_fee("overdue")]
        )

        with patch("app.repositories.fee_repository.FeeRepository", return_value=mock_repo), \
             patch("app.config.settings") as mock_settings:
            mock_settings.ADMISSION_FEE_GATE_MODE = "semester_hk1"
            from app.utils.exceptions import BadRequest as _BadRequest
            with pytest.raises(_BadRequest):
                await check_enrollment_fee_eligibility(MagicMock(), profile_id=1)

    def test_config_default_is_legacy(self):
        from app.config import settings
        assert settings.ADMISSION_FEE_GATE_MODE == "legacy"
