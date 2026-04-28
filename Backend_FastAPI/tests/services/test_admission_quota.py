"""
ADM-026: Quota enforcement tests.

Validates ``_assert_quota_or_bypass`` semantics for approve / bulk_approve /
finalize. Hits the real DB via ``AsyncSessionLocal`` (matches existing
``test_admission_workflow.py`` pattern).

Cases covered:
1. Under-cap approve → passes silently.
2. At-cap approve without bypass → ``BusinessRuleViolation``.
3. At-cap approve with admin bypass + valid reason → passes + audit row.
4. At-cap approve with manager bypass → ``PermissionDeniedError``.
5. At-cap approve with admin bypass but short reason → ``ValidationError``.
6. Bulk approve mixed: under-cap items succeed, over-cap third raises into
   ``errors`` map without rolling back the batch.
7. Finalize on already-approved profile → passes (already in count, net-zero).
8. Quota=None (legacy / unconfigured) → enforcement skipped.
9. Withdrawn profile does NOT count toward cap.
"""

import pytest
from sqlalchemy import select

from app import models
from app.core.constants import UserRole
from app.database import AsyncSessionLocal
from app.services import admission_service
from app.utils.exceptions import (
    BusinessRuleViolation,
    PermissionDeniedError,
    ValidationError,
)


pytestmark = pytest.mark.asyncio


# =========================================================================
# Test fixtures (reuse seed_lead_dependencies for unit + major)
# =========================================================================


async def _seed_offering_with_quota(
    *,
    quota: int | None,
    seed_major_program_id: int,
    seed_unit_id: int,
    academic_year: int = 2026,
    suffix: str = "",
) -> dict:
    """
    Create a unique ProgramOffering + OfferingAcademicInfo for one test.
    Reuses unit + major seeded by ``seed_lead_dependencies`` so each test
    case isolates only on the offering+academic_info rows the quota helper
    actually reads.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            offering = models.ProgramOffering(
                offering_type=f"ADM-026 Offering {suffix}",
                program_id=seed_major_program_id,
                is_active=True,
            )
            session.add(offering)
            await session.flush()

            academic_info = models.OfferingAcademicInfo(
                academic_year=academic_year,
                annual_admission_quota=quota,
                offering_id=offering.id,
                is_published=True,
            )
            session.add(academic_info)
            await session.flush()

            return {
                "unit_id": seed_unit_id,
                "offering_id": offering.id,
                "academic_info_id": academic_info.id,
                "academic_year": academic_year,
            }


async def _seed_lead_and_profile(
    *,
    seeds: dict,
    citizen_id: str,
    status: str,
    assigned_officer_id: int | None = None,
) -> int:
    """Create a lead + profile in given status for a seeded offering. Returns profile_id."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Quota Test {citizen_id}",
                phone=f"09{citizen_id[-9:]}",
                email=f"q{citizen_id}@test.com",
                source="website",
                unit_id=seeds["unit_id"],
                offering_id=seeds["offering_id"],
                assigned_officer_id=assigned_officer_id,
            )
            session.add(lead)
            await session.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                status=status,
                citizen_id=citizen_id,
                academic_year=seeds["academic_year"],
                version=1,
                applied_rules={
                    "academic_info_id": seeds["academic_info_id"],
                    "min_gpa": 0,
                    "mandatory_docs": [],
                },
            )
            session.add(profile)
            await session.flush()
            return profile.id


async def _make_user(
    *,
    role: str,
    unit_id: int,
    suffix: str,
) -> models.User:
    """Create a test user. Caller passes a unique ``suffix`` per case."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            user = models.User(
                username=f"adm026_{suffix}",
                email=f"adm026_{suffix}@test.com",
                full_name=f"ADM-026 {suffix}",
                password_hash="x",
                role=role,
                unit_id=unit_id,
            )
            session.add(user)
            await session.flush()
            # Detach so callers can use the instance after the session closes.
            session.expunge(user)
            return user


async def _reload_profile(profile_id: int) -> models.AdmissionProfile:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one()


async def _profile_with_lead(session, profile_id: int) -> models.AdmissionProfile:
    """Eager-load lead so the helper's offering-id fallback works."""
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))
    )
    return result.scalar_one()


# =========================================================================
# Tests
# =========================================================================


class TestQuotaHelper:
    """Direct unit tests of ``_assert_quota_or_bypass``."""

    async def test_under_cap_passes(self, setup_test_database, seed_lead_dependencies):
        """Cap=2, currently 0 approved → next approve attempt allowed under cap."""
        seeds = await _seed_offering_with_quota(
            quota=2,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="under",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="under_admin"
        )
        # Profile is in submitted (not yet occupying a seat).
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000001", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # No raise expected.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    admin,
                    bypass_quota=False,
                    bypass_reason=None,
                    transition="approve",
                )

    async def test_at_cap_blocks_without_bypass(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Cap=2, 2 already approved → 3rd approve raises BusinessRuleViolation."""
        seeds = await _seed_offering_with_quota(
            quota=2,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="atcap",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="atcap_mgr"
        )
        # Two already-approved profiles fill the quota.
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000010", status="approved"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000011", status="approved"
        )
        # Third profile, still in submitted, attempting to approve.
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000012", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(BusinessRuleViolation) as exc_info:
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        manager,
                        bypass_quota=False,
                        bypass_reason=None,
                        transition="approve",
                    )
                assert "chỉ tiêu" in str(exc_info.value).lower()

    async def test_admin_bypass_passes_and_writes_audit(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Cap=1, 1 approved, admin bypass with valid reason → passes + audit row."""
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="bypass",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="bypass_admin"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000020", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000021", status="submitted"
        )

        reason = "Late transfer applicant approved by Tổng Giám Đốc per email 2026-04-28."
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # Should NOT raise.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    admin,
                    bypass_quota=True,
                    bypass_reason=reason,
                    transition="approve",
                )

        # Verify audit row landed in entity_audit_log.
        async with AsyncSessionLocal() as session:
            audit_rows = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.entity_type == "AdmissionProfile",
                        models.EntityAuditLog.entity_id == pid,
                        models.EntityAuditLog.action == "quota_bypassed",
                    )
                )
            ).scalars().all()
            assert len(audit_rows) == 1, f"expected 1 audit row, got {len(audit_rows)}"
            row = audit_rows[0]
            assert row.actor_user_id == admin.id
            assert row.reason == reason
            assert row.changes is not None
            assert row.changes["quota"]["new"] == 1
            assert row.changes["enrolled_count_before"]["new"] == 1
            assert row.changes["enrolled_count_after"]["new"] == 2
            assert row.changes["transition"]["new"] == "approve"

    async def test_manager_bypass_rejected(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Manager attempting bypass → PermissionDeniedError (admin-only per Q12 Option B)."""
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="mgrbypass",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="mgr_bypass"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000030", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000031", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(PermissionDeniedError) as exc_info:
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        manager,
                        bypass_quota=True,
                        bypass_reason="Manager attempting bypass with valid-looking reason that is long enough",
                        transition="approve",
                    )
                assert "admin" in str(exc_info.value).lower()

    async def test_admin_bypass_short_reason_rejected(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Admin bypass with reason <20 chars → ValidationError at service layer."""
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="shortrsn",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="short_admin"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000040", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000041", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(ValidationError) as exc_info:
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        admin,
                        bypass_quota=True,
                        bypass_reason="too short",
                        transition="approve",
                    )
                assert "20" in str(exc_info.value)

    async def test_quota_unconfigured_skipped(
        self, setup_test_database, seed_lead_dependencies
    ):
        """quota=None → enforcement skipped (treat as unlimited)."""
        seeds = await _seed_offering_with_quota(
            quota=None,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="nullq",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="nullq_mgr"
        )
        # Even with 5 approved profiles, no enforcement.
        for i in range(5):
            await _seed_lead_and_profile(
                seeds=seeds, citizen_id=f"20000000005{i}", status="approved"
            )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000059", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # No raise expected.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    manager,
                    bypass_quota=False,
                    bypass_reason=None,
                    transition="approve",
                )

    async def test_withdrawn_does_not_count(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Withdrawn profiles must NOT occupy a quota seat."""
        seeds = await _seed_offering_with_quota(
            quota=2,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="withdrawn",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="wdr_mgr"
        )
        # 1 approved + 5 withdrawn → only 1 occupies seat. Cap is 2 → next approve allowed.
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000060", status="approved"
        )
        for i in range(5):
            await _seed_lead_and_profile(
                seeds=seeds, citizen_id=f"20000000006{i + 1}", status="withdrawn"
            )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000067", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # No raise: only 1 occupies seat, cap=2, +1 = 2 ≤ 2.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    manager,
                    bypass_quota=False,
                    bypass_reason=None,
                    transition="approve",
                )

    async def test_finalize_on_already_approved_passes(
        self, setup_test_database, seed_lead_dependencies
    ):
        """
        Profile already counted (status=overridden) → finalize transition is
        net-zero, count stays within cap. Happy path for finalize gate.
        """
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="finalok",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="finalok_admin"
        )
        # Single overridden profile occupying the only seat. Finalize → enrolled.
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000070", status="overridden"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # No raise: profile already in count (excluded as self),
                # count_before=0, count_after=count_before, within cap=1.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    admin,
                    bypass_quota=False,
                    bypass_reason=None,
                    transition="finalize",
                )


class TestQuotaIntegrationApprove:
    """End-to-end via ``approve_profile`` service entry."""

    async def test_approve_blocked_at_cap(
        self, setup_test_database, seed_lead_dependencies
    ):
        """
        Approve via service path: cap=1, 1 already approved → ``approve_profile``
        propagates the BusinessRuleViolation up.
        """
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="aprblk",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="aprblk_mgr"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000090", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds,
            citizen_id="200000000091",
            status="submitted",
            assigned_officer_id=None,
        )

        async with AsyncSessionLocal() as session:
            with pytest.raises(BusinessRuleViolation):
                await admission_service.approve_profile(
                    db=session,
                    profile_id=pid,
                    approver=manager,
                    data={"version": 1, "notes": None},
                )

    async def test_approve_admin_bypass_succeeds(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Admin can override with bypass_quota+bypass_reason ≥20 chars."""
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="aprbypass",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="aprbypass_admin"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000100", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds,
            citizen_id="200000000101",
            status="submitted",
            assigned_officer_id=None,
        )

        async with AsyncSessionLocal() as session:
            profile, _cb = await admission_service.approve_profile(
                db=session,
                profile_id=pid,
                approver=admin,
                data={
                    "version": 1,
                    "notes": None,
                    "bypass_quota": True,
                    "bypass_reason": "Đặc cách theo công văn Tổng Giám Đốc 2026-04-28 cho thí sinh chuyển trường muộn",
                },
            )
            await session.commit()

        reloaded = await _reload_profile(pid)
        assert reloaded.status == "approved"

        async with AsyncSessionLocal() as session:
            audit_rows = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.entity_type == "AdmissionProfile",
                        models.EntityAuditLog.entity_id == pid,
                        models.EntityAuditLog.action == "quota_bypassed",
                    )
                )
            ).scalars().all()
            assert len(audit_rows) == 1


class TestQuotaIntegrationBulkApprove:
    """End-to-end via ``bulk_approve``."""

    async def test_bulk_partial_over_cap(
        self, setup_test_database, seed_lead_dependencies
    ):
        """
        Cap=2, 0 approved. Bulk submit 3 profiles. First 2 succeed; 3rd
        lands in errors map without rolling back the batch.
        """
        seeds = await _seed_offering_with_quota(
            quota=2,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="bulkpartial",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="bulk_mgr"
        )
        pid1 = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000110", status="submitted"
        )
        pid2 = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000111", status="submitted"
        )
        pid3 = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000112", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            result, _cb = await admission_service.bulk_approve(
                db=session,
                items=[
                    {"profile_id": pid1, "version": 1},
                    {"profile_id": pid2, "version": 1},
                    {"profile_id": pid3, "version": 1},
                ],
                approver=manager,
                notes="Batch test",
            )
            await session.commit()

        assert result["success_count"] == 2
        assert result["failed_count"] == 1
        assert pid3 in result["failed_ids"]
        assert "chỉ tiêu" in result["errors"][pid3].lower()

        # First two are approved, third still submitted.
        for pid, expected_status in [
            (pid1, "approved"),
            (pid2, "approved"),
            (pid3, "submitted"),
        ]:
            reloaded = await _reload_profile(pid)
            assert reloaded.status == expected_status, (
                f"profile {pid} expected {expected_status}, got {reloaded.status}"
            )

    async def test_bulk_per_item_admin_bypass_mixes_with_normal(
        self, setup_test_database, seed_lead_dependencies
    ):
        """
        Cap=1, 1 already approved. Bulk submit 2 items: first without
        bypass (fails), second with admin bypass (succeeds) → audit row
        for second only.
        """
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="bulkmixed",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="bulkmix_admin"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000120", status="approved"
        )
        pid_no_bypass = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000121", status="submitted"
        )
        pid_bypass = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000122", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            result, _cb = await admission_service.bulk_approve(
                db=session,
                items=[
                    {"profile_id": pid_no_bypass, "version": 1},
                    {
                        "profile_id": pid_bypass,
                        "version": 1,
                        "bypass_quota": True,
                        "bypass_reason": "Bulk override per email policy 2026-04-28 from Tổng Giám Đốc",
                    },
                ],
                approver=admin,
                notes=None,
            )
            await session.commit()

        assert pid_no_bypass in result["failed_ids"]
        assert pid_bypass not in result["failed_ids"]
        no_bypass_profile = await _reload_profile(pid_no_bypass)
        bypass_profile = await _reload_profile(pid_bypass)
        assert no_bypass_profile.status == "submitted"
        assert bypass_profile.status == "approved"

        async with AsyncSessionLocal() as session:
            audit_count = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.action == "quota_bypassed",
                        models.EntityAuditLog.entity_id.in_([pid_no_bypass, pid_bypass]),
                    )
                )
            ).scalars().all()
            assert len(audit_count) == 1
            assert audit_count[0].entity_id == pid_bypass
