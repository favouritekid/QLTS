"""ADM-014 regression: ``override_profile`` writes a durable audit row to
``entity_audit_log``, not just ``log.warning``.

Admin override is a bypass action that must be queryable for compliance
long after runtime logs rotate. The service now calls
``audit_service.log_changes`` mirroring claim/unclaim/approve, recording
old/new status, version bump, override_reason, and bypass_rules.
"""

import time

import pytest
import pytest_asyncio
from datetime import datetime, timezone
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


async def _create_lead(unit_id: int, assigned_officer_id: int | None = None) -> int:
    """Minimal lead seed for an override test (we don't go through full
    workflow — just need an approved profile attached to a lead in the
    seeded unit)."""
    ts = int(time.time() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="ADM-014 Lead",
                phone=f"09{str(ts)[-9:]}"[-10:],
                email=f"adm014_{ts}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
            )
            s.add(lead)
            await s.flush()
            return lead.id


async def _create_approved_profile(
    lead_id: int, citizen_id: str
) -> models.AdmissionProfile:
    """Create an AdmissionProfile already in 'approved' status — that's
    the only state from which override is a valid transition."""
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


class TestAdminOverrideAuditTrail:
    """ADM-014: admin override must persist to entity_audit_log."""

    async def test_override_writes_durable_audit_row(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "888800001111")

        admin_headers = await _login(client, admin_user_in_db)

        before_call = datetime.now(timezone.utc)

        response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "ADM-014 audit regression — VIP applicant override",
                "bypass_rules": ["confirmation_required", "fee_required"],
                "version": profile.version,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, (
            f"Override failed: {response.status_code} - {response.text}"
        )
        assert response.json()["status"] == "overridden"

        # Query entity_audit_log for the override row directly.
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                select(models.EntityAuditLog)
                .where(
                    models.EntityAuditLog.entity_type == "AdmissionProfile",
                    models.EntityAuditLog.entity_id == profile.id,
                    models.EntityAuditLog.action == "overridden",
                )
                .order_by(models.EntityAuditLog.created_at.desc())
            )
            rows = list(result.scalars().all())

        assert len(rows) == 1, (
            f"ADM-014: expected exactly 1 audit row for override, got {len(rows)}"
        )
        row = rows[0]

        # Actor + timestamp + source
        assert row.actor_user_id == admin_user_in_db["id"], (
            "Audit row must record the admin who fired the override"
        )
        assert row.created_at >= before_call, (
            "Audit row timestamp must be at-or-after the request start"
        )
        assert row.source == "api"
        assert row.reason and "VIP applicant override" in row.reason

        # Changes payload — status transition + override metadata
        assert row.changes is not None, (
            "Audit row must carry the structured changes JSONB"
        )
        changes = row.changes

        assert changes.get("status", {}).get("old") == "approved"
        assert changes.get("status", {}).get("new") == "overridden"

        assert changes.get("override_reason", {}).get("old") is None
        assert "VIP applicant override" in (
            changes.get("override_reason", {}).get("new") or ""
        )

        assert changes.get("bypass_rules", {}).get("new") == [
            "confirmation_required",
            "fee_required",
        ]

        # Version was bumped
        assert (
            changes.get("version", {}).get("new")
            == changes.get("version", {}).get("old") + 1
        )

        assert changes.get("overridden_by_id", {}).get("new") == admin_user_in_db["id"]

    async def test_override_with_empty_bypass_rules_still_audits(
        self,
        client: AsyncClient,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """``bypass_rules`` is optional — empty list (or missing) must
        still produce a clean audit row. Catches a regression where the
        helper coerces None → empty list rather than crashing."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await _create_lead(unit_id)
        profile = await _create_approved_profile(lead_id, "888800002222")

        admin_headers = await _login(client, admin_user_in_db)

        response = await client.post(
            f"/api/admissions/{profile.id}/override",
            json={
                "reason": "ADM-014 — bypass_rules omitted, audit must still run",
                "version": profile.version,
            },
            headers=admin_headers,
        )
        assert response.status_code == 200, (
            f"Override failed: {response.status_code} - {response.text}"
        )

        async with AsyncSessionLocal() as s:
            result = await s.execute(
                select(models.EntityAuditLog).where(
                    models.EntityAuditLog.entity_type == "AdmissionProfile",
                    models.EntityAuditLog.entity_id == profile.id,
                    models.EntityAuditLog.action == "overridden",
                )
            )
            row = result.scalars().first()

        assert row is not None
        assert row.changes.get("bypass_rules", {}).get("new") == []
