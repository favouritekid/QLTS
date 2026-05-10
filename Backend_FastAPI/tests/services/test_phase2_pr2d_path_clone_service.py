"""Anchor tests cho PathCloneService deep-copy (Phase 2 v8.2 PR-2D Q6).

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_clone_creates_new_criteria_with_derived_code``
- ``test_clone_skips_when_target_already_has_path``
- ``test_clone_resets_quota_fields_on_target``
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.schemas.path_subject_group import ClonePathsRequest
from app.services.path_clone_service import PathCloneService
from app.utils.exceptions import BusinessRuleViolation


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def clone_seed(seed_lead_dependencies: dict) -> dict:
    """Seed source path với criteria + 2 rounds (DOT_1 source, DOT_2 target)."""
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

            r_source = models.OfferingAdmissionRound(
                academic_year=2026, round_code=f"S{ts}"[:20],
                round_name=f"Source {ts}", is_active=True,
            )
            r_target = models.OfferingAdmissionRound(
                academic_year=2026, round_code=f"T{ts}"[:20],
                round_name=f"Target {ts}", is_active=True,
            )
            s.add_all([r_source, r_target]); await s.flush()

            method = models.AdmissionMethod(
                code=f"M{ts}"[:20], name=f"M {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"C{ts}"[:20], name=f"Crit {ts}",
                min_score=Decimal("18.00"),
                max_possible_score=Decimal("30.00"),
                policy_version="2026.1",
                is_active=True,
            )
            s.add(criteria); await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=r_source.id,
                criteria_id=criteria.id,
                round_quota=10,  # source has quota set
                admit_quota=8,
                submission_count=2,
                status="active",
                display_name="Source path",
                visibility="public",
            )
            s.add(path); await s.flush()

            return {
                "academic_info_id": ai.id,
                "method_id": method.id,
                "source_round_id": r_source.id,
                "target_round_id": r_target.id,
                "source_path_id": path.id,
                "source_criteria_id": criteria.id,
                "source_criteria_code": criteria.code,
            }


@pytest.mark.asyncio
async def test_clone_creates_new_criteria_with_derived_code(
    clone_seed: dict,
):
    """ANCHOR Q6 v8.2: clone creates NEW AdmissionCriteria via template."""
    async with AsyncSessionLocal() as s:
        svc = PathCloneService(s)
        response = await svc.clone_paths_from_round(
            target_round_id=clone_seed["target_round_id"],
            source_round_id=clone_seed["source_round_id"],
            payload=ClonePathsRequest(
                criteria_code_template="{source_code}_R{target_round_id}",
            ),
        )
        await s.commit()

    assert response.cloned_count == 1
    assert response.skipped_count == 0
    assert len(response.items) == 1

    cloned_item = response.items[0]
    assert cloned_item.source_path_id == clone_seed["source_path_id"]
    assert cloned_item.source_criteria_code == clone_seed["source_criteria_code"]
    # New code derived per template
    expected = f"{clone_seed['source_criteria_code']}_R{clone_seed['target_round_id']}"
    assert cloned_item.cloned_criteria_code == expected

    # Verify cloned criteria distinct từ source
    async with AsyncSessionLocal() as s:
        cloned_path = await s.get(models.AdmissionPath, cloned_item.cloned_path_id)
        assert cloned_path.criteria_id != clone_seed["source_criteria_id"]
        assert cloned_path.admission_round_id == clone_seed["target_round_id"]


@pytest.mark.asyncio
async def test_clone_resets_quota_fields_on_target(
    clone_seed: dict,
):
    """ANCHOR Q6 v8.2: cloned path resets round_quota/admit_quota/submission_count
    to NULL/0 — admin sets per target round."""
    async with AsyncSessionLocal() as s:
        svc = PathCloneService(s)
        response = await svc.clone_paths_from_round(
            target_round_id=clone_seed["target_round_id"],
            source_round_id=clone_seed["source_round_id"],
            payload=ClonePathsRequest(),
        )
        await s.commit()

    cloned_item = response.items[0]
    async with AsyncSessionLocal() as s:
        cloned_path = await s.get(models.AdmissionPath, cloned_item.cloned_path_id)
        assert cloned_path.round_quota is None
        assert cloned_path.admit_quota is None
        assert cloned_path.submission_count == 0
        # Source path UNCHANGED
        source_path = await s.get(
            models.AdmissionPath, clone_seed["source_path_id"]
        )
        assert source_path.round_quota == 10
        assert source_path.admit_quota == 8
        assert source_path.submission_count == 2


@pytest.mark.asyncio
async def test_clone_rejects_same_round_id(clone_seed: dict):
    """BusinessRuleViolation khi source_round_id == target_round_id."""
    async with AsyncSessionLocal() as s:
        svc = PathCloneService(s)
        with pytest.raises(BusinessRuleViolation, match="phải khác nhau"):
            await svc.clone_paths_from_round(
                target_round_id=clone_seed["source_round_id"],
                source_round_id=clone_seed["source_round_id"],
                payload=ClonePathsRequest(),
            )


@pytest.mark.asyncio
async def test_clone_filtered_by_academic_info_ids(clone_seed: dict, seed_lead_dependencies: dict):
    """Clone respects academic_info_ids filter — chỉ clone matching paths."""
    # Add 2nd path under different academic_info — should NOT be cloned
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering2 = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="part_time",
                duration_semesters=8,
            )
            s.add(offering2); await s.flush()
            ai2 = models.OfferingAcademicInfo(
                offering_id=offering2.id,
                academic_year=2026,
                annual_admission_quota=10,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai2); await s.flush()
            criteria2 = models.AdmissionCriteria(
                method_id=clone_seed["method_id"],
                code=f"C2_{ts}"[:20], name=f"Crit2 {ts}",
                min_score=Decimal("15.00"),
                policy_version="2026.1", is_active=True,
            )
            s.add(criteria2); await s.flush()
            path2 = models.AdmissionPath(
                academic_info_id=ai2.id,
                admission_method_id=clone_seed["method_id"],
                admission_round_id=clone_seed["source_round_id"],
                criteria_id=criteria2.id,
                status="active",
            )
            s.add(path2); await s.flush()

    # Clone với filter chỉ matching academic_info_id #1
    async with AsyncSessionLocal() as s:
        svc = PathCloneService(s)
        response = await svc.clone_paths_from_round(
            target_round_id=clone_seed["target_round_id"],
            source_round_id=clone_seed["source_round_id"],
            payload=ClonePathsRequest(
                academic_info_ids=[clone_seed["academic_info_id"]],
            ),
        )
        await s.commit()

    assert response.cloned_count == 1  # Chỉ matching academic_info_id #1
    assert response.items[0].source_path_id == clone_seed["source_path_id"]
