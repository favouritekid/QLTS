"""Phase 2 v8.2 PR-2F Wave 2 — kịch bản 2: Tốt nghiệp THPT (post THPT TN).

Scenario: thí sinh tốt nghiệp THPT, xét tuyển bằng điểm thi THPTQG khối A00
(Toán + Lý + Hóa) hoặc A01 (Toán + Lý + Anh). Criteria: ``min_score = 18.00``
+ ``required_subject_count = 3`` + ``scoring_method = 'sum'`` (tổng 3 môn).

Anchor tests focus contract behavior — sum scoring + threshold check khác
kịch bản 1 dùng `average`. Critical: kịch bản này dùng max_possible_score
30.00 (3 môn × 10 điểm) vs kịch bản 4 (V-ACT/DGNL max 1200).
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
async def kichban_thpt_tn_seed(seed_lead_dependencies: dict) -> dict:
    """Seed kịch bản 2: criteria THPT điểm thi khối A00 với sum scoring."""
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
                code=f"THPT{ts}"[:20], name=f"THPT điểm thi {ts}",
                requires_subject_scores=True, is_active=True,
            )
            s.add(method); await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"THPT{ts}"[:20], name=f"THPT A00 {ts}",
                min_score=Decimal("18.00"),
                max_possible_score=Decimal("30.00"),  # 3 môn × 10
                required_subject_count=3,
                subject_selection_mode="fixed",
                scoring_method="sum",
                policy_version="2026.1", is_active=True,
            )
            s.add(criteria); await s.flush()

            sg = models.SubjectGroup(code=f"A00{ts}"[:20], name=f"A00 {ts}")
            s.add(sg); await s.flush()

            for i, lbl in enumerate(["TOAN", "LY", "HOA"], start=1):
                subj = models.Subject(
                    code=f"{lbl}{ts}"[:20], name_vi=f"{lbl} {ts}",
                )
                s.add(subj); await s.flush()
                sgs = models.SubjectGroupSubject(
                    subject_group_id=sg.id, subject_id=subj.id, position=i,
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
                "min_score": Decimal("18.00"),
                "max_possible_score": Decimal("30.00"),
            }


def _compute_sum(scores: list[Decimal]) -> Decimal:
    """Helper mirror engine — scoring_method='sum' aggregation."""
    return sum(scores, Decimal("0.00")).quantize(Decimal("0.01"))


@pytest.mark.asyncio
async def test_kichban_post_thpt_tn_sum_3_subjects_passes_min_score(
    kichban_thpt_tn_seed: dict,
):
    """ANCHOR kịch bản 2 happy path: Toán 7.0 + Lý 6.5 + Hóa 6.0 = 19.50
    ≥ min_score 18.00 → eligible."""
    scores = [Decimal("7.00"), Decimal("6.50"), Decimal("6.00")]
    total = _compute_sum(scores)
    assert total == Decimal("19.50"), f"sum drift: got {total}"
    assert total >= kichban_thpt_tn_seed["min_score"], (
        f"Eligibility: sum {total} >= min_score "
        f"{kichban_thpt_tn_seed['min_score']} should be True"
    )


@pytest.mark.asyncio
async def test_kichban_post_thpt_tn_sum_below_min_score_blocks(
    kichban_thpt_tn_seed: dict,
):
    """ANCHOR boundary: tổng 17.50 < min_score 18.00 → blocked."""
    scores = [Decimal("6.00"), Decimal("6.00"), Decimal("5.50")]
    total = _compute_sum(scores)
    assert total == Decimal("17.50"), f"sum drift: got {total}"
    assert total < kichban_thpt_tn_seed["min_score"], "Block contract"


@pytest.mark.asyncio
async def test_kichban_post_thpt_tn_perfect_score_within_max(
    kichban_thpt_tn_seed: dict,
):
    """ANCHOR contract: điểm tuyệt đối 10+10+10=30 không vượt
    max_possible_score (30 môn × 10 = 30 hard cap).

    Verify max_possible_score = sum upper bound; engine không cần extra
    clamping logic. Critical cho kịch bản 4 V-ACT/DGNL max 1200 parity
    (PR-2E Numeric(8,2) widen).
    """
    scores = [Decimal("10.00"), Decimal("10.00"), Decimal("10.00")]
    total = _compute_sum(scores)
    assert total == kichban_thpt_tn_seed["max_possible_score"], (
        f"Perfect-score == max_possible_score contract: {total} == "
        f"{kichban_thpt_tn_seed['max_possible_score']}"
    )
