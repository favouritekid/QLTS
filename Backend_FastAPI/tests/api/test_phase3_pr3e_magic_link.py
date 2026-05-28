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
async def test_consume_withdraw_happy_path(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Token issued with action_type='withdraw' → 200 + status='withdrawn'.

    FU PR-CO-2-BE-2 (2026-05-15) wires the withdraw handler. Candidate
    self-service magic-link with correct CCCD must:
      1. Transition profile to 'withdrawn' (terminal state)
      2. Stamp token.confirmed_at (one-shot consumption)
      3. Persist withdrawal reason on the profile

    Was previously a stub asserting 400 'not yet enabled' before wire.
    """
    # sts08 (lead status for withdrawn profiles) is NOT in the default
    # conftest seed list — seed it inline so lead_admission_sync can
    # update lead.consultation_status_id post-withdraw. Mirrors the
    # ``seed_sts08`` fixture in ``tests/services/test_admission_withdraw.py``.
    async with AsyncSessionLocal() as s:
        async with s.begin():
            existing = await s.get(models.ConsultationStatus, "sts08")
            if existing is None:
                s.add(
                    models.ConsultationStatus(
                        id="sts08",
                        name="Tu choi tu van",
                        color_code="#FF0000",
                        stage_id="stg02",
                    )
                )

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
                version=1,
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
    assert response.status_code == 200, (
        f"Expected 200 for wired withdraw; got {response.status_code}: {response.text}"
    )

    async with AsyncSessionLocal() as s:
        token_q = await s.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == token_value
            )
        )
        token_after = token_q.scalar_one()
        assert token_after.confirmed_at is not None, "Token must be consumed"

        profile_after = await s.get(models.AdmissionProfile, token_after.profile_id)
        assert profile_after.status == "withdrawn", (
            f"Profile must transition to 'withdrawn'; got '{profile_after.status}'"
        )


# ----------------------------------------------------------------------------
# Submit + resubmit happy-path anchors (FU PR-CO-2-BE-2 wire, 2026-05-15)
# ----------------------------------------------------------------------------
# Pre-wire these tests asserted 400 "not yet enabled" stubs. After the
# wire FU lands, both actions deliver real candidate-side flows and
# must transition the profile through the state machine.
#
# Edge cases (validation failure, state mismatch, terminal blocked,
# IDOR bypass anchor, anti-regression officer-submit) live in the
# dedicated wire test file ``test_magic_link_3_actions_wire.py`` so
# this file remains the consume-router happy-path contract suite.


@pytest.mark.asyncio
async def test_consume_resubmit_happy_path(
    client: AsyncClient,
    seed_lead_dependencies: dict,
):
    """Token action_type='resubmit' on revision_requested profile → 200.

    The state edge ``revision_requested → resubmitted`` already exists
    in ``ALLOWED_TRANSITIONS`` so the standard ``resubmit_profile``
    accepts the candidate path with ``officer=None``. Asserts the
    transition + token consumption.
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
                version=1,
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
    assert response.status_code == 200, (
        f"Expected 200 for wired resubmit; got "
        f"{response.status_code}: {response.text}"
    )

    async with AsyncSessionLocal() as s:
        token_q = await s.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == token_value
            )
        )
        token_after = token_q.scalar_one()
        assert token_after.confirmed_at is not None, "Token must be consumed"

        profile_after = await s.get(models.AdmissionProfile, token_after.profile_id)
        assert profile_after.status == "resubmitted", (
            f"Profile must transition to 'resubmitted'; "
            f"got '{profile_after.status}'"
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


# ============================================================================
# PR-2 (2026-05-28) — Magic-link submit round cutoff enforcement
#
# magic_link_service._handle_submit() delegates to
# admission_service.submit_and_evaluate(current_user=None) → cutoff gate
# trong submit_and_evaluate (PR-2 Step 3) tự fire cho magic-link path.
# Anchor end-to-end through magic-link router để khẳng định gate KHÔNG bị
# bypass khi candidate self-service submit qua link.
# ============================================================================


@pytest_asyncio.fixture
async def magic_link_submit_seed_closed_round(seed_lead_dependencies: dict) -> dict:
    """Profile draft + submit-action token + round đã đóng (end_date yesterday).

    Mô phỏng candidate fill form trong ngày cuối, click submit hôm sau —
    middleware không re-check round trước khi route, gate phải fire ở
    submit_and_evaluate.
    """
    from datetime import date, timedelta
    from decimal import Decimal

    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    citizen_id = f"7{ts:08d}1"[:12]
    last4 = citizen_id[-4:]
    token_value = secrets.token_urlsafe(32)

    async with AsyncSessionLocal() as s:
        async with s.begin():
            # Seed minimal admission config chain so applied_rules.admission_path_id
            # resolves to a real path → round (gate load path).
            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
                is_active=True,
            )
            s.add(offering); await s.flush()
            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=20,
                tuition_fee_per_year=Decimal("1000000"),
                is_published=True,
            )
            s.add(ai); await s.flush()

            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026,
            )

            method = models.AdmissionMethod(
                code=f"PR2ML_{ts}",
                name=f"PR2 ML method {ts}",
                requires_subject_scores=False,
                requires_gpa=False,
                is_active=True,
            )
            s.add(method); await s.flush()

            path = models.AdmissionPath(
                academic_info_id=ai.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                status="active",
            )
            s.add(path); await s.flush()

            # Close the round AFTER path setup so all FKs resolve cleanly
            round_obj = await s.get(models.OfferingAdmissionRound, round_id)
            round_obj.end_date = date.today() - timedelta(days=1)
            await s.flush()

            lead = models.Lead(
                full_name=f"PR-2 ML Lead {ts}",
                phone=f"097{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead); await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=citizen_id,
                status="draft",
                applied_rules={"admission_path_id": path.id},
                academic_year=2026,
            )
            s.add(profile); await s.flush()

            token = models.AdmissionConfirmationToken(
                profile_id=profile.id,
                action_type="submit",
                token=token_value,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
                confirmed_at=None,
                attempt_count=0,
            )
            s.add(token); await s.flush()

            return {
                "profile_id": profile.id,
                "lead_id": lead.id,
                "token": token_value,
                "last4": last4,
                "round_id": round_id,
                "path_id": path.id,
            }


@pytest.mark.asyncio
async def test_magic_link_submit_410_when_round_closed(
    client: AsyncClient,
    magic_link_submit_seed_closed_round: dict,
):
    """Candidate self-service magic-link submit sau round closed → 410.

    Anchor PR-2 cutoff gate fire qua magic_link_service._handle_submit
    → admission_service.submit_and_evaluate. Verify candidate KHÔNG bypass
    được cutoff qua link path (sự cố tiềm tàng nếu gate chỉ ở officer
    UI route).
    """
    response = await client.post(
        f"/api/v2/admissions/magic-link/submit/{magic_link_submit_seed_closed_round['token']}",
        json={"cccd": magic_link_submit_seed_closed_round["last4"]},
    )
    assert response.status_code == 410, (
        f"Magic-link submit sau round closed phải 410 Gone; "
        f"got {response.status_code}: {response.text[:200]}"
    )
    body = response.json()
    # Assert via stable error_code (i18n-safe) per PR #346 review nit #4.
    assert body.get("error_code") == "ROUND_CLOSED", (
        f"Error code phải 'ROUND_CLOSED'; got: {body}"
    )

    # Token must NOT be marked consumed (gate fired before _handle_submit body)
    async with AsyncSessionLocal() as s:
        token = (await s.execute(
            select(models.AdmissionConfirmationToken).where(
                models.AdmissionConfirmationToken.token == magic_link_submit_seed_closed_round["token"]
            )
        )).scalar_one()
        assert token.confirmed_at is None, (
            "Token must NOT be marked consumed when cutoff blocks submit"
        )
