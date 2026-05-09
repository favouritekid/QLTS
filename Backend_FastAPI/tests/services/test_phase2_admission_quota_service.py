"""Service-level tests for AdmissionQuotaService (Phase 2 v8.2 PR-2B v2).

Covers Tier 1 chain (per academic_info scope) + Tier 2 path invariant.

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_tier1_chain_per_academic_info_scope`` — MANDATORY per Q2 v8.2
- ``test_admission_path_quota_fields_persist_independent_of_round_metadata``
- ``test_tier2_invariant_admit_le_round``
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.services.admission_quota_service import AdmissionQuotaService
from app.utils.exceptions import BusinessRuleViolation, ResourceNotFoundError


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def quota_seed(seed_lead_dependencies: dict) -> dict:
    """Seed minimal academic_info với annual_admission_quota=10 + 1 path
    để Tier 1 chain compute baseline."""
    # round_code max 20 chars (Phase 2 v8.2 schema constraint).
    # Use suffix-only timestamp to keep within bound.
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Round (DOT_1) cho FK admission_round_id
            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"T_{ts}",
                round_name=f"Test Round {ts}",
                is_active=True,
            )
            s.add(round_obj)
            await s.flush()

            # Re-use academic_info seed by lead deps; nếu không có,
            # filter test fixture or create new academic_info from
            # offering_id.
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering)
            await s.flush()

            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=10,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai)
            await s.flush()

            # Path with admit_quota=4 → leaves 6 capacity.
            method = models.AdmissionMethod(
                code=f"M_{ts}",
                name=f"Method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()
            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_obj.id,
                admit_quota=4,
                round_quota=10,
                status="active",
            )
            s.add(path)
            await s.flush()

            return {
                "round_id": round_obj.id,
                "academic_info_id": ai.id,
                "path_id": path.id,
            }


@pytest.mark.asyncio
async def test_tier1_chain_pass_within_capacity(quota_seed: dict):
    """ANCHOR Q2 v8.2: Tier 1 chain pass khi delta + sum ≤ annual cap."""
    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # Delta=5 → 4 + 5 = 9 ≤ 10 → pass
        await svc.validate_tier1_chain_on_path_quota_change(
            academic_info_id=quota_seed["academic_info_id"],
            delta_admit_quota=5,
        )


@pytest.mark.asyncio
async def test_tier1_chain_block_overflow(quota_seed: dict):
    """ANCHOR Q2 v8.2: Tier 1 chain block khi delta + sum > annual cap."""
    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # Delta=7 → 4 + 7 = 11 > 10 → block
        with pytest.raises(BusinessRuleViolation, match="Tier 1 chain violated"):
            await svc.validate_tier1_chain_on_path_quota_change(
                academic_info_id=quota_seed["academic_info_id"],
                delta_admit_quota=7,
            )


@pytest.mark.asyncio
async def test_tier1_chain_per_academic_info_scope(
    quota_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR P3-2 v8.2: Tier 1 scope = per academic_info, KHÔNG school-wide.

    Khác academic_info có annual cap riêng — sum không cross.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="part_time",
                duration_semesters=8,
            )
            s.add(offering)
            await s.flush()
            other_ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2027,
                annual_admission_quota=10,
                tuition_fee_per_year=1_000_000,
            )
            s.add(other_ai)
            await s.flush()
            other_id = other_ai.id

    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # Other AI cap=10, sum=0 → delta=10 should pass; KHÔNG bị
        # block bởi quota_seed AI's 4 đã chiếm.
        await svc.validate_tier1_chain_on_path_quota_change(
            academic_info_id=other_id,
            delta_admit_quota=10,
        )


@pytest.mark.asyncio
async def test_tier1_chain_excludes_archived_paths(
    quota_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR P0-1 v8.1: Tier 1 filter dùng path.status != 'archived',
    KHÔNG có path.archived_at column."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            ts2 = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
            method2 = models.AdmissionMethod(
                code=f"M2_{ts2}",
                name=f"Method2 {ts2}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method2)
            await s.flush()
            archived_path = models.AdmissionPath(
                academic_info_id=quota_seed["academic_info_id"],
                admission_method_id=method2.id,
                admission_round_id=quota_seed["round_id"],
                admit_quota=8,  # archived → KHÔNG count vào sum
                status="archived",
            )
            s.add(archived_path)
            await s.flush()

    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # 4 (active) + 8 (archived, excluded) + delta 6 = 10 ≤ cap 10 → pass
        await svc.validate_tier1_chain_on_path_quota_change(
            academic_info_id=quota_seed["academic_info_id"],
            delta_admit_quota=6,
        )


@pytest.mark.asyncio
async def test_tier2_invariant_admit_le_round():
    """ANCHOR Q2 v8.2: Tier 2 path invariant admit_quota ≤ round_quota."""
    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # admit > round → block
        with pytest.raises(BusinessRuleViolation, match="Tier 2 invariant violated"):
            await svc.validate_tier2_path_invariant(admit_quota=10, round_quota=8)
        # admit ≤ round → pass
        await svc.validate_tier2_path_invariant(admit_quota=8, round_quota=10)
        # NULL trên 1 trong 2 = pass-through
        await svc.validate_tier2_path_invariant(admit_quota=None, round_quota=10)
        await svc.validate_tier2_path_invariant(admit_quota=8, round_quota=None)


@pytest.mark.asyncio
async def test_tier1_unbounded_when_annual_cap_null(
    seed_lead_dependencies: dict
):
    """NULL annual_admission_quota = unbounded; Tier 1 inactive."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering)
            await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=None,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai)
            await s.flush()
            ai_id = ai.id

    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # delta=10000 nhưng cap=NULL → no block
        await svc.validate_tier1_chain_on_path_quota_change(
            academic_info_id=ai_id,
            delta_admit_quota=10000,
        )


@pytest.mark.asyncio
async def test_tier1_raises_when_academic_info_missing():
    """ResourceNotFoundError nếu academic_info_id không tồn tại."""
    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        with pytest.raises(ResourceNotFoundError):
            await svc.validate_tier1_chain_on_path_quota_change(
                academic_info_id=999_999_999,
                delta_admit_quota=1,
            )
