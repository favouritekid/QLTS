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


# =========================================================================
# ADM-026 review (Major #2): concurrent-approve race
# =========================================================================


class TestQuotaConcurrentRace:
    """
    ADM-026 lock contract: ``with_for_update()`` on OfferingAcademicInfo
    must serialize concurrent approves so the cap holds even when two
    transactions race against the same offering at boundary.
    """

    async def test_concurrent_approves_at_cap_only_one_succeeds(
        self, setup_test_database, seed_lead_dependencies
    ):
        """
        Cap=1, currently 0 approved. Two SEPARATE sessions each try to
        approve their own profile in parallel via ``asyncio.gather``.
        Without the FOR UPDATE row lock both would see ``count<quota`` and
        succeed → cap blown by 1. With the lock, they serialize and the
        second sees ``count=1`` and raises.
        """
        import asyncio

        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="race",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="race_mgr"
        )
        pid_a = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000200", status="submitted"
        )
        pid_b = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000201", status="submitted"
        )

        # Each task runs in its OWN session/transaction — must not share
        # AsyncSession across asyncio.gather (memory: async-session-gather).
        async def _try_approve(pid: int) -> str:
            try:
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        profile = await _profile_with_lead(session, pid)
                        await admission_service._assert_quota_or_bypass(
                            session,
                            profile,
                            manager,
                            bypass_quota=False,
                            bypass_reason=None,
                            transition="approve",
                        )
                        # Mimic the approve mutation by occupying a seat
                        # within the same locked txn — the helper above
                        # already locked OfferingAcademicInfo, so this
                        # row update commits the seat consumption.
                        profile.status = "approved"
                        await session.flush()
                return "ok"
            except BusinessRuleViolation:
                return "blocked"

        result_a, result_b = await asyncio.gather(
            _try_approve(pid_a), _try_approve(pid_b)
        )
        outcomes = sorted([result_a, result_b])
        # Exactly one succeeds, exactly one is blocked.
        assert outcomes == ["blocked", "ok"], (
            f"Concurrency contract broken: outcomes={outcomes}"
        )

        # DB invariant: at most ONE of the two profiles ended in 'approved'.
        async with AsyncSessionLocal() as session:
            approved = (
                await session.execute(
                    select(models.AdmissionProfile.id).where(
                        models.AdmissionProfile.id.in_([pid_a, pid_b]),
                        models.AdmissionProfile.status == "approved",
                    )
                )
            ).scalars().all()
            assert len(approved) == 1


# =========================================================================
# ADM-026 review (Round 2): bulk autoflush-counted overflow
# =========================================================================


class TestQuotaBulkAutoflush:
    """
    Bulk approve must observe IN-BATCH inserts when checking the cap.
    ``_assert_quota_or_bypass`` re-runs ``_count_quota_occupying_profiles``
    for every item; that count must see the prior items' status updates
    that were flushed earlier in the same batch (audit_service.log_audit
    + sync_lead_from_admission both call ``db.flush()`` per item, even
    though the sessionmaker has ``autoflush=False``).

    Failure mode if this regresses: cap=2, 0 currently approved, batch
    of 3 → all 3 approved (cap blown by 1). This test pins the contract
    by asserting per-item outcomes AND by introspecting the per-item
    error message to prove the count progression actually saw the
    in-batch inserts.
    """

    async def test_bulk_overflow_detected_via_in_batch_autoflush(
        self, setup_test_database, seed_lead_dependencies
    ):
        seeds = await _seed_offering_with_quota(
            quota=2,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="autoflush",
        )
        manager = await _make_user(
            role=UserRole.MANAGER,
            unit_id=seeds["unit_id"],
            suffix="autoflush_mgr",
        )
        # Start clean: NO existing approved profiles. Items 1+2 must
        # succeed (count goes 0→1→2 within the batch); item 3 must fail
        # with the count_before reflecting items 1+2.
        pids = []
        for i in range(3):
            pids.append(
                await _seed_lead_and_profile(
                    seeds=seeds,
                    citizen_id=f"20000000040{i}",
                    status="submitted",
                )
            )

        async with AsyncSessionLocal() as session:
            result, _cb = await admission_service.bulk_approve(
                db=session,
                items=[{"profile_id": pid, "version": 1} for pid in pids],
                approver=manager,
                notes="Autoflush contract test",
            )
            await session.commit()

        # Items 1+2 succeed, item 3 fails because in-batch count saw
        # items 1+2 already approved.
        assert result["success_count"] == 2, (
            f"Autoflush regression: expected 2 successes, got "
            f"{result['success_count']}. Bulk likely missing per-item flush "
            f"between items — item 3 saw count=0 instead of count=2."
        )
        assert result["failed_count"] == 1
        assert pids[2] in result["failed_ids"]

        # Stronger assertion: error message for item 3 mentions "2/2" so
        # we can prove the count_before observed the in-batch inserts.
        err_msg = result["errors"][pids[2]]
        assert "2/2" in err_msg or "đã đầy" in err_msg.lower(), (
            f"Item 3 error didn't reference cap-full state: {err_msg!r}"
        )

        # DB invariant: exactly 2 of the 3 profiles ended in 'approved'.
        async with AsyncSessionLocal() as session:
            approved = (
                await session.execute(
                    select(models.AdmissionProfile.id).where(
                        models.AdmissionProfile.id.in_(pids),
                        models.AdmissionProfile.status == "approved",
                    )
                )
            ).scalars().all()
            assert len(approved) == 2


# =========================================================================
# ADM-026 review (Round 2): quota=0 means "offering closed", not unlimited
# =========================================================================


class TestQuotaZeroBlocks:
    """
    Schema currently allows annual_admission_quota = 0 (ge=0). Conflating
    that with quota = NULL (unlimited) would let staff admit unbounded
    students into a deliberately closed cohort. ADM-026 round-2 fix:
    quota=0 blocks ALL approves; only NULL means unlimited. Admin bypass
    with valid reason still works as a documented escape hatch.
    """

    async def test_quota_zero_blocks_approve_without_bypass(
        self, setup_test_database, seed_lead_dependencies
    ):
        seeds = await _seed_offering_with_quota(
            quota=0,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="zero_block",
        )
        manager = await _make_user(
            role=UserRole.MANAGER,
            unit_id=seeds["unit_id"],
            suffix="zero_block_mgr",
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000600", status="submitted"
        )
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(BusinessRuleViolation):
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        manager,
                        bypass_quota=False,
                        bypass_reason=None,
                        transition="approve",
                    )

    async def test_quota_zero_admin_bypass_still_works(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Admin bypass with valid reason is the documented escape."""
        seeds = await _seed_offering_with_quota(
            quota=0,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="zero_bypass",
        )
        admin = await _make_user(
            role=UserRole.ADMIN,
            unit_id=seeds["unit_id"],
            suffix="zero_bypass_admin",
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000610", status="submitted"
        )
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # Should NOT raise — admin override on quota=0 cohort.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    admin,
                    bypass_quota=True,
                    bypass_reason=(
                        "Cohort closed (quota=0) but admit per Hiệu Trưởng "
                        "directive 2026-04-29."
                    ),
                    transition="approve",
                )

    async def test_quota_null_remains_unlimited(
        self, setup_test_database, seed_lead_dependencies
    ):
        """quota=None still means unlimited (no enforcement)."""
        seeds = await _seed_offering_with_quota(
            quota=None,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="null_unlimited",
        )
        manager = await _make_user(
            role=UserRole.MANAGER,
            unit_id=seeds["unit_id"],
            suffix="null_mgr",
        )
        # Even with several already approved, quota=None lets next pass.
        for i in range(3):
            await _seed_lead_and_profile(
                seeds=seeds,
                citizen_id=f"20000000062{i}",
                status="approved",
            )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000625", status="submitted"
        )
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                # No raise — quota=None means unlimited.
                await admission_service._assert_quota_or_bypass(
                    session,
                    profile,
                    manager,
                    bypass_quota=False,
                    bypass_reason=None,
                    transition="approve",
                )


# =========================================================================
# ADM-026 review (Major #3): denied bypass attempts produce audit rows
# =========================================================================


class TestQuotaDeniedAudit:
    """
    Compliance contract: any attempt to override the cap — even a denied
    one — must leave an entity_audit_log row. The denial path raises and
    the caller's transaction rolls back, so the audit row is written via
    a fresh session inside ``_audit_quota_bypass_denied``.
    """

    async def test_manager_denial_writes_audit_row(
        self, setup_test_database, seed_lead_dependencies
    ):
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="denied_role",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="denied_mgr"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000300", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000301", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(PermissionDeniedError):
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        manager,
                        bypass_quota=True,
                        bypass_reason=(
                            "Trưởng phòng cần ghi đè cho kỳ này lý do hợp lệ"
                        ),
                        transition="approve",
                    )

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.action == "quota_bypass_denied_role",
                        models.EntityAuditLog.entity_id == pid,
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].actor_user_id == manager.id

    async def test_admin_short_reason_writes_audit_row(
        self, setup_test_database, seed_lead_dependencies
    ):
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="denied_reason",
        )
        admin = await _make_user(
            role=UserRole.ADMIN, unit_id=seeds["unit_id"], suffix="denied_admin"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000310", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000311", status="submitted"
        )

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(ValidationError):
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        admin,
                        bypass_quota=True,
                        bypass_reason="ngắn",  # <20 chars
                        transition="approve",
                    )

        async with AsyncSessionLocal() as session:
            rows = (
                await session.execute(
                    select(models.EntityAuditLog).where(
                        models.EntityAuditLog.action == "quota_bypass_denied_reason",
                        models.EntityAuditLog.entity_id == pid,
                    )
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].actor_user_id == admin.id


# =========================================================================
# Test-gap follow-ups: Pydantic 422, boundary 1/1+1, legacy fallback
# =========================================================================


class TestQuotaPydanticValidation:
    """Schema-layer validation (Pydantic 422) for the bypass pair.

    These are pure-sync schema checks. The module-level ``pytestmark =
    pytest.mark.asyncio`` paints them with the asyncio marker, which
    pytest-asyncio warns about for non-async functions. The warning is
    cosmetic — tests still execute correctly because pytest-asyncio only
    cares when the test body needs awaiting.
    """

    def test_bypass_quota_true_short_reason_raises_at_schema_level(self):
        """ValueError at schema parse — FastAPI maps to 422 Unprocessable."""
        from app.schemas.admission import ApproveRequest

        with pytest.raises(ValueError) as exc_info:
            ApproveRequest(
                version=1,
                bypass_quota=True,
                bypass_reason="quá ngắn",
            )
        assert "20" in str(exc_info.value)

    def test_bypass_quota_false_no_reason_ok(self):
        """Bypass off → reason optional → schema accepts."""
        from app.schemas.admission import ApproveRequest

        req = ApproveRequest(version=1)
        assert req.bypass_quota is False
        assert req.bypass_reason is None

    def test_bypass_quota_true_valid_reason_ok(self):
        from app.schemas.admission import ApproveRequest

        req = ApproveRequest(
            version=1,
            bypass_quota=True,
            bypass_reason="Đặc cách tuyển sinh ngày 2026-04-29 do Hiệu Trưởng",
        )
        assert req.bypass_quota is True


class TestQuotaBoundary:
    """Edge boundary: occupied count exactly equals quota."""

    async def test_one_of_one_blocks_next_attempt(
        self, setup_test_database, seed_lead_dependencies
    ):
        """Cap=1, count=1 → next approve raises (sharper than 2/2 case)."""
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="boundary11",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="boundary11_mgr"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000400", status="approved"
        )
        pid = await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000401", status="submitted"
        )
        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(BusinessRuleViolation):
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        manager,
                        bypass_quota=False,
                        bypass_reason=None,
                        transition="approve",
                    )


class TestQuotaLegacyFallback:
    """Legacy profile path: applied_rules.academic_info_id missing."""

    async def test_legacy_profile_falls_back_to_offering_academic_year(
        self, setup_test_database, seed_lead_dependencies
    ):
        """
        Profile snapshotted before academic_info_id was added still gets
        enforced by the (lead.offering_id, profile.academic_year) lookup.
        """
        seeds = await _seed_offering_with_quota(
            quota=1,
            seed_unit_id=seed_lead_dependencies["unit_id"],
            seed_major_program_id=seed_lead_dependencies["major_program_id"],
            suffix="legacy",
        )
        manager = await _make_user(
            role=UserRole.MANAGER, unit_id=seeds["unit_id"], suffix="legacy_mgr"
        )
        await _seed_lead_and_profile(
            seeds=seeds, citizen_id="200000000500", status="approved"
        )
        # Legacy profile: applied_rules has no academic_info_id field.
        async with AsyncSessionLocal() as session:
            async with session.begin():
                lead = models.Lead(
                    full_name="Legacy applicant",
                    phone="0900000501",
                    email="legacy501@test.com",
                    source="website",
                    unit_id=seeds["unit_id"],
                    offering_id=seeds["offering_id"],
                )
                session.add(lead)
                await session.flush()
                legacy = models.AdmissionProfile(
                    lead_id=lead.id,
                    status="submitted",
                    citizen_id="200000000501",
                    academic_year=seeds["academic_year"],
                    version=1,
                    applied_rules={
                        "min_gpa": 0,
                        "mandatory_docs": [],
                        # No academic_info_id — legacy snapshot.
                    },
                )
                session.add(legacy)
                await session.flush()
                pid = legacy.id

        async with AsyncSessionLocal() as session:
            async with session.begin():
                profile = await _profile_with_lead(session, pid)
                with pytest.raises(BusinessRuleViolation):
                    await admission_service._assert_quota_or_bypass(
                        session,
                        profile,
                        manager,
                        bypass_quota=False,
                        bypass_reason=None,
                        transition="approve",
                    )
