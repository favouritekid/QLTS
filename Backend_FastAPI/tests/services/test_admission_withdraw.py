"""
Tests for the admission withdraw flow (PR5).

Covers both the service (withdraw_profile) and the HTTP endpoint
(POST /admissions/{id}/withdraw).

Service-level:
- Happy path: submitted -> withdrawn; version bumped; lead synced to sts08.
- State machine: approved profile cannot be withdrawn.
- Optimistic locking: wrong version -> 409.

HTTP + RBAC contract:
- Admin: 200 happy path.
- Officer (assigned): 200 happy path (granted via OFFICER_TEMPLATE,
  manager/admin inherit via diamond).
- Regular user (role=user): 403 from Casbin (no /withdraw permission).
- Invalid state: 400.
- Version mismatch: 409.
- Schema validation (short reason): 422.
- Missing profile: 404.

Uses real DB. Channel delivery is not exercised here — notification
dispatch is covered by the broader notification tests.
"""

from __future__ import annotations

import random
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest_asyncio.fixture(scope="function")
async def seed_sts08(seed_lead_dependencies: dict):
    """Ensure sts08 exists (lead status for withdrawn profiles).

    seed_lead_dependencies seeds sts06/07/09/10/11/12/13/14/16/17/18 but
    NOT sts08, which lead_admission_sync uses when a profile is withdrawn.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            existing = await session.get(models.ConsultationStatus, "sts08")
            if existing is None:
                session.add(
                    models.ConsultationStatus(
                        id="sts08",
                        name="Tu choi tu van",
                        color_code="#FF0000",
                        stage_id="stg02",
                    )
                )
    return seed_lead_dependencies


# ==============================================================================
# HELPERS
# ==============================================================================


async def _create_lead(unit_id: int, officer_id: int | None = None) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            unique = uuid.uuid4().hex[:12]
            lead = models.Lead(
                full_name=f"Withdraw Test Lead {unique}",
                phone=f"090{random.randint(1000000, 9999999)}",
                email=f"withdraw_{unique}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
                consultation_status_id="sts06",
            )
            session.add(lead)
            await session.flush()
            return lead.id


async def _create_profile(lead_id: int, status: str = "submitted") -> models.AdmissionProfile:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            citizen = f"20{random.randint(1000000000, 9999999999)}"  # 12 digits
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen,
                academic_year=2026,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
            )
            session.add(profile)
            await session.flush()
            pid = profile.id

        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == pid)
            .options(selectinload(models.AdmissionProfile.lead))
        )
        return result.scalar_one()


async def _reload_profile(profile_id: int) -> models.AdmissionProfile:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AdmissionProfile).where(
                models.AdmissionProfile.id == profile_id
            )
        )
        return result.scalar_one()


async def _get_lead_status(lead_id: int) -> str | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(models.Lead, lead_id)
        return row.consultation_status_id if row else None


async def _get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")
    token = res.cookies.get("access_token")
    if not token:
        pytest.fail("Login OK but access_token cookie missing")
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# SERVICE-LEVEL TESTS
# ==============================================================================


class TestWithdrawService:
    """Direct calls to admission_service.withdraw_profile()."""

    async def test_submitted_profile_is_withdrawn(
        self,
        admin_user_in_db: dict,
        seed_sts08: dict,
    ):
        """Happy path: submitted -> withdrawn, version bumps, lead -> sts08."""
        from app.services import admission_service

        unit_id = seed_sts08["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="submitted")

        actor = models.User(
            id=officer_id,
            username=admin_user_in_db["username"],
            email="withdraw@test.com",
            password_hash="x",
            role="admin",
            status="active",
        )

        async with AsyncSessionLocal() as session:
            result, callback = await admission_service.withdraw_profile(
                db=session,
                profile_id=profile.id,
                actor=actor,
                data={"reason": "Student changed their mind", "version": 1},
            )
            await session.commit()
            await callback()

        reloaded = await _reload_profile(profile.id)
        assert reloaded.status == "withdrawn"
        assert reloaded.version == 2
        assert await _get_lead_status(lead_id) == "sts08"

    async def test_cannot_withdraw_approved_profile(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """State machine blocks approved -> withdrawn."""
        from app.services import admission_service
        from app.utils.exceptions import BadRequest

        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="approved")

        actor = models.User(
            id=officer_id,
            username=admin_user_in_db["username"],
            email="x@test.com",
            password_hash="x",
            role="admin",
            status="active",
        )

        async with AsyncSessionLocal() as session:
            with pytest.raises(BadRequest):
                await admission_service.withdraw_profile(
                    db=session,
                    profile_id=profile.id,
                    actor=actor,
                    data={"reason": "Try to withdraw approved", "version": 1},
                )

        # State unchanged
        reloaded = await _reload_profile(profile.id)
        assert reloaded.status == "approved"

    async def test_version_mismatch_raises_conflict(
        self,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Wrong version raises ConflictError."""
        from app.services import admission_service
        from app.utils.exceptions import ConflictError

        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="submitted")

        actor = models.User(
            id=officer_id,
            username=admin_user_in_db["username"],
            email="x@test.com",
            password_hash="x",
            role="admin",
            status="active",
        )

        async with AsyncSessionLocal() as session:
            with pytest.raises(ConflictError):
                await admission_service.withdraw_profile(
                    db=session,
                    profile_id=profile.id,
                    actor=actor,
                    data={"reason": "Stale client version", "version": 999},
                )

    async def test_admitted_profile_withdraws_directly(
        self,
        admin_user_in_db: dict,
        seed_sts08: dict,
    ):
        """PR-B v3 scenario (f): an ``admitted`` (seat-occupying) profile is
        withdrawn STRAIGHT to ``withdrawn`` — the orchestrator's STEP 0 keeps the
        legacy direct path (no auto-refund/cancel, no ``withdrawal_pending``) so
        withdrawal never churns quota-seat accounting."""
        from app.services import admission_service

        unit_id = seed_sts08["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="admitted")

        actor = models.User(
            id=officer_id,
            username=admin_user_in_db["username"],
            email="admitted@test.com",
            password_hash="x",
            role="admin",
            status="active",
        )

        async with AsyncSessionLocal() as session:
            result, callback = await admission_service.withdraw_profile(
                db=session,
                profile_id=profile.id,
                actor=actor,
                data={"reason": "Trúng tuyển nhưng đổi ý", "version": 1},
            )
            await session.commit()
            if callback:
                await callback()

        reloaded = await _reload_profile(profile.id)
        assert reloaded.status == "withdrawn"
        assert await _get_lead_status(lead_id) == "sts08"


# ==============================================================================
# HTTP-LEVEL TESTS
# ==============================================================================


class TestWithdrawEndpoint:
    """POST /api/admissions/{profile_id}/withdraw."""

    async def test_happy_path_returns_200_and_withdraws(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_sts08: dict,
    ):
        unit_id = seed_sts08["unit_id"]
        officer_id = admin_user_in_db["id"]

        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="submitted")

        headers = await _get_auth_headers(client, admin_user_in_db)

        res = await client.post(
            f"/api/admissions/{profile.id}/withdraw",
            json={"reason": "Applicant requested withdrawal", "version": 1},
            headers=headers,
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "withdrawn"
        assert body["version"] == 2

        # Lead pipeline synced to sts08
        assert await _get_lead_status(lead_id) == "sts08"

    async def test_invalid_transition_returns_400(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = admin_user_in_db["id"]
        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="approved")

        headers = await _get_auth_headers(client, admin_user_in_db)
        res = await client.post(
            f"/api/admissions/{profile.id}/withdraw",
            json={"reason": "Try on approved profile", "version": 1},
            headers=headers,
        )
        assert res.status_code == 400, res.text

    async def test_version_mismatch_returns_409(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = admin_user_in_db["id"]
        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="submitted")

        headers = await _get_auth_headers(client, admin_user_in_db)
        res = await client.post(
            f"/api/admissions/{profile.id}/withdraw",
            json={"reason": "Stale version from client", "version": 42},
            headers=headers,
        )
        assert res.status_code == 409, res.text

    async def test_short_reason_returns_422(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Pydantic schema rejects reason shorter than 5 chars."""
        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = admin_user_in_db["id"]
        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="submitted")

        headers = await _get_auth_headers(client, admin_user_in_db)
        res = await client.post(
            f"/api/admissions/{profile.id}/withdraw",
            json={"reason": "no", "version": 1},
            headers=headers,
        )
        assert res.status_code == 422, res.text

    async def test_nonexistent_profile_returns_404(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        headers = await _get_auth_headers(client, admin_user_in_db)
        res = await client.post(
            "/api/admissions/9999999/withdraw",
            json={"reason": "Nonexistent profile", "version": 1},
            headers=headers,
        )
        assert res.status_code == 404, res.text

    async def test_officer_assigned_can_withdraw(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        seed_sts08: dict,
    ):
        """RBAC contract: officer has /withdraw via OFFICER_TEMPLATE,
        and can withdraw a profile whose lead is assigned to them.
        """
        unit_id = seed_sts08["unit_id"]
        officer_id = officer_user_in_db["id"]

        lead_id = await _create_lead(unit_id, officer_id)
        profile = await _create_profile(lead_id, status="submitted")

        headers = await _get_auth_headers(client, officer_user_in_db)
        res = await client.post(
            f"/api/admissions/{profile.id}/withdraw",
            json={"reason": "Officer-initiated withdrawal", "version": 1},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "withdrawn"
        assert await _get_lead_status(lead_id) == "sts08"

    async def test_regular_user_blocked_by_casbin(
        self,
        client: AsyncClient,
        regular_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """RBAC contract: role=user has no /withdraw in BASIC_USER_TEMPLATE,
        so Casbin rejects with 403 before the service or IDOR layer runs.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        # Seed profile via admin's officer_id so the data exists; the
        # important assertion is the 403 from Casbin at the route level.
        lead_id = await _create_lead(unit_id, admin_user_in_db["id"])
        profile = await _create_profile(lead_id, status="submitted")

        headers = await _get_auth_headers(client, regular_user_in_db)
        res = await client.post(
            f"/api/admissions/{profile.id}/withdraw",
            json={"reason": "Unauthorized caller", "version": 1},
            headers=headers,
        )
        assert res.status_code == 403, res.text
