"""Anchor tests cho Phase 2 v8.2 PR-2C v2 ⚠ ONE-WAY (NOT NULL + 3-col UNIQUE).

Anchor tests per memory pattern-change-impact-audit (P3-2 v8.2):
- ``test_three_col_unique_blocks_dup_round_acad_method`` — invariant
- ``test_three_col_unique_allows_distinct_rounds_same_acad_method`` —
  enables Phase 2 multi-round scaling (4 đợt × major × method)
- ``test_admission_round_id_is_not_null`` — schema-level NOT NULL guard
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def two_rounds_seed(seed_lead_dependencies: dict) -> dict:
    """Seed academic_info + 2 rounds (DOT_1, DOT_2) cho 3-col UNIQUE tests."""
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
                annual_admission_quota=20,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai)
            await s.flush()

            method = models.AdmissionMethod(
                code=f"M2C_{ts}",
                name=f"PR-2C method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()

            r1 = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"D1_{ts}",
                round_name="Test DOT_1",
                is_active=True,
            )
            r2 = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"D2_{ts}",
                round_name="Test DOT_2",
                is_active=True,
            )
            s.add_all([r1, r2])
            await s.flush()

            return {
                "academic_info_id": ai.id,
                "method_id": method.id,
                "round1_id": r1.id,
                "round2_id": r2.id,
            }


@pytest.mark.asyncio
async def test_three_col_unique_blocks_dup_round_acad_method(
    two_rounds_seed: dict,
):
    """ANCHOR Q5 v8.2: 3-col UNIQUE blocks duplicate
    (admission_round_id, academic_info_id, admission_method_id)."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path1 = models.AdmissionPath(
                academic_info_id=two_rounds_seed["academic_info_id"],
                admission_method_id=two_rounds_seed["method_id"],
                admission_round_id=two_rounds_seed["round1_id"],
                status="active",
            )
            s.add(path1)
            await s.flush()

    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                path_dup = models.AdmissionPath(
                    academic_info_id=two_rounds_seed["academic_info_id"],
                    admission_method_id=two_rounds_seed["method_id"],
                    admission_round_id=two_rounds_seed["round1_id"],
                    status="active",
                )
                s.add(path_dup)
                await s.flush()


@pytest.mark.asyncio
async def test_three_col_unique_allows_distinct_rounds_same_acad_method(
    two_rounds_seed: dict,
):
    """ANCHOR Q5 v8.2: same (academic_info, method) but distinct rounds = OK.

    Enables Phase 2 multi-round scaling (4 đợt × major × method = 4×
    capacity vs old 2-col UNIQUE blocking to 1× capacity).
    """
    async with AsyncSessionLocal() as s:
        async with s.begin():
            path_dot1 = models.AdmissionPath(
                academic_info_id=two_rounds_seed["academic_info_id"],
                admission_method_id=two_rounds_seed["method_id"],
                admission_round_id=two_rounds_seed["round1_id"],
                status="active",
            )
            path_dot2 = models.AdmissionPath(
                academic_info_id=two_rounds_seed["academic_info_id"],
                admission_method_id=two_rounds_seed["method_id"],
                admission_round_id=two_rounds_seed["round2_id"],  # different round
                status="active",
            )
            s.add_all([path_dot1, path_dot2])
            await s.flush()

    async with AsyncSessionLocal() as s:
        count = await s.execute(
            select(models.AdmissionPath).where(
                models.AdmissionPath.academic_info_id == two_rounds_seed["academic_info_id"],
                models.AdmissionPath.admission_method_id == two_rounds_seed["method_id"],
            )
        )
        rows = list(count.scalars().all())
        assert len(rows) == 2
        round_ids = {r.admission_round_id for r in rows}
        assert two_rounds_seed["round1_id"] in round_ids
        assert two_rounds_seed["round2_id"] in round_ids


@pytest.mark.asyncio
async def test_admission_round_id_is_not_null(
    two_rounds_seed: dict,
):
    """ANCHOR PR-2C v2: admission_round_id NOT NULL constraint enforced."""
    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as s:
            async with s.begin():
                path_null = models.AdmissionPath(
                    academic_info_id=two_rounds_seed["academic_info_id"],
                    admission_method_id=two_rounds_seed["method_id"],
                    admission_round_id=None,  # violates NOT NULL
                    status="active",
                )
                s.add(path_null)
                await s.flush()


@pytest.mark.asyncio
async def test_archive_table_exists():
    """ANCHOR PR-2C v2: _archive_admission_path_dup ready cho rollback playbook.

    Note: Test DB uses Base.metadata.create_all() (per memory
    test-db-schema-source) — alembic raw SQL creates table KHÔNG được
    replicate. Skip on test DB; verify manually trên dev/prod alembic
    rollout (already verified 2026-05-09 dev: \\d _archive_admission_path_dup
    returns 23-col archive structure).
    """
    pytest.skip(
        "Archive table created via raw SQL in alembic migration; "
        "test DB uses Base.metadata.create_all() so table not replicated. "
        "Verified manually on dev DB."
    )
