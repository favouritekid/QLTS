"""#7 — diacritic-insensitive (f_unaccent) search for admission profiles.

Mirrors the lead search behavior (already shipped via leadsrch01): typing
"nguyen" must match "Nguyễn". Pins BOTH the admission list query AND the
status-counts path (they share ``_name_search_condition`` → list/count parity).

User search is intentionally OUT OF SCOPE: the real /api/admin/users path
(``search_with_hierarchy`` → ``_apply_user_filters``) and the CSV export both
match on ``search_vector @@ to_tsquery`` (tsvector), not ILIKE — diacritic
folding there needs a tsvector-config change, deferred.

Requires the test DB's ``f_unaccent`` wrapper (created in
tests/fixtures/database.py for the same reason).
"""
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories import AdmissionRepository


pytestmark = pytest.mark.asyncio


async def _seed_admission(db: AsyncSession, unit_id, status_id, full_name: str):
    ts = datetime.now().timestamp()
    lead = models.Lead(
        full_name=full_name,
        phone=f"09{int(ts) % 10_000_000:07d}",
        email=f"srch_{ts:.6f}@test.com",
        source="website",
        unit_id=unit_id,
        consultation_status_id=status_id,
        status="new",
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        citizen_id=f"0{int(ts * 1000) % 10**11:011d}",
        version=1,
        applied_rules={},
        academic_year=2026,
        full_name=full_name,
        phone=lead.phone,
    )
    db.add(profile)
    await db.flush()
    return profile


async def test_admission_search_unaccent_list_and_counts(
    db: AsyncSession, seeded_dependencies: dict
):
    """Unaccented "nguyen van a" must match "Nguyễn Văn Á" in BOTH the list
    query and the status-counts aggregate (shared helper → parity)."""
    unit_id = seeded_dependencies["unit_id"]
    status_id = seeded_dependencies["initial_status_id"]
    profile = await _seed_admission(db, unit_id, status_id, "Nguyễn Văn Á")

    repo = AdmissionRepository(db)

    profiles, total = await repo.get_filtered_with_count(
        unit_id=unit_id, search="nguyen van a", limit=50,
    )
    assert any(p.id == profile.id for p in profiles), (
        "list search must f_unaccent-match the diacritic name"
    )

    counts = await repo.get_status_counts(unit_id=unit_id, search="nguyen van a")
    assert counts["total"] >= 1, (
        "status-counts must f_unaccent-match too (parity with the list query)"
    )


async def test_admission_search_unaccent_discriminates_between_profiles(
    db: AsyncSession, seeded_dependencies: dict
):
    """With TWO profiles seeded, the search must return ONLY the matching one —
    guards against an over-broad f_unaccent/ilike clause that would match both."""
    unit_id = seeded_dependencies["unit_id"]
    status_id = seeded_dependencies["initial_status_id"]
    target = await _seed_admission(db, unit_id, status_id, "Nguyễn Văn Á")
    other = await _seed_admission(db, unit_id, status_id, "Hoàng Thị Bích")

    repo = AdmissionRepository(db)
    profiles, _ = await repo.get_filtered_with_count(
        unit_id=unit_id, search="nguyen van a", limit=50,
    )
    ids = {p.id for p in profiles}
    assert target.id in ids, "matching profile must be returned"
    assert other.id not in ids, "non-matching profile must NOT be returned"
