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
            path = models.AdmissionPath(
                academic_info_id=academic_info_id,
                admission_method_id=admission_method_id,
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
            path = models.AdmissionPath(
                academic_info_id=academic_info_id,
                admission_method_id=admission_method_id,
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

    async def test_officer_cannot_record_fee_payment(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_admission_statuses: dict,
    ):
        """Test officer cannot record fee payment (admin only)."""
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

        assert response.status_code == 403, f"Expected 403, got {response.status_code}"

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

        officer_headers = await get_auth_headers(client, officer_user_in_db)
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
