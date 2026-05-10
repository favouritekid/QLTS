"""Phase 2 v8.2 PR-2F engine sweep — Tier 1+2+3 unified quota chain.

Anchor tests cho full quota chain integration (post Phase 2 plan v8.2):
- Tier 1: ∑(path.admit_quota WHERE academic_info_id=X) ≤ academic_info[X].annual_admission_quota
- Tier 2: path.admit_quota ≤ path.round_quota (path-level invariant)
- Tier 3: ∑(group_quota in path) ≤ path.admit_quota

Refer back to PR-2B v2 admission_quota_service + PR-2D PathSubjectGroupService
for service-layer guard implementations. This file integration-tests the
full chain end-to-end.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.schemas.path_subject_group import PathSubjectGroupConfigCreate
from app.services.admission_quota_service import AdmissionQuotaService
from app.services.path_subject_group_service import PathSubjectGroupService
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def chain_seed(seed_lead_dependencies: dict) -> dict:
    """Seed academic_info (annual=20) + 1 path + 2 subject groups."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=20,  # Tier 1 cap
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )

            method = models.AdmissionMethod(
                code=f"M{ts}"[:20], name=f"M {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                round_quota=15,  # Tier 2 cap
                admit_quota=10,  # Tier 1 contribution + Tier 3 cap
                status="active",
            )
            s.add(path); await s.flush()

            sg_a = models.SubjectGroup(code=f"A{ts}"[:20], name=f"SG A {ts}")
            sg_b = models.SubjectGroup(code=f"B{ts}"[:20], name=f"SG B {ts}")
            s.add_all([sg_a, sg_b]); await s.flush()

            return {
                "academic_info_id": ai.id,
                "path_id": path.id,
                "subject_group_a_id": sg_a.id,
                "subject_group_b_id": sg_b.id,
            }


@pytest.mark.asyncio
async def test_tier1_chain_blocks_when_aggregate_exceeds_annual(
    chain_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR Tier 1: ∑(admit_quota) per academic_info ≤ annual cap.

    Path đã có admit_quota=10 (annual=20). Add 2nd path delta=11 → 10+11=21 > 20 → BLOCK.
    """
    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        with pytest.raises(BusinessRuleViolation, match="Tier 1 chain violated"):
            await svc.validate_tier1_chain_on_path_quota_change(
                academic_info_id=chain_seed["academic_info_id"],
                delta_admit_quota=11,
            )


@pytest.mark.asyncio
async def test_tier2_path_invariant_admit_le_round(chain_seed: dict):
    """ANCHOR Tier 2: path.admit_quota ≤ path.round_quota."""
    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # Pass: 10 ≤ 15
        await svc.validate_tier2_path_invariant(admit_quota=10, round_quota=15)
        # Block: 16 > 15
        with pytest.raises(BusinessRuleViolation, match="Tier 2 invariant violated"):
            await svc.validate_tier2_path_invariant(admit_quota=16, round_quota=15)


@pytest.mark.asyncio
async def test_tier3_group_quota_chain_blocks_overflow(chain_seed: dict):
    """ANCHOR Tier 3: ∑(group_quota in path) ≤ path.admit_quota.

    path.admit_quota=10. Config A group_quota=6 pass.
    Config B group_quota=5 → 6+5=11 > 10 → BLOCK.
    """
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        await svc.create_config(
            chain_seed["path_id"],
            PathSubjectGroupConfigCreate(
                subject_group_id=chain_seed["subject_group_a_id"],
                group_quota=6,
            ),
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(BusinessRuleViolation, match="Tier 3 chain violated"):
            await svc.create_config(
                chain_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=chain_seed["subject_group_b_id"],
                    group_quota=5,  # 6+5=11 > admit_quota 10
                ),
            )


@pytest.mark.asyncio
async def test_tier1_per_academic_info_scope_not_school_wide(
    chain_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR Q2 v8.2 MANDATORY: Tier 1 scope = per academic_info, NOT school-wide."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering2 = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="part_time",  # different offering
                duration_semesters=8,
            )
            s.add(offering2); await s.flush()
            ai2 = models.OfferingAcademicInfo(
                offering_id=offering2.id,
                academic_year=2026,
                annual_admission_quota=15,  # different cap from chain_seed AI
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai2); await s.flush()
            other_id = ai2.id

    async with AsyncSessionLocal() as s:
        svc = AdmissionQuotaService(s)
        # Other AI sum=0, cap=15 → delta=15 should pass
        # NOT affected by chain_seed AI's 10 already used
        await svc.validate_tier1_chain_on_path_quota_change(
            academic_info_id=other_id,
            delta_admit_quota=15,
        )


@pytest.mark.asyncio
async def test_tier3_unbounded_when_admit_quota_null(
    seed_lead_dependencies: dict,
):
    """ANCHOR: NULL path.admit_quota → Tier 3 inactive (skip check)."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=20,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )
            method = models.AdmissionMethod(
                code=f"M{ts}"[:20], name=f"M {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()
            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                admit_quota=None,  # unbounded → Tier 3 inactive
                status="active",
            )
            s.add(path); await s.flush()
            sg = models.SubjectGroup(code=f"X{ts}"[:20], name=f"SG {ts}")
            s.add(sg); await s.flush()
            path_id, sg_id = path.id, sg.id

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # Massive group_quota — would block normally, but admit_quota NULL bypasses
        await svc.create_config(
            path_id,
            PathSubjectGroupConfigCreate(
                subject_group_id=sg_id, group_quota=10_000,
            ),
        )
