"""
Integration tests for Admission State Machine endpoints.

Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.5.3:
- 🔥 Killer Test Case 1: Race Condition (concurrent approve/reject)
- 🔥 Killer Test Case 2: Replay Attack (double approval)
- State transition workflows
- IDOR protection tests
- Version checking tests

These tests are CRITICAL for production safety - DO NOT SKIP.
"""

import pytest
import pytest_asyncio
import asyncio
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.main import fastapi_app as app
from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _isolate_resend_quota(test_redis_client):
    """Reset per-profile magic-link resend counters before every test.

    The 3/24h resend cap (``admission_confirmation_resend_limit``) keys Redis
    on ``profile_id`` with a 24h TTL. fakeredis's ``_fake_server`` is
    process-global and ``setup_test_database`` resets the profile-id identity
    sequence per test, so a counter left behind by an earlier
    ``send-confirmation`` test collides on a reused id and trips the cap in a
    later test — surfacing as HTTP 429 on the setup send (``429 == 400``) or
    ``NoResultFound`` when the suppressed resend never issues a token. Wiping
    the ``admission:confirm:resend:*`` namespace at setup isolates each test's
    quota without touching unrelated Redis state (Casbin / Socket.IO).
    """
    async for key in test_redis_client.scan_iter("admission:confirm:resend:*"):
        await test_redis_client.delete(key)
    yield


# ==============================================================================
# SHARED HELPER FUNCTIONS
# ==============================================================================


async def create_test_lead(
    unit_id: int, 
    assigned_officer_id: int = None,
    consultation_status_id: str = None
) -> int:
    """Create a test lead for admission profile.
    
    Args:
        unit_id: OrganizationUnit ID
        assigned_officer_id: Optional officer ID for assignment
        consultation_status_id: Optional status ID (from seed_lead_dependencies)
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Test Applicant",
                phone="0901234567",
                email="test@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
                consultation_status_id=consultation_status_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id



async def create_admission_profile(
    lead_id: int,
    status: str = "submitted",
    citizen_id: str = None,
    approved_by_id: int = None,
) -> models.AdmissionProfile:
    """Create an admission profile in specified state."""
    if citizen_id is None:
        citizen_id = f"0{datetime.now().timestamp():.0f}"[:12]

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # If status is approved+, ensure approved_by_id is set for milestone consultation
            if approved_by_id is None and status in ("approved", "confirmed", "enrolled"):
                result = await session.execute(
                    select(models.Lead.assigned_officer_id).where(models.Lead.id == lead_id)
                )
                approved_by_id = result.scalar() or 1  # fallback to admin

            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen_id,
                version=1,
                applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
                academic_year=2025,  # FIXED: Required field
                approved_by_id=approved_by_id,
            )
            session.add(profile)
            await session.flush()
            profile_id = profile.id
        
        # Reload to get relationships
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
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
    
    # CRITICAL FIX: Clear cookies so subsequent requests don't use this user's session automatically.
    # This prevents "Officer cookie overriding Manager header" when sharing the client.
    client.cookies.delete("access_token")

    return {"Authorization": f"Bearer {access_token}"}


async def reload_profile(profile_id: int) -> models.AdmissionProfile:
    """Reload profile from database."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one_or_none()


# ==============================================================================
# 🔥 KILLER TEST CASE 1: RACE CONDITION (CONCURRENT APPROVE/REJECT)
# ==============================================================================


class TestRaceCondition:
    """
    Test concurrent state transitions to prevent data corruption.

    Scenario: 2 managers try to approve/reject the same profile simultaneously.
    Expected: One succeeds, one fails with clear error message.
    Risk: Without proper locking, both could succeed causing invalid state.

    ⚠️ KNOWN HARNESS ARTIFACT: these two HTTP-level tests currently
    observe [200, 200] because httpx.ASGITransport + asyncio.gather
    in this in-process test setup lets both requests clear the
    business-rule gate before either commits. The row locking itself
    is verified at the DB and service layers in
    ``tests/integration/test_race_condition_probe.py`` and the
    real concurrency contract holds.

    See docs/RACE_CONDITION_INVESTIGATION.md for the full investigation.
    Treat the [200, 200] failure here as a signal that the harness has
    not been replaced, not as a production concurrency bug.
    """

    async def test_concurrent_approve_reject(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 1.1: Concurrent approve and reject.

        Expected behavior:
        - One request succeeds (200 OK)
        - Other request fails (400 Bad Request - invalid transition)
        - Final state is consistent (approved OR rejected, not both)
        - Version is incremented exactly once
        """
        # Setup: Create SUBMITTED profile
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        initial_version = profile.version

        # Get auth token
        headers = await get_auth_headers(client, manager_user_in_db)

        # Simulate concurrent requests
        async def approve_request():
            return await client.post(
                f"/api/admissions/{profile.id}/approve",
                json={"notes": "Approved by manager 1", "version": profile.version},
                headers=headers,
            )

        async def reject_request():
            return await client.post(
                f"/api/admissions/{profile.id}/reject",
                json={"reason": "Rejected by manager 2 - insufficient documents", "version": profile.version},
                headers=headers,
            )

        # Execute concurrently
        results = await asyncio.gather(
            approve_request(),
            reject_request(),
            return_exceptions=True,
        )

        # Assertions
        status_codes = [r.status_code for r in results if hasattr(r, "status_code")]

        # One should succeed (200), one should fail (400)
        assert 200 in status_codes, f"At least one request should succeed. Got: {status_codes}"
        # The other might be 400 (invalid transition) or 409 (version conflict)
        assert any(code in [400, 409] for code in status_codes), \
            f"Concurrent request should fail with 400 or 409. Got: {status_codes}"

        # Verify final state is consistent
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.status in ["approved", "rejected"], \
            f"Final state must be valid, got: {updated_profile.status}"
        assert updated_profile.version == initial_version + 1, \
            f"Version should be incremented once, got: {updated_profile.version}"

    async def test_concurrent_double_approve(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 1.2: Two managers try to approve simultaneously.

        Expected behavior:
        - First approve succeeds
        - Second approve fails (cannot approve already-approved profile)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        
        headers = await get_auth_headers(client, manager_user_in_db)

        # Concurrent approvals
        async def approve():
            return await client.post(
                f"/api/admissions/{profile.id}/approve",
                json={"notes": "Approved", "version": profile.version},
                headers=headers,
            )

        results = await asyncio.gather(approve(), approve(), return_exceptions=True)
        status_codes = [r.status_code for r in results if hasattr(r, "status_code")]

        assert status_codes.count(200) == 1, f"Only one approval should succeed. Got: {status_codes}"
        assert any(code in [400, 409] for code in status_codes), \
            f"Second approval should fail. Got: {status_codes}"


# ==============================================================================
# 🔥 KILLER TEST CASE 2: REPLAY ATTACK (DOUBLE APPROVAL)
# ==============================================================================


class TestReplayAttack:
    """
    Test idempotency and replay attack prevention.

    Scenario: Attacker captures approve request and replays it.
    Expected: Second request fails with clear error message.
    Risk: Without state validation, profile could be corrupted.
    """

    async def test_approve_already_approved_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 2.1: Try to approve already-approved profile.

        Expected:
        - First approve: 200 OK, status=approved
        - Second approve: 400 Bad Request, clear error message
        - Status remains approved (not corrupted)
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        
        headers = await get_auth_headers(client, manager_user_in_db)

        # First approval - should succeed
        response1 = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Initial approval", "version": profile.version},
            headers=headers,
        )
        assert response1.status_code == 200, f"First approve failed: {response1.text}"
        assert response1.json()["status"] == "approved"

        # Second approval - should fail
        response2 = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Replay attack", "version": profile.version},  # Should be 1 (stale) or 2? Actually replay attack often implies reusing EXACT payload.
            # But the test expects 400 (Business Rule) not 409 (Conflict) because it's ALREADY approved.
            # Passing 'version': 1 might Trigger 409 if logic checks version first.
            # However, Replay Attack test says "Expected ... 400 Bad Request". 
            # If we send version=1 and DB is version=2 (after approval), we get 409.
            # To test "Already Approved" logical check, we should probably send correct current version OR the check happens before version check?
            # State check usually happens before version check in optimistic locking? No, version check is for concurrency.
            # If status is approved, version doesn't matter much unless we want to update it.
            # Let's send `profile.version` (which is 1). After first approve, DB is 2.
            # So this WILL return 409 Conflict.
            # BUT the test expects 400.
            # Let's see... If status is already final, maybe it rejects early?
            # Replay attack means reusing the OLD request. So version=1.
            # So 409 is actually CORRECT for a replay attack in optimistic locking system.
            # I will update the assertion in the next step if needed, but for now let's add version.
            # Wait, if I want to emulate Replay, I reuse the old payload (ver 1).
            headers=headers,
        )
        # Second approve should fail (400=state error or 409=version conflict)
        assert response2.status_code in [400, 409], f"Second approve should fail: {response2.text}"

        # Verify status is still approved (not corrupted)
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.status == "approved"

    async def test_reject_already_rejected_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test Case 2.2: Try to reject already-rejected profile."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        # First rejection
        response1 = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={"reason": "Initial rejection - missing documents", "version": profile.version},
            headers=headers,
        )
        assert response1.status_code == 200

        # Second rejection - should fail (400=state error or 409=version conflict)
        response2 = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={"reason": "Replay attack rejection", "version": profile.version},
            headers=headers,
        )
        assert response2.status_code in [400, 409]

    async def test_confirm_already_confirmed_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test Case 2.3: Try to confirm already-confirmed profile via token (replay attack)."""
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "111122223333"  # Known citizen_id
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved", citizen_id=citizen_id)
        
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        # Generate confirmation token
        send_response = await client.post(
            f"/api/admissions/{profile.id}/send-confirmation",
            headers=manager_headers,
        )
        assert send_response.status_code == 200, f"Send link failed: {send_response.text}"
        
        # Get token from database
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_obj = result.scalar_one()
            token_value = token_obj.token

        # First confirm - should succeed
        response1 = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "3333"},  # Last 4 digits
        )
        assert response1.status_code == 200, f"First confirm failed: {response1.text}"

        # Second confirm with same token - should fail (replay attack)
        response2 = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "3333"},
        )
        assert response2.status_code == 400, f"Replay attack should fail, got: {response2.status_code}"
        assert "already been used" in response2.json()["detail"]


# ==============================================================================
# VERSION CHECKING TESTS
# ==============================================================================


class TestVersionChecking:
    """
    Test optimistic locking via version field.

    Prevents lost updates when multiple users edit the same profile.
    """

    async def test_approve_with_stale_version(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 3.1: Approve with outdated version number.

        Expected:
        - Request with correct version: 200 OK
        - Request with stale version: 409 Conflict
        - Error message mentions version mismatch
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        current_version = profile.version
        
        headers = await get_auth_headers(client, manager_user_in_db)

        # Manually advance version in DB to 2
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_profile = await session.get(models.AdmissionProfile, profile.id)
                db_profile.version = 2
                await session.flush()

        # Request with stale version (1)
        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Approval", "version": 1},
            headers=headers,
        )

        assert response.status_code == 409, f"Should return 409 for stale version, got {response.status_code}: {response.text}"
        assert "version" in response.json()["detail"].lower()

    async def test_reject_with_correct_version(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test Case 3.2: Reject with correct version succeeds."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        current_version = profile.version
        
        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={
                "reason": "Rejection with version check",
                "version": current_version,
            },
            headers=headers,
        )

        assert response.status_code == 200, f"Reject with correct version should succeed: {response.text}"
        
        updated_profile = await reload_profile(profile.id)
        assert updated_profile.version == current_version + 1


# ==============================================================================
# IDOR PROTECTION TESTS
# ==============================================================================


class TestIDORProtection:
    """
    Test IDOR (Insecure Direct Object Reference) protection.

    Per AUTHORIZATION_GUIDELINES: Return 404 (not 403) for unauthorized access.
    """

    async def test_manager_cannot_access_other_unit_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 4.1: Manager from Unit A tries to approve profile from Unit B.

        Expected: 404 Not Found (fake 404 for IDOR protection)
        """
        # Create profile in a DIFFERENT unit (unit_id = 999)
        # First, we need to create that unit
        async with AsyncSessionLocal() as session:
            async with session.begin():
                other_unit = models.OrganizationUnit(
                    id=999,
                    name="Other Unit",
                    type="faculty"  # Required field
                )
                session.add(other_unit)
        
        lead_id = await create_test_lead(unit_id=999)
        profile = await create_admission_profile(lead_id, status="submitted")
        
        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Cross-unit approval attempt", "version": profile.version},
            headers=headers,
        )

        # Must return 404, not 403 (IDOR protection)
        assert response.status_code == 404, \
            f"Should return 404 for IDOR protection, got: {response.status_code}"

    async def test_wrong_cccd_prevents_confirmation(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 4.2: Wrong CCCD digits prevent confirmation (replaces SELF check).

        Expected: 400 Bad Request with attempts remaining info
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "444455556666"  # Known citizen_id
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved", citizen_id=citizen_id)
        
        manager_headers = await get_auth_headers(client, manager_user_in_db)

        # Generate confirmation token
        send_response = await client.post(
            f"/api/admissions/{profile.id}/send-confirmation",
            headers=manager_headers,
        )
        assert send_response.status_code == 200
        
        # Get token from database
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_obj = result.scalar_one()
            token_value = token_obj.token

        # Try to confirm with WRONG CCCD digits
        response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "0000"},  # Wrong digits (should be 6666)
        )

        assert response.status_code == 400, \
            f"Should return 400 for wrong CCCD, got: {response.status_code}"
        assert "Incorrect CCCD" in response.json()["detail"]
        assert "attempts remaining" in response.json()["detail"]

    async def test_admin_can_access_any_profile(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test Case 4.3: Admin can access profiles from any unit."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        
        headers = await get_auth_headers(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Admin approval", "version": profile.version},
            headers=headers,
        )

        # Admin should be able to access (200 or 400 if wrong state, but not 404)
        assert response.status_code != 404, \
            f"Admin should not get 404, got: {response.status_code}"


# ==============================================================================
# STATE TRANSITION WORKFLOW TESTS
# ==============================================================================


class TestStateTransitionWorkflows:
    """Test complete workflows through the state machine."""

    async def test_happy_path_normal_flow(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        regular_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 5.1: Happy path - normal flow.

        Workflow: SUBMITTED → APPROVED → CONFIRMED → ENROLLED
        """
        unit_id = seed_lead_dependencies["unit_id"]
        
        # Create profile with specific citizen_id for token confirmation test
        lead_id = await create_test_lead(unit_id)
        citizen_id = "123456789012"  # Known citizen_id for CCCD verification
        profile = await create_admission_profile(lead_id, status="submitted", citizen_id=citizen_id)
        
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        admin_headers = await get_auth_headers(client, admin_user_in_db)

        # 1. Manager approves
        approve_response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Approved - all criteria met", "version": profile.version},
            headers=manager_headers,
        )
        assert approve_response.status_code == 200, f"Approve failed: {approve_response.text}"
        assert approve_response.json()["status"] == "approved"

        # 2. Manager sends confirmation link (generates magic link token)
        send_link_response = await client.post(
            f"/api/admissions/{profile.id}/send-confirmation",
            headers=manager_headers,
        )
        assert send_link_response.status_code == 200, f"Send link failed: {send_link_response.text}"
        
        # 3. Get the token from database for testing (in production, lead receives via email)
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_obj = result.scalar_one()
            token_value = token_obj.token

        # 4. Lead gets token info (public endpoint)
        token_info_response = await client.get(f"/api/admissions/confirm/{token_value}")
        assert token_info_response.status_code == 200, f"Token info failed: {token_info_response.text}"
        token_info = token_info_response.json()
        assert token_info["valid"] is True
        # PR1 Commit 7: profile_name is MASKED on this public, pre-verification
        # endpoint (the full name is only revealed after CCCD verify).
        assert token_info["profile_name"] == "T••• A•••"
        assert token_info["profile_name"] != "Test Applicant"

        # 5. Lead confirms with wrong CCCD (should fail)
        wrong_confirm_response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "0000"},
        )
        assert wrong_confirm_response.status_code == 400, f"Should fail with wrong CCCD"

        # 6. Lead confirms with correct CCCD (last 4 digits of citizen_id)
        correct_confirm_response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "9012"},  # Last 4 digits of 123456789012
        )
        assert correct_confirm_response.status_code == 200, f"Confirm failed: {correct_confirm_response.text}"
        assert correct_confirm_response.json()["status"] == "confirmed"

        # 7. Admin finalizes — ADM-015 requires current ``version``.
        # ``ConfirmTokenResponse`` (the magic-link confirm response
        # shape) does not carry ``version``, so we fetch the latest
        # profile state via GET before issuing the finalize.
        profile_after_confirm = await client.get(
            f"/api/admissions/{profile.id}",
            headers=admin_headers,
        )
        assert profile_after_confirm.status_code == 200, profile_after_confirm.text
        finalize_response = await client.post(
            f"/api/admissions/{profile.id}/finalize",
            json={"version": profile_after_confirm.json()["version"]},
            headers=admin_headers,
        )
        assert finalize_response.status_code == 200, f"Finalize failed: {finalize_response.text}"
        assert finalize_response.json()["status"] == "enrolled"

    async def test_rejection_recovery_flow(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 5.2: Rejection and recovery flow.

        Workflow: SUBMITTED → REJECTED → RESUBMITTED → APPROVED
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="submitted")
        
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        officer_headers = await get_auth_headers(client, officer_user_in_db)

        # 1. Manager rejects
        reject_response = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={"reason": "Missing required documents - please upload ID card", "version": profile.version},
            headers=manager_headers,
        )
        assert reject_response.status_code == 200, f"Reject failed: {reject_response.text}"
        assert reject_response.json()["status"] == "rejected"

        # 2. Officer resubmits after fixing
        # Reject incremented version from 1 to 2, so resubmit must send 2
        resubmit_response = await client.post(
            f"/api/admissions/{profile.id}/resubmit",
            json={"notes": "Uploaded missing ID card document", "version": 2},
            headers=officer_headers,
        )
        assert resubmit_response.status_code == 200, f"Resubmit failed: {resubmit_response.text}"
        assert resubmit_response.json()["status"] == "resubmitted"

        # 3. Manager approves after resubmit
        approve_response = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Approved after resubmission", "version": 3}, # Resubmit (2) -> 3.
            headers=manager_headers,
        )
        assert approve_response.status_code == 200, f"Approve after resubmit failed: {approve_response.text}"
        assert approve_response.json()["status"] == "approved"

    async def test_admin_override_flow(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Test Case 5.3: Admin override exception flow.

        Workflow: APPROVED → OVERRIDDEN → ENROLLED
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved")
        
        admin_headers = await get_auth_headers(client, admin_user_in_db)

        # 1. Admin overrides normal flow
        override_response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "Special case - VIP applicant requires immediate enrollment",
                "bypass_rules": ["confirmation_required"],
                "version": profile.version,
            },
            headers=admin_headers,
        )
        assert override_response.status_code == 200, f"Override failed: {override_response.text}"
        assert override_response.json()["status"] == "overridden"

        # 2. Admin finalizes — ADM-015 requires current ``version``
        finalize_response = await client.post(
            f"/api/admissions/{profile.id}/finalize",
            json={"version": override_response.json()["version"]},
            headers=admin_headers,
        )
        assert finalize_response.status_code == 200, f"Finalize failed: {finalize_response.text}"
        assert finalize_response.json()["status"] == "enrolled"


# ==============================================================================
# TOKEN-BASED CONFIRMATION TESTS
# ==============================================================================


class TestTokenBasedConfirmation:
    """Test magic link + CCCD verification flow."""

    async def test_get_token_info_valid(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test GET /confirm/{token} returns valid token info."""
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "999988887777"
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved", citizen_id=citizen_id)
        
        headers = await get_auth_headers(client, manager_user_in_db)
        
        # Send confirmation link
        await client.post(f"/api/admissions/{profile.id}/send-confirmation", headers=headers)
        
        # Get token from DB
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_value = result.scalar_one().token
        
        # Get token info (public endpoint)
        response = await client.get(f"/api/admissions/confirm/{token_value}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["expired"] is False
        assert data["locked"] is False
        assert data["already_used"] is False
        assert data["attempts_remaining"] == 5
        # PR1 Commit 7: profile_name is MASKED on this public, pre-verification
        # endpoint (full name only after CCCD verify).
        assert data["profile_name"] == "T••• A•••"
        assert data["profile_name"] != "Test Applicant"

    async def test_invalid_token_returns_404(
        self,
        client: AsyncClient,
    ):
        """Test GET /confirm/{invalid_token} returns 404."""
        response = await client.get("/api/admissions/confirm/invalid_token_abc123")
        assert response.status_code == 404

    async def test_token_locked_after_max_attempts(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test token gets locked after 5 failed CCCD attempts."""
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "777766665555"
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved", citizen_id=citizen_id)
        
        headers = await get_auth_headers(client, manager_user_in_db)
        await client.post(f"/api/admissions/{profile.id}/send-confirmation", headers=headers)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_value = result.scalar_one().token
        
        # Make 5 wrong attempts
        for i in range(5):
            response = await client.post(
                f"/api/admissions/confirm/{token_value}",
                json={"last_digits_citizen_id": "0000"},
            )
            assert response.status_code == 400

        # 6th attempt should show locked message
        response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "5555"},  # Even correct digits
        )
        assert response.status_code == 400
        assert "locked" in response.json()["detail"].lower()

    async def test_expired_token_rejected(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test expired token is rejected."""
        from datetime import timedelta
        
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "555544443333"
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved", citizen_id=citizen_id)
        
        headers = await get_auth_headers(client, manager_user_in_db)
        await client.post(f"/api/admissions/{profile.id}/send-confirmation", headers=headers)
        
        # Manually expire the token
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(models.AdmissionConfirmationToken)
                    .where(models.AdmissionConfirmationToken.profile_id == profile.id)
                )
                token = result.scalar_one()
                token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
                token_value = token.token
        
        # Try to confirm - should fail
        response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "3333"},
        )
        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()

    async def test_concurrent_confirm_same_token(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Two simultaneous POST /confirm/{token} with the same token —
        only one should win; the other must be rejected because the
        SELECT FOR UPDATE row lock serialises the transactions and the
        profile is already 'confirmed' by the time the loser acquires it.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "111122223344"  # last 4 = "3344"

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(
            lead_id, status="approved", citizen_id=citizen_id
        )

        headers = await get_auth_headers(client, manager_user_in_db)
        await client.post(
            f"/api/admissions/{profile.id}/send-confirmation", headers=headers
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_value = result.scalar_one().token

        # Fire both confirms with the correct CCCD at the same time.
        responses = await asyncio.gather(
            client.post(
                f"/api/admissions/confirm/{token_value}",
                json={"last_digits_citizen_id": "3344"},
            ),
            client.post(
                f"/api/admissions/confirm/{token_value}",
                json={"last_digits_citizen_id": "3344"},
            ),
        )

        statuses = sorted(r.status_code for r in responses)
        # Exactly one 200 winner and one rejection (400 "already used" /
        # "not in approved state"). No double-commit, no 500.
        assert statuses == [200, 400], (
            f"Expected [200, 400], got {statuses}: "
            f"{[r.text for r in responses]}"
        )

        # Final DB state: profile confirmed exactly once.
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile.id
                )
            )
            final = result.scalar_one()
            assert final.status == "confirmed"
            assert final.confirmed_at is not None

    async def test_token_expires_at_boundary(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Document the inclusive/exclusive semantics of the expiry check.

        Current code at admission_service.verify_and_confirm uses
        `token_obj.expires_at < now` — strict `<`. So a token whose
        `expires_at` is exactly `now` is still considered valid (by a hair).
        This test locks that behaviour in so any future change that flips
        the comparison to `<=` becomes a visible breaking change rather
        than a silent UX shift.
        """
        from datetime import timedelta

        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "222211119988"  # last 4 = "9988"

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(
            lead_id, status="approved", citizen_id=citizen_id
        )

        headers = await get_auth_headers(client, manager_user_in_db)
        await client.post(
            f"/api/admissions/{profile.id}/send-confirmation", headers=headers
        )

        # Pin expires_at a few milliseconds in the future so the comparison
        # `expires_at < now` is false and the token is still accepted.
        async with AsyncSessionLocal() as session:
            async with session.begin():
                result = await session.execute(
                    select(models.AdmissionConfirmationToken)
                    .where(
                        models.AdmissionConfirmationToken.profile_id == profile.id
                    )
                )
                token = result.scalar_one()
                token.expires_at = datetime.now(timezone.utc) + timedelta(
                    milliseconds=200
                )
                token_value = token.token

        response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "9988"},
        )

        assert response.status_code == 200, (
            f"Boundary expires_at (now + 200ms) should still be valid, got "
            f"{response.status_code}: {response.text}"
        )
        assert response.json()["status"] == "confirmed"

    async def test_verify_and_confirm_bumps_version(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Guard the optimistic-lock contract around the confirm transition.

        Any subsequent mutation that relies on version matching (PUT
        /admissions/{id}, withdraw, etc.) would otherwise observe a
        stale version and 409 silently. If this test ever fails, the
        version bump in verify_and_confirm has regressed and downstream
        clients need to be told.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "444455556677"  # last 4 = "6677"

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(
            lead_id, status="approved", citizen_id=citizen_id
        )
        version_before = profile.version

        headers = await get_auth_headers(client, manager_user_in_db)
        await client.post(
            f"/api/admissions/{profile.id}/send-confirmation", headers=headers
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_value = result.scalar_one().token

        response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "6677"},
        )
        assert response.status_code == 200

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile.id
                )
            )
            updated = result.scalar_one()
            assert updated.version == version_before + 1, (
                f"Expected version {version_before + 1}, got {updated.version}"
            )
            assert updated.status == "confirmed"

    async def test_resend_confirmation_invalidates_old_token(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Test resending confirmation link invalidates old token."""
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "333322221111"
        
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved", citizen_id=citizen_id)
        
        headers = await get_auth_headers(client, manager_user_in_db)
        
        # First send
        await client.post(f"/api/admissions/{profile.id}/send-confirmation", headers=headers)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            old_token = result.scalar_one().token
        
        # Second send (resend)
        await client.post(f"/api/admissions/{profile.id}/send-confirmation", headers=headers)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            new_token = result.scalar_one().token
        
        # Old token should no longer work
        assert old_token != new_token
        
        old_token_response = await client.get(f"/api/admissions/confirm/{old_token}")
        assert old_token_response.status_code == 404
        
        # New token should work
        new_token_response = await client.get(f"/api/admissions/confirm/{new_token}")
        assert new_token_response.status_code == 200

    async def test_verify_and_confirm_succeeds_without_officer(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """BUG-1 regression guard.

        Lead approved without assigned_officer_id → applicant should still
        be able to confirm. Milestone consultation is skipped gracefully
        (logged warning) rather than raising 400.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        citizen_id = "888877776666"  # last 4 = "6666"

        # Create lead WITHOUT assigned_officer_id — the orphan edge case.
        lead_id = await create_test_lead(unit_id, assigned_officer_id=None)
        profile = await create_admission_profile(
            lead_id, status="approved", citizen_id=citizen_id
        )

        headers = await get_auth_headers(client, manager_user_in_db)
        await client.post(
            f"/api/admissions/{profile.id}/send-confirmation", headers=headers
        )

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionConfirmationToken)
                .where(models.AdmissionConfirmationToken.profile_id == profile.id)
            )
            token_value = result.scalar_one().token

        # Double-check lead really has no officer before we confirm.
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.Lead.assigned_officer_id).where(models.Lead.id == lead_id)
            )
            assert result.scalar_one() is None

        response = await client.post(
            f"/api/admissions/confirm/{token_value}",
            json={"last_digits_citizen_id": "6666"},
        )

        assert response.status_code == 200, (
            f"Confirm must succeed even without an officer on the lead. "
            f"Got {response.status_code}: {response.text}"
        )
        assert response.json()["status"] == "confirmed"

        # Profile status committed.
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile.id
                )
            )
            final = result.scalar_one()
            assert final.status == "confirmed"
            assert final.confirmed_at is not None

    async def test_assigned_officer_sees_send_confirmation_permission_on_approved(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Contract guard for P1/P2 from the 2026-04-19 review.

        The Casbin policy grants POST /send-confirmation to every role
        (policy_templates.py:139), and get_admission_for_manager permits
        officers who are assigned to the lead within their own unit. The
        permission builder in _compute_frontend_fields MUST mirror that —
        otherwise the UI button is invisible to the very users who ARE
        allowed to call the endpoint.

        Setup: approved profile, officer assigned to the lead, same unit.
        Expect: GET /api/admissions/{id} response has
        permissions.send_confirmation == True.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(
            unit_id, assigned_officer_id=officer_user_in_db["id"]
        )
        profile = await create_admission_profile(
            lead_id, status="approved", citizen_id="554433221100"
        )

        officer_headers = await get_auth_headers(client, officer_user_in_db)
        response = await client.get(
            f"/api/admissions/{profile.id}", headers=officer_headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "approved"
        assert body["permissions"].get("send_confirmation") is True, (
            f"Assigned officer must receive send_confirmation=True on an "
            f"approved profile. Full permissions: {body['permissions']}"
        )
        # Cross-check: the same permission flips false when the profile
        # leaves the approved window (applicant already confirmed etc.).
        # Covered here implicitly by the "submitted does NOT show" UI test
        # in AdmissionActions.test.tsx and by confirmed-state tests above.

    async def test_send_confirmation_response_includes_confirm_url(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Ops gap 1 regression guard.

        `/send-confirmation` must return a ready-to-share `confirm_url` so
        officers don't need to hardcode FRONTEND_URL + /confirm/ + token
        themselves. Also verifies the canonical `phone` field is present.
        """
        from app.config import settings

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(
            lead_id, status="approved", citizen_id="776655443322"
        )

        headers = await get_auth_headers(client, manager_user_in_db)
        response = await client.post(
            f"/api/admissions/{profile.id}/send-confirmation", headers=headers
        )

        assert response.status_code == 200
        body = response.json()

        # Canonical confirm_url built from settings, not composed by caller.
        assert body["confirm_url"].startswith(settings.FRONTEND_URL.rstrip("/"))
        assert "/confirm/" in body["confirm_url"]
        assert body["token_value"] in body["confirm_url"]

        # Canonical phone field present; deprecated `sent_to_phone` alias
        # removed after one cycle (originally shipped 2026-04-19).
        assert "phone" in body
        assert "sent_to_phone" not in body


# ==============================================================================
# LIST ENDPOINT HARDENING (BUG-2)
# ==============================================================================


class TestAdmissionListNullJsonbFields:
    """BUG-2 regression guard: GET /admissions must tolerate rows with NULL
    JSONB list columns (family_info, academic_history). Pre-fix this crashed
    the whole page with pydantic `list_type` validation error.
    """

    async def test_list_tolerates_profile_with_null_list_fields(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Seed a profile with family_info=NULL + academic_history=NULL
        (simulating legacy rows or partial migrations that bypass service).
        Listing the page must 200 with `[]` for those fields, not 500.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="draft",
                    citizen_id="990088007700",
                    version=1,
                    applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
                    academic_year=2025,
                    family_info=None,  # Intentional poison
                    academic_history=None,  # Intentional poison
                )
                session.add(profile)
                await session.flush()
                profile_id = profile.id

        headers = await get_auth_headers(client, manager_user_in_db)
        response = await client.get(
            "/api/admissions?page=1&page_size=50", headers=headers
        )

        assert response.status_code == 200, (
            f"List endpoint must not 500 on a profile with NULL list JSONB "
            f"fields. Got {response.status_code}: {response.text[:300]}"
        )

        # Find the poisoned row in the response; its list fields must have
        # been coerced to `[]`.
        body = response.json()
        rows = body.get("profiles") or body.get("items") or []
        poison = next((p for p in rows if p["id"] == profile_id), None)
        assert poison is not None, (
            f"Poisoned profile {profile_id} missing from response; list "
            f"may have silently dropped it."
        )
        assert poison["family_info"] == []
        assert poison["academic_history"] == []


# ==============================================================================
# CLAIM/UNCLAIM WORKFLOW TESTS
# ==============================================================================


class TestClaimUnclaimWorkflow:
    """
    Test claim/unclaim workflow for admission profile review.

    Claim = Manager/Admin "locks" a submitted profile for review.
    Unclaim = Release the lock (self or admin override).
    """

    async def test_manager_can_claim_submitted_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Manager claims submitted profile → 200, assigned_reviewer_id set."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=headers,
        )

        assert response.status_code == 200, f"Claim failed: {response.text}"
        data = response.json()
        assert data["assigned_reviewer_id"] == manager_user_in_db["id"], \
            f"Expected reviewer_id={manager_user_in_db['id']}, got {data.get('assigned_reviewer_id')}"

    async def test_claim_already_claimed_by_another_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Double claim by different users → 400."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        # Manager claims first
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        response1 = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=manager_headers,
        )
        assert response1.status_code == 200

        # Admin tries to claim same profile
        admin_headers = await get_auth_headers(client, admin_user_in_db)
        new_version = response1.json()["version"]
        response2 = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": new_version},
            headers=admin_headers,
        )
        assert response2.status_code == 400, \
            f"Double claim should fail: {response2.status_code} - {response2.text}"

    async def test_cannot_claim_draft_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Draft profile → claim → 400 (only submitted/resubmitted can be claimed)."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="draft")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=headers,
        )

        assert response.status_code == 400, \
            f"Should not claim draft: {response.status_code} - {response.text}"

    async def test_manager_can_claim_resubmitted_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Resubmitted profile → claim → 200."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="resubmitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=headers,
        )

        assert response.status_code == 200, f"Claim resubmitted failed: {response.text}"
        assert response.json()["assigned_reviewer_id"] == manager_user_in_db["id"]

    async def test_manager_can_unclaim_own_profile(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Manager unclaims own claimed profile → 200, reviewer_id = null."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        # Claim first
        claim_resp = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=headers,
        )
        assert claim_resp.status_code == 200
        claimed_version = claim_resp.json()["version"]

        # Unclaim
        unclaim_resp = await client.post(
            f"/api/admissions/{profile.id}/unclaim",
            json={"version": claimed_version},
            headers=headers,
        )

        assert unclaim_resp.status_code == 200, f"Unclaim failed: {unclaim_resp.text}"
        assert unclaim_resp.json()["assigned_reviewer_id"] is None, \
            "Reviewer should be null after unclaim"

    async def test_unclaim_not_owned_by_manager_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Manager cannot unclaim profile claimed by another user → 400."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        # Admin claims the profile
        admin_headers = await get_auth_headers(client, admin_user_in_db)
        claim_resp = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=admin_headers,
        )
        assert claim_resp.status_code == 200
        claimed_version = claim_resp.json()["version"]

        # Manager tries to unclaim admin's profile
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        unclaim_resp = await client.post(
            f"/api/admissions/{profile.id}/unclaim",
            json={"version": claimed_version},
            headers=manager_headers,
        )

        assert unclaim_resp.status_code == 400, \
            f"Manager should not unclaim admin's profile: {unclaim_resp.status_code} - {unclaim_resp.text}"

    async def test_admin_can_unclaim_anyone(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Admin can unclaim profile claimed by any manager → 200."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        # Manager claims the profile
        manager_headers = await get_auth_headers(client, manager_user_in_db)
        claim_resp = await client.post(
            f"/api/admissions/{profile.id}/claim",
            json={"version": profile.version},
            headers=manager_headers,
        )
        assert claim_resp.status_code == 200
        claimed_version = claim_resp.json()["version"]

        # Admin unclaims
        admin_headers = await get_auth_headers(client, admin_user_in_db)
        unclaim_resp = await client.post(
            f"/api/admissions/{profile.id}/unclaim",
            json={"version": claimed_version},
            headers=admin_headers,
        )

        assert unclaim_resp.status_code == 200, \
            f"Admin should unclaim anyone: {unclaim_resp.status_code} - {unclaim_resp.text}"
        assert unclaim_resp.json()["assigned_reviewer_id"] is None

    async def test_unclaim_no_reviewer_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Unclaim profile with no reviewer → 400."""
        unit_id = seed_lead_dependencies["unit_id"]

        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/unclaim",
            json={"version": profile.version},
            headers=headers,
        )

        assert response.status_code == 400, \
            f"Should not unclaim when no reviewer: {response.status_code} - {response.text}"


# ==============================================================================
# REVISION REQUEST TESTS (Phase 5a)
# ==============================================================================


class TestRevisionRequestWorkflow:
    """
    Test request-revision endpoint (Phase 5a).

    Workflow: SUBMITTED/RESUBMITTED → REVISION_REQUESTED → RESUBMITTED → ...
    """

    async def test_manager_can_request_revision_on_submitted(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """SUBMITTED → request-revision → 200, status=revision_requested."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "Thiếu ảnh CCCD mặt sau, vui lòng bổ sung",
                "version": profile.version,
            },
            headers=headers,
        )

        assert response.status_code == 200, f"Request revision failed: {response.text}"
        data = response.json()
        assert data["status"] == "revision_requested"
        assert data["revision_reason"] == "Thiếu ảnh CCCD mặt sau, vui lòng bổ sung"
        assert data["revision_requested_by_id"] == manager_user_in_db["id"]
        assert data["revision_requested_at"] is not None

    async def test_manager_can_request_revision_on_resubmitted(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """RESUBMITTED → request-revision → 200."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="resubmitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "Bổ sung thêm bản sao giấy khai sinh có công chứng",
                "version": profile.version,
            },
            headers=headers,
        )

        assert response.status_code == 200, f"Request revision on resubmitted failed: {response.text}"
        assert response.json()["status"] == "revision_requested"

    async def test_request_revision_on_draft_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """DRAFT → request-revision → 400 (invalid transition)."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="draft")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "Should not work on draft profiles at all",
                "version": profile.version,
            },
            headers=headers,
        )

        assert response.status_code == 400, \
            f"Should not request revision on draft: {response.status_code}"

    async def test_request_revision_on_approved_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """APPROVED → request-revision → 400 (invalid transition)."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="approved")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "Should not work on already approved profiles",
                "version": profile.version,
            },
            headers=headers,
        )

        assert response.status_code == 400

    async def test_request_revision_short_reason_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Reason < 10 chars → 422 validation error."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={"reason": "short", "version": profile.version},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_request_revision_stale_version_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Stale version → 409 Conflict."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        # Manually bump version
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_profile = await session.get(models.AdmissionProfile, profile.id)
                db_profile.version = 5

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "This should fail due to stale version number",
                "version": 1,
            },
            headers=headers,
        )

        assert response.status_code == 409

    async def test_revision_then_resubmit_flow(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        officer_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        Full flow: SUBMITTED → REVISION_REQUESTED → RESUBMITTED → APPROVED.
        Verifies revision fields are preserved after resubmit.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id, assigned_officer_id=officer_user_in_db["id"])
        profile = await create_admission_profile(lead_id, status="submitted")

        manager_headers = await get_auth_headers(client, manager_user_in_db)
        officer_headers = await get_auth_headers(client, officer_user_in_db)

        # 1. Manager requests revision
        rev_resp = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "Cần bổ sung giấy khám sức khỏe có xác nhận",
                "version": profile.version,
            },
            headers=manager_headers,
        )
        assert rev_resp.status_code == 200
        assert rev_resp.json()["status"] == "revision_requested"
        rev_version = rev_resp.json()["version"]

        # 2. Officer resubmits
        resub_resp = await client.post(
            f"/api/admissions/{profile.id}/resubmit",
            json={"notes": "Đã bổ sung giấy khám", "version": rev_version},
            headers=officer_headers,
        )
        assert resub_resp.status_code == 200
        assert resub_resp.json()["status"] == "resubmitted"
        resub_version = resub_resp.json()["version"]

        # 3. Manager approves
        approve_resp = await client.post(
            f"/api/admissions/{profile.id}/approve",
            json={"notes": "Hồ sơ đầy đủ sau bổ sung", "version": resub_version},
            headers=manager_headers,
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # Verify revision fields are preserved (not overwritten by resubmit/approve)
        final = await reload_profile(profile.id)
        assert final.revision_reason == "Cần bổ sung giấy khám sức khỏe có xác nhận"
        assert final.revision_requested_at is not None

    async def test_revision_then_reject_flow(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """
        REVISION_REQUESTED → REJECTED (manager rejects without waiting for resubmit).
        Both revision and rejection fields should be preserved independently.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        # 1. Request revision
        rev_resp = await client.post(
            f"/api/admissions/{profile.id}/request-revision",
            json={
                "reason": "Hồ sơ thiếu nhiều giấy tờ cần thiết, yêu cầu bổ sung",
                "version": profile.version,
            },
            headers=headers,
        )
        assert rev_resp.status_code == 200
        rev_version = rev_resp.json()["version"]

        # 2. Reject without waiting (allowed by state machine)
        reject_resp = await client.post(
            f"/api/admissions/{profile.id}/reject",
            json={
                "reason": "Quyết định từ chối do hồ sơ không đáp ứng yêu cầu",
                "version": rev_version,
            },
            headers=headers,
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

        # Both revision and rejection audit trails preserved
        final = await reload_profile(profile.id)
        assert final.revision_reason is not None
        assert final.rejection_reason is not None
        assert final.revision_requested_at is not None
        assert final.rejected_at is not None


# ==============================================================================
# DROP STUDENT TESTS (Phase 5b)
# ==============================================================================


class TestDropStudentWorkflow:
    """
    Test drop endpoint (Phase 5b).

    Side-channel: status stays "enrolled", is_dropped=True.
    """

    async def test_manager_can_drop_enrolled_student(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """ENROLLED + drop → 200, is_dropped=True, status stays enrolled."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="enrolled")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/drop",
            json={
                "reason": "Sinh viên tự nguyện nghỉ học do hoàn cảnh gia đình",
                "version": profile.version,
            },
            headers=headers,
        )

        assert response.status_code == 200, f"Drop failed: {response.text}"
        data = response.json()
        assert data["status"] == "enrolled", "Status should remain 'enrolled'"
        assert data["is_dropped"] is True
        assert data["dropped_reason"] == "Sinh viên tự nguyện nghỉ học do hoàn cảnh gia đình"
        assert data["dropped_by_id"] == manager_user_in_db["id"]
        assert data["dropped_at"] is not None
        # is_dropped is a terminal side-channel — no workflow/mutation action
        # applies anymore, so available_actions collapses to read-only 'view'.
        # Guards against stale buttons (calculate_fee, minor_correction, …) on a
        # dropped seat whose status deliberately stays 'enrolled'.
        assert data["available_actions"] == ["view"], (
            f"Dropped profile must expose only 'view', got {data['available_actions']}"
        )
        assert data["permissions"].get("has_decision") is False

    async def test_drop_non_enrolled_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """SUBMITTED → drop → 400 (can only drop enrolled students)."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/drop",
            json={
                "reason": "Should not work on non-enrolled profiles at all",
                "version": profile.version,
            },
            headers=headers,
        )

        assert response.status_code == 400

    async def test_drop_already_dropped_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Double drop → 400 (already dropped)."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)

        # Create enrolled + already dropped profile
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = models.AdmissionProfile(
                    lead_id=lead_id,
                    status="enrolled",
                    citizen_id="888877776666",
                    version=1,
                    is_dropped=True,
                    applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
                    academic_year=2025,
                )
                session.add(profile)
                await session.flush()
                profile_id = profile.id

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile_id}/drop",
            json={
                "reason": "Should not work on already dropped students whatsoever",
                "version": 1,
            },
            headers=headers,
        )

        assert response.status_code == 400

    async def test_drop_short_reason_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Reason < 10 chars → 422."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="enrolled")

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/drop",
            json={"reason": "short", "version": profile.version},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_drop_stale_version_fails(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Stale version → 409 Conflict."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="enrolled")

        # Bump version
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_profile = await session.get(models.AdmissionProfile, profile.id)
                db_profile.version = 5

        headers = await get_auth_headers(client, manager_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/drop",
            json={
                "reason": "This should fail due to stale version number here",
                "version": 1,
            },
            headers=headers,
        )

        assert response.status_code == 409

    async def test_drop_clears_available_actions(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """After drop, available_actions should be empty."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="enrolled")

        headers = await get_auth_headers(client, manager_user_in_db)

        # Drop the student
        drop_resp = await client.post(
            f"/api/admissions/{profile.id}/drop",
            json={
                "reason": "Sinh viên vi phạm quy chế đào tạo nhiều lần",
                "version": profile.version,
            },
            headers=headers,
        )
        assert drop_resp.status_code == 200

        # Fetch profile and check no workflow actions remain (only view is allowed)
        get_resp = await client.get(
            f"/api/admissions/{profile.id}",
            headers=headers,
        )
        assert get_resp.status_code == 200
        actions = get_resp.json()["available_actions"]
        # No admission-workflow actions (approve, reject, drop, enroll, etc.)
        # remain after drop. ``view`` is always allowed; ``assign_officer``
        # targets the lead-officer relationship (lead.assigned_officer_id),
        # not the admission lifecycle — the route permits it at any status,
        # so it's excluded from the workflow-empty check.
        non_workflow = {"view", "assign_officer"}
        workflow_actions = [a for a in actions if a not in non_workflow]
        assert workflow_actions == [], f"Dropped student should have no workflow actions, got: {actions}"
        assert get_resp.json()["is_dropped"] is True

    async def test_drop_dispatches_application_status_changed(
        self,
        client: AsyncClient,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Drop must dispatch APPLICATION_STATUS_CHANGED just like
        approve/reject/confirm/enroll.

        Regression guard for the W3-E5 cleanup (2026-04-20): before the
        fix, mark_student_dropped only logged in post_commit and the
        router dispatched LEAD_STATUS_CHANGED alone, so the admission
        feed had no profile-level trail of the drop transition.

        Path C / Arch-3 update (2026-04-22): dispatch is now owned by the
        service via ``dispatch_bundle`` (savepoint-atomic pair). We
        intercept at the bundle's ``dispatch`` import seam instead of
        the router-level ``safe_dispatch`` (which the router no longer
        calls for paired admission events).
        """
        from unittest.mock import AsyncMock, patch

        from app.core.events import SystemEvents

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="enrolled")

        headers = await get_auth_headers(client, manager_user_in_db)

        # Bundle dispatch returns ``(notification_ids, post_commit_cb)``;
        # the helper unpacks the tuple, so a bare AsyncMock that returns
        # ``([], None)`` is enough to satisfy the contract.
        with patch(
            "app.services.notification_bundle.dispatch",
            new=AsyncMock(return_value=([], None)),
        ) as mock_dispatch:
            drop_resp = await client.post(
                f"/api/admissions/{profile.id}/drop",
                json={
                    "reason": "Sinh viên nghỉ theo nguyện vọng của gia đình",
                    "version": profile.version,
                },
                headers=headers,
            )

        assert drop_resp.status_code == 200

        dispatched_events = [
            call.kwargs["event"] for call in mock_dispatch.await_args_list
        ]
        assert SystemEvents.APPLICATION_STATUS_CHANGED in dispatched_events, (
            "Drop must dispatch APPLICATION_STATUS_CHANGED; got "
            f"{[e.value if hasattr(e, 'value') else e for e in dispatched_events]}"
        )

        app_call = next(
            call for call in mock_dispatch.await_args_list
            if call.kwargs.get("event") == SystemEvents.APPLICATION_STATUS_CHANGED
        )
        payload = app_call.kwargs["payload"]
        assert payload["application_id"] == profile.id
        assert payload["lead_id"] == lead_id
        assert payload["old_status"] == "enrolled"
        # Drop is a side-channel transition — status stays "enrolled" on
        # the row (is_dropped=True flag), so the event carries a sentinel
        # new_status so downstream consumers can branch without having to
        # read is_dropped separately.
        assert payload["new_status"] == "enrolled_dropped"
        assert app_call.kwargs["dedupe_key"] == f"admission_profile_dropped:{profile.id}"
