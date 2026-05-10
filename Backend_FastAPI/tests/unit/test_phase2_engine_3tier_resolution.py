"""Phase 2 v8.2 PR-2F engine sweep — 3-tier resolution (item > config > criteria).

Anchor tests cho path-level subject group resolution chain:
- Tier 3 (most specific): PathSubjectGroupItem.min_subject_score override
- Tier 2: PathSubjectGroupConfig.min_subject_score
- Tier 1 (default): AdmissionCriteria.min_subject_score

Resolution precedence: item.min_subject_score (NOT NULL) > config.min_subject_score
(NOT NULL) > criteria.min_subject_score (NULL falls back).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def tier_seed(seed_lead_dependencies: dict) -> dict:
    """Seed criteria + path + config + item with tiered min_subject_score."""
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

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"C{ts}"[:20], name=f"Crit {ts}",
                min_score=Decimal("18.00"),
                min_subject_score=Decimal("3.00"),  # Tier 1 default
                policy_version="2026.1", is_active=True,
            )
            s.add(criteria); await s.flush()

            sg = models.SubjectGroup(code=f"SG{ts}"[:20], name=f"SG {ts}")
            s.add(sg); await s.flush()

            subj = models.Subject(code=f"S{ts}"[:20], name_vi=f"Subj {ts}")
            s.add(subj); await s.flush()

            sgs = models.SubjectGroupSubject(
                subject_group_id=sg.id, subject_id=subj.id, position=1,
            )
            s.add(sgs); await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id,
                status="active",
            )
            s.add(path); await s.flush()

            return {
                "criteria_id": criteria.id,
                "path_id": path.id,
                "subject_group_id": sg.id,
                "subject_group_subject_id": sgs.id,
            }


def _resolve_min_subject_score(
    item: models.PathSubjectGroupItem | None,
    config: models.PathSubjectGroupConfig,
    criteria: models.AdmissionCriteria,
) -> Decimal | None:
    """3-tier resolution: item > config > criteria.

    Implementation matches engine logic — engine implementation should
    use this same precedence. Test imports/calls actual engine when
    engine module ships; for now anchor the contract behavior.
    """
    if item is not None and item.min_subject_score is not None:
        return item.min_subject_score
    if config.min_subject_score is not None:
        return config.min_subject_score
    return criteria.min_subject_score


@pytest.mark.asyncio
async def test_tier3_item_override_wins(tier_seed: dict):
    """ANCHOR Tier 3: item.min_subject_score overrides config + criteria."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            config = models.PathSubjectGroupConfig(
                admission_path_id=tier_seed["path_id"],
                subject_group_id=tier_seed["subject_group_id"],
                min_subject_score=Decimal("5.00"),  # Tier 2
            )
            s.add(config); await s.flush()
            item = models.PathSubjectGroupItem(
                path_subject_group_config_id=config.id,
                subject_group_subject_id=tier_seed["subject_group_subject_id"],
                min_subject_score=Decimal("7.50"),  # Tier 3 override
            )
            s.add(item); await s.flush()

            criteria = await s.get(models.AdmissionCriteria, tier_seed["criteria_id"])
            resolved = _resolve_min_subject_score(item, config, criteria)
            assert resolved == Decimal("7.50"), "Tier 3 item override should win"


@pytest.mark.asyncio
async def test_tier2_config_when_item_null(tier_seed: dict):
    """ANCHOR Tier 2: config.min_subject_score when item.min_subject_score IS NULL."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            config = models.PathSubjectGroupConfig(
                admission_path_id=tier_seed["path_id"],
                subject_group_id=tier_seed["subject_group_id"],
                min_subject_score=Decimal("5.00"),  # Tier 2
            )
            s.add(config); await s.flush()
            item = models.PathSubjectGroupItem(
                path_subject_group_config_id=config.id,
                subject_group_subject_id=tier_seed["subject_group_subject_id"],
                min_subject_score=None,  # Tier 3 NULL → fallback
            )
            s.add(item); await s.flush()

            criteria = await s.get(models.AdmissionCriteria, tier_seed["criteria_id"])
            resolved = _resolve_min_subject_score(item, config, criteria)
            assert resolved == Decimal("5.00"), "Tier 2 config should apply"


@pytest.mark.asyncio
async def test_tier1_criteria_default_when_item_and_config_null(tier_seed: dict):
    """ANCHOR Tier 1: criteria.min_subject_score when both item + config NULL."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            config = models.PathSubjectGroupConfig(
                admission_path_id=tier_seed["path_id"],
                subject_group_id=tier_seed["subject_group_id"],
                min_subject_score=None,  # Tier 2 NULL
            )
            s.add(config); await s.flush()
            item = models.PathSubjectGroupItem(
                path_subject_group_config_id=config.id,
                subject_group_subject_id=tier_seed["subject_group_subject_id"],
                min_subject_score=None,  # Tier 3 NULL
            )
            s.add(item); await s.flush()

            criteria = await s.get(models.AdmissionCriteria, tier_seed["criteria_id"])
            resolved = _resolve_min_subject_score(item, config, criteria)
            assert resolved == Decimal("3.00"), "Tier 1 criteria default should apply"


@pytest.mark.asyncio
async def test_no_item_falls_back_to_config(tier_seed: dict):
    """ANCHOR: missing item entry falls back to config."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            config = models.PathSubjectGroupConfig(
                admission_path_id=tier_seed["path_id"],
                subject_group_id=tier_seed["subject_group_id"],
                min_subject_score=Decimal("4.00"),
            )
            s.add(config); await s.flush()

            criteria = await s.get(models.AdmissionCriteria, tier_seed["criteria_id"])
            resolved = _resolve_min_subject_score(None, config, criteria)
            assert resolved == Decimal("4.00"), "No item → fallback to config"


@pytest.mark.asyncio
async def test_no_item_no_config_value_fallback_criteria(tier_seed: dict):
    """ANCHOR: full chain fallback to criteria when item missing + config NULL."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            config = models.PathSubjectGroupConfig(
                admission_path_id=tier_seed["path_id"],
                subject_group_id=tier_seed["subject_group_id"],
                min_subject_score=None,
            )
            s.add(config); await s.flush()

            criteria = await s.get(models.AdmissionCriteria, tier_seed["criteria_id"])
            resolved = _resolve_min_subject_score(None, config, criteria)
            assert resolved == Decimal("3.00"), "Full fallback chain to criteria"
