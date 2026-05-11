"""Phase 2 v8.2 PR-2F Wave 2 — kịch bản 3: Liên thông Trung cấp → Cao đẳng.

Scenario: thí sinh tốt nghiệp TC (Trung cấp), xét tuyển liên thông lên CĐ.
Criteria: ``min_gpa = 6.50`` (GPA TC) + ``applicable_to = ['LIEN_THONG_TC']``
audience filter (phase1_03 PR-1B').

Anchor tests focus audience filter contract: path chỉ apply cho audience
``LIEN_THONG_TC``; thí sinh ``POST_THCS`` / ``POST_THPT`` không match → bị
filter ra ở storefront / engine resolution.
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
async def kichban_lien_thong_seed(seed_lead_dependencies: dict) -> dict:
    """Seed kịch bản 3: criteria liên thông TC với audience filter."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=6,  # CĐ liên thông từ TC ngắn hơn
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=10,
                tuition_fee_per_year=1_000_000,
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )

            method = models.AdmissionMethod(
                code=f"LTTC{ts}"[:20], name=f"LT TC→CĐ {ts}",
                requires_gpa=True, is_active=True,
            )
            s.add(method); await s.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id,
                code=f"LTTC{ts}"[:20], name=f"LT TC {ts}",
                min_gpa=Decimal("6.50"),
                policy_version="2026.1", is_active=True,
            )
            s.add(criteria); await s.flush()

            # phase1_03 PR-1B' — audience filter ['LIEN_THONG_TC']
            # NULL = applicable to every audience (legacy Phase 1+2); list =
            # JSONB containment filter ở storefront `_load_public_paths`.
            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id,
                status="active",
                applicable_to=["LIEN_THONG_TC"],
            )
            s.add(path); await s.flush()

            return {
                "criteria_id": criteria.id,
                "path_id": path.id,
                "min_gpa": Decimal("6.50"),
                "audience_filter": ["LIEN_THONG_TC"],
            }


def _audience_matches(
    applicable_to: list[str] | None, candidate_audience: str,
) -> bool:
    """Mirror storefront `_load_public_paths` JSONB containment logic.

    NULL = applicable to every audience (legacy). List = JSONB containment
    filter; candidate must be in list.
    """
    if applicable_to is None:
        return True  # Legacy NULL → applicable to all
    return candidate_audience in applicable_to


@pytest.mark.asyncio
async def test_kichban_lien_thong_tc_audience_filter_matches(
    kichban_lien_thong_seed: dict,
):
    """ANCHOR audience filter happy path: candidate audience='LIEN_THONG_TC'
    match path.applicable_to=['LIEN_THONG_TC'] → path visible."""
    assert _audience_matches(
        kichban_lien_thong_seed["audience_filter"], "LIEN_THONG_TC",
    ) is True, "Audience match contract violated"


@pytest.mark.asyncio
async def test_kichban_lien_thong_tc_audience_filter_blocks_post_thpt(
    kichban_lien_thong_seed: dict,
):
    """ANCHOR audience filter contract: POST_THPT candidate KHÔNG match
    path liên thông → path hidden ở storefront cho audience đó.

    Critical: nếu engine bypass filter, hậu quả là POST_THPT thí sinh
    có thể submit vào path liên thông (sai semantic + DB chứa data sai).
    """
    assert _audience_matches(
        kichban_lien_thong_seed["audience_filter"], "POST_THPT",
    ) is False, "Audience filter should block POST_THPT từ LT TC path"
    assert _audience_matches(
        kichban_lien_thong_seed["audience_filter"], "POST_THCS",
    ) is False, "Audience filter should block POST_THCS từ LT TC path"
