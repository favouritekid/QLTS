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
# PR-1 Commit 3 (2026-05-23) — CSV export streaming + injection sanitize
# ============================================================================


@pytest.mark.asyncio
async def test_csv_export_stream_yields_one_chunk_per_row(backfill_seed: dict):
    """Per-row streaming contract — drive the generator directly.

    ``httpx.ASGITransport`` (in-process test transport) buffers the full
    ``StreamingResponse`` body before yielding to ``client.stream``, so
    chunk-count assertions can NOT be made through the HTTP layer.
    Instead, exercise ``_csv_export_stream`` directly + count yields.

    Before PR-1 Commit 3 the router materialised every row into a single
    ``io.StringIO`` then wrapped ``iter([buf.getvalue()])`` —
    ``StreamingResponse`` only ever saw one chunk. After the fix the
    body is an async generator: header chunk first, then one chunk per
    row, then end-of-stream. Pin: with 3 seeded rows we expect 4
    chunks (1 header + 3 data).
    """
    from app.routers.admin_backfill import _csv_export_stream

    async with AsyncSessionLocal() as s:
        chunks: list[bytes] = []
        finish_calls: list[int] = []

        async for chunk in _csv_export_stream(
            s,
            exception_type=None,
            is_resolved=None,
            on_finish=lambda count: finish_calls.append(count),
        ):
            chunks.append(chunk)

    # 1 header + ≥3 seeded rows. The seed fixture writes exactly 3 rows
    # for this profile but other tests in the suite may seed more, so the
    # assertion is "> 1 chunk" — pre-fix behaviour was exactly 1.
    assert len(chunks) > 1, (
        f"Expected per-row streaming (> 1 chunk) but got {len(chunks)}. "
        f"Router may have regressed to ``iter([buf.getvalue()])``."
    )
    # ``on_finish`` callback must fire exactly once with the row count
    # (rows yielded, not including the header chunk).
    assert len(finish_calls) == 1
    assert finish_calls[0] == len(chunks) - 1, (
        f"on_finish row_count {finish_calls[0]} should equal data chunks "
        f"{len(chunks) - 1} (chunks minus header)."
    )

    # First chunk MUST be the header line (preserves pre-PR-1 unquoted
    # header shape so downstream grep continues to work).
    header = chunks[0].decode("utf-8")
    assert header.startswith("id,profile_id,exception_type"), (
        f"First chunk must be header line; got: {header!r}"
    )

    # All seeded ids present somewhere in the data chunks.
    body = b"".join(chunks).decode("utf-8")
    for ex_id in backfill_seed["exception_ids"]:
        assert str(ex_id) in body, f"Seeded row id={ex_id} missing from CSV body"


@pytest.mark.asyncio
async def test_csv_export_sanitizes_formula_injection_in_resolution_notes(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_lead_dependencies: dict,
):
    """User-controlled ``resolution_notes`` cells with formula-trigger
    prefix MUST be sanitised via ``sanitize_csv_cell`` before CSV emit.

    OWASP CWE-1236. The shared helper at ``app/utils/csv_helpers.py:55``
    prepends a single quote so Excel treats the cell as text, not as a
    formula. PR-1 Commit 3 wires this into the streaming generator —
    regression here would re-open the formula-injection vector.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"Sanitize seed lead {ts}",
                phone=f"097{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"5{ts:08d}2"[:12],
                status="draft",
                applied_rules={},
                academic_year=2026,
                uses_choice_engine=False,
            )
            s.add(profile)
            await s.flush()
            ex = models.AdmissionBackfillException(
                profile_id=profile.id,
                exception_type="selected_subject_group_ambiguous",
                details={"matches": [1, 2]},
            )
            s.add(ex)
            await s.flush()
            ex_id = ex.id

    # Resolve with a dangerous-prefix notes string. Avoid characters that
    # csv would auto-quote (comma / quote / newline) so we can assert on
    # the raw cell content without quoting-layer interference.
    malicious = "=DANGEROUS_FORMULA()"
    resolve = await client.patch(
        f"/api/v2/admin/admission-backfill-exceptions/{ex_id}/resolve",
        headers=admin_token_headers,
        json={"resolution_notes": malicious},
    )
    assert resolve.status_code == 200, resolve.text

    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions/export.csv",
        headers=admin_token_headers,
        params={"exception_type": "selected_subject_group_ambiguous"},
    )
    assert response.status_code == 200
    text = response.text

    # Sanitised: cell content starts with a literal single quote followed
    # by the original formula. resolution_notes is the LAST column so it
    # is preceded by a comma and terminated by CR/LF.
    sanitised_cell = f",'{malicious}\r\n"
    assert sanitised_cell in text, (
        f"Expected sanitised cell {sanitised_cell!r} in CSV body; "
        f"first 600 chars:\n{text[:600]!r}"
    )
    # And the raw, unsanitised form (no leading single quote) MUST NOT
    # appear as a cell — that would mean sanitize_csv_cell was bypassed.
    raw_cell = f",{malicious}\r\n"
    assert raw_cell not in text, (
        f"CSV contains malicious formula unprefixed — sanitiser bypass. "
        f"CWE-1236 regression."
    )


@pytest.mark.asyncio
async def test_csv_export_handles_empty_result(
    client: AsyncClient,
    admin_token_headers: dict,
):
    """Zero matching rows still emits the header line + 200 status.

    Defensive: a filter combo that matches nothing must not raise — the
    async generator yields only the header chunk.
    """
    response = await client.get(
        "/api/v2/admin/admission-backfill-exceptions/export.csv",
        headers=admin_token_headers,
        params={"exception_type": "__nonexistent_type__"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    text = response.text
    # Header line emitted (unquoted shape, preserves pre-PR-1 contract)
    assert text.startswith("id,profile_id,exception_type"), (
        f"Expected header line as sole chunk; got: {text[:200]!r}"
    )
    # No data rows — only the header line
    lines = [line for line in text.split("\n") if line.strip()]
    assert len(lines) == 1, (
        f"Empty-result CSV should have exactly 1 line (header); got {len(lines)} lines"
    )


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
