"""PR-CO-2-BE / PR-3E — Integration tests cho multi-action magic-link
consume endpoint.

Endpoint under test:
- POST /api/v2/admissions/magic-link/{action}/{token}

6 contract tests:
1. Happy path confirm: valid token + correct CCCD last4 → 200, profile.status='confirmed'
2. Action enum mismatch: URL action ≠ token row action_type → 404 (anti-enumeration)
3. CCCD wrong: increments attempt_count + returns 400 + cooldown applied
4. Expired token: expires_at in past → 400
5. Not-yet-wired actions (submit/resubmit/withdraw): → 400 BusinessRuleViolation
6. Hotfix R1 anchor: APPLICATION_STATUS_CHANGED dispatch fires after happy-path
   confirm (parity with legacy /api/admissions/confirm/{token})

Race + per-token rate-limit tests deferred to FU PR-CO-2-BE-2 (need concurrent
client harness + Redis mocking).

Non-tautological per memory `pattern-change-impact-audit`: each test asserts
SPECIFIC status code + response body shape OR DB state mutation OR dispatch
call shape.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.core.events import SystemEvents
from app.database import AsyncSessionLocal


log = logging.getLogger(__name__)


# ============================================================================
# Seed: AdmissionProfile (approved + citizen_id) + AdmissionConfirmationToken
# ============================================================================


@pytest_asyncio.fixture
async def magic_link_seed(seed_lead_dependencies: dict) -> dict:
    """Seed an approved AdmissionProfile + a fresh ``confirm`` token.

    Returns:
        dict with profile_id, lead_id, token, citizen_id, last4.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id = f"7{ts:08d}1"[:12]
    last4 = citizen_id[-4:]
    token_value = secrets.token_urlsafe(32)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"PR-3E Lead {ts}",
                phone=f"097{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="approved",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="confirm",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)
            await s.flush()

            return {
                "profile_id": profile.id,
                "lead_id": lead.id,
                "token": token_value,
                "citizen_id": citizen_id,
                "last4": last4,
            }


# ============================================================================
# 1. Happy path: confirm action with correct CCCD last 4
# ============================================================================


@pytest.mark.asyncio
async def test_consume_confirm_happy_path(
    client: AsyncClient,
    magic_link_seed: dict,
):
    """POST /magic-link/confirm/{token} with correct CCCD → 200 + status='confirmed'."""
    response = await client.post(
        f"/api/v2/admissions/magic-link/confirm/{magic_link_seed['token']}",
        json={"cccd": magic_link_seed["last4"]},
    )
    assert response.status_code == 200, (
        f"Expected 200; got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["profile_id"] == magic_link_seed["profile_id"]
    assert body["action"] == "confirm"
    assert body["status"] == "confirmed"
    assert body["consumed_at"] is not None

    # DB state mutation check
    async with AsyncSessionLocal() as s:
        profile = await s.get(models.AdmissionProfile, magic_link_seed["profile_id"])
        assert profile.status == "confirmed"
        assert profile.confirmed_at is not None

        token_q = await s.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == magic_link_seed["token"]
            )
        )
        token = token_q.scalar_one()
        assert token.confirmed_at is not None, "Token must be marked consumed"


# ============================================================================
# 2. Action enum mismatch: URL says 'submit' but token is 'confirm' → 404
# ============================================================================


@pytest.mark.asyncio
async def test_consume_action_mismatch_returns_404(
    client: AsyncClient,
    magic_link_seed: dict,
):
    """URL action 'submit' on a 'confirm' token → 404 (anti-enumeration).

    Same response shape as "token not found" — do not leak whether the token
    exists for a different action_type.
    """
    response = await client.post(
        f"/api/v2/admissions/magic-link/submit/{magic_link_seed['token']}",
        json={"cccd": magic_link_seed["last4"]},
    )
    assert response.status_code == 404, (
        f"Expected 404; got {response.status_code}: {response.text}"
    )

    # Token row should NOT have been mutated (no consume, no attempt bump)
    async with AsyncSessionLocal() as s:
        token_q = await s.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == magic_link_seed["token"]
            )
        )
        token = token_q.scalar_one()
        assert token.confirmed_at is None, "Mismatched action must NOT consume token"
        assert token.attempt_count == 0, "Mismatched action must NOT bump attempts"


# ============================================================================
# 3. CCCD wrong: attempt_count++ + 400 BadRequest
# ============================================================================


@pytest.mark.asyncio
async def test_consume_cccd_wrong_returns_400_and_increments_attempts(
    client: AsyncClient,
    magic_link_seed: dict,
):
    """Wrong CCCD last4 → 400 + attempt_count incremented + token NOT consumed."""
    response = await client.post(
        f"/api/v2/admissions/magic-link/confirm/{magic_link_seed['token']}",
        json={"cccd": "0000"},  # last 4 cannot start with 0000 in our fixture
    )
    assert response.status_code == 400, (
        f"Expected 400; got {response.status_code}: {response.text}"
    )

    async with AsyncSessionLocal() as s:
        token_q = await s.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == magic_link_seed["token"]
            )
        )
        token = token_q.scalar_one()
        assert token.confirmed_at is None, "Wrong CCCD must NOT consume token"
        assert token.attempt_count >= 1, "Wrong CCCD must bump attempt_count"


# ============================================================================
# 4. Expired token: 400 BadRequest
# ============================================================================


@pytest.mark.asyncio
async def test_consume_expired_token_returns_400(
    client: AsyncClient,
    magic_link_seed: dict,
):
    """Token with expires_at in the past → 400 with 'expired' phrasing."""
    # Backdate the token to be expired
    async with AsyncSessionLocal() as s:
        async with s.begin():
            token_q = await s.execute(
                select(models.AdmissionConfirmationToken).where(
                    models.AdmissionConfirmationToken.token == magic_link_seed["token"]
                )
            )
            token = token_q.scalar_one()
            token.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)

    response = await client.post(
        f"/api/v2/admissions/magic-link/confirm/{magic_link_seed['token']}",
        json={"cccd": magic_link_seed["last4"]},
    )
    assert response.status_code == 400, (
        f"Expected 400 for expired; got {response.status_code}: {response.text}"
    )
    assert "expired" in response.text.lower() or "hết hạn" in response.text.lower()


# ============================================================================
# 5. Not-yet-wired actions stub return 400 BusinessRuleViolation
# ============================================================================


@pytest.mark.asyncio
async def test_consume_withdraw_action_returns_400_not_implemented(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Token issued with action_type='withdraw' → 400 'not yet enabled'.

    PR-CO-2-BE infrastructure ships the 4-action router surface but only
    wires the confirm handler. submit/resubmit/withdraw are stubbed as
    BusinessRuleViolation pending FU PR-CO-2-BE-2.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id = f"7{ts:08d}2"[:12]
    last4 = citizen_id[-4:]
    token_value = secrets.token_urlsafe(32)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"PR-3E Withdraw Lead {ts}",
                phone=f"096{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="submitted",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="withdraw",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)

    response = await client.post(
        f"/api/v2/admissions/magic-link/withdraw/{token_value}",
        json={"cccd": last4},
    )
    assert response.status_code == 400, (
        f"Expected 400 for not-yet-wired; got {response.status_code}: {response.text}"
    )
    assert "not yet enabled" in response.text.lower() or "withdraw" in response.text.lower()


# ----------------------------------------------------------------------------
# H2 (review FU) — parity stub anchors for the other 2 not-yet-wired actions
# ----------------------------------------------------------------------------
# The PR-CO-2-BE infrastructure ships the 4-action router but only wires
# the confirm handler; submit/resubmit/withdraw all return
# ``BusinessRuleViolation`` 400 "not yet enabled" until FU PR-CO-2-BE-2.
# The withdraw branch already had a stub anchor — this FU adds parity
# coverage for submit + resubmit so a future wire of any single action
# (without the others) cannot silently turn a 400 into a 500 / 200 here.
#
# Non-tautological per memory ``pattern-change-impact-audit``: each test
# seeds an action-typed token + asserts the exact status code + body text
# ("not yet enabled" or the action name) — the next dev wiring an action
# must either (a) flip the stub assertion to a happy-path assertion, or
# (b) remove the stub test entirely. Either signal makes the wire-up
# explicit.


@pytest.mark.asyncio
async def test_consume_submit_action_returns_400_not_implemented(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Token issued with action_type='submit' → 400 'not yet enabled'.

    Mirror of ``test_consume_withdraw_action_returns_400_not_implemented``
    for the submit branch. PR-CO-2-BE infrastructure ships the router
    surface; submit handler is stubbed pending FU PR-CO-2-BE-2.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id = f"7{ts:08d}3"[:12]
    last4 = citizen_id[-4:]
    token_value = secrets.token_urlsafe(32)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"PR-3E Submit Lead {ts}",
                phone=f"095{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="draft",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="submit",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)

    response = await client.post(
        f"/api/v2/admissions/magic-link/submit/{token_value}",
        json={"cccd": last4},
    )
    assert response.status_code == 400, (
        f"Expected 400 for not-yet-wired submit; got "
        f"{response.status_code}: {response.text}"
    )
    assert (
        "not yet enabled" in response.text.lower()
        or "submit" in response.text.lower()
    )


@pytest.mark.asyncio
async def test_consume_resubmit_action_returns_400_not_implemented(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Token issued with action_type='resubmit' → 400 'not yet enabled'.

    Mirror of the withdraw + submit stub anchors. Closes H2 review
    finding by giving each of the 3 not-yet-wired actions a parity
    assertion so a partial wire-up cannot silently regress the
    stubs that remain.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id = f"7{ts:08d}4"[:12]
    last4 = citizen_id[-4:]
    token_value = secrets.token_urlsafe(32)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"PR-3E Resubmit Lead {ts}",
                phone=f"094{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="revision_requested",
                applied_rules={},
                academic_year=2026,
            )
            s.add(profile)
            await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="resubmit",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token)

    response = await client.post(
        f"/api/v2/admissions/magic-link/resubmit/{token_value}",
        json={"cccd": last4},
    )
    assert response.status_code == 400, (
        f"Expected 400 for not-yet-wired resubmit; got "
        f"{response.status_code}: {response.text}"
    )
    assert (
        "not yet enabled" in response.text.lower()
        or "resubmit" in response.text.lower()
    )


# ============================================================================
# 6. Hotfix R1: APPLICATION_STATUS_CHANGED dispatch fires after confirm
# ============================================================================


@pytest.mark.asyncio
async def test_consume_confirm_dispatches_status_changed_event(
    client: AsyncClient,
    magic_link_seed: dict,
):
    """Hotfix R1 anchor: v2 router MUST broadcast APPLICATION_STATUS_CHANGED.

    The legacy /api/admissions/confirm/{token} (admissions.py:2160-2174)
    fires this event after the candidate-facing callback so officer /
    admin / socket clients see the status flip realtime. PR-CO-2-BE
    initially missed this dispatch — this anchor prevents regression.

    Asserts:
      - safe_dispatch called once
      - event = APPLICATION_STATUS_CHANGED
      - payload contains application_id + lead_id + new_status='confirmed'
      - dedupe_key namespaced on profile.id
    """
    with patch(
        "app.routers.admissions_magic_link.safe_dispatch",
        new=AsyncMock(),
    ) as mock_dispatch:
        response = await client.post(
            f"/api/v2/admissions/magic-link/confirm/{magic_link_seed['token']}",
            json={"cccd": magic_link_seed["last4"]},
        )

    assert response.status_code == 200, (
        f"Happy-path confirm broke; got {response.status_code}: {response.text}"
    )
    assert mock_dispatch.call_count == 1, (
        f"Expected 1 APPLICATION_STATUS_CHANGED dispatch, got {mock_dispatch.call_count}"
    )

    _, kwargs = mock_dispatch.call_args
    assert kwargs["event"] is SystemEvents.APPLICATION_STATUS_CHANGED
    payload = kwargs["payload"]
    assert payload["application_id"] == magic_link_seed["profile_id"]
    assert payload["lead_id"] == magic_link_seed["lead_id"]
    assert payload["new_status"] == "confirmed"
    assert payload["old_status"] == "approved"
    assert kwargs["dedupe_key"] == f"admission_profile_confirmed:{magic_link_seed['profile_id']}"
