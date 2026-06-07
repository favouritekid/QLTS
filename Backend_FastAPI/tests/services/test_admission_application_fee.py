"""
Tests for Application Fee functionality in Admission workflow.

Tests:
- create_profile: Snapshots application_fee and fee_status correctly
- record_application_fee_payment: Updates fee_status and syncs lead to sts13
- approve_profile: Blocks if fee not paid, allows if paid or exempt
- Full flow: With fee payment -> sts13 -> sts09
- Full flow: Without fee (exempt) -> sts09 directly

Uses real database via fixtures.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from decimal import Decimal
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ==============================================================================
# FIXTURES: Seed consultation statuses required for admission workflow
# ==============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_admission_statuses(seed_lead_dependencies: dict):
    """
    Return consultation status IDs required for admission workflow.

    These statuses are already seeded by seed_lead_dependencies (conftest.py):
    - sts06: Đồng ý tư vấn (Consultation phase - starting point)
    - sts07: Đã tiếp nhận (Admission phase - after create profile)
    - sts09: Đủ điều kiện (Fee phase - after approve)
    - sts13: Đã hoàn lệ phí (Fee phase - after fee payment)
    """
    return {
        **seed_lead_dependencies,
        "sts06_id": "sts06",
        "sts07_id": "sts07",
        "sts09_id": "sts09",
        "sts13_id": "sts13",
    }


@pytest_asyncio.fixture(scope="function", autouse=True)
async def seed_application_fee_finance_dependencies(setup_test_database):
    """Seed metadata-created test DB rows normally owned by Alembic."""
    from tests.fixtures.constants import TestUsers

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for username, email in (
                ("system", "system@qlts.internal"),
                ("backfill", "backfill@qlts.internal"),
            ):
                result = await session.execute(
                    select(models.User).where(models.User.username == username)
                )
                user = result.scalar_one_or_none()
                if user is None:
                    session.add(
                        models.User(
                            username=username,
                            email=email,
                            password_hash=TestUsers.DEFAULT["real_hash"],
                            full_name=f"{username.title()} Policy User",
                            role="user",
                            status="inactive",
                            unit_id=None,
                            current_assignment_id=None,
                        )
                    )
                else:
                    user.email = email
                    user.password_hash = TestUsers.DEFAULT["real_hash"]
                    user.role = "user"
                    user.status = "inactive"
                    user.unit_id = None
                    user.current_assignment_id = None

            result = await session.execute(
                select(models.PaymentMethod).where(models.PaymentMethod.code == "cash")
            )
            if result.scalar_one_or_none() is None:
                session.add(
                    models.PaymentMethod(
                        code="cash",
                        name="Tiền mặt",
                        is_online=False,
                        requires_verification=True,
                        gateway_code=None,
                        display_order=2,
                        is_active=True,
                    )
                )


async def create_fee_scope_user(
    *,
    username: str,
    email: str,
    role: str,
    unit_id: int,
    app_instance,
) -> dict:
    """Create an active test user for fee-collection IDOR cases."""
    from casbin_async_sqlalchemy_adapter.adapter import CasbinRule

    from app.security import get_password_hash
    from tests.fixtures.users import create_user_with_role

    return await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": username,
            "email": email,
            "password": "ScopedPassword!123",
            "role": role,
            "status": "active",
        },
        casbin_role=f"role:{role}",
        unit_id=unit_id,
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=app_instance,
    )


@pytest_asyncio.fixture(scope="function")
async def accountant_user_in_db(
    setup_test_database,
    seed_lead_dependencies: dict,
    app_instance,
):
    return await create_fee_scope_user(
        username="fee_accountant_unit1",
        email="fee_accountant_unit1@example.com",
        role="accountant",
        unit_id=seed_lead_dependencies["unit_id"],
        app_instance=app_instance,
    )


@pytest_asyncio.fixture(scope="function")
async def accountant_other_unit_user_in_db(
    setup_test_database,
    seed_other_unit: dict,
    app_instance,
):
    return await create_fee_scope_user(
        username="fee_accountant_unit2",
        email="fee_accountant_unit2@example.com",
        role="accountant",
        unit_id=seed_other_unit["unit_id"],
        app_instance=app_instance,
    )


@pytest_asyncio.fixture(scope="function")
async def officer_peer_user_in_db(
    setup_test_database,
    seed_lead_dependencies: dict,
    app_instance,
):
    return await create_fee_scope_user(
        username="fee_officer_peer",
        email="fee_officer_peer@example.com",
        role="officer",
        unit_id=seed_lead_dependencies["unit_id"],
        app_instance=app_instance,
    )


@pytest_asyncio.fixture(scope="function")
async def officer_other_unit_user_in_db(
    setup_test_database,
    seed_other_unit: dict,
    app_instance,
):
    return await create_fee_scope_user(
        username="fee_officer_unit2",
        email="fee_officer_unit2@example.com",
        role="officer",
        unit_id=seed_other_unit["unit_id"],
        app_instance=app_instance,
    )


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


async def create_test_lead_with_consultation(
    unit_id: int,
    assigned_officer_id: int,
) -> int:
    """Create a test lead with a consultation (required for admission profile)."""
    import time
    timestamp = int(time.time() * 1000)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Create lead
            lead = models.Lead(
                full_name="Fee Test Lead",
                phone=f"09{timestamp}"[-10:],
                email=f"feetest_{timestamp}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
                consultation_status_id="sts06",  # Đồng ý tư vấn
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id

            # Create consultation (required before creating admission profile)
            consultation = models.Consultation(
                lead_id=lead_id,
                officer_id=assigned_officer_id,
                consultation_status_id="sts06",  # Đồng ý tư vấn
                consultation_date=datetime.now(timezone.utc),
                method="phone",
                notes="Test consultation for fee testing",
            )
            session.add(consultation)

    return lead_id


async def create_admission_path_with_fee(
    academic_info_id: int,
    admission_method_id: int,
    application_fee: Decimal = Decimal("100000"),
) -> int:
    """Create an admission path with application fee configured."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(session, academic_year=2026)
            path = models.AdmissionPath(
                academic_info_id=academic_info_id,
                admission_method_id=admission_method_id,
                admission_round_id=round_id,
                status="active",
                display_name="Test Path with Fee",
                application_fee=application_fee,
            )
            session.add(path)
            await session.flush()
            return path.id


async def create_admission_path_no_fee(
    academic_info_id: int,
    admission_method_id: int,
) -> int:
    """Create an admission path without application fee (exempt)."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(session, academic_year=2026)
            path = models.AdmissionPath(
                academic_info_id=academic_info_id,
                admission_method_id=admission_method_id,
                admission_round_id=round_id,
                status="active",
                display_name="Test Path No Fee",
                application_fee=Decimal("0"),
            )
            session.add(path)
            await session.flush()
            return path.id


async def create_admission_profile_with_fee_status(
    lead_id: int,
    citizen_id: str,
    academic_year: int,
    requires_fee: bool = True,
    fee_status: str = "pending",
    status: str = "submitted",
) -> models.AdmissionProfile:
    """Create an admission profile with fee configuration."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            applied_rules = {
                "min_gpa": 0,
                "mandatory_docs": [],
                "application_fee": 100000 if requires_fee else 0,
                "requires_application_fee": requires_fee,
                "fee_status": fee_status,
            }

            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen_id,
                academic_year=academic_year,
                version=1,
                applied_rules=applied_rules,
            )
            session.add(profile)
            await session.flush()
            profile_id = profile.id

        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(selectinload(models.AdmissionProfile.lead))
        )
        return result.scalar_one()


async def create_pending_fee_profile(
    *,
    unit_id: int,
    assigned_officer_id: int,
    citizen_id: str,
) -> models.AdmissionProfile:
    lead_id = await create_test_lead_with_consultation(
        unit_id=unit_id,
        assigned_officer_id=assigned_officer_id,
    )
    return await create_admission_profile_with_fee_status(
        lead_id=lead_id,
        citizen_id=citizen_id,
        academic_year=2026,
        requires_fee=True,
        fee_status="pending",
    )


async def get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    """Login and get auth headers."""
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)

    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")

    access_token = res.cookies.get("access_token")
    if not access_token:
        pytest.fail("Login succeeded but access_token cookie not found")

    return {"Authorization": f"Bearer {access_token}"}


async def post_record_fee_payment(
    client: AsyncClient,
    profile_id: int,
    user_info: dict,
    transaction_id: str,
):
    headers = await get_auth_headers(client, user_info)
    return await client.post(
        f"/api/admissions/{profile_id}/record-fee-payment",
        params={
            "transaction_id": transaction_id,
            "amount": 100000,
        },
        headers=headers,
    )


async def reload_profile(profile_id: int) -> models.AdmissionProfile:
    """Reload profile from database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
            .options(selectinload(models.AdmissionProfile.lead))
        )
        return result.scalar_one_or_none()


async def get_lead_status(lead_id: int) -> str:
    """Get lead's current consultation_status_id."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.Lead.consultation_status_id)
            .where(models.Lead.id == lead_id)
        )
        return result.scalar_one_or_none()


async def get_application_fee_chain(profile_id: int):
    async with AsyncSessionLocal() as session:
        fee_result = await session.execute(
            select(models.Fee)
            .where(
                models.Fee.admission_profile_id == profile_id,
                models.Fee.fee_type == "application",
            )
            .options(
                selectinload(models.Fee.invoices)
                .selectinload(models.Invoice.payments)
                .selectinload(models.Payment.method)
            )
        )
        fee = fee_result.scalar_one()
        tx_result = await session.execute(
            select(models.PaymentTransaction).where(
                models.PaymentTransaction.fee_id == fee.id
            )
        )
        return fee, tx_result.scalars().all()


# ==============================================================================
# TEST: FEE STATUS ENDPOINT
# ==============================================================================


class TestFeeStatusEndpoint:
    """Test GET /admissions/{id}/fee-status endpoint."""

    async def test_get_fee_status_requires_fee(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test fee status for profile that requires fee."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = officer_user_in_db["id"]

        # Create lead and profile with fee requirement
        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000001",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.get(
            f"/api/admissions/{profile.id}/fee-status",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["requires_fee"] is True
        assert data["fee_status"] == "pending"
        assert data["can_approve"] is False
        assert data["fee_amount"] == 100000

    async def test_get_fee_status_exempt(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test fee status for profile that is fee exempt."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = officer_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000002",
            academic_year=2026,
            requires_fee=False,
            fee_status="exempt",
        )

        headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.get(
            f"/api/admissions/{profile.id}/fee-status",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["requires_fee"] is False
        assert data["fee_status"] == "exempt"
        assert data["can_approve"] is True


# ==============================================================================
# TEST: RECORD FEE PAYMENT
# ==============================================================================


class TestRecordFeePayment:
    """Test POST /admissions/{id}/record-fee-payment endpoint."""

    async def test_admin_can_record_fee_payment(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test admin can record fee payment successfully."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000003",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
        )

        admin_headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/record-fee-payment",
            params={
                "transaction_id": "TXN123456",
                "amount": 100000,
            },
            headers=admin_headers,
        )

        assert response.status_code == 200, f"Failed: {response.text}"

        # Verify fee status updated
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "paid"
        assert updated_profile.applied_rules.get("fee_paid_at") is not None

        # Verify lead synced to sts13
        lead_status = await get_lead_status(lead_id)
        assert lead_status == "sts13", f"Expected sts13, got {lead_status}"

        fee, transactions = await get_application_fee_chain(profile.id)
        assert fee.status == "paid"
        assert fee.base_amount == Decimal("100000.00")
        assert fee.paid_amount == Decimal("100000.00")
        assert fee.waived_amount == Decimal("0.00")
        assert fee.semester_no is None
        assert len(fee.invoices) == 1
        invoice = fee.invoices[0]
        assert invoice.invoice_number == f"APP-{fee.id}"
        assert invoice.status == "paid"
        assert len(invoice.payments) == 1
        payment = invoice.payments[0]
        assert payment.status == "verified"
        assert payment.method.code == "cash"
        assert payment.intent_id is None
        assert payment.verified_by_id != payment.created_by_id
        assert len(transactions) == 1
        assert transactions[0].transaction_type == "payment"
        assert transactions[0].performed_by_id == payment.verified_by_id
        assert transactions[0].external_reference == "TXN123456"

    async def test_assigned_officer_can_record_fee_payment(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Assigned officer can collect application fee."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = officer_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000004",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
        )

        officer_headers = await get_auth_headers(client, officer_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/record-fee-payment",
            params={
                "transaction_id": "TXN123456",
                "amount": 100000,
            },
            headers=officer_headers,
        )

        assert response.status_code == 200, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "paid"

    async def test_manager_same_unit_can_record_fee_payment(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Manager can collect for profiles in their unit."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000104",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            manager_user_in_db,
            "IDORMGR01",
        )

        assert response.status_code == 200, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "paid"

    async def test_accountant_same_unit_can_record_fee_payment(
        self,
        client: AsyncClient,
        accountant_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Accountant can collect for profiles in their unit."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000105",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            accountant_user_in_db,
            "IDORACCT1",
        )

        assert response.status_code == 200, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "paid"

    async def test_officer_same_unit_but_not_assigned_gets_404(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        officer_peer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Officer in the same unit still needs assignment."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_peer_user_in_db["id"],
            citizen_id="200000000106",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            officer_user_in_db,
            "IDOROFF01",
        )

        assert response.status_code == 404, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "pending"

    async def test_accountant_other_unit_gets_404(
        self,
        client: AsyncClient,
        accountant_other_unit_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Accountant cannot collect outside their unit."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000107",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            accountant_other_unit_user_in_db,
            "IDORACCT2",
        )

        assert response.status_code == 404, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "pending"

    async def test_manager_other_unit_gets_404(
        self,
        client: AsyncClient,
        manager_other_unit_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Manager cannot collect outside their unit."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000108",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            manager_other_unit_user_in_db,
            "IDORMGR02",
        )

        assert response.status_code == 404, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "pending"

    async def test_officer_other_unit_gets_404(
        self,
        client: AsyncClient,
        officer_other_unit_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Officer cannot collect outside their unit."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000109",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            officer_other_unit_user_in_db,
            "IDOROFF02",
        )

        assert response.status_code == 404, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "pending"

    async def test_regular_user_denied_by_casbin(
        self,
        client: AsyncClient,
        regular_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """role:user has no Casbin allow for this route → denied 403 at the
        route layer (CasbinAuth), BEFORE the IDOR scope dependency runs. The
        404 no-leak applies to allowed roles with the wrong *scope* (officer
        non-assigned / other-unit — covered by the tests above), not to a role
        that may never collect fees at all. Mirrors every other admission write
        endpoint, which is CasbinAuth-gated."""
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000110",
        )

        response = await post_record_fee_payment(
            client,
            profile.id,
            regular_user_in_db,
            "IDORUSER1",
        )

        assert response.status_code == 403, response.text
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.applied_rules.get("fee_status") == "pending"

    async def test_record_fee_payment_idempotent(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test recording fee payment is idempotent (already paid)."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        # Create profile with fee already paid
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000005",
            academic_year=2026,
            requires_fee=True,
            fee_status="paid",  # Already paid
        )

        admin_headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/record-fee-payment",
            params={
                "transaction_id": "TXN123456",
                "amount": 100000,
            },
            headers=admin_headers,
        )

        # Should return 200 (idempotent), not error
        assert response.status_code == 200


class TestRecordFeePaymentPermissionFlag:
    """GET detail exposes the Thin-Client action flag for fee collection."""

    async def _get_detail(
        self,
        client: AsyncClient,
        profile_id: int,
        user_info: dict,
    ) -> dict:
        headers = await get_auth_headers(client, user_info)
        response = await client.get(f"/api/admissions/{profile_id}", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    async def test_admin_pending_profile_can_record_fee(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000601",
        )

        data = await self._get_detail(client, profile.id, admin_user_in_db)

        assert data["permissions"]["record_fee_payment"] is True
        assert "record_fee_payment" in data["available_actions"]

    async def test_assigned_officer_pending_profile_can_record_fee(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000602",
        )

        data = await self._get_detail(client, profile.id, officer_user_in_db)

        assert data["permissions"]["record_fee_payment"] is True
        assert "record_fee_payment" in data["available_actions"]

    async def test_manager_same_unit_pending_profile_can_record_fee(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000603",
        )

        data = await self._get_detail(client, profile.id, manager_user_in_db)

        assert data["permissions"]["record_fee_payment"] is True
        assert "record_fee_payment" in data["available_actions"]

    async def test_admin_paid_profile_cannot_record_fee_again(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        lead_id = await create_test_lead_with_consultation(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
        )
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000604",
            academic_year=2026,
            requires_fee=True,
            fee_status="paid",
        )

        data = await self._get_detail(client, profile.id, admin_user_in_db)

        assert data["permissions"]["record_fee_payment"] is False
        assert "record_fee_payment" not in data["available_actions"]

    async def test_admin_exempt_profile_cannot_record_fee(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        lead_id = await create_test_lead_with_consultation(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
        )
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000605",
            academic_year=2026,
            requires_fee=False,
            fee_status="exempt",
        )

        data = await self._get_detail(client, profile.id, admin_user_in_db)

        assert data["permissions"]["record_fee_payment"] is False
        assert "record_fee_payment" not in data["available_actions"]


class TestFeePaymentDataExposed:
    """GET detail preserves payment snapshot fields for the frontend panel."""

    async def test_fee_payment_snapshot_survives_response_schema(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
        silence_fee_dispatch,
    ):
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000606",
        )

        paid = await post_record_fee_payment(
            client,
            profile.id,
            admin_user_in_db,
            "SNAPSHOT-001",
        )
        assert paid.status_code == 200, paid.text

        headers = await get_auth_headers(client, admin_user_in_db)
        detail = await client.get(f"/api/admissions/{profile.id}", headers=headers)
        assert detail.status_code == 200, detail.text
        applied_rules = detail.json()["applied_rules"]

        assert applied_rules["fee_paid_at"] is not None
        assert (
            applied_rules["fee_payment_data"]["transaction_id"]
            == "SNAPSHOT-001"
        )


# ==============================================================================
# TEST: APPROVE WITH FEE CHECK
# ==============================================================================


class TestApproveWithFeeCheck:
    """Test approve endpoint with fee validation."""

    async def test_approve_blocked_if_fee_not_paid(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test approval is blocked if fee is pending."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = manager_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000006",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
            status="submitted",
        )

        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"version": 1, "notes": "Approved"},
            headers=manager_headers,
        )

        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        assert "lệ phí" in response.text.lower() or "fee" in response.text.lower()

    async def test_approve_allowed_if_fee_paid(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test approval is allowed if fee is paid."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = manager_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000007",
            academic_year=2026,
            requires_fee=True,
            fee_status="paid",  # Fee already paid
            status="submitted",
        )

        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"version": 1, "notes": "Approved after fee payment"},
            headers=manager_headers,
        )

        assert response.status_code == 200, f"Failed: {response.text}"

        updated_profile = await reload_profile(profile.id)
        assert updated_profile.status == "approved"

        # Verify lead synced to sts09
        lead_status = await get_lead_status(lead_id)
        assert lead_status == "sts09", f"Expected sts09, got {lead_status}"

    async def test_approve_allowed_if_fee_exempt(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test approval is allowed if fee is exempt."""
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = manager_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000008",
            academic_year=2026,
            requires_fee=False,
            fee_status="exempt",
            status="submitted",
        )

        manager_headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"version": 1, "notes": "Approved - no fee required"},
            headers=manager_headers,
        )

        assert response.status_code == 200, f"Failed: {response.text}"

        updated_profile = await reload_profile(profile.id)
        assert updated_profile.status == "approved"


# ==============================================================================
# TEST: FULL FLOW WITH FEE
# ==============================================================================


class TestFullFlowWithFee:
    """Test complete admission flow with fee payment."""

    async def test_full_flow_with_fee_payment(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        admin_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """
        Test complete flow: Draft -> Submitted -> Fee Paid -> Approved.

        1. Create profile with fee requirement
        2. Submit profile
        3. Try approve (should fail - fee pending)
        4. Record fee payment (lead -> sts13)
        5. Approve profile (lead -> sts09)
        """
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = officer_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        # Create profile with fee pending
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000009",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
            status="submitted",
        )

        manager_headers = await get_auth_headers(client, manager_user_in_db)
        admin_headers = await get_auth_headers(client, admin_user_in_db)

        # Step 1: Try to approve without fee payment (should fail)
        approve_response_1 = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"version": 1},
            headers=manager_headers,
        )
        assert approve_response_1.status_code == 400, "Should fail - fee pending"

        # Step 2: Admin records fee payment
        fee_response = await client.post(
            f"/api/admissions/{profile.id}/record-fee-payment",
            params={
                "transaction_id": "TXN_FLOW_TEST",
                "amount": 100000,
            },
            headers=admin_headers,
        )
        assert fee_response.status_code == 200, f"Fee payment failed: {fee_response.text}"

        # Verify lead is at sts13
        lead_status = await get_lead_status(lead_id)
        assert lead_status == "sts13", f"Expected sts13 after fee, got {lead_status}"

        # Step 3: Manager approves (should succeed now)
        # Reload profile to get updated version
        updated_profile = await reload_profile(profile.id)

        approve_response_2 = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"version": updated_profile.version, "notes": "Approved after fee"},
            headers=manager_headers,
        )
        assert approve_response_2.status_code == 200, f"Approve failed: {approve_response_2.text}"

        # Verify final state
        final_profile = await reload_profile(profile.id)
        assert final_profile.status == "approved"

        final_lead_status = await get_lead_status(lead_id)
        assert final_lead_status == "sts09", f"Expected sts09 after approve, got {final_lead_status}"

    async def test_full_flow_without_fee(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """
        Test flow without fee: Submitted -> Approved (direct).

        No fee payment step required.
        """
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = manager_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )

        # Create profile without fee requirement
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000010",
            academic_year=2026,
            requires_fee=False,
            fee_status="exempt",
            status="submitted",
        )

        manager_headers = await get_auth_headers(client, manager_user_in_db)

        # Approve directly (no fee step)
        approve_response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"version": 1, "notes": "Approved - exempt from fee"},
            headers=manager_headers,
        )
        assert approve_response.status_code == 200, f"Approve failed: {approve_response.text}"

        # Verify lead went directly to sts09 (skipped sts13)
        lead_status = await get_lead_status(lead_id)
        assert lead_status == "sts09", f"Expected sts09, got {lead_status}"


# ==============================================================================
# TEST: APPLICATION_FEE_PAID EVENT DISPATCH
# ==============================================================================


class TestApplicationFeePaidEvent:
    """Verify record_application_fee_payment emits the user-facing event."""

    async def test_dispatches_application_fee_paid_with_correct_payload(
        self,
        admin_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """
        Calling the service directly and awaiting the returned post_commit
        callback must invoke safe_dispatch(APPLICATION_FEE_PAID, ...) with
        the full payload shape declared in the event catalog.
        """
        from unittest.mock import AsyncMock, patch
        from app.services import admission_service
        from app.core.events import SystemEvents

        unit_id = seed_admission_statuses["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000020",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
        )

        recorded_by = models.User(
            id=admin_user_in_db["id"],
            username=admin_user_in_db["username"],
            email="admin@fee.test",
            password_hash="x",
            role="admin",
            status="active",
            full_name="Fee Admin",
        )

        async with AsyncSessionLocal() as session:
            with patch(
                "app.services.notification_dispatcher.safe_dispatch",
                new=AsyncMock(),
            ) as mock_dispatch:
                _, callback = await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={
                        "transaction_id": "TXN-DISPATCH-001",
                        "amount": 100000,
                    },
                    recorded_by=recorded_by,
                )
                await session.commit()
                await callback()

                mock_dispatch.assert_called_once()
                kwargs = mock_dispatch.call_args.kwargs
                assert kwargs["event"] == SystemEvents.APPLICATION_FEE_PAID
                # dedupe_key should NOT be passed explicitly — dispatcher
                # renders it from the catalog's dedup_key_template to keep
                # dedup contract centralised.
                assert "dedupe_key" not in kwargs

                payload = kwargs["payload"]
                assert payload["application_id"] == profile.id
                assert payload["lead_id"] == lead_id
                assert payload["unit_id"] == unit_id
                assert payload["officer_id"] == officer_id
                assert payload["amount"] == "100000.00"
                assert payload["transaction_id"] == "TXN-DISPATCH-001"
                assert payload["actor_id"] == recorded_by.id
                assert payload["actor_name"] in (
                    recorded_by.full_name,
                    recorded_by.username,
                )

    async def test_catalog_dedupe_template_renders_expected_key(self):
        """Guard: catalog's dedup_key_template for APPLICATION_FEE_PAID
        must render the canonical per-application key. Guarantees that
        omitting dedupe_key at the call site still produces a sane value.
        """
        from app.core.event_catalog import EVENT_CATALOG
        from app.core.events import SystemEvents
        from string import Template

        defn = EVENT_CATALOG[SystemEvents.APPLICATION_FEE_PAID]
        assert defn.dedup_key_template == "app:${application_id}:fee_paid"
        rendered = Template(defn.dedup_key_template).substitute(application_id=42)
        assert rendered == "app:42:fee_paid"

    async def test_end_to_end_delivery_via_real_db_rule(
        self,
        admin_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """
        Full E2E: seed rule into DB via sync_notification_rules, then run
        dispatch() for APPLICATION_FEE_PAID. Verify a real Notification row
        is created in the DB for the lead owner.

        Channel send is mocked so no real socket/email is emitted; every
        other step (rule lookup, resolver, recipient resolution, row
        creation) is real.
        """
        from unittest.mock import AsyncMock, MagicMock, patch
        from sqlalchemy import select
        from app.core.events import SystemEvents
        from app.scripts.sync_notification_rules import sync_notification_rules
        from app.services.notification_dispatcher import dispatch
        from app.services.notification_rule_loader import invalidate_rule_cache

        unit_id = seed_admission_statuses["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000030",
            academic_year=2026,
            requires_fee=True,
            fee_status="pending",
        )

        async with AsyncSessionLocal() as session:
            # 1. Seed rules from catalog → DB row for application_fee_paid
            await sync_notification_rules(session)
            await session.commit()

            # 2. Verify rule exists for this event
            rule_stmt = select(models.NotificationRule).where(
                models.NotificationRule.event == "application_fee_paid",
                models.NotificationRule.enabled == True,  # noqa: E712
            )
            rule_row = (await session.execute(rule_stmt)).scalars().first()
            assert rule_row is not None, "sync_notification_rules must seed the rule"

            # 3. Cache hygiene so dispatcher sees freshly seeded rule
            await invalidate_rule_cache("application_fee_paid")

            # 4. Real dispatch with channel send mocked (no real delivery side-effects)
            mock_result = MagicMock(sent_count=1, failed_ids=[], success=True)
            with patch(
                "app.services.notification_dispatcher._send_via_channel",
                new=AsyncMock(return_value=("browser", mock_result, None)),
            ):
                payload = {
                    "application_id": profile.id,
                    "lead_id": lead_id,
                    "unit_id": unit_id,
                    "officer_id": officer_id,
                    "amount": "100000",
                    "transaction_id": "TXN-E2E-001",
                    "actor_id": officer_id,
                    "actor_name": admin_user_in_db["username"],
                }
                notification_ids, callback = await dispatch(
                    db=session,
                    event=SystemEvents.APPLICATION_FEE_PAID,
                    payload=payload,
                )
                await session.commit()
                if callback:
                    await callback()

            # 5. Notification row must exist for the lead owner
            assert notification_ids, (
                "APPLICATION_FEE_PAID rule exists → notification must be created"
            )
            notif_stmt = select(models.Notification).where(
                models.Notification.id.in_(notification_ids)
            )
            notifs = (await session.execute(notif_stmt)).scalars().all()
            assert len(notifs) >= 1
            recipient_ids = {n.user_id for n in notifs}
            assert officer_id in recipient_ids, (
                f"Lead owner {officer_id} must receive the notification; "
                f"got recipients {recipient_ids}"
            )
            # Template rendering + payload snapshot survived into the row
            matching = next(n for n in notifs if n.user_id == officer_id)
            assert matching.title == "Lệ phí xét tuyển đã thanh toán"
            assert str(profile.id) in matching.message
            assert "100000" in matching.message
            # Data JSON carries the source event type for audit/trace
            assert matching.data is not None
            assert matching.data.get("event") == "application_fee_paid"

    async def test_idempotent_call_does_not_dispatch(
        self,
        admin_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """A second call on an already-paid profile returns a noop callback
        and must not dispatch APPLICATION_FEE_PAID."""
        from unittest.mock import AsyncMock, patch
        from app.services import admission_service

        unit_id = seed_admission_statuses["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await create_test_lead_with_consultation(
            unit_id=unit_id,
            assigned_officer_id=officer_id,
        )
        profile = await create_admission_profile_with_fee_status(
            lead_id=lead_id,
            citizen_id="200000000021",
            academic_year=2026,
            requires_fee=True,
            fee_status="paid",  # already paid
        )

        recorded_by = models.User(
            id=admin_user_in_db["id"],
            username=admin_user_in_db["username"],
            email="admin@fee.test",
            password_hash="x",
            role="admin",
            status="active",
        )

        async with AsyncSessionLocal() as session:
            with patch(
                "app.services.notification_dispatcher.safe_dispatch",
                new=AsyncMock(),
            ) as mock_dispatch:
                _, callback = await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={"transaction_id": "TXN-IDEM-001", "amount": 100000},
                    recorded_by=recorded_by,
                )
                await callback()
                mock_dispatch.assert_not_called()


# ==============================================================================
# ADVERSARIAL / FINANCIAL-INTEGRITY TESTS (plan v8 — guards, fingerprint,
# reconcile-conflict, replay, race). Happy-path + IDOR live above.
# ==============================================================================


async def _load_user(user_id: int) -> models.User:
    async with AsyncSessionLocal() as session:
        return await session.get(models.User, user_id)


async def _load_system_user() -> models.User:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.User).where(models.User.username == "system")
        )
        return result.scalar_one()


async def _tamper_system(**fields) -> None:
    """Mutate the seeded ``system`` principal in a committed txn so the runtime
    fingerprint check (`_get_system_application_fee_user`) sees the tamper."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(models.User).where(models.User.username == "system")
            )
            system = result.scalar_one()
            for key, value in fields.items():
                setattr(system, key, value)


async def _load_paid_chain_objects(session, profile_id: int):
    fee = (
        await session.execute(
            select(models.Fee)
            .where(
                models.Fee.admission_profile_id == profile_id,
                models.Fee.fee_type == "application",
            )
            .options(
                selectinload(models.Fee.invoices).selectinload(
                    models.Invoice.payments
                )
            )
        )
    ).scalar_one()
    invoice = fee.invoices[0]
    payment = invoice.payments[0]
    txn = (
        await session.execute(
            select(models.PaymentTransaction).where(
                models.PaymentTransaction.fee_id == fee.id
            )
        )
    ).scalar_one()
    return fee, invoice, payment, txn


# --- reconcile-conflict drift mutators (committable single-field tampers) --- #
def _m_payment_status_pending(s, fee, invoice, payment, txn):
    payment.status = "pending"


def _m_payment_amount_drift(s, fee, invoice, payment, txn):
    # Stays > 0 (chk_payment_amount_positive) but != expected → reconcile rejects.
    payment.amount = Decimal("1.00")


def _m_fee_paid_amount_drift(s, fee, invoice, payment, txn):
    fee.paid_amount = Decimal("1.00")


def _m_invoice_installment_no(s, fee, invoice, payment, txn):
    invoice.installment_no = 2


def _m_invoice_penalty_drift(s, fee, invoice, payment, txn):
    invoice.penalty_amount = Decimal("1.00")


def _m_txn_external_ref_drift(s, fee, invoice, payment, txn):
    txn.external_reference = "WRONG-REF"


def _m_extra_adjustment_txn(s, fee, invoice, payment, txn):
    # P0-3: an extra adjustment/waive txn sharing fee_id (payment_id NULL) must
    # be caught by cardinality-per-fee_id, NOT slip past payment.transactions.
    s.add(
        models.PaymentTransaction(
            payment_id=None,
            fee_id=fee.id,
            transaction_type="adjustment",
            amount=Decimal("0"),
            balance_before=Decimal("0"),
            balance_after=Decimal("0"),
            performed_by_id=None,
            created_at=datetime.now(timezone.utc),
        )
    )


@pytest_asyncio.fixture
async def silence_fee_dispatch():
    """Isolate ledger/reconcile/replay assertions from the notification
    subsystem. The ``application_fee_paid`` rule is NOT seeded in the
    create_all() test DB, and a sibling test that seeds a real rule leaves a
    stale process cache → the post-commit ``safe_dispatch`` would FK-violate on
    a missing rule row. These tests assert the finance ledger, not delivery."""
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.services.notification_dispatcher.safe_dispatch",
        new=AsyncMock(),
    ):
        yield


class TestRecordFeePaymentGuards:
    """Guard rails: amount must equal expected, cash-only, real recorder."""

    async def test_amount_mismatch_returns_400(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000401",
        )
        headers = await get_auth_headers(client, admin_user_in_db)
        response = await client.post(
            f"/api/admissions/{profile.id}/record-fee-payment",
            params={"transaction_id": "AMT-MISMATCH-1", "amount": 99999},
            headers=headers,
        )
        assert response.status_code == 400, response.text
        updated = await reload_profile(profile.id)
        assert updated.applied_rules.get("fee_status") == "pending"

    async def test_non_cash_method_returns_400(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000402",
        )
        headers = await get_auth_headers(client, admin_user_in_db)
        response = await client.post(
            f"/api/admissions/{profile.id}/record-fee-payment",
            params={
                "transaction_id": "METHOD-BANK-1",
                "amount": 100000,
                "payment_method_code": "bank_transfer",
            },
            headers=headers,
        )
        assert response.status_code == 400, response.text
        updated = await reload_profile(profile.id)
        assert updated.applied_rules.get("fee_status") == "pending"

    async def test_system_user_cannot_be_recorder_raises_bad_request(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        from app.services import admission_service
        from app.utils.exceptions import BadRequest

        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000403",
        )
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.User).where(models.User.username == "system")
            )
            system = result.scalar_one()
            with pytest.raises(BadRequest):
                await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={
                        "transaction_id": "SYS-RECORDER-1",
                        "amount": 100000,
                    },
                    recorded_by=system,
                )


class TestSystemPrincipalFingerprint:
    """P1-5: any tamper of the `system` principal fails closed (ConflictError),
    incl. the UserUnitAssignment source-of-truth (not just the user cache)."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("status", "active"),
            ("role", "admin"),
            ("email", "evil@qlts.internal"),
        ],
    )
    async def test_attribute_tamper_raises_conflict(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
        field: str,
        value: str,
    ):
        from app.services import admission_service
        from app.utils.exceptions import ConflictError

        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id=f"20000000041{['status', 'role', 'email'].index(field)}",
        )
        await _tamper_system(**{field: value})
        async with AsyncSessionLocal() as session:
            recorded_by = await session.get(models.User, admin_user_in_db["id"])
            with pytest.raises(ConflictError):
                await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={
                        "transaction_id": f"FPRINT-{field}",
                        "amount": 100000,
                    },
                    recorded_by=recorded_by,
                )

    async def test_unit_id_tamper_raises_conflict(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        from app.services import admission_service
        from app.utils.exceptions import ConflictError

        unit_id = seed_admission_statuses["unit_id"]
        profile = await create_pending_fee_profile(
            unit_id=unit_id,
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000420",
        )
        await _tamper_system(unit_id=unit_id)
        async with AsyncSessionLocal() as session:
            recorded_by = await session.get(models.User, admin_user_in_db["id"])
            with pytest.raises(ConflictError):
                await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={"transaction_id": "FPRINT-unit", "amount": 100000},
                    recorded_by=recorded_by,
                )

    async def test_active_unit_assignment_raises_conflict(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """SoT cross-check: an active UserUnitAssignment for `system` (cache
        fields untouched) still fails closed."""
        from app.services import admission_service
        from app.utils.exceptions import ConflictError

        unit_id = seed_admission_statuses["unit_id"]
        profile = await create_pending_fee_profile(
            unit_id=unit_id,
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000421",
        )
        system = await _load_system_user()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                session.add(
                    models.UserUnitAssignment(
                        user_id=system.id,
                        unit_id=unit_id,
                        role="user",
                        is_active=True,
                    )
                )
        async with AsyncSessionLocal() as session:
            recorded_by = await session.get(models.User, admin_user_in_db["id"])
            with pytest.raises(ConflictError):
                await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={"transaction_id": "FPRINT-assign", "amount": 100000},
                    recorded_by=recorded_by,
                )

    async def test_current_assignment_id_tamper_raises_conflict(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Cache field `current_assignment_id` non-null (pointing at an INACTIVE
        assignment) fails closed before the active-assignment query runs."""
        from app.services import admission_service
        from app.utils.exceptions import ConflictError

        unit_id = seed_admission_statuses["unit_id"]
        profile = await create_pending_fee_profile(
            unit_id=unit_id,
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000422",
        )
        system = await _load_system_user()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                assignment = models.UserUnitAssignment(
                    user_id=system.id,
                    unit_id=unit_id,
                    role="user",
                    is_active=False,
                    end_date=datetime.now(timezone.utc),
                )
                session.add(assignment)
                await session.flush()
                target = await session.get(models.User, system.id)
                target.current_assignment_id = assignment.id
        async with AsyncSessionLocal() as session:
            recorded_by = await session.get(models.User, admin_user_in_db["id"])
            with pytest.raises(ConflictError):
                await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={"transaction_id": "FPRINT-cur", "amount": 100000},
                    recorded_by=recorded_by,
                )


class TestRecordFeePaymentReconcile:
    """Reconcile is strict: a paid chain that drifts on ANY field (or grows an
    extra txn) must ConflictError on replay — never silently auto-verify."""

    @pytest.mark.parametrize(
        "case_id,mutator",
        [
            ("payment_status_pending", _m_payment_status_pending),
            ("payment_amount_drift", _m_payment_amount_drift),
            ("fee_paid_amount_drift", _m_fee_paid_amount_drift),
            ("invoice_installment_no", _m_invoice_installment_no),
            ("invoice_penalty_drift", _m_invoice_penalty_drift),
            ("txn_external_ref_drift", _m_txn_external_ref_drift),
            ("extra_adjustment_txn", _m_extra_adjustment_txn),
        ],
    )
    async def test_drift_then_replay_raises_conflict(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
        silence_fee_dispatch,
        case_id: str,
        mutator,
    ):
        from app.services import admission_service
        from app.utils.exceptions import ConflictError

        receipt = f"RECON-{case_id[:8].upper()}"
        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id=f"2000000005{abs(hash(case_id)) % 90 + 10}",
        )
        # 1. Pay once → full consistent chain (committed by router).
        ok = await post_record_fee_payment(
            client, profile.id, admin_user_in_db, receipt
        )
        assert ok.status_code == 200, ok.text
        # 2. Drift one ledger field (committed).
        async with AsyncSessionLocal() as session:
            async with session.begin():
                fee, invoice, payment, txn = await _load_paid_chain_objects(
                    session, profile.id
                )
                mutator(session, fee, invoice, payment, txn)
        # 3. Replay same receipt → reconcile detects drift → ConflictError.
        async with AsyncSessionLocal() as session:
            recorded_by = await session.get(models.User, admin_user_in_db["id"])
            with pytest.raises(ConflictError):
                await admission_service.record_application_fee_payment(
                    db=session,
                    profile_id=profile.id,
                    payment_data={"transaction_id": receipt, "amount": 100000},
                    recorded_by=recorded_by,
                )


class TestApplicationFeeReplayProtection:
    """A receipt is single-use across profiles — incl. legacy-patched keys."""

    async def test_same_receipt_other_profile_conflicts(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
        silence_fee_dispatch,
    ):
        unit_id = seed_admission_statuses["unit_id"]
        officer_id = officer_user_in_db["id"]
        profile_a = await create_pending_fee_profile(
            unit_id=unit_id, assigned_officer_id=officer_id,
            citizen_id="200000000601",
        )
        profile_b = await create_pending_fee_profile(
            unit_id=unit_id, assigned_officer_id=officer_id,
            citizen_id="200000000602",
        )
        shared = "SHARED-RCPT-1"
        first = await post_record_fee_payment(
            client, profile_a.id, admin_user_in_db, shared
        )
        assert first.status_code == 200, first.text
        second = await post_record_fee_payment(
            client, profile_b.id, admin_user_in_db, shared
        )
        assert second.status_code == 409, second.text
        b_after = await reload_profile(profile_b.id)
        assert b_after.applied_rules.get("fee_status") == "pending"

    async def test_legacy_patched_receipt_conflicts(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
        silence_fee_dispatch,
    ):
        """Mimic migration `_patch_legacy_keys`: a pre-existing txn's
        idempotency_key set from a legacy reference must block a runtime
        collection of that same receipt on another profile."""
        from app.utils.fee_receipt import canonical_receipt_key

        unit_id = seed_admission_statuses["unit_id"]
        officer_id = officer_user_in_db["id"]
        profile_legacy = await create_pending_fee_profile(
            unit_id=unit_id, assigned_officer_id=officer_id,
            citizen_id="200000000603",
        )
        profile_new = await create_pending_fee_profile(
            unit_id=unit_id, assigned_officer_id=officer_id,
            citizen_id="200000000604",
        )
        seeded = await post_record_fee_payment(
            client, profile_legacy.id, admin_user_in_db, "ORIG-LEGACY-1"
        )
        assert seeded.status_code == 200, seeded.text
        legacy_receipt = "WIRE-REF-2024-XYZ"
        async with AsyncSessionLocal() as session:
            async with session.begin():
                fee = (
                    await session.execute(
                        select(models.Fee).where(
                            models.Fee.admission_profile_id == profile_legacy.id,
                            models.Fee.fee_type == "application",
                        )
                    )
                ).scalar_one()
                txn = (
                    await session.execute(
                        select(models.PaymentTransaction).where(
                            models.PaymentTransaction.fee_id == fee.id
                        )
                    )
                ).scalar_one()
                txn.idempotency_key = canonical_receipt_key(legacy_receipt)
                txn.external_reference = legacy_receipt
        blocked = await post_record_fee_payment(
            client, profile_new.id, admin_user_in_db, legacy_receipt
        )
        assert blocked.status_code == 409, blocked.text
        new_after = await reload_profile(profile_new.id)
        assert new_after.applied_rules.get("fee_status") == "pending"


class TestRecordFeePaymentRace:
    """Concurrent collection on one profile must not double-charge: the row
    lock + unique idempotency_key collapse to exactly one ledger chain."""

    async def test_concurrent_same_receipt_single_chain(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        import asyncio

        from app.services import admission_service

        profile = await create_pending_fee_profile(
            unit_id=seed_admission_statuses["unit_id"],
            assigned_officer_id=officer_user_in_db["id"],
            citizen_id="200000000701",
        )
        admin_id = admin_user_in_db["id"]
        receipt = "RACE-RCPT-01"

        async def _record():
            # Separate session per coroutine — never share AsyncSession across
            # asyncio.gather (memory: async-session-gather).
            async with AsyncSessionLocal() as session:
                recorded_by = await session.get(models.User, admin_id)
                try:
                    _, _cb = await admission_service.record_application_fee_payment(
                        db=session,
                        profile_id=profile.id,
                        payment_data={"transaction_id": receipt, "amount": 100000},
                        recorded_by=recorded_by,
                    )
                    await session.commit()
                    return "ok"
                except Exception as exc:  # noqa: BLE001 — loser may raise
                    await session.rollback()
                    return type(exc).__name__

        await asyncio.gather(_record(), _record(), return_exceptions=True)

        # Invariant that matters: exactly one fee + one transaction (no
        # double-charge), regardless of which coroutine won the row lock.
        fee, txns = await get_application_fee_chain(profile.id)
        assert fee is not None
        assert len(txns) == 1, f"expected 1 txn, got {len(txns)}"
        paid = await reload_profile(profile.id)
        assert paid.applied_rules.get("fee_status") == "paid"
