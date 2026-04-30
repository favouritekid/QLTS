"""ADM-011 — verify ``bulk_assign`` takes a row lock + writes accurate
audit chain even under concurrent assignment from two managers.

Background
----------
Pre-fix, ``admission_service.bulk_assign`` looped through profiles
without ``with_for_update()`` and without optimistic version check.
Two managers in the same unit clicking bulk-assign on overlapping
profiles in the same sub-second window could silently overwrite
each other — second writer's commit beats first, audit log of the
loser records ``old=NULL`` (stale read) instead of the actual
intermediate state.

Sister service ``bulk_approve`` already runs under
``with_for_update()`` + optimistic version check; ``bulk_assign``
was missed.

Fix shape
---------
- Sort ``profile_ids`` ascending so every caller takes locks in the
  same global order — eliminates the deadlock cycle a non-sorted
  loop would create when two managers bulk-assign the same set in
  different orders.
- ``select(...).with_for_update()`` per profile — second concurrent
  caller blocks until first commits, then sees the post-first state
  and writes against it. Audit log chain stays accurate.
- Bump ``profile.version`` so any optimistic-lock callers (UI
  ``If-Match``-style) see the change.

Tests anchor against business reality, not helper SQL — run real
concurrent ``bulk_assign`` calls and assert the resulting audit log
+ DB state are internally consistent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app import models
from app.core.constants import UserRole
from app.database import AsyncSessionLocal
from app.services import admission_service


ADMISSIONS = "/api/admissions"


@pytest_asyncio.fixture
async def concurrency_setup(
    seed_lead_dependencies: dict, admin_user_in_db: dict
):
    """Seed a path + 3 profiles + 2 officer targets so the concurrency
    test has real rows to lock.

    Two officers (X and Y) both in the same unit so the assigner-unit
    rule stays out of the way — the lock is the variable under test.
    """
    from app.security import get_password_hash

    uid = seed_lead_dependencies["unit_id"]
    mpid = seed_lead_dependencies["major_program_id"]
    ts = f"{int(datetime.now().timestamp() * 1000)}"

    async with AsyncSessionLocal() as s:
        async with s.begin():
            ot = models.ConfigOfferingType(
                code=f"tq_{ts}", name=f"TQ_{ts}", display_order=1
            )
            s.add(ot)
            await s.flush()
            po = models.ProgramOffering(
                offering_type=f"TQ_{ts}",
                program_id=mpid,
                offering_type_id=ot.id,
                is_active=True,
                duration_semesters=6,
            )
            s.add(po)
            await s.flush()

            # Two officer targets — both must be active + role=officer
            # + same unit as assigner (admin bypasses last rule).
            officer_x = models.User(
                username=f"adm011_officer_x_{ts}",
                email=f"adm011_x_{ts}@test.com",
                password_hash=get_password_hash("Test!1234567890"),
                role=UserRole.OFFICER,
                status="active",
                unit_id=uid,
            )
            officer_y = models.User(
                username=f"adm011_officer_y_{ts}",
                email=f"adm011_y_{ts}@test.com",
                password_hash=get_password_hash("Test!1234567890"),
                role=UserRole.OFFICER,
                status="active",
                unit_id=uid,
            )
            s.add_all([officer_x, officer_y])
            await s.flush()

            # Three leads + draft profiles to bulk-assign across.
            profile_ids = []
            for i in range(3):
                lead = models.Lead(
                    full_name=f"ADM011 Lead {i} {ts}",
                    phone=(
                        f"098"
                        f"{int(datetime.now().timestamp() * 1000) % 10**7:07d}"
                    ),
                    email=f"adm011_lead_{i}_{ts}@test.com",
                    source="website",
                    unit_id=uid,
                    offering_id=po.id,
                )
                s.add(lead)
                await s.flush()
                profile = models.AdmissionProfile(
                    lead_id=lead.id,
                    status="submitted",
                    citizen_id=(
                        f"012345"
                        f"{int(datetime.now().timestamp() * 1000) % 10**6:06d}"
                    ),
                    academic_year=2026,
                    version=1,
                    applied_rules={},
                )
                s.add(profile)
                await s.flush()
                profile_ids.append(profile.id)

    return {
        "unit_id": uid,
        "officer_x_id": officer_x.id,
        "officer_y_id": officer_y.id,
        "admin_id": admin_user_in_db["id"],
        "profile_ids": profile_ids,
    }


async def _bulk_assign_in_own_session(
    profile_ids: list[int],
    officer_id: int,
    assigner_id: int,
) -> Dict[str, Any]:
    """Run ``admission_service.bulk_assign`` inside its own
    ``AsyncSessionLocal`` and commit. Each concurrent caller MUST get
    its own session (per memory ``feedback_async_session_gather``) —
    sharing one would race on SQLAlchemy's identity map regardless
    of what Postgres locks do.
    """
    async with AsyncSessionLocal() as session:
        try:
            assigner = await session.get(models.User, assigner_id)
            result = await admission_service.bulk_assign(
                db=session,
                profile_ids=profile_ids,
                officer_id=officer_id,
                assigner=assigner,
            )
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


@pytest.mark.asyncio
async def test_bulk_assign_locks_and_writes_accurate_audit_chain(
    concurrency_setup: dict,
):
    """Two concurrent ``bulk_assign`` calls (X then Y) on the same
    profile must serialize via the row lock — second caller blocks
    until first commits, then sees the post-first state and writes
    against it. Final state: lead.assigned_officer_id is one of
    {X, Y}; audit log has TWO entries; the second entry's ``old``
    value matches the ``new`` value of the first.

    Anchor against business reality (audit log chain), not against
    SQL emitted — a future change that drops the lock would leave
    audit chain broken (second entry shows old=NULL) even if the
    final state happens to coincide.
    """
    setup = concurrency_setup
    profile_id = setup["profile_ids"][0]

    # Run both concurrently. Postgres ``FOR UPDATE`` will serialise
    # them; without the lock, both reads happen before either write
    # commits and the audit chain breaks.
    results = await asyncio.gather(
        _bulk_assign_in_own_session(
            [profile_id], setup["officer_x_id"], setup["admin_id"]
        ),
        _bulk_assign_in_own_session(
            [profile_id], setup["officer_y_id"], setup["admin_id"]
        ),
    )

    # Both calls must succeed.
    assert all(r["success_count"] == 1 for r in results), results

    # Final lead.assigned_officer_id ∈ {X, Y}.
    async with AsyncSessionLocal() as s:
        rows = (
            await s.execute(
                select(models.AdmissionProfile, models.Lead)
                .join(models.Lead)
                .where(models.AdmissionProfile.id == profile_id)
            )
        ).first()
        profile, lead = rows
        assert lead.assigned_officer_id in (
            setup["officer_x_id"],
            setup["officer_y_id"],
        )
        # ``profile.version`` deliberately NOT bumped on assignment —
        # bulk_assign writes ``lead.assigned_officer_id`` (lead-level
        # op), not a profile field. Asserting version stays unchanged
        # guards against a future change that bumps it here and
        # forces unrelated UI callers to refetch.
        assert profile.version == 1, (
            f"Profile version should NOT change on bulk_assign "
            f"(lead-level op), got {profile.version}"
        )
        # ``lead.version`` MUST bump per successful assignment — the
        # FOR UPDATE serialises 2 calls so they bump sequentially
        # (1 → 2 → 3). Without the bump, a stale-snapshot client
        # could overwrite our assignment without optimistic-lock
        # rejecting it.
        assert lead.version == 3, (
            f"Lead version should bump twice (1→2→3) under 2 "
            f"sequential locked writes, got {lead.version}"
        )

    # Audit chain: 2 entries, second's old == first's new.
    async with AsyncSessionLocal() as s:
        audit_rows = (
            (
                await s.execute(
                    select(models.EntityAuditLog)
                    .where(
                        models.EntityAuditLog.entity_type == "Lead",
                        models.EntityAuditLog.entity_id == lead.id,
                        models.EntityAuditLog.action == "assigned",
                    )
                    .order_by(models.EntityAuditLog.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    assert (
        len(audit_rows) >= 2
    ), f"Expected ≥2 audit rows for lead {lead.id}, got {len(audit_rows)}"
    # First entry's ``old`` may be NULL (lead seeded without officer)
    # or a prior officer; what matters is the second entry's old ==
    # first entry's new — that's the chain-integrity invariant.
    first = audit_rows[0]
    second = audit_rows[1]
    first_change = (first.changes or {}).get("assigned_officer_id") or {}
    second_change = (second.changes or {}).get("assigned_officer_id") or {}
    assert second_change.get("old") == first_change.get("new"), (
        "Audit chain broken — second entry's old value does not match "
        f"first entry's new. First: {first_change}, Second: {second_change}. "
        "This is the regression flagged by ADM-011."
    )


@pytest.mark.asyncio
async def test_bulk_assign_sort_ascending_no_deadlock(
    concurrency_setup: dict,
):
    """Two concurrent ``bulk_assign`` calls passing the SAME profile
    set in DIFFERENT orders must not deadlock. Sort-ascending in the
    service guarantees both callers acquire locks in the same global
    order (id 1 → id 2 → id 3), eliminating the deadlock cycle.

    Without the sort, caller A locks 1 then 2 while caller B locks
    2 then 1 — classic AB-BA deadlock. Postgres would detect and
    abort one with ``DeadlockDetectedError``; the test would catch
    that exception and fail.
    """
    setup = concurrency_setup
    pids = setup["profile_ids"]  # [p1, p2, p3]

    # Caller A gets [p1, p2, p3]; caller B gets [p3, p2, p1].
    # Without service-level sort, lock order would diverge → deadlock.
    results = await asyncio.gather(
        _bulk_assign_in_own_session(
            list(pids), setup["officer_x_id"], setup["admin_id"]
        ),
        _bulk_assign_in_own_session(
            list(reversed(pids)), setup["officer_y_id"], setup["admin_id"]
        ),
        return_exceptions=True,
    )

    # No deadlock means both calls returned a result dict (not an
    # exception). DeadlockDetectedError would surface here as the
    # exception object in ``results``.
    for idx, r in enumerate(results):
        assert not isinstance(r, BaseException), (
            f"Caller {idx} raised {type(r).__name__}: {r}. "
            "ADM-011 sort-ascending guarantee was supposed to "
            "prevent this."
        )
        assert r["success_count"] == 3, (
            f"Caller {idx} only assigned {r['success_count']}/3 — "
            f"errors={r.get('errors')}"
        )

    # Final state: each profile's lead.assigned_officer_id ∈ {X, Y}.
    async with AsyncSessionLocal() as s:
        for pid in pids:
            row = (
                await s.execute(
                    select(models.Lead)
                    .join(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == pid)
                )
            ).scalar_one()
            assert row.assigned_officer_id in (
                setup["officer_x_id"],
                setup["officer_y_id"],
            ), (
                f"Profile {pid} lead unexpected "
                f"officer={row.assigned_officer_id}"
            )


@pytest.mark.asyncio
async def test_bulk_assign_blocks_when_lead_row_locked_by_outside_writer(
    concurrency_setup: dict,
):
    """Stronger anchor than ``asyncio.gather`` — that test could
    false-pass if the asyncio scheduler ran sessions sequentially
    (no real concurrent DB hit) AND the implementation forgot the
    lock entirely. This test proves the lock is REAL by holding it
    from an outside session and measuring that ``bulk_assign``
    physically blocks waiting for it.

    Pattern:
    1. Session A holds ``SELECT ... FOR UPDATE`` on the lead row —
       mimics any concurrent assignment writer (admission
       ``bulk_assign`` itself, ``lead_service.assign_lead_manually``,
       auto-assignment, future writers).
    2. Spawn session B's ``bulk_assign`` as a background task.
    3. Wait 500ms — assert task hasn't completed (B is blocked).
    4. Release A's lock.
    5. Wait task → measure elapsed; assert > 400ms (real wait, not
       race-through).

    If the service drops ``with_for_update(of=Lead)``, B never
    blocks → finishes in tens of ms → assertion in step 3 fails.
    Anchor against business reality (real DB lock contention),
    not against an asyncio scheduler artefact.
    """
    import time

    setup = concurrency_setup
    profile_id = setup["profile_ids"][0]

    # Resolve lead_id once (outside the locked transaction).
    async with AsyncSessionLocal() as s:
        lead_id = (
            await s.execute(
                select(models.Lead.id)
                .join(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == profile_id)
            )
        ).scalar_one()

    b_done = asyncio.Event()
    elapsed_holder: dict = {}

    async def _run_b():
        start = time.monotonic()
        try:
            async with AsyncSessionLocal() as b:
                admin = await b.get(models.User, setup["admin_id"])
                await admission_service.bulk_assign(
                    db=b,
                    profile_ids=[profile_id],
                    officer_id=setup["officer_x_id"],
                    assigner=admin,
                )
                await b.commit()
        finally:
            elapsed_holder["seconds"] = time.monotonic() - start
            b_done.set()

    # Session A holds the FOR UPDATE lock on the lead row.
    async with AsyncSessionLocal() as a:
        await a.execute(
            text("SELECT id FROM lead WHERE id = :id FOR UPDATE"),
            {"id": lead_id},
        )

        # Start B in background; B should attempt FOR UPDATE on the
        # same lead row → block.
        b_task = asyncio.create_task(_run_b())

        # Give B 500ms to try and fail the lock attempt. With the
        # service correctly taking ``with_for_update(of=Lead)``, B
        # will block on the row lock A holds → ``b_done`` stays
        # unset.
        try:
            await asyncio.wait_for(b_done.wait(), timeout=0.5)
            # If we reach here, B finished BEFORE we released A —
            # that means the lock was NOT actually taken by B.
            pytest.fail(
                "bulk_assign completed without waiting for the "
                "lead-row FOR UPDATE lock — service is NOT locking "
                f"correctly (elapsed={elapsed_holder.get('seconds')}s)"
            )
        except asyncio.TimeoutError:
            # Expected — B is correctly blocked.
            pass

        # Release A's lock.
        await a.rollback()

    # B should now complete. Allow generous timeout — Windows CI can
    # be slow.
    await asyncio.wait_for(b_task, timeout=5.0)

    # Sanity: B's elapsed time must reflect the wait (≥ ~400ms of
    # the 500ms barrier). A pure race-through would finish in tens
    # of ms.
    elapsed = elapsed_holder.get("seconds", 0.0)
    assert elapsed > 0.4, (
        f"bulk_assign elapsed {elapsed:.3f}s — too fast to have "
        "actually waited on the lock. Service may not be holding "
        "the FOR UPDATE."
    )

    # Final state: assignment succeeded after lock release.
    async with AsyncSessionLocal() as s:
        lead = (
            await s.execute(
                select(models.Lead).where(models.Lead.id == lead_id)
            )
        ).scalar_one()
        assert lead.assigned_officer_id == setup["officer_x_id"]
