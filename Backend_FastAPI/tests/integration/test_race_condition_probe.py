"""
Service-layer concurrency regression tests (PR8).

Background: `tests/integration/test_admission_state_transitions.py`
has TestRaceCondition cases that drive two concurrent requests through
the ASGI in-process test client and fail with [200, 200]. PR8's
investigation (docs/RACE_CONDITION_INVESTIGATION.md) showed the row
locking itself is correct — the [200, 200] is a test-harness artifact.

This module locks the *real* concurrency contract at the service
layer so a future removal of `with_for_update()` in
`approve_profile()` / `reject_profile()` breaks a fast, deterministic
test rather than slipping past the flaky HTTP tests.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app import models
from app.database import AsyncSessionLocal

from tests.integration.test_admission_state_transitions import (
    create_test_lead,
    create_admission_profile,
)


pytestmark = pytest.mark.asyncio


async def _snapshot_version_and_status(profile_id: int) -> tuple[int, str]:
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(models.AdmissionProfile.version, models.AdmissionProfile.status)
            .where(models.AdmissionProfile.id == profile_id)
        )
        v, s = row.one()
        return v, s


async def _fetch_user(user_id: int) -> models.User:
    async with AsyncSessionLocal() as session:
        return await session.get(models.User, user_id)


class TestRowLockContract:
    """FOR UPDATE behavior at the DB layer — independent of any service."""

    async def test_raw_for_update_serializes_across_sessions(
        self, seed_lead_dependencies: dict,
    ):
        """Holder locks row for ~500ms; waiter must block until commit."""
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        raw_lock_sql = text(
            "SELECT id, status, version FROM admission_profile "
            "WHERE id = :pid FOR UPDATE"
        )
        events: list[tuple[float, str]] = []

        def mark(label: str) -> None:
            events.append((asyncio.get_event_loop().time(), label))

        async def holder():
            async with AsyncSessionLocal() as session:
                await session.execute(raw_lock_sql, {"pid": profile.id})
                mark("holder:lock")
                await asyncio.sleep(0.5)
                await session.commit()
                mark("holder:commit")

        async def waiter():
            await asyncio.sleep(0.05)
            async with AsyncSessionLocal() as session:
                mark("waiter:before")
                await session.execute(raw_lock_sql, {"pid": profile.id})
                mark("waiter:lock")
                await session.rollback()

        await asyncio.gather(holder(), waiter())

        holder_commit = next(t for t, l in events if l == "holder:commit")
        waiter_lock = next(t for t, l in events if l == "waiter:lock")
        assert waiter_lock >= holder_commit - 0.005, (
            "Postgres FOR UPDATE must block the waiter until the holder "
            f"commits. Got waiter_lock={waiter_lock:.4f}, "
            f"holder_commit={holder_commit:.4f}"
        )

    async def test_service_query_for_update_serializes(
        self, seed_lead_dependencies: dict,
    ):
        """
        Exact ORM shape used by approve_profile / reject_profile.
        Regression fires if someone strips with_for_update() or
        rewrites the options() chain in a way that defeats locking.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")

        def _svc_stmt():
            return (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile.id)
                .options(
                    selectinload(models.AdmissionProfile.lead)
                    .selectinload(models.Lead.assigned_officer),
                    selectinload(models.AdmissionProfile.assigned_reviewer),
                )
                .with_for_update()
            )

        events: list[tuple[float, str]] = []

        def mark(label: str) -> None:
            events.append((asyncio.get_event_loop().time(), label))

        async def holder():
            async with AsyncSessionLocal() as session:
                await session.execute(_svc_stmt())
                mark("holder:lock")
                await asyncio.sleep(0.4)
                await session.commit()
                mark("holder:commit")

        async def waiter():
            await asyncio.sleep(0.05)
            async with AsyncSessionLocal() as session:
                await session.execute(_svc_stmt())
                mark("waiter:lock")
                await session.rollback()

        await asyncio.gather(holder(), waiter())

        holder_commit = next(t for t, l in events if l == "holder:commit")
        waiter_lock = next(t for t, l in events if l == "waiter:lock")
        assert waiter_lock >= holder_commit - 0.005, (
            "Service ORM query must acquire FOR UPDATE lock. Removing "
            "with_for_update() or adding a JOIN that defeats it will "
            "break this guarantee."
        )


class TestAdmissionServiceConcurrency:
    """
    End-to-end service layer check: two independent sessions attempt
    approve + reject simultaneously. Exactly one must succeed; the
    other must raise a state-machine / version error.

    This is the regression signal missing from the HTTP-level tests.
    If this test ever fails, production concurrency really is broken.
    """

    async def test_concurrent_approve_reject_produces_single_winner(
        self, admin_user_in_db: dict, seed_lead_dependencies: dict,
    ):
        from app.services import admission_service

        unit_id = seed_lead_dependencies["unit_id"]
        lead_id = await create_test_lead(unit_id)
        profile = await create_admission_profile(lead_id, status="submitted")
        initial_version = profile.version

        admin = await _fetch_user(admin_user_in_db["id"])

        async def approve():
            async with AsyncSessionLocal() as session:
                try:
                    result, _cb = await admission_service.approve_profile(
                        db=session,
                        profile_id=profile.id,
                        approver=admin,
                        data={"version": initial_version, "notes": "approve"},
                    )
                    await session.commit()
                    return ("ok", result.status)
                except Exception as e:
                    await session.rollback()
                    return ("err", type(e).__name__)

        async def reject():
            async with AsyncSessionLocal() as session:
                try:
                    result, _cb = await admission_service.reject_profile(
                        db=session,
                        profile_id=profile.id,
                        rejector=admin,
                        data={
                            "version": initial_version,
                            "reason": "reject reason text long enough",
                        },
                    )
                    await session.commit()
                    return ("ok", result.status)
                except Exception as e:
                    await session.rollback()
                    return ("err", type(e).__name__)

        results = await asyncio.gather(approve(), reject())

        ok = [r for r in results if r[0] == "ok"]
        err = [r for r in results if r[0] == "err"]
        assert len(ok) == 1, (
            f"Exactly one service call must succeed under concurrent "
            f"approve+reject; got {results}"
        )
        assert len(err) == 1, (
            f"Exactly one service call must fail under concurrent "
            f"approve+reject; got {results}"
        )
        # The failing call must be a known, policy-correct rejection.
        assert err[0][1] in {"BadRequest", "ConflictError"}, (
            f"Failing call should surface BadRequest (state) or "
            f"ConflictError (version); got {err[0][1]}"
        )

        final_version, final_status = await _snapshot_version_and_status(profile.id)
        assert final_version == initial_version + 1, (
            f"Version must bump exactly once across both transactions; "
            f"got {final_version} from initial {initial_version}"
        )
        assert final_status in {"approved", "rejected"}, (
            f"Final status must be one of the two targets; got {final_status!r}"
        )
