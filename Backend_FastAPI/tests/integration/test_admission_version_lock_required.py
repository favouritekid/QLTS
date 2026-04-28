"""ADM-015 regression suite: optimistic-lock ``version`` required for
override + finalize.

Pre-fix, ``OverrideRequest`` had no ``version`` field and
``FinalizeRequest`` was an empty model. Pydantic stripped any
``version`` the client sent and the service ``data.get("version") is
not None`` guard silently skipped the check — the route doc claimed
optimistic locking, the implementation never enforced it.

After the fix, both schemas mirror the existing ``ApproveRequest``
pattern: ``version: int = Field(..., ge=1)`` REQUIRED. Service
compares ``data["version"] != profile.version`` directly so a future
schema/router drift fails loud (KeyError) instead of silently
skipping.

Three corners of the contract are pinned per endpoint:

1. Missing ``version`` → 422 (Pydantic validation error).
2. Stale ``version`` → 409 (ConflictError → router maps).
3. Current ``version`` → 200 + ``profile.version`` increments by 1.
"""

import time
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient, user_info: dict) -> dict:
    res = await client.post(
        "/api/auth/login",
        data={"username": user_info["username"], "password": user_info["password"]},
    )
    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")
    token = res.cookies.get("access_token")
    if not token:
        pytest.fail("Login succeeded but access_token cookie not found")
    return {"Authorization": f"Bearer {token}"}


async def _create_lead(unit_id: int) -> int:
    ts = int(time.time() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="ADM-015 Lead",
                phone=f"09{str(ts)[-9:]}"[-10:],
                email=f"adm015_{ts}@test.com",
                source="website",
                unit_id=unit_id,
            )
            s.add(lead)
            await s.flush()
            return lead.id


async def _create_approved_profile(
    lead_id: int, citizen_id: str
) -> models.AdmissionProfile:
    """Approved-state profile is the only valid source-state for
    override; finalize tests transition through override then call
    finalize on the resulting overridden state."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="approved",
                citizen_id=citizen_id,
                academic_year=2026,
                version=1,
                applied_rules={
                    "min_gpa": 0,
                    "mandatory_docs": [],
                    "fee_status": "exempt",
                    "requires_application_fee": False,
                },
            )
            s.add(profile)
            await s.flush()
            profile_id = profile.id

        result = await s.execute(
            select(models.AdmissionProfile).where(
                models.AdmissionProfile.id == profile_id
            )
        )
        return result.scalar_one()


# ---------------------------------------------------------------------------
# OverrideRequest
# ---------------------------------------------------------------------------


class TestOverrideRequiresVersion:
    """ADM-015: ``version`` is required by Pydantic at the schema layer
    AND enforced by the service against the current row."""

    async def test_missing_version_returns_422(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "915001000001")

        admin_headers = await _login(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "ADM-015 missing-version regression",
                # version field intentionally omitted
            },
            headers=admin_headers,
        )
        assert response.status_code == 422, (
            f"Missing version must surface as Pydantic 422, got "
            f"{response.status_code}: {response.text[:300]}"
        )
        body = response.json()
        # The project's exception handler maps Pydantic 422s to a body
        # of shape ``{"detail": "Request validation failed",
        # "error_code": "VALIDATION_ERROR", "errors": [<list of err
        # dicts>]}`` — each err dict carries a ``loc`` ending with the
        # missing field name.
        errors = body.get("errors") or []
        assert any(
            "version" in (item.get("loc") or [])
            for item in errors
        ), f"422 must reference the missing ``version`` field: {body}"

    async def test_stale_version_returns_409(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "915002000002")

        admin_headers = await _login(client, admin_user_in_db)

        # Send a version that's ≥ 1 (so Pydantic ``ge=1`` accepts it)
        # but mismatches ``profile.version`` so the service raises
        # ConflictError → router maps to 409. We use ``+999`` rather
        # than ``-1`` because the seeded ``version=1`` would underflow
        # past the Pydantic constraint and surface a 422 instead of
        # the 409 we want to assert here.
        response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "ADM-015 stale-version regression",
                "version": profile.version + 999,
            },
            headers=admin_headers,
        )
        assert response.status_code == 409, (
            f"Stale version must surface as 409 Conflict, got "
            f"{response.status_code}: {response.text[:300]}"
        )
        # The error message should at least mention "version" or
        # "modified" so an end client can show a meaningful refresh
        # prompt.
        body = response.json()
        detail = (body.get("detail") or "").lower()
        assert "version" in detail or "modified" in detail

    async def test_current_version_succeeds_and_increments(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "915003000003")
        old_version = profile.version

        admin_headers = await _login(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "ADM-015 happy-path regression",
                "version": profile.version,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, (
            f"Current version must succeed, got {response.status_code}: "
            f"{response.text[:300]}"
        )
        body = response.json()
        assert body["status"] == "overridden"
        assert body["version"] == old_version + 1, (
            "Override must bump version so the next state-changing call "
            "(finalize) cannot reuse the same value"
        )


# ---------------------------------------------------------------------------
# FinalizeRequest
# ---------------------------------------------------------------------------


class TestFinalizeRequiresVersion:
    """Finalize tests transition: approved → overridden (via override)
    → enrolled (via finalize). Each finalize call uses the version
    returned from the prior override response."""

    async def _override_to_overridden(
        self,
        client: AsyncClient,
        profile: models.AdmissionProfile,
        admin_headers: dict,
    ) -> int:
        """Drive profile from approved → overridden, return the new
        version that the next finalize call must carry."""
        response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "ADM-015 setup — overridden so finalize is valid",
                "version": profile.version,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()["version"]

    async def test_missing_version_returns_422(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "915004000004")
        admin_headers = await _login(client, admin_user_in_db)
        await self._override_to_overridden(client, profile, admin_headers)

        response = await client.post(
            f"/api/admissions/{profile.id}/finalize",
            json={},  # version intentionally omitted
            headers=admin_headers,
        )
        assert response.status_code == 422, (
            f"Missing version must surface as Pydantic 422, got "
            f"{response.status_code}: {response.text[:300]}"
        )
        body = response.json()
        # See ``test_missing_version_returns_422`` on
        # OverrideRequiresVersion for the project's 422 body shape.
        errors = body.get("errors") or []
        assert any(
            "version" in (item.get("loc") or [])
            for item in errors
        ), f"422 must reference the missing ``version`` field: {body}"

    async def test_stale_version_returns_409(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "915005000005")
        admin_headers = await _login(client, admin_user_in_db)
        version_after_override = await self._override_to_overridden(
            client, profile, admin_headers,
        )

        # See ``test_stale_version_returns_409`` on OverrideRequiresVersion
        # for why we use ``+999`` rather than ``-1``: any non-equal
        # ``int >= 1`` triggers the service-layer ConflictError without
        # tripping Pydantic's ``ge=1`` constraint first.
        response = await client.post(
            f"/api/admissions/{profile.id}/finalize",
            json={"version": version_after_override + 999},
            headers=admin_headers,
        )
        assert response.status_code == 409, (
            f"Stale version must surface as 409 Conflict, got "
            f"{response.status_code}: {response.text[:300]}"
        )
        body = response.json()
        detail = (body.get("detail") or "").lower()
        assert "version" in detail or "modified" in detail

    async def test_current_version_succeeds_and_increments(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "915006000006")
        admin_headers = await _login(client, admin_user_in_db)
        version_after_override = await self._override_to_overridden(
            client, profile, admin_headers,
        )

        response = await client.post(
            f"/api/admissions/{profile.id}/finalize",
            json={"version": version_after_override},
            headers=admin_headers,
        )
        assert response.status_code == 200, (
            f"Current version must succeed, got {response.status_code}: "
            f"{response.text[:300]}"
        )
        body = response.json()
        assert body["status"] == "enrolled"
        # Finalize is the terminal transition; version is bumped by
        # the enrollment core. Just assert it moved forward, don't
        # pin the exact delta — that's enrollment's contract, not
        # this test's contract.
        assert body["version"] > version_after_override


# ---------------------------------------------------------------------------
# Schema-level validation (no DB required)
# ---------------------------------------------------------------------------


class TestSchemasRejectMissingVersion:
    """Belt-and-braces: even if a future test or caller bypasses the
    HTTP layer and constructs the schema directly, missing ``version``
    must raise a Pydantic ``ValidationError``."""

    def test_override_schema_rejects_missing_version(self):
        from pydantic import ValidationError

        from app.schemas.admission import OverrideRequest

        with pytest.raises(ValidationError) as exc_info:
            OverrideRequest(
                reason="ADM-015 schema regression — version is required",
                bypass_rules=[],
            )
        # ``loc`` should point at the missing ``version`` field
        errors = exc_info.value.errors()
        assert any("version" in (e.get("loc") or ()) for e in errors), (
            f"Validation error must mention the missing version field: {errors}"
        )

    def test_finalize_schema_rejects_missing_version(self):
        from pydantic import ValidationError

        from app.schemas.admission import FinalizeRequest

        with pytest.raises(ValidationError) as exc_info:
            FinalizeRequest()
        errors = exc_info.value.errors()
        assert any("version" in (e.get("loc") or ()) for e in errors), (
            f"Validation error must mention the missing version field: {errors}"
        )

    def test_override_schema_rejects_zero_version(self):
        """``ge=1`` constraint — version must be a positive int."""
        from pydantic import ValidationError

        from app.schemas.admission import OverrideRequest

        with pytest.raises(ValidationError):
            OverrideRequest(
                reason="ADM-015 ge=1 regression",
                version=0,
            )

    def test_finalize_schema_rejects_zero_version(self):
        from pydantic import ValidationError

        from app.schemas.admission import FinalizeRequest

        with pytest.raises(ValidationError):
            FinalizeRequest(version=0)
