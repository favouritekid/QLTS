"""PR-1 (2026-05-28) — Choice engine quota guard concurrent serialization.

Single concurrent anchor: two cascade publishes on the SAME path with
admit_quota=1 must serialize via the SELECT FOR UPDATE locks inside
`check_choice_admit_capacity` — exactly 1 admit, exactly 1 waitlist.

Without PR-1 locks (Tier 1 OfferingAcademicInfo + Tier 2 AdmissionPath
FOR UPDATE), two concurrent cascades both read count_before=0, both
write decision='admitted' → over-admit by 1.

Test calls `evaluate_cascade()` directly (NOT via HTTP) for two reasons:
  1. asyncio.gather on HTTP would need 2 client tasks + serialized
     session pool; direct service call is simpler and exercises the
     same lock paths (the lock is in the helper, NOT the router).
  2. Forces `_evaluate_single_choice` to return 'admitted' via
     monkeypatch — isolates the capacity gate from scoring infra
     (mirrors deterministic cascade tests in test_phase3_pr3c_routers_
     integration.py).

Mirror pattern: `tests/api/test_admission_bulk_assign_concurrency.py`
`test_bulk_assign_locks_and_writes_accurate_audit_chain` — anchors
business invariant (1 admit + 1 waitlist), NOT the SQL emitted. A
future change that drops `.with_for_update()` would let both cascades
admit → invariant breaks → test fails.

Execution context per `local-test-oneoff-container-pattern` memory:
heavy/destructive concurrent tests MUST run in a one-off backend
container with explicit `-e DATABASE_URL=...qlts_test` override and
main stack stopped. See plan v4 sprint test gate section.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.integration


# ============================================================================
# Seed helpers (inlined — fixture file pattern mirror test_phase3_pr3c_*)
# ============================================================================


@pytest_asyncio.fixture
async def two_profiles_one_seat(seed_lead_dependencies: dict) -> dict:
    """Seed scenario: 1 path admit_quota=1 + 2 reviewing profiles each with
    1 choice on that path. Cascade publishes both concurrently → only 1
    should land admit; the other must waitlist via the lock.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
                is_active=True,
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                # Plenty so Tier 1 doesn't fire; Tier 2 path cap is the gate
                annual_admission_quota=100,
                tuition_fee_per_year=Decimal("1000000"),
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )
            method = models.AdmissionMethod(
                code=f"PR1CC_{ts}",
                name=f"PR-1 concurrent method {ts}",
                requires_subject_scores=False,
                requires_gpa=False,
                is_active=True,
            )
            s.add(method); await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                status="active",
                admit_quota=1,       # PR-1 gate setpoint
                round_quota=10,
            )
            s.add(path); await s.flush()

            sg = models.SubjectGroup(
                code=f"GCC{ts}"[:20], name=f"Grp CC {ts}",
            )
            s.add(sg); await s.flush()
            subj = models.Subject(
                code=f"SCC{ts}"[:20], name_vi=f"Subj CC {ts}",
                max_score=Decimal("10.00"),
            )
            s.add(subj); await s.flush()
            s.add(models.SubjectGroupSubject(
                subject_group_id=sg.id, subject_id=subj.id, position=1,
            )); await s.flush()
            config = models.PathSubjectGroupConfig(
                admission_path_id=path.id,
                subject_group_id=sg.id,
                min_score=Decimal("0.0"),
            )
            s.add(config); await s.flush()

            # Two profiles, each with offering_id matched for Tier 1 count
            profile_ids = []
            for idx in range(2):
                lead = models.Lead(
                    full_name=f"Concurrent lead {ts}_{idx}",
                    phone=f"097{ts:07d}"[:10][:9] + str(idx),
                    unit_id=seed_lead_dependencies["unit_id"],
                    pipeline_stage_id=seed_lead_dependencies["stage_id"],
                    source="walkin",
                    offering_id=offering.id,
                )
                s.add(lead); await s.flush()
                profile = models.AdmissionProfile(
                    lead_id=lead.id,
                    citizen_id=f"7{ts:08d}{idx}"[:12],
                    status="reviewing",
                    applied_rules={"admission_path_id": path.id},
                    academic_year=2026,
                    uses_choice_engine=True,
                )
                s.add(profile); await s.flush()
                s.add(models.AdmissionProfileChoice(
                    admission_profile_id=profile.id,
                    admission_path_id=path.id,
                    path_subject_group_config_id=config.id,
                    display_order=1,
                    decision="pending",
                )); await s.flush()
                profile_ids.append(profile.id)

            return {
                "path_id": path.id,
                "config_id": config.id,
                "offering_id": offering.id,
                "academic_info_id": ai.id,
                "profile_ids": profile_ids,
            }


async def _cascade_in_own_session(profile_id: int) -> str:
    """Run evaluate_cascade in an isolated session and return final_status."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import selectinload as sa_sl
    from app.services import admission_choice_engine_service as engine_mod

    async with AsyncSessionLocal() as s:
        try:
            stmt = (
                sa_select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
                .options(
                    sa_sl(models.AdmissionProfile.lead),
                    sa_sl(models.AdmissionProfile.choices)
                    .selectinload(models.AdmissionProfileChoice.admission_path)
                    .selectinload(models.AdmissionPath.academic_info),
                    sa_sl(models.AdmissionProfile.choices)
                    .selectinload(models.AdmissionProfileChoice.admission_path)
                    .selectinload(models.AdmissionPath.admission_method),
                    sa_sl(models.AdmissionProfile.choices)
                    .selectinload(models.AdmissionProfileChoice.admission_path)
                    .selectinload(models.AdmissionPath.admission_round),
                )
            )
            profile = (await s.execute(stmt)).scalar_one()
            result, _cb = await engine_mod.evaluate_cascade(s, profile)
            await s.commit()
            return result.final_status
        except Exception:
            await s.rollback()
            raise


@pytest.mark.asyncio
async def test_cascade_concurrent_two_profiles_one_seat(
    monkeypatch, two_profiles_one_seat: dict,
):
    """⭐ Concurrent anchor: 2 cascades on same path admit_quota=1 must
    serialize via SELECT FOR UPDATE locks in check_choice_admit_capacity.

    With PR-1 locks:
      - Caller A acquires path lock first → counts 0 → admits → commits
      - Caller B blocks on path lock → after A commits, counts 1 →
        capacity blocks → waitlists → commits
      - Final: exactly 1 admit + 1 waitlist (deterministic per-call
        ordering OS-dependent, but invariant is the same)

    Without locks (regression):
      - Both callers count 0 → both write decision='admitted' → final
        DB has 2 admitted choices on path → admit_quota=1 BLOWN
      - The path admit count post-cascade would be 2 instead of 1,
        breaking quota invariant

    Force-admit via monkeypatch isolates the cascade's NEW PR-1 capacity
    gate from scoring infrastructure. Mirror approach used by
    deterministic cascade tests in
    test_phase3_pr3c_routers_integration.py.
    """
    from app.services import admission_choice_engine_service as engine_mod

    # Force every NV to evaluate as 'admitted' so only capacity gate decides
    def _force_admit(profile, choice, priority_bonus=None):
        return "admitted", None, []
    monkeypatch.setattr(engine_mod, "_evaluate_single_choice", _force_admit)

    seed = two_profiles_one_seat
    p_a, p_b = seed["profile_ids"]

    # Concurrent cascade — race for the single seat
    results = await asyncio.gather(
        _cascade_in_own_session(p_a),
        _cascade_in_own_session(p_b),
        return_exceptions=True,
    )

    # Both should return without exception (lock serializes; capacity
    # gate produces waitlist for loser, not exception)
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert not exceptions, (
        f"Concurrent cascade must serialize without exception; "
        f"got {len(exceptions)} exception(s). FIRST: {exceptions[0]!r}. "
        f"This indicates the FOR UPDATE lock was bypassed (PR-1 regression)."
    )

    # Exactly 1 admit + 1 waitlist final_status
    sorted_results = sorted(results)
    assert sorted_results == ["admitted", "waitlisted"], (
        f"Quota=1 + 2 cascades must produce exactly 1 admit + 1 waitlist; "
        f"got {results}. Without lock both could admit (race), causing "
        f"['admitted', 'admitted'] and blowing the cap."
    )

    # DB invariant: exactly 1 choice admitted on the path (the cap)
    from sqlalchemy import func, select as sa_select
    async with AsyncSessionLocal() as s:
        admitted_count = int((await s.execute(
            sa_select(func.count(models.AdmissionProfileChoice.id)).where(
                models.AdmissionProfileChoice.admission_path_id == seed["path_id"],
                models.AdmissionProfileChoice.decision == "admitted",
            )
        )).scalar_one() or 0)
    assert admitted_count == 1, (
        f"Path admit_quota=1 invariant: exactly 1 choice must be admitted; "
        f"got {admitted_count}. >1 = lock bypassed; <1 = both waitlisted "
        f"(unexpected deadlock or both lost race)."
    )
