"""Phase 3 PR-3D-B BE-2 — Integration tests cho 4 admin backfill endpoints.

Endpoints under test:
- GET    /api/v2/admin/admission-backfill-exceptions
- PATCH  /api/v2/admin/admission-backfill-exceptions/{id}/resolve
- POST   /api/v2/admin/admission-backfill-exceptions/bulk-resolve
- GET    /api/v2/admin/admission-backfill-exceptions/export.csv

12 tests organized:
- A. Happy paths (4) — one per endpoint, admin scope
- B. Auth gates (2) — no-auth 401, manager DENY
- C. Service prechecks (4) — already-resolved 400, missing-ids accounting,
                            empty bulk 400, resolution_notes too short 422
- D. Filters + pagination (2) — exception_type filter + is_resolved=False filter

Non-tautological: each test asserts SPECIFIC status code + body/DB state.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal


@pytest_asyncio.fixture
async def backfill_seed(seed_lead_dependencies: dict) -> dict:
    """Seed 3 backfill exception rows on a single profile.

    Rows differ by exception_type so admin filter tests have distinct
    targets. Both unresolved initially (resolved_at = NULL).
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Backfill seed lead {ts}",
                phone=f"098{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"5{ts:08d}1"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
                uses_choice_engine=False,  # legacy → backfill exception domain
            )
            s.add(profile)
            await s.flush()

            ex_ids = []
            for tag, detail in [
                ("selected_subject_group_ambiguous", {"matches": [1, 2]}),
                ("gpa_out_of_range", {"value": -0.5}),
                ("grad_year_unparseable", {"raw": "2k25"}),
            ]:
                ex = models.AdmissionBackfillException(
                    profile_id=profile.id,
                    exception_type=tag,
                    details=detail,
                )
                s.add(ex)
                await s.flush()
                ex_ids.append(ex.id)

            return {
                "profile_id": profile.id,
                "exception_ids": ex_ids,
                "ambiguous_id": ex_ids[0],
                "gpa_id": ex_ids[1],
                "grad_year_id": ex_ids[2],
            }


# ============================================================================
# A. Happy paths (4 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_list_exceptions_happy_admin(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """GET /admin/admission-backfill-exceptions returns 3 seeded rows with
    total + items envelope.
    """
    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions",
        headers=admin_token_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 3
    assert "items" in body
    seeded_ids = set(backfill_seed["exception_ids"])
    returned_ids = {item["id"] for item in body["items"]}
    assert seeded_ids.issubset(returned_ids)


@pytest.mark.asyncio
async def test_resolve_single_happy_admin(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """PATCH /{id}/resolve marks row resolved + records resolved_by_user_id."""
    ex_id = backfill_seed["ambiguous_id"]
    response = await client.patch(
        f"/api/v2/admin/admission-backfill-exceptions/{ex_id}/resolve",
        headers=admin_token_headers,
        json={"resolution_notes": "Manually mapped to path 1 after audit."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == ex_id
    assert body["resolved_at"] is not None
    assert body["resolved_by_user_id"] is not None
    assert "Manually mapped" in body["resolution_notes"]

    # Verify DB write
    async with AsyncSessionLocal() as s:
        row = await s.get(models.AdmissionBackfillException, ex_id)
        assert row.resolved_at is not None


@pytest.mark.asyncio
async def test_bulk_resolve_happy_admin(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """POST /bulk-resolve resolves N rows + returns precise counters."""
    ids = backfill_seed["exception_ids"]
    response = await client.post(
        "/api/v2/admin/admission-backfill-exceptions/bulk-resolve",
        headers=admin_token_headers,
        json={
            "exception_ids": ids + [9999999],  # +1 missing for counter assertion
            "resolution_notes": "Bulk closed after batch backfill rerun.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requested"] == len(ids) + 1
    assert body["resolved"] == len(ids)
    assert body["missing"] == 1
    assert 9999999 in body["missing_ids"]


@pytest.mark.asyncio
async def test_export_csv_happy_admin(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """GET /export.csv returns text/csv with header row + all seeded rows."""
    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions/export.csv",
        headers=admin_token_headers,
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    text = response.text
    # Header row present
    assert "id,profile_id,exception_type" in text
    # At least 3 data rows
    assert text.count("\n") >= 4  # 1 header + 3+ data + trailing newline


# ============================================================================
# B. Auth gates (2 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_list_no_auth_returns_401(
    client: AsyncClient,
    backfill_seed: dict,
):
    """No auth → 401."""
    response = await client.get("/api/v2/admin/admission-backfill-exceptions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_manager_forbidden(
    client: AsyncClient,
    manager_token_headers: dict,
    backfill_seed: dict,
):
    """Manager role denied by require_admin gate → 403."""
    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions",
        headers=manager_token_headers,
    )
    assert response.status_code == 403


# ============================================================================
# C. Service prechecks (4 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_resolve_already_resolved_400(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """Resolve once → 200. Resolve again → 400 (idempotent reject)."""
    ex_id = backfill_seed["gpa_id"]
    payload = {"resolution_notes": "First resolution pass for tests."}
    first = await client.patch(
        f"/api/v2/admin/admission-backfill-exceptions/{ex_id}/resolve",
        headers=admin_token_headers,
        json=payload,
    )
    assert first.status_code == 200
    second = await client.patch(
        f"/api/v2/admin/admission-backfill-exceptions/{ex_id}/resolve",
        headers=admin_token_headers,
        json=payload,
    )
    assert second.status_code == 400
    assert "đã được xử lý" in second.text


@pytest.mark.asyncio
async def test_resolve_nonexistent_404(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """Resolve a non-existent ID returns 404 via IDOR gate."""
    response = await client.patch(
        "/api/v2/admin/admission-backfill-exceptions/9999999/resolve",
        headers=admin_token_headers,
        json={"resolution_notes": "should not reach service"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bulk_resolve_empty_ids_422(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """min_length=1 violated → 422 schema rejection."""
    response = await client.post(
        "/api/v2/admin/admission-backfill-exceptions/bulk-resolve",
        headers=admin_token_headers,
        json={"exception_ids": [], "resolution_notes": "should not reach service"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_resolve_notes_too_short_422(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """min_length=5 on resolution_notes — '1234' rejected at Pydantic layer."""
    ex_id = backfill_seed["grad_year_id"]
    response = await client.patch(
        f"/api/v2/admin/admission-backfill-exceptions/{ex_id}/resolve",
        headers=admin_token_headers,
        json={"resolution_notes": "1234"},
    )
    assert response.status_code == 422


# ============================================================================
# D. Filters + pagination (2 tests)
# ============================================================================


@pytest.mark.asyncio
async def test_list_filter_by_exception_type(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """Filter exception_type=selected_subject_group_ambiguous returns only
    matching row.
    """
    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions",
        headers=admin_token_headers,
        params={"exception_type": "selected_subject_group_ambiguous"},
    )
    assert response.status_code == 200
    body = response.json()
    for item in body["items"]:
        assert item["exception_type"] == "selected_subject_group_ambiguous"
    # The seeded ambiguous row should appear
    returned_ids = {item["id"] for item in body["items"]}
    assert backfill_seed["ambiguous_id"] in returned_ids


@pytest.mark.asyncio
async def test_list_filter_is_resolved_false_excludes_closed(
    client: AsyncClient,
    admin_token_headers: dict,
    backfill_seed: dict,
):
    """Resolve 1 row, then is_resolved=false filter excludes it."""
    closed_id = backfill_seed["ambiguous_id"]
    # First close it
    await client.patch(
        f"/api/v2/admin/admission-backfill-exceptions/{closed_id}/resolve",
        headers=admin_token_headers,
        json={"resolution_notes": "Closed for filter test setup."},
    )

    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions",
        headers=admin_token_headers,
        params={"is_resolved": False},
    )
    assert response.status_code == 200
    body = response.json()
    returned_ids = {item["id"] for item in body["items"]}
    # Closed row should be filtered out
    assert closed_id not in returned_ids
    # Other 2 seeded open rows should remain
    assert backfill_seed["gpa_id"] in returned_ids
    assert backfill_seed["grad_year_id"] in returned_ids


# ============================================================================
# PR-CO-4 (FU #118) — Bulk-resolve atomicity anchor
# ============================================================================


@pytest.mark.asyncio
async def test_bulk_resolve_partial_fail_rolls_back_all(backfill_seed: dict):
    """FU #118 anchor: if any row in the batch fails to persist, the
    WHOLE batch rolls back — counters never reflect a partial state.

    Strategy (reviewer M1 fix):
      - Disable session ``autoflush`` so the pre-fetch ``db.execute(SELECT)``
        cannot accidentally trigger our exploding flush BEFORE the mutation
        loop runs. Without this, the test would pass vacuously: autoflush
        would raise on the SELECT, no mutations would ever happen, and the
        fresh-session check below would trivially confirm "no writes" —
        without ever proving the service has atomicity.
      - Monkey-patch ``AsyncSession.flush`` to raise. With autoflush off
        this is hit ONLY by the explicit ``await db.flush()`` the service
        calls AFTER the mutation loop completes (admission_backfill_service.py:180).
      - Track flush invocation count so we can ASSERT the explicit
        service-level flush actually executed — proves the mutation loop
        ran before the failure injection (not skipped by an earlier raise).
      - Wrap the call in ``async with session.begin()`` so a flush failure
        rolls the whole transaction frame back (mirrors router commit
        contract).
      - Verify in a FRESH ``AsyncSessionLocal()`` (no identity-map carry-
        over per memory ``async-session-gather``) that none of the rows
        carry the mutations — atomic rollback held.

    Note: BE-2 admin backfill routes (4 endpoints under
    ``/api/v2/admin/admission-backfill-*``) use ``require_admin`` FastAPI
    dep, NOT ``CasbinAuth``. Casbin enforce matrix in
    ``test_casbin_phase3_routes.py`` therefore covers only the 4 BE-1
    choice CRUD routes; BE-2 admin gating is covered by the
    ``test_list_manager_forbidden`` style tests above.
    """
    from app.services.admission_backfill_service import (
        bulk_resolve_exceptions,
    )

    ids = backfill_seed["exception_ids"]
    notes = "Atomicity test — should be rolled back."

    failing_session = AsyncSessionLocal()
    # Disable autoflush so only the EXPLICIT service-level flush triggers
    # the exploding patch (reviewer M1 fix).
    failing_session.sync_session.autoflush = False

    flush_calls = 0

    async def _explode(*args, **kwargs):
        nonlocal flush_calls
        flush_calls += 1
        raise RuntimeError(
            "Simulated DB error mid-bulk-resolve (FU #118 anchor)"
        )

    failing_session.flush = _explode  # type: ignore[assignment]

    try:
        with pytest.raises(RuntimeError, match="Simulated DB error"):
            async with failing_session.begin():
                await bulk_resolve_exceptions(
                    failing_session,
                    exception_ids=ids,
                    resolution_notes=notes,
                    actor_id=999,
                )
    finally:
        await failing_session.close()

    # Anchor: prove our explode hook was actually reached. Without this
    # the test could PASS for the wrong reason if the service or its
    # callers raised before the mutation loop (e.g., autoflush on SELECT).
    assert flush_calls == 1, (
        f"Expected exactly 1 flush() call (the explicit service-level "
        f"flush after mutations); got {flush_calls}. If 0, autoflush "
        f"or an earlier raise short-circuited the loop and the atomicity "
        f"guarantee was NEVER exercised."
    )

    # Verify atomicity in a fresh session — no row should carry the
    # resolved_at / resolution_notes / resolved_by_user_id mutations
    # the service tried to apply.
    async with AsyncSessionLocal() as verify_session:
        result = await verify_session.execute(
            models.AdmissionBackfillException.__table__.select().where(
                models.AdmissionBackfillException.id.in_(ids)
            )
        )
        rows = list(result.mappings())
        assert len(rows) == len(ids), (
            f"Seed lost rows mid-test (expected {len(ids)}, got {len(rows)})"
        )
        for row in rows:
            assert row["resolved_at"] is None, (
                f"Row {row['id']} carries resolved_at={row['resolved_at']!r} "
                "— atomicity violated: partial write reached DB."
            )
            assert row["resolved_by_user_id"] is None
            assert row["resolution_notes"] is None
