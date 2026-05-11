"""Phase 2 v8.2 PR-2F Wave 2 — kịch bản 4: Xét tuyển thẳng.

Scenario: thí sinh thuộc đối tượng ưu tiên (HS giỏi cấp tỉnh / quốc gia /
con thương binh / dân tộc thiểu số) được tuyển thẳng — bypass GPA + điểm
thi threshold. Criteria: ``min_gpa = NULL`` + ``min_score = NULL`` +
``conditions`` text mô tả đối tượng ưu tiên.

Anchor tests: priority bypass contract — NULL gpa/score thresholds nghĩa
là engine không apply numeric filter; eligibility quyết định bởi conditions
text + admin manual review (defer Phase 3 multi-NV automation).
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
async def kichban_tuyen_thang_seed(seed_lead_dependencies: dict) -> dict:
    """Seed kịch bản 4: criteria xét tuyển thẳng với min thresholds = NULL."""
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
                annual_admission_quota=5,  # Quota ưu tiên nhỏ
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )

            method = models.AdmissionMethod(
                code=f"TT{ts}"[:20], name=f"Tuyển thẳng {ts}",
                requires_gpa=False, requires_subject_scores=False,
                is_active=True,
            )
            s.add(method); await s.flush()

            # min_score=0 (constraint requires non-null nhưng 0 = no filter
            # effectively per AdmissionCriteria.conditions text dùng cho
            # qualitative gate).
            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"TT{ts}"[:20], name=f"TT {ts}",
                min_score=Decimal("0.00"),
                conditions="HS giỏi cấp tỉnh trở lên HOẶC con thương binh HOẶC dân tộc thiểu số",
                policy_version="2026.1", is_active=True,
            )
            s.add(criteria); await s.flush()

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
                "method_requires_gpa": False,
                "method_requires_subject_scores": False,
            }


@pytest.mark.asyncio
async def test_kichban_tuyen_thang_no_score_threshold(
    kichban_tuyen_thang_seed: dict,
):
    """ANCHOR: tuyển thẳng method KHÔNG requires_gpa + KHÔNG requires_subject_scores.

    Engine contract: nếu method.requires_* = False, engine skip numeric
    threshold check; eligibility quyết định bởi qualitative conditions +
    admin manual review trên `applied_rules.priority_object` snapshot.
    """
    async with AsyncSessionLocal() as s:
        method = await s.get(
            models.AdmissionMethod,
            (await s.get(models.AdmissionCriteria, kichban_tuyen_thang_seed["criteria_id"])).method_id,
        )
        assert method.requires_gpa is False, "Tuyển thẳng method KHÔNG cần GPA"
        assert method.requires_subject_scores is False, (
            "Tuyển thẳng method KHÔNG cần subject scores"
        )


@pytest.mark.asyncio
async def test_kichban_tuyen_thang_conditions_text_documented(
    kichban_tuyen_thang_seed: dict,
):
    """ANCHOR contract: criteria.conditions text non-empty cho qualitative gate.

    Tuyển thẳng dùng `conditions` text mô tả đối tượng ưu tiên — admin
    parse + verify thủ công ở Phase 1+2. Phase 3 sẽ tự động hóa qua
    `priority_object` enum + auto-eligibility check.
    """
    async with AsyncSessionLocal() as s:
        criteria = await s.get(
            models.AdmissionCriteria, kichban_tuyen_thang_seed["criteria_id"],
        )
        assert criteria.conditions is not None, (
            "Conditions text required cho tuyển thẳng qualitative gate"
        )
        assert len(criteria.conditions) > 10, (
            "Conditions text phải đủ thông tin (ít nhất 1 đối tượng ưu tiên)"
        )
        # Quan trọng: conditions chứa từ khóa đối tượng ưu tiên cho
        # admin parsing tool tương lai.
        priority_keywords = ["HS giỏi", "thương binh", "dân tộc thiểu số"]
        matched = [kw for kw in priority_keywords if kw in criteria.conditions]
        assert len(matched) >= 1, (
            f"Conditions phải mention ít nhất 1 priority keyword: "
            f"{priority_keywords}, got: '{criteria.conditions}'"
        )
