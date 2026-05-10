"""Anchor tests cho Phase 2 v8.2 PR-2E (score precision Numeric(8,2)).

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_admission_criteria_accepts_1200_point_v_act_score``
- ``test_profile_subject_score_accepts_1200_v_act_score``
- ``test_profile_subject_score_blocks_negative``
- ``test_admission_criteria_min_subject_score_widened``
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def precision_seed(seed_lead_dependencies: dict) -> dict:
    """Seed academic_info + method + path + 1 subject + 1 profile."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
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
                annual_admission_quota=10,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai)
            await s.flush()
            method = models.AdmissionMethod(
                code=f"VACT_{ts}",
                name=f"V-ACT method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()
            subj = models.Subject(
                code=f"S{ts}",
                name_vi=f"Subject {ts}",
            )
            s.add(subj)
            await s.flush()
            return {
                "academic_info_id": ai.id,
                "method_id": method.id,
                "subject_id": subj.id,
            }


@pytest.mark.asyncio
async def test_admission_criteria_accepts_1200_point_v_act_score(
    precision_seed: dict,
):
    """ANCHOR PR-2E: AdmissionCriteria.min_score / max_possible_score
    accept 1200-point V-ACT scale (Numeric(8,2) precision)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            criteria = models.AdmissionCriteria(
                code=f"VACT_C_{precision_seed['method_id']}",
                name="V-ACT criteria",
                method_id=precision_seed["method_id"],
                min_score=Decimal("750.50"),  # 750.5 / 1200 V-ACT scale
                max_possible_score=Decimal("1200.00"),
                min_subject_score=Decimal("100.00"),
                is_active=True,
            )
            s.add(criteria)
            await s.flush()
            crit_id = criteria.id

    async with AsyncSessionLocal() as s:
        crit_db = await s.get(models.AdmissionCriteria, crit_id)
        assert crit_db.min_score == Decimal("750.50")
        assert crit_db.max_possible_score == Decimal("1200.00")
        assert crit_db.min_subject_score == Decimal("100.00")


@pytest.mark.asyncio
async def test_profile_subject_score_accepts_1200_v_act_score(
    precision_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR PR-2E: profile_subject_score.score accepts up to 1200
    after CHECK relaxed (was 0-10, now >= 0 only)."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"V-ACT Lead {ts}",
                phone=f"097{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"5{ts:08d}0"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()
            score_row = models.ProfileSubjectScore(
                profile_id=profile.id,
                subject_id=precision_seed["subject_id"],
                score=Decimal("1180.75"),  # V-ACT high score
            )
            s.add(score_row)
            await s.flush()
            score_id = score_row.id

    async with AsyncSessionLocal() as s:
        row = await s.get(models.ProfileSubjectScore, score_id)
        assert row.score == Decimal("1180.75")


@pytest.mark.asyncio
async def test_profile_subject_score_blocks_negative(
    precision_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR PR-2E: relaxed CHECK still blocks negative scores."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Neg Lead {ts}",
                phone=f"098{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"6{ts:08d}0"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()
            profile_id = profile.id

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                bad_score = models.ProfileSubjectScore(
                    profile_id=profile_id,
                    subject_id=precision_seed["subject_id"],
                    score=Decimal("-1.00"),  # negative blocked
                )
                s.add(bad_score)
                await s.flush()


@pytest.mark.asyncio
async def test_score_precision_two_decimal_places(
    precision_seed: dict, seed_lead_dependencies: dict
):
    """ANCHOR PR-2E: Numeric(8,2) preserves 2-decimal precision
    (vs old Numeric(3,1) only 1 decimal)."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Decimal Lead {ts}",
                phone=f"099{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"7{ts:08d}0"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()
            score_row = models.ProfileSubjectScore(
                profile_id=profile.id,
                subject_id=precision_seed["subject_id"],
                score=Decimal("8.75"),  # 2 decimals
            )
            s.add(score_row)
            await s.flush()
            score_id = score_row.id

    async with AsyncSessionLocal() as s:
        row = await s.get(models.ProfileSubjectScore, score_id)
        assert row.score == Decimal("8.75")


@pytest.mark.asyncio
async def test_admission_criteria_min_subject_score_widened(
    precision_seed: dict,
):
    """ANCHOR PR-2E: min_subject_score column widened cho V-ACT subject
    minimums (e.g., 100/300 per subject)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            criteria = models.AdmissionCriteria(
                code=f"VACT_MS_{precision_seed['method_id']}",
                name="V-ACT subject min",
                method_id=precision_seed["method_id"],
                min_subject_score=Decimal("250.00"),  # >100 max trước PR-2E
                is_active=True,
            )
            s.add(criteria)
            await s.flush()
            crit_id = criteria.id

    async with AsyncSessionLocal() as s:
        crit_db = await s.get(models.AdmissionCriteria, crit_id)
        assert crit_db.min_subject_score == Decimal("250.00")
