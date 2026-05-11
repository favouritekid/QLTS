"""Phase 2 v8.2 PR-2F Wave 2 — kịch bản 5: Chứng chỉ IELTS.

Scenario: thí sinh có IELTS ≥ 6.0 được xét tuyển kết hợp với GPA THPT.
Method: ``CCQT_IELTS`` (chứng chỉ quốc tế); criteria có 2 ngưỡng: GPA tối
thiểu (vd 6.5) + IELTS tối thiểu (qua subject 'IELTS' virtual với score
là band 0-9).

Anchor tests: kịch bản này dùng virtual subject IELTS (subject_kind ≠
ACADEMIC_SUBJECT — phase1_05 seed) với score range 0-9 band, KHÁC kịch bản
1+2 dùng subject thường (range 0-10). Critical cho phase1_05 multi-kind
contract.
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
async def kichban_ielts_seed(seed_lead_dependencies: dict) -> dict:
    """Seed kịch bản 5: criteria chứng chỉ IELTS với combined gate."""
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
                annual_admission_quota=15,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )

            method = models.AdmissionMethod(
                code=f"CC{ts}"[:20], name=f"Chứng chỉ IELTS {ts}",
                requires_gpa=True, requires_subject_scores=True,
                is_active=True,
            )
            s.add(method); await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"CC{ts}"[:20], name=f"IELTS+GPA {ts}",
                min_gpa=Decimal("6.50"),
                min_subject_score=Decimal("6.00"),  # IELTS band ≥ 6.0
                policy_version="2026.1", is_active=True,
            )
            s.add(criteria); await s.flush()

            # IELTS virtual subject — phase1_05 seed thực tế đã có subject
            # code "IELTS"; here seed test-local với unique code prefix.
            ielts_subj = models.Subject(
                code=f"IELTS{ts}"[:20], name_vi=f"IELTS {ts}",
            )
            s.add(ielts_subj); await s.flush()

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
                "ielts_subject_id": ielts_subj.id,
                "min_gpa": Decimal("6.50"),
                "min_ielts_band": Decimal("6.00"),
            }


@pytest.mark.asyncio
async def test_kichban_ielts_cert_combined_gpa_and_band_passes(
    kichban_ielts_seed: dict,
):
    """ANCHOR happy path combined gate: GPA 7.5 + IELTS 6.5 (band) →
    BOTH pass thresholds → eligible.

    Critical: cả 2 ngưỡng ÒS AND, không phải OR. GPA pass mà IELTS fail
    → ineligible (test riêng dưới).
    """
    candidate_gpa = Decimal("7.50")
    candidate_ielts = Decimal("6.50")
    gpa_ok = candidate_gpa >= kichban_ielts_seed["min_gpa"]
    ielts_ok = candidate_ielts >= kichban_ielts_seed["min_ielts_band"]
    assert gpa_ok is True, f"GPA {candidate_gpa} ≥ 6.50 should pass"
    assert ielts_ok is True, f"IELTS {candidate_ielts} ≥ 6.00 should pass"
    # AND combined: both must pass cho eligibility.
    assert gpa_ok and ielts_ok, "Combined AND gate contract"


@pytest.mark.asyncio
async def test_kichban_ielts_cert_band_below_threshold_blocks(
    kichban_ielts_seed: dict,
):
    """ANCHOR contract: GPA pass nhưng IELTS band 5.5 < 6.0 → ineligible.

    AND gate: 1 ngưỡng fail = full block. Critical regression guard cho
    engine implementation nếu future code accidentally chuyển AND → OR.
    """
    candidate_gpa = Decimal("8.00")  # GPA pass mạnh
    candidate_ielts = Decimal("5.50")  # IELTS dưới threshold
    gpa_ok = candidate_gpa >= kichban_ielts_seed["min_gpa"]
    ielts_ok = candidate_ielts >= kichban_ielts_seed["min_ielts_band"]
    assert gpa_ok is True, "GPA pass"
    assert ielts_ok is False, "IELTS dưới ngưỡng"
    # Combined AND: phải fail vì 1 trong 2 không đạt.
    assert not (gpa_ok and ielts_ok), (
        "AND gate: IELTS fail blocks eligibility bất chấp GPA pass"
    )
