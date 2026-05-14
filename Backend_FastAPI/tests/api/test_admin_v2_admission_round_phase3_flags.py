"""Phase 3 close-out 2026-05-14: anchor PATCH wiring tests for the two
Phase 3 ``OfferingAdmissionRound`` columns surfaced via the admin
``PATCH /api/v2/admin/rounds/{round_id}`` endpoint.

``phase3_01`` migration deployed ``allow_multi_nv BOOLEAN DEFAULT false``
and ``confirm_expiry_hours INT DEFAULT 168`` on 2026-05-12, but the
Pydantic ``AdmissionRoundUpdate`` / ``AdmissionRoundResponse`` schemas
were not wired at the same time. Without the schema wiring the columns
were unreachable from the admin UI — admin had to mutate via direct
SQL.

Non-tautological anchor (memory ``pattern-change-impact-audit``):
asserts (a) the PATCH persists the new value, (b) the same value comes
back on the next GET, and (c) the value untouched by a PATCH that
doesn't include the field stays at its previous value (no implicit
default reset). A regression that strips the field from
``AdmissionRoundUpdate`` would silently flip the assertion on (a).
"""
from __future__ import annotations

import logging
import time

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


log = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def seeded_round() -> int:
    """Create a fresh round and return its id.

    Uses a randomised ``round_code`` so concurrent test runs don't
    collide on the ``(academic_year, round_code)`` UNIQUE constraint.
    """
    # Keep year inside the 1900–2100 CHECK from Phase 1 #09a — derive from
    # the current second-of-day so each test invocation gets a unique year
    # without crossing the upper bound.
    year = 2000 + (int(time.time()) % 100)
    round_code = f"AT_{int(time.time() * 1000) % 1_000_000}"
    async with AsyncSessionLocal() as s:
        async with s.begin():
            r = models.OfferingAdmissionRound(
                academic_year=year,
                round_code=round_code,
                round_name=f"Anchor round {round_code}",
                is_active=True,
                # DB defaults: allow_multi_nv=false, confirm_expiry_hours=168
            )
            s.add(r)
            await s.flush()
            return r.id


# ---------------------------------------------------------------------
# Anchor 1 — PATCH persists allow_multi_nv
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_allow_multi_nv_persists_and_round_trips(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_round: int,
) -> None:
    """Flipping ``allow_multi_nv`` via PATCH must survive a follow-up GET.

    A regression that drops the field from ``AdmissionRoundUpdate`` would
    silently strip it on payload validation, leaving the column at the
    server_default ``false`` — the second GET assertion catches that.
    """
    patch_resp = await client.patch(
        f"/api/v2/admin/rounds/{seeded_round}",
        json={"allow_multi_nv": True},
        headers=admin_token_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    body = patch_resp.json()
    assert body["allow_multi_nv"] is True, (
        f"PATCH response should echo the new flag value, got {body!r}"
    )

    get_resp = await client.get(
        f"/api/v2/admin/rounds/{seeded_round}",
        headers=admin_token_headers,
    )
    assert get_resp.status_code == 200
    fresh = get_resp.json()
    assert fresh["allow_multi_nv"] is True
    # Untouched column stays at server_default — drift detector for
    # "PATCH bleeds defaults into untouched fields".
    assert fresh["confirm_expiry_hours"] == 168


# ---------------------------------------------------------------------
# Anchor 2 — PATCH persists confirm_expiry_hours
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_confirm_expiry_hours_persists_and_round_trips(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_round: int,
) -> None:
    """Setting ``confirm_expiry_hours=24`` (shorter window) round-trips.

    Combined with Anchor 1 this proves both new fields are independently
    addressable — schema wiring did not regress either column.
    """
    patch_resp = await client.patch(
        f"/api/v2/admin/rounds/{seeded_round}",
        json={"confirm_expiry_hours": 24},
        headers=admin_token_headers,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["confirm_expiry_hours"] == 24

    get_resp = await client.get(
        f"/api/v2/admin/rounds/{seeded_round}",
        headers=admin_token_headers,
    )
    assert get_resp.status_code == 200
    fresh = get_resp.json()
    assert fresh["confirm_expiry_hours"] == 24
    # Sibling flag untouched stays at default.
    assert fresh["allow_multi_nv"] is False


# ---------------------------------------------------------------------
# Anchor 3 — Bounds enforced by Pydantic
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_confirm_expiry_hours_rejects_out_of_range(
    client: AsyncClient,
    admin_token_headers: dict,
    seeded_round: int,
) -> None:
    """Reject 0 and >8760 (1 year ceiling).

    Bounds documented in Pydantic + Zod schemas so the FE NumberInput's
    max attribute stays aligned with the BE guard.
    """
    too_small = await client.patch(
        f"/api/v2/admin/rounds/{seeded_round}",
        json={"confirm_expiry_hours": 0},
        headers=admin_token_headers,
    )
    assert too_small.status_code == 422

    too_big = await client.patch(
        f"/api/v2/admin/rounds/{seeded_round}",
        json={"confirm_expiry_hours": 8761},
        headers=admin_token_headers,
    )
    assert too_big.status_code == 422

    # Verify nothing got mutated by the rejected payloads.
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(models.OfferingAdmissionRound).where(
                models.OfferingAdmissionRound.id == seeded_round
            )
        )
        row = result.scalar_one()
        assert row.confirm_expiry_hours == 168
