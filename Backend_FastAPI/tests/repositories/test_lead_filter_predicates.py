# tests/repositories/test_lead_filter_predicates.py
"""Repository-level tests for the lead filter predicates added by
LEAD_FILTER_UX_PLAN §3-§4.5:

- B1 search unaccent (f_unaccent on full_name)
- B2 actionable filters: unassigned / overdue / next_activity_from-to /
  no_consultation / is_hot
- B3 consultation_status_id (single + multi, mirrors pipeline_stage_id)

These exercise ``LeadRepository.get_filtered`` directly (no auth layer), so
they assert the SQL predicate logic. RBAC scope (officer forced to self) is
verified at the BE layer here via the empty-AND anchor
(``assigned_officer_id`` + ``unassigned`` → 0 rows) and end-to-end through
the API in ``tests/api/test_lead_filters_api.py``.

Test DB note: ``f_unaccent`` + ``unaccent`` are created by the test bootstrap
(``tests/fixtures/database.py``) since the DB is built with create_all(), not
Alembic (memory ``test-db-schema-source``).
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app import models
from app.repositories import LeadRepository

ACCEPTED_STATUS_ID = "sts06"   # "Đồng ý tư vấn" (non-final)
GIVEUP_STATUS_ID = "sts20"     # "Đã ngừng tư vấn" (final)


@pytest_asyncio.fixture
async def filter_dataset(db, seeded_dependencies, officer_user_in_db) -> dict:
    """Seed a small, fully-controlled dataset covering every new predicate.

    L1 "Nguyễn Văn Hùng": officer, hot, cc=5, overdue,   status=sts06
    L2 "Trần Thị Bình":   UNASSIGNED, cold, cc=0, future, status=sts20(final)
    L3 "Lê Văn Cường":    officer, cold, cc=3, na=NULL,   status=initial
    L4 "Phạm Thị Dung":   officer, hot, cc=0, overdue,    status=sts06
    """
    unit_id = seeded_dependencies["unit_id"]
    stage_id = seeded_dependencies["stage_id"]
    initial_status_id = seeded_dependencies["initial_status_id"]
    officer_id = officer_user_in_db["id"]

    db.add_all([
        models.ConsultationStatus(
            id=ACCEPTED_STATUS_ID, name="Đồng ý tư vấn",
            color_code="#00AA00", stage_id=stage_id, is_final=False,
        ),
        models.ConsultationStatus(
            id=GIVEUP_STATUS_ID, name="Đã ngừng tư vấn",
            color_code="#AA0000", stage_id=stage_id, is_final=True,
        ),
    ])
    await db.flush()

    now = datetime.now(timezone.utc)

    def _lead(name, phone, **kw):
        base = dict(
            full_name=name, phone=phone, source="Website", unit_id=unit_id,
            status=initial_status_id, pipeline_stage_id=stage_id,
        )
        base.update(kw)
        return models.Lead(**base)

    leads = {
        "L1": _lead(
            "Nguyễn Văn Hùng", "0900000001",
            consultation_status_id=ACCEPTED_STATUS_ID,
            assigned_officer_id=officer_id, assigned_at=now,
            is_hot_lead=True, consultation_count=5,
            next_activity_at=now - timedelta(hours=2),
        ),
        "L2": _lead(
            "Trần Thị Bình", "0900000002",
            consultation_status_id=GIVEUP_STATUS_ID,
            assigned_officer_id=None, assigned_at=None,
            is_hot_lead=False, consultation_count=0,
            next_activity_at=now + timedelta(hours=48),
        ),
        "L3": _lead(
            "Lê Văn Cường", "0900000003",
            consultation_status_id=initial_status_id,
            assigned_officer_id=officer_id, assigned_at=now,
            is_hot_lead=False, consultation_count=3,
            next_activity_at=None,
        ),
        "L4": _lead(
            "Phạm Thị Dung", "0900000004",
            consultation_status_id=ACCEPTED_STATUS_ID,
            assigned_officer_id=officer_id, assigned_at=now,
            is_hot_lead=True, consultation_count=0,
            next_activity_at=now - timedelta(minutes=30),
        ),
    }
    db.add_all(list(leads.values()))
    await db.flush()
    for lead in leads.values():
        await db.refresh(lead)

    return {
        "officer_id": officer_id,
        "ids": {k: v.id for k, v in leads.items()},
        "all_ids": {v.id for v in leads.values()},
    }


async def _run(db, **filters) -> set:
    """Run get_filtered and return the set of matched lead ids."""
    repo = LeadRepository(db)
    _total, leads = await repo.get_filtered(skip=0, limit=100, **filters)
    return {lead.id for lead in leads}


# ============================================================================
# B1 — Search unaccent
# ============================================================================

@pytest.mark.asyncio
async def test_search_unaccent_matches_without_diacritics(db, filter_dataset):
    ids = filter_dataset["ids"]
    # "nguyen van" (no diacritics) matches "Nguyễn Văn Hùng"
    assert ids["L1"] in await _run(db, search="nguyen van")
    # case-insensitive
    assert ids["L1"] in await _run(db, search="NGUYEN")
    # accented input still works
    assert ids["L2"] in await _run(db, search="trần")


@pytest.mark.asyncio
async def test_search_unaccent_does_not_overmatch(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(db, search="Nguyen Vana")
    assert ids["L1"] not in res


# ============================================================================
# B2 — Actionable filters
# ============================================================================

@pytest.mark.asyncio
async def test_unassigned_only_null_officer(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(db, unassigned=True)
    assert ids["L2"] in res
    assert ids["L1"] not in res
    assert ids["L3"] not in res
    assert ids["L4"] not in res


@pytest.mark.asyncio
async def test_overdue_realtime_excludes_future_and_null(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(db, overdue=True)
    assert {ids["L1"], ids["L4"]} <= res   # past next_activity_at
    assert ids["L2"] not in res            # future
    assert ids["L3"] not in res            # NULL next_activity_at


@pytest.mark.asyncio
async def test_next_activity_range(db, filter_dataset):
    ids = filter_dataset["ids"]
    now = datetime.now(timezone.utc)
    # from now+24h → only the future lead (L2 at +48h)
    res_from = await _run(db, next_activity_from=now + timedelta(hours=24))
    assert ids["L2"] in res_from
    assert ids["L1"] not in res_from and ids["L4"] not in res_from
    assert ids["L3"] not in res_from       # NULL never in a range
    # until now → only the overdue (past) leads
    res_to = await _run(db, next_activity_to=now)
    assert {ids["L1"], ids["L4"]} <= res_to
    assert ids["L2"] not in res_to and ids["L3"] not in res_to


@pytest.mark.asyncio
async def test_no_consultation_zero_count(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(db, no_consultation=True)
    assert {ids["L2"], ids["L4"]} <= res   # consultation_count == 0
    assert ids["L1"] not in res            # cc=5
    assert ids["L3"] not in res            # cc=3


@pytest.mark.asyncio
async def test_is_hot_only_hot_leads(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(db, is_hot=True)
    assert {ids["L1"], ids["L4"]} <= res
    assert ids["L2"] not in res
    assert ids["L3"] not in res


@pytest.mark.asyncio
async def test_falsey_bool_params_do_not_filter(db, filter_dataset):
    """unassigned=False / overdue=False must NOT invert — they are no-ops."""
    all_ids = filter_dataset["all_ids"]
    res = await _run(db, unassigned=False, overdue=False, is_hot=False,
                     no_consultation=False)
    assert all_ids <= res


# ============================================================================
# B3 — consultation_status_id (mirror pipeline_stage_id)
# ============================================================================

@pytest.mark.asyncio
async def test_consultation_status_single(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(db, consultation_status_id=ACCEPTED_STATUS_ID)
    assert {ids["L1"], ids["L4"]} <= res
    assert ids["L2"] not in res
    assert ids["L3"] not in res


@pytest.mark.asyncio
async def test_consultation_status_multi(db, filter_dataset):
    ids = filter_dataset["ids"]
    res = await _run(
        db, consultation_status_id=f"{ACCEPTED_STATUS_ID},{GIVEUP_STATUS_ID}"
    )
    assert {ids["L1"], ids["L4"], ids["L2"]} <= res
    assert ids["L3"] not in res


# ============================================================================
# Combos + RBAC (BE) anchor
# ============================================================================

@pytest.mark.asyncio
async def test_combo_overdue_hot_officer(db, filter_dataset):
    ids = filter_dataset["ids"]
    officer_id = filter_dataset["officer_id"]
    res = await _run(
        db, overdue=True, is_hot=True, assigned_officer_id=str(officer_id)
    )
    assert {ids["L1"], ids["L4"]} <= res
    assert ids["L2"] not in res
    assert ids["L3"] not in res


@pytest.mark.asyncio
async def test_officer_plus_unassigned_is_empty_and(db, filter_dataset):
    """RBAC anchor at BE: officer scope (assigned_officer_id == self) AND
    unassigned (assigned_officer_id IS NULL) can never both hold → 0 rows.
    (deps.py forces effective_officer_id=self for officers.)"""
    officer_id = filter_dataset["officer_id"]
    res = await _run(
        db, assigned_officer_id=str(officer_id), unassigned=True
    )
    assert res == set()


@pytest.mark.asyncio
async def test_consultation_status_with_is_final(db, filter_dataset):
    ids = filter_dataset["ids"]
    # sts20 is final → present with is_final=True
    res_final = await _run(
        db, consultation_status_id=GIVEUP_STATUS_ID, is_final=True
    )
    assert ids["L2"] in res_final
    # sts06 is non-final: present under is_final=False, ABSENT under is_final=True
    # — proves is_final actually discriminates rather than being a no-op for
    # this status (the same sts06 set flips on the is_final value).
    res_nonfinal = await _run(
        db, consultation_status_id=ACCEPTED_STATUS_ID, is_final=False
    )
    assert {ids["L1"], ids["L4"]} <= res_nonfinal
    res_empty = await _run(
        db, consultation_status_id=ACCEPTED_STATUS_ID, is_final=True
    )
    assert ids["L1"] not in res_empty
    assert ids["L4"] not in res_empty
