"""PR0 — admission stats must exclude profiles of soft-deleted leads.

``AdmissionProfile`` has no soft-delete column; a profile is "deleted" when its
parent ``Lead.deleted_at`` is set. The list / status-counts / aggregate /
distinct-years read paths all JOIN ``Lead`` but historically did NOT filter
``Lead.deleted_at``, so a soft-deleted lead's profiles leaked into counts,
``conversion_rate``, and the academic-year dropdown. These tests pin the
exclusion across all four paths.
"""

import itertools
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.admission_config.profile_data import ProfileDocument
from app.repositories import AdmissionRepository


pytestmark = pytest.mark.asyncio

# Monotonic sequence → unique citizen_id / phone / email regardless of timing
# (guards uq_citizen_academic_year + lead phone/email uniqueness).
_seed_seq = itertools.count(1)


async def _seed_profile(
    db: AsyncSession,
    unit_id,
    status_id,
    *,
    deleted: bool = False,
    academic_year: int = 2099,
    status: str = "submitted",
) -> models.AdmissionProfile:
    """Seed one Lead + AdmissionProfile. ``deleted`` soft-deletes the parent lead."""
    n = next(_seed_seq)
    lead = models.Lead(
        full_name=f"SoftDelete Lead {n}",
        phone=f"09{n:08d}",
        email=f"sd_{n}@test.com",
        source="website",
        unit_id=unit_id,
        consultation_status_id=status_id,
        status="new",
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status=status,
        citizen_id=f"{n:012d}",
        version=1,
        applied_rules={},
        academic_year=academic_year,
    )
    db.add(profile)
    await db.flush()
    return profile


async def test_soft_deleted_lead_excluded_from_list_status_and_aggregate(
    db: AsyncSession, seeded_dependencies: dict
):
    """A profile whose parent lead is soft-deleted must NOT appear in the list,
    status-counts, or aggregate stats. An isolated academic_year keeps totals
    exact regardless of any other seeded data."""
    unit_id = seeded_dependencies["unit_id"]
    status_id = seeded_dependencies["initial_status_id"]
    year = 2099

    active = await _seed_profile(
        db, unit_id, status_id, deleted=False, academic_year=year
    )
    deleted = await _seed_profile(
        db, unit_id, status_id, deleted=True, academic_year=year
    )

    repo = AdmissionRepository(db)

    # 1) list query (count + data share base_conditions)
    profiles, total = await repo.get_filtered_with_count(
        unit_id=unit_id,
        academic_year=year,
        limit=50,
    )
    ids = {p.id for p in profiles}
    assert active.id in ids, "active lead's profile must be listed"
    assert deleted.id not in ids, "soft-deleted lead's profile must NOT be listed"
    assert total == 1, "count must exclude the soft-deleted lead's profile"

    # 2) status counts (via _build_base_conditions)
    counts = await repo.get_status_counts(unit_id=unit_id, academic_year=year)
    assert counts["total"] == 1, "status-counts total must exclude soft-deleted"

    # 3) aggregate stats (feeds total_profiles + conversion_rate)
    agg = await repo.get_aggregate_stats(unit_id=unit_id, academic_year=year)
    assert agg["total_profiles"] == 1, "aggregate total must exclude soft-deleted"
    assert agg["submitted_count"] == 1


async def test_soft_deleted_lead_year_not_leaked_into_distinct_years(
    db: AsyncSession, seeded_dependencies: dict
):
    """get_distinct_academic_years must not surface a year that exists ONLY via a
    soft-deleted lead's profile (otherwise the year dropdown leaks it)."""
    unit_id = seeded_dependencies["unit_id"]
    status_id = seeded_dependencies["initial_status_id"]

    await _seed_profile(db, unit_id, status_id, deleted=False, academic_year=2099)
    await _seed_profile(db, unit_id, status_id, deleted=True, academic_year=2098)

    repo = AdmissionRepository(db)
    years = await repo.get_distinct_academic_years(unit_id=unit_id)

    assert 2099 in years, "active lead's year must be present"
    assert 2098 not in years, "year only via soft-deleted lead must be excluded"


async def test_soft_deleted_lead_excluded_from_pending_diploma(
    db: AsyncSession, seeded_dependencies: dict
):
    """list_profiles_with_pending_diploma (live diploma-debt reminder) must not
    return profiles whose parent lead is soft-deleted."""
    unit_id = seeded_dependencies["unit_id"]
    status_id = seeded_dependencies["initial_status_id"]

    active = await _seed_profile(
        db, unit_id, status_id, deleted=False, academic_year=2097
    )
    deleted = await _seed_profile(
        db, unit_id, status_id, deleted=True, academic_year=2097
    )

    # Attach a provisional-cert diploma doc to each. The query filters on
    # graduation_proof_kind only (category is irrelevant), so priority_evidence
    # keeps the seed FK-free (no ConfigDocumentType row needed).
    for idx, p in enumerate((active, deleted)):
        db.add(
            ProfileDocument(
                profile_id=p.id,
                category="priority_evidence",
                priority_sub_code=f"{idx:02d}",
                status="paper_submitted",
                graduation_proof_kind="provisional_cert",
            )
        )
    await db.flush()

    repo = AdmissionRepository(db)
    profiles = await repo.list_profiles_with_pending_diploma(unit_id=unit_id)
    ids = {p.id for p in profiles}
    assert active.id in ids, "active lead's pending-diploma profile must be listed"
    assert deleted.id not in ids, "soft-deleted lead's profile must NOT be reminded"
