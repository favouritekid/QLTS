"""CoverageRow round metadata (PR matrix-funnel — readiness nhóm-theo-đợt).

``AdmissionPathService.get_coverage_matrix`` populates flat round fields
(``admission_round_id`` / ``round_code`` / ``round_name`` / ``round_is_active``)
from the eager-loaded ``admission_round`` relationship so the FE can group
readiness rows by đợt. Anchor: a path bound to DOT_1 surfaces that round's
code/name/active flag on its CoverageRow.

Execution: DB seed — one-off backend container per
``local-test-oneoff-container-pattern``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.services.admission_path_service import AdmissionPathService

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def coverage_seed(seed_lead_dependencies: dict) -> dict:
    """1 academic_info(2026) + 1 explicit round + 1 path bound to it."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
                is_active=True,
            )
            s.add(offering)
            await s.flush()

            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=50,
                tuition_fee_per_year=Decimal("1000000"),
            )
            s.add(ai)
            await s.flush()

            round_obj = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"CVR_{ts}"[:20],
                round_name=f"Đợt CVR {ts}",
                is_active=True,
            )
            s.add(round_obj)
            await s.flush()

            method = models.AdmissionMethod(
                code=f"MCV{ts}"[:20],
                name=f"Method CV {ts}",
                requires_subject_scores=False,
                requires_gpa=False,
                is_active=True,
            )
            s.add(method)
            await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_obj.id,
                status="draft",
                admit_quota=10,
                round_quota=20,
            )
            s.add(path)
            await s.flush()

            return {
                "academic_info_id": ai.id,
                "path_id": path.id,
                "round_id": round_obj.id,
                "round_code": round_obj.round_code,
                "round_name": round_obj.round_name,
            }


@pytest.mark.asyncio
async def test_coverage_row_carries_round_metadata(coverage_seed: dict):
    """CoverageRow exposes round_id/code/name/is_active từ admission_round."""
    async with AsyncSessionLocal() as s:
        result, _ = await AdmissionPathService(s).get_coverage_matrix(
            coverage_seed["academic_info_id"]
        )

    row = next(r for r in result.rows if r.path_id == coverage_seed["path_id"])
    assert row.admission_round_id == coverage_seed["round_id"]
    assert row.round_code == coverage_seed["round_code"]
    assert row.round_name == coverage_seed["round_name"]
    assert row.round_is_active is True
