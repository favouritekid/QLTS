"""Service-level tests cho PathSubjectGroupService Tier 3 chain + composite invariant.

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_tier3_chain_blocks_when_group_quota_exceed_admit_quota``
- ``test_composite_invariant_blocks_cross_group_subject``
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.database import AsyncSessionLocal
from app.schemas.path_subject_group import (
    PathSubjectGroupConfigCreate,
    PathSubjectGroupItemCreate,
)
from app.services.path_subject_group_service import PathSubjectGroupService
from app.utils.exceptions import BusinessRuleViolation, DuplicateResourceError


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def t3_seed(seed_lead_dependencies: dict) -> dict:
    """Seed path với admit_quota=10 + 2 subject groups + 1 sgs."""
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
                code=f"M{ts}", name=f"M {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                admit_quota=10,  # Tier 3 cap
                status="active",
            )
            s.add(path); await s.flush()

            sg_a = models.SubjectGroup(code=f"A{ts}"[:20], name=f"SG A {ts}")
            sg_b = models.SubjectGroup(code=f"B{ts}"[:20], name=f"SG B {ts}")
            s.add_all([sg_a, sg_b]); await s.flush()

            subj = models.Subject(code=f"S{ts}"[:20], name_vi=f"Subj {ts}")
            s.add(subj); await s.flush()

            sgs_in_a = models.SubjectGroupSubject(
                subject_group_id=sg_a.id, subject_id=subj.id, position=1,
            )
            s.add(sgs_in_a); await s.flush()

            return {
                "path_id": path.id,
                "subject_group_a_id": sg_a.id,
                "subject_group_b_id": sg_b.id,
                "sgs_in_a_id": sgs_in_a.id,
            }


@pytest.mark.asyncio
async def test_tier3_chain_blocks_when_group_quota_exceed_admit_quota(
    t3_seed: dict,
):
    """ANCHOR Tier 3: ∑(group_quota in path) ≤ path.admit_quota.

    Path admit_quota=10. Create config 1 với group_quota=6 → pass.
    Create config 2 với group_quota=7 → 6+7=13 > 10 → BLOCK.
    """
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # Config 1: group A, quota=6 → pass
        await svc.create_config(
            t3_seed["path_id"],
            PathSubjectGroupConfigCreate(
                subject_group_id=t3_seed["subject_group_a_id"],
                group_quota=6,
            ),
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # Config 2: group B, quota=7 → block (Tier 3 violated)
        with pytest.raises(BusinessRuleViolation, match="Tier 3 chain violated"):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_b_id"],
                    group_quota=7,
                ),
            )


@pytest.mark.asyncio
async def test_composite_invariant_blocks_cross_group_subject(
    t3_seed: dict,
):
    """ANCHOR Composite invariant: subject_group_subject.subject_group_id
    MUST equal config.subject_group_id.

    sgs_in_a thuộc group A. Config gán group B + item dùng sgs_in_a → BLOCK.
    """
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(BusinessRuleViolation, match="Composite invariant violated"):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_b_id"],  # B
                    items=[
                        PathSubjectGroupItemCreate(
                            subject_group_subject_id=t3_seed["sgs_in_a_id"],  # A
                        ),
                    ],
                ),
            )


@pytest.mark.asyncio
async def test_create_config_duplicate_blocked(t3_seed: dict):
    """DuplicateResourceError khi tạo config thứ 2 cho same (path, group)."""
    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        await svc.create_config(
            t3_seed["path_id"],
            PathSubjectGroupConfigCreate(
                subject_group_id=t3_seed["subject_group_a_id"],
                min_score=Decimal("18.00"),
            ),
        )
        await s.commit()

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        with pytest.raises(DuplicateResourceError):
            await svc.create_config(
                t3_seed["path_id"],
                PathSubjectGroupConfigCreate(
                    subject_group_id=t3_seed["subject_group_a_id"],  # dup
                    min_score=Decimal("19.00"),
                ),
            )


@pytest.mark.asyncio
async def test_tier3_chain_unbounded_when_admit_quota_null(
    seed_lead_dependencies: dict,
):
    """NULL path.admit_quota → Tier 3 inactive (skip check)."""
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
                code=f"M{ts}", name=f"M {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()
            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                admit_quota=None,  # NULL = unbounded
                status="active",
            )
            s.add(path); await s.flush()
            sg = models.SubjectGroup(code=f"X{ts}"[:20], name=f"SG {ts}")
            s.add(sg); await s.flush()
            path_id, sg_id = path.id, sg.id

    async with AsyncSessionLocal() as s:
        svc = PathSubjectGroupService(s)
        # group_quota=10000 — would normally violate, but admit_quota=NULL bypasses
        await svc.create_config(
            path_id,
            PathSubjectGroupConfigCreate(
                subject_group_id=sg_id, group_quota=10000,
            ),
        )
