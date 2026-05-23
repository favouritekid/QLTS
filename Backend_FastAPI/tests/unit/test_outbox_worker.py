"""B2.4 / T0-4b — real worker behavior tests.

Replaces the T0-4a no-op return-shape coverage. Exercises the
``dispatch_pending_outbox`` worker against a real
``notification_outbox`` table (via ``setup_test_database``) with
``app.tasks.notification_outbox_tasks.dispatch`` patched so the
test does not need notification_rule + template seed data.

What's locked here:

* Empty queue returns ``status=ok`` + zero counters (cheap tick is safe).
* A pending row gets ``dispatched_at`` set, ``claimed_until`` cleared,
  ``attempts`` incremented to 1.
* A dispatch failure (mock raises) leaves ``dispatched_at`` NULL,
  writes a truncated ``last_error``, clears ``claimed_until``, and
  increments ``attempts`` (so the DLQ cap eventually catches
  repeatedly-failing rows).
* A row with ``claimed_until`` in the past is re-claimed (covers
  the crashed-worker recovery scenario the lease window is designed
  for).
* A row with ``claimed_until`` in the future is **not** claimed
  (another worker holds the lease — the no-double-claim guarantee
  the ``FOR UPDATE SKIP LOCKED`` + lease pair provides).
* A row with ``attempts >= MAX_ATTEMPTS`` is excluded from the
  claim (DLQ — manual review required).
* The dispatch call gets the right kwargs from the catalog
  (``skip_preference_check`` reflects ``bypass_consent_check``,
  ``strict=True`` is forwarded so persistence errors propagate).

Concurrency note: a true two-worker race test would require a
multi-process harness because ``run_async_task`` already spawns a
fresh thread per call from the pytest event loop and Postgres'
``FOR UPDATE SKIP LOCKED`` resolves contention at the connection
level. The "active claim filter" test below covers the same
guarantee from the SQL side — it proves the predicate is applied —
without the multi-process plumbing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


# All tests need a real DB schema.
pytestmark = pytest.mark.asyncio


def _run_worker_sync():
    """Invoke the Celery task body synchronously, unwrapping the
    Celery decorator so we don't need a worker process."""
    from app.tasks.notification_outbox_tasks import dispatch_pending_outbox

    raw = getattr(dispatch_pending_outbox, "run", dispatch_pending_outbox)
    return raw()


# --- 1. Empty queue --------------------------------------------------------


async def test_empty_queue_returns_zero_claimed(setup_test_database):
    result = _run_worker_sync()
    assert result["status"] == "ok"
    assert result["claimed"] == 0
    assert result["dispatched"] == 0
    assert result["failed"] == 0
    assert result["task_id"] == "T0-4b"
    assert result.get("reason") == "queue_empty"


# --- 2. Successful dispatch ------------------------------------------------


async def test_single_pending_row_dispatched_ok_marks_dispatched_at(
    setup_test_database,
):
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    # Seed a single pending row.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = NotificationOutbox(
                event_code="admission_decision_admitted",
                payload={"profile_id": 42, "choice_priority": 1},
                idempotency_key="ADMITTED:42:1",
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    # Patch dispatch to succeed without touching real notification rules.
    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ) as mock_dispatch:
        result = _run_worker_sync()

    assert result["claimed"] == 1
    assert result["dispatched"] == 1
    assert result["failed"] == 0

    # Verify dispatch was called with the right shape.
    assert mock_dispatch.await_count == 1
    call_kwargs = mock_dispatch.call_args.kwargs
    from app.core.events import SystemEvents

    assert call_kwargs["event"] == SystemEvents.ADMISSION_DECISION_ADMITTED
    assert call_kwargs["payload"] == {"profile_id": 42, "choice_priority": 1}
    assert call_kwargs["dedupe_key"] == "ADMITTED:42:1"
    assert call_kwargs["strict"] is True
    # ADMISSION_DECISION_ADMITTED carries bypass_consent_check=True per the
    # live B2.1 catalog (verified in test_dispatch_event_wrapper).
    assert call_kwargs["skip_preference_check"] is True

    # Verify final DB state.
    async with AsyncSessionLocal() as session:
        fresh = await session.get(NotificationOutbox, row_id)
        assert fresh is not None
        assert fresh.dispatched_at is not None, "Step 3 must set dispatched_at"
        assert fresh.claimed_until is None, "Step 3 must clear claimed_until"
        assert fresh.attempts == 1, "Step 1 incremented attempts"
        assert fresh.last_error is None


async def test_post_commit_callback_is_awaited_when_dispatch_returns_one(
    setup_test_database,
):
    """``dispatch()`` returns ``(notif_ids, callback)``. The worker must
    await the callback after commit so realtime + delivery enqueue still
    fire even when the route went through the outbox."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                NotificationOutbox(
                    event_code="admission_decision_admitted",
                    payload={},
                    idempotency_key="CB-AWAIT-CHECK",
                )
            )

    callback_mock = AsyncMock()
    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], callback_mock),
    ):
        result = _run_worker_sync()

    assert result["dispatched"] == 1
    callback_mock.assert_awaited_once()


# --- 3. Dispatch failure path ---------------------------------------------


async def test_dispatch_failure_increments_attempts_writes_last_error(
    setup_test_database,
):
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = NotificationOutbox(
                event_code="admission_decision_admitted",
                payload={"profile_id": 7},
                idempotency_key="FAIL-PATH",
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        side_effect=RuntimeError("simulated dispatch failure"),
    ):
        result = _run_worker_sync()

    assert result["claimed"] == 1
    assert result["dispatched"] == 0
    assert result["failed"] == 1

    async with AsyncSessionLocal() as session:
        fresh = await session.get(NotificationOutbox, row_id)
        assert fresh is not None
        assert fresh.dispatched_at is None, "Failed row must not be marked dispatched"
        assert fresh.claimed_until is None, "Failed row releases the claim for retry"
        assert fresh.attempts == 1, "Step 1 incremented attempts even on failure"
        assert fresh.last_error is not None
        assert "simulated dispatch failure" in fresh.last_error


# --- 4. Lease expiry → re-claim --------------------------------------------


async def test_expired_claim_is_re_claimable(setup_test_database):
    """Crashed-worker recovery: row with ``claimed_until`` in the past
    must be re-claimed by a fresh worker tick. ``attempts`` increments
    each claim so the DLQ threshold still applies."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = NotificationOutbox(
                event_code="admission_decision_admitted",
                payload={},
                idempotency_key="EXPIRED-LEASE",
                attempts=1,  # previous attempt
                claimed_at=past,
                claimed_until=past,  # lease expired long ago
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ):
        result = _run_worker_sync()

    assert result["claimed"] == 1, "Expired-lease row must be re-claimable"
    assert result["dispatched"] == 1

    async with AsyncSessionLocal() as session:
        fresh = await session.get(NotificationOutbox, row_id)
        assert fresh.attempts == 2, "attempts++ on re-claim"
        assert fresh.dispatched_at is not None
        assert fresh.claimed_until is None


# --- 5. Active lease blocks re-claim --------------------------------------


async def test_active_claim_is_not_re_claimed(setup_test_database):
    """No-double-claim guarantee: row with ``claimed_until`` in the
    future must be skipped (another worker holds the lease)."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = NotificationOutbox(
                event_code="admission_decision_admitted",
                payload={},
                idempotency_key="ACTIVE-LEASE",
                attempts=1,
                claimed_at=datetime.now(timezone.utc),
                claimed_until=future,
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    # No dispatch patch — if the worker tries to dispatch this row, the
    # real ``dispatch()`` would either raise on missing rule or burn time;
    # the assertion that no dispatch happened is what matters.
    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ) as mock_dispatch:
        result = _run_worker_sync()

    assert result["claimed"] == 0
    assert result["dispatched"] == 0
    mock_dispatch.assert_not_awaited()

    async with AsyncSessionLocal() as session:
        fresh = await session.get(NotificationOutbox, row_id)
        # State unchanged — attempts still 1, claim still active.
        assert fresh.attempts == 1
        assert fresh.dispatched_at is None
        assert fresh.claimed_until == future


# --- 6. DLQ — attempts cap excludes from claim ----------------------------


async def test_max_attempts_excludes_row_from_claim(setup_test_database):
    """A row that has already failed ``MAX_ATTEMPTS`` times must not
    be re-claimed — operator must inspect ``last_error`` manually."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox
    from app.tasks.notification_outbox_tasks import MAX_ATTEMPTS

    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = NotificationOutbox(
                event_code="admission_decision_admitted",
                payload={},
                idempotency_key="DLQ-CAPPED",
                attempts=MAX_ATTEMPTS,
                last_error="prior failures",
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ) as mock_dispatch:
        result = _run_worker_sync()

    assert result["claimed"] == 0
    mock_dispatch.assert_not_awaited()

    async with AsyncSessionLocal() as session:
        fresh = await session.get(NotificationOutbox, row_id)
        # State unchanged — DLQ row stays parked.
        assert fresh.attempts == MAX_ATTEMPTS
        assert fresh.dispatched_at is None


# --- 6b. Successful retry clears stale last_error -------------------------


async def test_retry_success_clears_prior_last_error(setup_test_database):
    """A row that previously failed (``last_error`` set, ``claimed_until``
    expired, ``attempts=1``) and is now successfully retried must have
    ``last_error`` cleared along with ``dispatched_at`` being set —
    otherwise the row carries stale failure text after success and the
    operator cannot tell at a glance which rows are still failing."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            row = NotificationOutbox(
                event_code="admission_decision_admitted",
                payload={},
                idempotency_key="RETRY-CLEARS-LAST-ERROR",
                attempts=1,
                claimed_at=past,
                claimed_until=past,  # expired lease — eligible for re-claim
                last_error="prior failure: simulated dispatch error",
            )
            session.add(row)
            await session.flush()
            row_id = row.id

    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ):
        result = _run_worker_sync()

    assert result["claimed"] == 1
    assert result["dispatched"] == 1
    assert result["failed"] == 0

    async with AsyncSessionLocal() as session:
        fresh = await session.get(NotificationOutbox, row_id)
        assert fresh.dispatched_at is not None
        assert fresh.claimed_until is None
        assert fresh.last_error is None, (
            "Successful retry must clear stale last_error; "
            f"got {fresh.last_error!r}"
        )
        assert fresh.attempts == 2


# --- 6c. Lease window adapts to actual claim count ------------------------


async def test_single_row_claim_lease_is_per_row_seconds(setup_test_database):
    """The claim lease must scale with the actual number of rows claimed,
    NOT with ``BATCH_LIMIT``. A 1-row claim should hold a lease of
    roughly ``PER_ROW_TIMEOUT_SECONDS`` (~5s), not
    ``BATCH_LIMIT * PER_ROW_TIMEOUT_SECONDS`` (~500s) — otherwise a
    crashed worker on a tiny batch leaves the row blocked far longer
    than the work warrants."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox
    from app.tasks.notification_outbox_tasks import (
        BATCH_LIMIT,
        PER_ROW_TIMEOUT_SECONDS,
        _claim_batch,
    )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                NotificationOutbox(
                    event_code="admission_decision_admitted",
                    payload={},
                    idempotency_key="LEASE-SINGLE-ROW",
                )
            )

    # Call _claim_batch directly so we can inspect claimed_until before
    # Step 3 finalize clears it.
    async with AsyncSessionLocal() as session:
        pending = await _claim_batch(session)
    assert len(pending) == 1

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        row = (
            await session.execute(select(NotificationOutbox))
        ).scalar_one()
        assert row.claimed_at is not None
        assert row.claimed_until is not None
        lease_seconds = (row.claimed_until - row.claimed_at).total_seconds()

    # 1 row × 5s/row = 5s lease (NOT BATCH_LIMIT * 5 = 500s).
    expected_lease = PER_ROW_TIMEOUT_SECONDS
    naive_buggy_lease = BATCH_LIMIT * PER_ROW_TIMEOUT_SECONDS

    # Postgres computes both NOW() calls inside the same statement at
    # statement_timestamp() (same value), so the difference equals the
    # interval exactly. Allow a small tolerance for serialization
    # quirks.
    assert abs(lease_seconds - expected_lease) < 0.5, (
        f"Single-row claim lease must be ~{expected_lease}s; "
        f"got {lease_seconds}s. The naive shape would yield "
        f"~{naive_buggy_lease}s — that's the regression slot this "
        "test guards."
    )
    # Sanity: lease is well under the cap.
    assert lease_seconds < naive_buggy_lease, (
        "Lease must NOT be the BATCH_LIMIT-sized window; got "
        f"{lease_seconds}s vs naive {naive_buggy_lease}s"
    )


# --- 7. Mixed batch — some succeed, some fail -----------------------------


async def test_mixed_batch_marks_each_row_independently(setup_test_database):
    """Per-row commit/rollback isolation — a failure on row N must not
    poison rows N+1, N+2 in the same batch."""
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add_all(
                [
                    NotificationOutbox(
                        event_code="admission_decision_admitted",
                        payload={"i": 0},
                        idempotency_key="MIX-OK-0",
                    ),
                    NotificationOutbox(
                        event_code="admission_decision_admitted",
                        payload={"i": 1},
                        idempotency_key="MIX-FAIL-1",
                    ),
                    NotificationOutbox(
                        event_code="admission_decision_admitted",
                        payload={"i": 2},
                        idempotency_key="MIX-OK-2",
                    ),
                ]
            )

    # Side effect alternates ok / fail / ok for the three rows.
    call_count = {"n": 0}

    async def _alternating_dispatch(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("middle row simulated failure")
        return ([], None)

    with patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        side_effect=_alternating_dispatch,
    ):
        result = _run_worker_sync()

    assert result["claimed"] == 3
    assert result["dispatched"] == 2
    assert result["failed"] == 1

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        rows = (
            await session.execute(
                select(NotificationOutbox).order_by(NotificationOutbox.id)
            )
        ).scalars().all()
        assert len(rows) == 3
        # Row 0 + Row 2 dispatched ok; Row 1 has last_error.
        assert rows[0].dispatched_at is not None
        assert rows[1].dispatched_at is None
        assert "middle row simulated failure" in (rows[1].last_error or "")
        assert rows[2].dispatched_at is not None
        for r in rows:
            assert r.claimed_until is None  # Step 3 cleared on every row
            assert r.attempts == 1


# --- 8. P2 anchor (2026-05-22) — rooms derivation from payload -------------


async def test_worker_passes_rooms_for_admission_event(setup_test_database):
    """Anchor: worker MUST resolve rooms từ payload và pass `rooms=`
    xuống `dispatch()`. Trước fix, sensitive event qua outbox bị
    `_emit_domain_event` fail-closed do `rooms=None` (notification_dispatcher.py:281).

    Test verify contract: ``_resolve_rooms_for_event`` derived rooms
    được forward đúng kwarg `rooms=` cho dispatcher. Patch helper để
    cô lập rooms logic khỏi DB load + isolate dispatch verification.
    """
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                NotificationOutbox(
                    event_code="admission_decision_admitted",
                    payload={"application_id": 100, "lead_id": 200},
                    idempotency_key="ANCHOR-ROOMS-1",
                )
            )

    expected_rooms = ["role_admin", "unit_5", "user_room_42"]

    with patch(
        "app.tasks.notification_outbox_tasks._resolve_rooms_for_event",
        new_callable=AsyncMock,
        return_value=expected_rooms,
    ), patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ) as mock_dispatch:
        result = _run_worker_sync()

    assert result["dispatched"] == 1
    assert mock_dispatch.await_count == 1
    call_kwargs = mock_dispatch.call_args.kwargs
    # Anchor: rooms kwarg MUST be forwarded (trước fix kwarg vắng mặt)
    assert "rooms" in call_kwargs, "Worker phải pass rooms= xuống dispatch()"
    assert call_kwargs["rooms"] == expected_rooms


async def test_worker_rooms_derivation_failure_falls_back_to_none(
    setup_test_database,
):
    """Defensive: nếu `_resolve_rooms_for_event` raise (e.g., DB
    transient error khi load profile), worker fallback `rooms=None`
    thay vì crash row. Dispatcher fail-closed cho sensitive event là
    đúng contract — row vẫn được mark ``ok`` (delivery sẽ retry qua
    in-app/email path khác, không lặp outbox).
    """
    from app.database import AsyncSessionLocal
    from app.models import NotificationOutbox

    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                NotificationOutbox(
                    event_code="admission_decision_admitted",
                    payload={"application_id": 9999},  # non-existent
                    idempotency_key="ANCHOR-ROOMS-FALLBACK",
                )
            )

    with patch(
        "app.tasks.notification_outbox_tasks._resolve_rooms_for_event",
        new_callable=AsyncMock,
        side_effect=RuntimeError("simulated rooms load failure"),
    ), patch(
        "app.tasks.notification_outbox_tasks.dispatch",
        new_callable=AsyncMock,
        return_value=([], None),
    ) as mock_dispatch:
        result = _run_worker_sync()

    # Row vẫn dispatch (rooms=None forward; dispatcher sẽ fail-closed sensitive,
    # nhưng đó là decision của dispatcher, không phải của worker)
    assert result["dispatched"] == 1
    assert mock_dispatch.await_count == 1
    call_kwargs = mock_dispatch.call_args.kwargs
    assert call_kwargs.get("rooms") is None


# ---------------------------------------------------------------------------
# PR #324 Commit 4 — rooms_for_admission contract anchor (P1-2).
#
# notification_outbox_tasks + 26 other modules import this helper to build
# the scoped `rooms=` list for sensitive events (admission mutations, lead
# updates, finance transactions). It's now a public API; the contract that
# admin always sees the event + unit/officer scoping only flows through the
# lead relationship needs an explicit anchor so a refactor that flips the
# return shape (e.g., admin scoping removed, or admin moved to fallback)
# fails loudly here.
# ---------------------------------------------------------------------------
class _StubLead:
    """Minimal duck-typed lead — the helper reads two attrs via getattr."""

    def __init__(self, unit_id, assigned_officer_id):
        self.unit_id = unit_id
        self.assigned_officer_id = assigned_officer_id


class _StubProfile:
    """Profile wrapper that may or may not have a lead attached."""

    def __init__(self, lead):
        self.lead = lead


def test_rooms_for_admission_returns_three_tuple_with_lead():
    """Admin + unit + assigned officer when lead is fully populated."""
    from app.services.notification_dispatcher import rooms_for_admission

    profile = _StubProfile(_StubLead(unit_id=5, assigned_officer_id=42))
    assert rooms_for_admission(profile) == [
        "role_admin",
        "unit_5",
        "user_room_42",
    ]


def test_rooms_for_admission_returns_admin_only_when_lead_null():
    """Profile without an eager-loaded lead still emits to role_admin only.

    Caller-responsibility contract: selectinload(profile.lead) before
    dispatch. The helper degrades gracefully — admins keep visibility,
    unit/officer scoping is skipped silently. This is the fallback path
    `notification_dispatcher.py:351` documents.
    """
    from app.services.notification_dispatcher import rooms_for_admission

    profile = _StubProfile(lead=None)
    assert rooms_for_admission(profile) == ["role_admin"]


def test_rooms_for_admission_skips_officer_when_unassigned():
    """Lead present + unit set + no assigned officer → admin + unit only.

    Distinct from the lead-null case above: this covers freshly created
    leads in the distribution-pending state where unit_id is set but
    assigned_officer_id is still null. unit-room subscribers must still
    receive the event (manager fanout); officer-room is rightly skipped.
    """
    from app.services.notification_dispatcher import rooms_for_admission

    profile = _StubProfile(_StubLead(unit_id=5, assigned_officer_id=None))
    assert rooms_for_admission(profile) == ["role_admin", "unit_5"]
