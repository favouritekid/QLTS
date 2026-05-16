"""QA Wave 7 anchors — W7-C.1 mark-as-read empty array + W7-A.1 race 409.

Wave 7 (2026-05-16) adversarial findings on notification + admission race.

**W7-C.1** 🟥 MAJOR — `POST /api/notifications/mark-as-read {"notification_ids":[]}`
marked ALL unread của user (truthy check on `[]` falsy → ID filter skipped
→ get_unread_for_user returned all unread).

Fix: `if notification_ids is not None:` thay vì `if notification_ids:`
(notification_repository.py:112).

**W7-A.1** 🟧 MAJOR — Concurrent approve race returns 400 "Invalid
transition" thay vì 409 ConflictError. Service ran state validation
BEFORE version check, so racing reviewer hit "approved → approved" guard
first instead of optimistic-lock guard.

Fix: swap version check BEFORE state validation in 4 services
(approve_profile, reject_profile, request_revision, mark_student_dropped).

Anchors hit the actual HTTP boundary (no mocks) to verify both:
- behavior is correct (response code, no unintended state change)
- guard order survives future refactor
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# W7-C.1 — notifications/mark-as-read empty array
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_3_unread_notifications(admin_user_in_db: dict) -> dict:
    """Seed 3 unread notifications for the admin user."""
    user_id = admin_user_in_db["id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            for i in range(3):
                n = models.Notification(
                    user_id=user_id,
                    title=f"W7-C.1 test {i}",
                    message=f"unread test notification {i}",
                    type="info",
                    is_read=False,
                    created_at=datetime.now(timezone.utc),
                )
                s.add(n)
    return {"user_id": user_id, "seeded_count": 3}


async def test_mark_as_read_empty_array_is_noop(
    client: AsyncClient,
    admin_token_headers: dict,
    seed_3_unread_notifications: dict,
):
    """`notification_ids=[]` MUST mark zero notifications (W7-C.1 fix).

    Pre-fix: marked ALL 3 unread → mass read flag wipe.
    Post-fix: marks 0 (explicit None vs empty list distinction).
    """
    response = await client.post(
        "/api/notifications/mark-as-read",
        headers=admin_token_headers,
        json={"notification_ids": []},
    )
    assert response.status_code == 200, response.text
    # Response wording: "Marked N notification(s) as read"
    assert "Marked 0" in response.text, (
        f"Empty array must be no-op (Marked 0); got: {response.text[:300]}"
    )

    # Verify DB state — all 3 still unread
    user_id = seed_3_unread_notifications["user_id"]
    async with AsyncSessionLocal() as s:
        unread_query = (
            select(models.Notification)
            .where(
                models.Notification.user_id == user_id,
                models.Notification.is_read == False,
                models.Notification.title.like("W7-C.1 test%"),
            )
        )
        result = await s.execute(unread_query)
        unread_rows = result.scalars().all()
    assert len(unread_rows) == 3, (
        f"All 3 seeded unread must remain unread; found {len(unread_rows)}"
    )


# ---------------------------------------------------------------------------
# W7-A.1 — race version check returns 409, not 400
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seed_submitted_profile_v1(seed_lead_dependencies: dict) -> dict:
    """Seed a submitted profile at version=1 ready for race test."""
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name="W7-A.1 race subject",
                phone="0900000007",
                unit_id=seed_lead_dependencies["unit_id"],
                pipeline_stage_id=seed_lead_dependencies["stage_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"W7A1{int(datetime.now(timezone.utc).timestamp() * 1000) % 99999999:08d}"[:12],
                status="submitted",
                applied_rules={},
                academic_year=2026,
                uses_choice_engine=False,
            )
            s.add(profile)
            await s.flush()
            return {"profile_id": profile.id, "version": profile.version}


async def test_stale_version_approve_returns_409_not_400(
    client: AsyncClient,
    manager_token_headers: dict,
    seed_submitted_profile_v1: dict,
):
    """Approve with stale version → 409 ConflictError (W7-A.1 fix).

    Pre-fix: state machine ran FIRST. If status changed (e.g. test bumps
    version externally), Manager sent stale version → state would still
    match submitted → version check would raise 409. The race-specific
    bug surfaced when status had ALREADY changed (`approved→approved` is
    invalid transition) → 400 fired before version check.

    Anchor simulates the post-race state: profile.version bumped to 2
    externally, manager still posts version=1 with stale state expectation.
    Now: version check fires first → 409.
    """
    profile_id = seed_submitted_profile_v1["profile_id"]
    stale_version = seed_submitted_profile_v1["version"]

    # Externally bump version + flip to approved to simulate "another
    # reviewer already committed". The 2-client parallel race is harder
    # to deterministically reproduce in tests; this single-client stale-
    # version probe still exercises the W7-A.1 fix path because:
    #   Pre-fix: validate_transition("approved","approved") → 400
    #   Post-fix: version check 2 != 1 → 409 before state validation
    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "approved"
            profile.version = stale_version + 1

    response = await client.post(
        f"/api/admissions/{profile_id}/approve",
        headers=manager_token_headers,
        json={"version": stale_version, "notes": "stale version race probe"},
    )
    assert response.status_code == 409, (
        f"Stale version + post-commit state must return 409 ConflictError; "
        f"got {response.status_code}: {response.text[:300]}"
    )
    # Error message should suggest refresh — UX contract
    assert "modified by another user" in response.text or "version" in response.text.lower()


async def test_stale_version_reject_returns_409_not_400(
    client: AsyncClient,
    manager_token_headers: dict,
    seed_submitted_profile_v1: dict,
):
    """Same anchor for reject_profile (mirror W7-A.1 fix)."""
    profile_id = seed_submitted_profile_v1["profile_id"]
    stale_version = seed_submitted_profile_v1["version"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "rejected"
            profile.version = stale_version + 1

    response = await client.post(
        f"/api/admissions/{profile_id}/reject",
        headers=manager_token_headers,
        json={"version": stale_version, "reason": "stale reject probe (>=10 chars)"},
    )
    assert response.status_code == 409, (
        f"Stale version reject must return 409 ConflictError; "
        f"got {response.status_code}: {response.text[:300]}"
    )


async def test_stale_version_request_revision_returns_409_not_400(
    client: AsyncClient,
    manager_token_headers: dict,
    seed_submitted_profile_v1: dict,
):
    """Same anchor for request_revision (mirror W7-A.1 fix)."""
    profile_id = seed_submitted_profile_v1["profile_id"]
    stale_version = seed_submitted_profile_v1["version"]

    async with AsyncSessionLocal() as s:
        async with s.begin():
            profile = await s.get(models.AdmissionProfile, profile_id)
            profile.status = "revision_requested"
            profile.version = stale_version + 1

    response = await client.post(
        f"/api/admissions/{profile_id}/request-revision",
        headers=manager_token_headers,
        json={"version": stale_version, "reason": "stale revision probe (>=10 chars)"},
    )
    assert response.status_code == 409, (
        f"Stale version request-revision must return 409 ConflictError; "
        f"got {response.status_code}: {response.text[:300]}"
    )
