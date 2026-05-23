# app/tasks/notification_outbox_tasks.py
"""B2.4 / T0-4b — real notification outbox worker.

Replaces the T0-4a no-op skeleton. Drains rows that B2.3's
``dispatch_event()`` wrapper inserts into the ``notification_outbox``
table (B2.2 / M-1-19a) for the seven ``requires_outbox=True`` events
in the B2.1 catalog.

Implements PLAN §3.3.f's three-step claim/dispatch/finalize loop:

1. **Short tx claim** (2-step CTE).
   ``SELECT id FOR UPDATE SKIP LOCKED`` filters pending +
   retry-eligible rows; the same statement ``UPDATE``s the locked
   set with ``claimed_at`` / ``claimed_until`` / ``attempts++`` and
   ``RETURNING`` the payload. Two workers cannot claim the same row
   (Postgres ``SKIP LOCKED``); the ``attempts < MAX_ATTEMPTS`` filter
   keeps repeatedly-failing rows out of the queue (manual DLQ
   review). The ``claimed_until`` lease lets a different worker
   re-claim rows orphaned by a crashed worker after the lease
   expires.

2. **Per-row dispatch loop** (no claim lock held — connection
   returned to the pool between Step 1 and Step 2).
   For each claimed row we resolve ``event_code`` → ``SystemEvents``
   enum, look up the catalog for ``bypass_consent_check``, and call
   ``dispatch(strict=True)``. Worker manages its own commit; the
   ``strict=True`` flag makes persistence errors propagate so this
   loop can mark the row as failed instead of silently rolling back
   (memory ``dispatch-bundle-strict-required``). The post-commit
   callback (socket.io / delivery enqueue) is awaited best-effort —
   callback failures are logged but do not fail the row, mirroring
   ``safe_dispatch()``'s convention for the same kind of work.

3. **Short tx finalize** (one tx for all rows).
   Each ``ok`` row gets ``dispatched_at = NOW()`` + ``claimed_until =
   NULL``; each ``error`` row gets ``last_error`` written and
   ``claimed_until = NULL`` so a retry cycle can pick it up again
   until ``attempts >= MAX_ATTEMPTS``.

This module is allowlisted as a raw ``dispatch()`` caller in
``app/scripts/check_notification_event_coverage.py`` (per B2.3) —
service code must use ``dispatch_event()``, but the worker IS the
dispatcher for outbox-flagged events.

Beat schedule contract (T0-4a → T0-4b transition; do not break):

* Task name ``dispatch_pending_outbox`` — beat entry
  ``dispatch-pending-outbox`` points at it (registered in
  ``app/celery_app.py``).
* Beat fires with zero args (cadence in ``app/celery_app.py``).
* Result dict shape carries ``status`` + ``task_id`` (load-bearing
  for ops monitoring); B2.4 adds ``claimed`` / ``dispatched`` /
  ``failed`` counters and flips ``task_id`` from ``"T0-4a"`` to
  ``"T0-4b"``.

See ``Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`` §3.5
T0-4b and ``Documents/ADMISSION_REFACTOR_PLAN.md`` §3.3.e/f.
"""
import logging

from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from ..celery_app import celery_app
from ..core.event_catalog import get_event
from ..core.events import SystemEvents
from ..services.notification_dispatcher import (
    rooms_for_admission,
    rooms_for_lead,
    rooms_for_user,
    dispatch,
)
from .utils import run_async_task, task_db_session


log = logging.getLogger("dispatch_pending_outbox")


# Worker tunables. Surfaced as module-level constants so tests +
# operators can reason about the lease window and DLQ threshold
# without grepping a magic number.
BATCH_LIMIT = 100
MAX_ATTEMPTS = 5
PER_ROW_TIMEOUT_SECONDS = 5
CLAIM_TIMEOUT_CAP_SECONDS = 600

# Discriminator to let ops tell the skeleton tick (T0-4a) apart from
# the real worker tick (T0-4b) in result dicts / log greps.
TASK_ID = "T0-4b"


@celery_app.task(name="dispatch_pending_outbox")
def dispatch_pending_outbox() -> dict:
    """Drain a batch of pending ``notification_outbox`` rows.

    Beat fires this with zero args. Returns a structured result
    so monitoring can count claimed / dispatched / failed rows
    per tick.
    """
    return run_async_task(
        async_func=_drain_outbox,
        task_name="dispatch_pending_outbox",
        task_log=log,
        validate_keys=["status", "claimed", "dispatched", "failed", "task_id"],
    )


async def _drain_outbox() -> dict:
    """Async body — 3-step claim/dispatch/finalize."""
    async with task_db_session() as session:
        pending = await _claim_batch(session)
        if not pending:
            log.info(
                "dispatch_pending_outbox: queue empty",
                extra={"task_id": TASK_ID, "claimed": 0},
            )
            return {
                "status": "ok",
                "claimed": 0,
                "dispatched": 0,
                "failed": 0,
                "task_id": TASK_ID,
                "reason": "queue_empty",
            }

        results = await _dispatch_each(session, pending)
        await _finalize(session, results)

    ok_count = sum(1 for _, status, _ in results if status == "ok")
    failed_count = sum(1 for _, status, _ in results if status == "error")
    log.info(
        "dispatch_pending_outbox: tick complete",
        extra={
            "task_id": TASK_ID,
            "claimed": len(pending),
            "dispatched": ok_count,
            "failed": failed_count,
        },
    )
    return {
        "status": "ok",
        "claimed": len(pending),
        "dispatched": ok_count,
        "failed": failed_count,
        "task_id": TASK_ID,
    }


async def _claim_batch(session) -> list[tuple]:
    """Step 1 — atomic 2-step CTE claim.

    Postgres-only: ``FOR UPDATE SKIP LOCKED`` is required for the
    no-double-claim guarantee. The CTE ``candidates`` selects up to
    ``BATCH_LIMIT`` row ids; the outer ``UPDATE ... WHERE id IN
    (SELECT id FROM candidates)`` mutates only those rows. This is
    the FIXED v2.3 pattern — the v2.2 ``UPDATE ... RETURNING ...``
    bug attempted to combine select-and-update into a single
    statement and ended up updating every pending row in the table
    (only the first 100 rows came back through ``fetchmany``, but
    the others still saw ``attempts++`` + a ``claimed_until``
    that no one held). Splitting into a CTE keeps the ``UPDATE``
    target set to exactly the locked candidates.

    The ``claimed_until`` lease is sized adaptively from the actual
    candidate count, computed inline via ``(SELECT COUNT(*) FROM
    candidates)``: ``LEAST(count * PER_ROW_TIMEOUT_SECONDS,
    CLAIM_TIMEOUT_CAP_SECONDS)`` seconds. A small batch (1-3 rows)
    gets a tight lease (~5-15s) so a crashed worker frees the rows
    quickly; a full 100-row batch gets up to the 600s cap so it
    has time to drain through external IO. Sizing the lease to
    ``BATCH_LIMIT * PER_ROW_TIMEOUT_SECONDS`` for every claim
    (regardless of how many rows actually claimed) — the prior
    naive shape — left a 1-row claim holding a 500s lease, which
    blocked recovery for far longer than the work warranted.

    Postgres materializes the ``candidates`` CTE once per
    statement, so the COUNT and the ``WHERE id IN (SELECT id ...)``
    both read the same materialized rowset — no double-locking
    or re-evaluation.
    """
    async with session.begin():
        rows = (
            await session.execute(
                text(
                    """
                    WITH candidates AS (
                        SELECT id FROM notification_outbox
                        WHERE dispatched_at IS NULL
                          AND attempts < :max_attempts
                          AND (claimed_until IS NULL OR claimed_until < NOW())
                        ORDER BY created_at
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE notification_outbox
                    SET claimed_at = NOW(),
                        claimed_until = NOW() + (interval '1 second' * LEAST(
                            (SELECT COUNT(*) FROM candidates) * :per_row_seconds,
                            :cap_seconds
                        )),
                        attempts = attempts + 1
                    WHERE id IN (SELECT id FROM candidates)
                    RETURNING id, event_code, payload, idempotency_key
                    """
                ),
                {
                    "max_attempts": MAX_ATTEMPTS,
                    "limit": BATCH_LIMIT,
                    "per_row_seconds": PER_ROW_TIMEOUT_SECONDS,
                    "cap_seconds": CLAIM_TIMEOUT_CAP_SECONDS,
                },
            )
        ).fetchall()
    return [(r.id, r.event_code, r.payload, r.idempotency_key) for r in rows]


async def _resolve_rooms_for_event(
    session,
    event: SystemEvents,
    payload: dict,
) -> Optional[list[str]]:
    """Derive Socket.IO target rooms cho 1 outbox row.

    P2 fix 2026-05-22 — bridge contract gap giữa outbox và dispatcher.
    Trước đây worker gọi ``dispatch(rooms=None)`` → dispatcher với
    ``SOCKET_SCOPED_EMIT=True`` (default) fail-closes sensitive event
    tại ``notification_dispatcher.py:281`` ("Sensitive event broadcast
    blocked: missing rooms"). Hệ quả: 6 ADMISSION_* events
    (RESULT_PUBLISHED, DECISION_ADMITTED/WAITLISTED/REJECTED,
    WAITLIST_PROMOTED/REJECTED) + các sensitive event khác đi qua outbox
    KHÔNG bao giờ tới Socket.IO browser dù FE đã có listener.

    Strategy: payload chứa entity ID (``application_id`` / ``lead_id`` /
    ``user_id``); load entity với eager-load + gọi helper room derivation
    có sẵn ở dispatcher module. Pattern mirror ``admission_tasks.py:127-141,
    196`` đã sử dụng cùng helper trong scope khác.

    Returns:
        List rooms cho dispatcher target, hoặc None nếu không derive được
        (dispatcher sẽ fail-closed cho sensitive event — đúng contract).
        Public event không cần rooms (dispatcher broadcast global).

    Note: helper safety — ``rooms_for_admission(None)`` trả
    ``["role_admin"]`` thay vì crash, nên fallback luôn có admin
    visibility tối thiểu khi profile bị delete giữa outbox INSERT và
    worker drain.
    """
    from .. import models

    # Admission-scoped events: payload chứa application_id (= profile.id)
    # per admission_state_service.py:459-470 payload contract.
    app_id = payload.get("application_id")
    if isinstance(app_id, int):
        stmt = (
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == app_id)
            .options(selectinload(models.AdmissionProfile.lead))
        )
        result = await session.execute(stmt)
        profile = result.scalar_one_or_none()
        return rooms_for_admission(profile)

    # Lead-scoped events: payload chứa lead_id.
    lead_id = payload.get("lead_id")
    if isinstance(lead_id, int):
        lead = await session.get(models.Lead, lead_id)
        return rooms_for_lead(lead)

    # User-targeted events: payload chứa user_id / target_user_id.
    user_id = payload.get("user_id") or payload.get("target_user_id")
    if isinstance(user_id, int):
        return rooms_for_user(user_id)

    # Public event (organization_*, pipeline_config_*) — dispatcher tự
    # broadcast global, rooms=None là intended path.
    return None


async def _dispatch_each(session, pending) -> list[tuple]:
    """Step 2 — per-row dispatch (no claim lock held).

    Each row owns its own commit/rollback. ``dispatch(strict=True)``
    raises on persistence error so the loop can mark the row as
    failed instead of leaking ``PendingRollbackError`` state into
    the next iteration.

    The post-commit callback (``notif_cb``) emits the realtime
    domain event + enqueues delivery tasks (Zalo / email / SMS).
    Callback failures are non-fatal — ``safe_dispatch()`` swallows
    them in its own pattern; the worker matches that here so a
    transient socket.io blip cannot cause repeated re-dispatch
    of the same outbox row.
    """
    results: list[tuple] = []
    for row_id, event_code, payload, idem_key in pending:
        # Resolve ``event_code`` (string column) → ``SystemEvents`` enum.
        try:
            event = SystemEvents(event_code)
        except ValueError:
            results.append(
                (row_id, "error", f"unknown event_code: {event_code!r}")
            )
            continue
        event_def = get_event(event)
        if event_def is None:
            results.append(
                (
                    row_id,
                    "error",
                    f"event {event.name} not in EVENT_CATALOG",
                )
            )
            continue

        # P2 fix 2026-05-22 — derive Socket.IO rooms từ payload trước
        # khi gọi dispatcher. Trước đây không truyền rooms → fail-closed
        # tại _emit_domain_event cho mọi sensitive event qua outbox path.
        try:
            rooms = await _resolve_rooms_for_event(session, event, payload)
        except Exception as room_err:  # noqa: BLE001
            # Defensive: rooms derivation failure không được crash worker
            # — nếu sensitive event, dispatcher sẽ fail-closed như cũ
            # (đúng contract); nếu public event, broadcast global vẫn ok.
            log.warning(
                "Outbox rooms derivation failed (non-fatal); fallback to None",
                extra={
                    "row_id": row_id,
                    "event_code": event_code,
                    "error": str(room_err)[:200],
                },
            )
            rooms = None

        try:
            notif_ids, notif_cb = await dispatch(
                db=session,
                event=event,
                payload=payload,
                dedupe_key=idem_key,
                skip_preference_check=event_def.bypass_consent_check,
                strict=True,
                rooms=rooms,
            )
            await session.commit()
        except Exception as e:  # noqa: BLE001 — worker isolates per-row failures
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            results.append((row_id, "error", str(e)[:1000]))
            continue

        if notif_cb is not None:
            try:
                await notif_cb()
            except Exception as cb_err:  # noqa: BLE001
                log.warning(
                    "Outbox post-commit callback failed (non-fatal); row marked ok",
                    extra={
                        "row_id": row_id,
                        "event_code": event_code,
                        "error": str(cb_err)[:200],
                    },
                )
        results.append((row_id, "ok", None))
    return results


async def _finalize(session, results) -> None:
    """Step 3 — short tx mark final state per row.

    ``ok`` rows: set ``dispatched_at = NOW()`` (terminal — never
    re-claimed), clear ``claimed_until``, AND clear ``last_error``
    so a successfully-retried row does not carry stale failure
    text from a prior attempt.
    ``error`` rows: write ``last_error`` (truncated to 1000 chars
    upstream) and clear ``claimed_until`` so a future tick can
    retry until ``attempts >= MAX_ATTEMPTS``.
    """
    if not results:
        return
    async with session.begin():
        for row_id, status, error in results:
            if status == "ok":
                await session.execute(
                    text(
                        """
                        UPDATE notification_outbox
                        SET dispatched_at = NOW(),
                            claimed_until = NULL,
                            last_error = NULL
                        WHERE id = :id
                        """
                    ),
                    {"id": row_id},
                )
            else:
                await session.execute(
                    text(
                        """
                        UPDATE notification_outbox
                        SET last_error = :err,
                            claimed_until = NULL
                        WHERE id = :id
                        """
                    ),
                    {"id": row_id, "err": error},
                )


# ============================================================================
# Wave 5-B / M-1-19d — weekly outbox archive sweep (90-day retention)
# ============================================================================
#
# Beat fires ``archive_outbox_dispatched_task`` every Sunday 02:00 VN per the
# entry in ``app/celery_app.py``. The task moves rows whose ``dispatched_at``
# is older than 90 days from ``notification_outbox`` into
# ``_archived_notification_outbox`` (created by ``phase1_17``, PR #215 squash
# ``0b17f394``).
#
# This is a MOVE (DELETE source + INSERT archive in a single CTE) — different
# from Wave 5-D admission profile archive which COPIES rows (source preserved
# per PLAN line 558-572). The atomic CTE form follows PLAN line 170-176 P1 fix
# #8 verbatim — ``DELETE...RETURNING *`` snapshot feeds the INSERT in the same
# statement, so a crash mid-flight cannot leave a row in both tables nor lose
# it.
#
# Memory ``async-session-gather`` (PR #105 lesson): the task uses ONE
# ``task_db_session()`` for the whole sweep — no ``asyncio.gather`` over the
# session.

archive_log = logging.getLogger("archive_outbox_dispatched_task")

# Discriminator in the result dict so ops can grep this task's ticks apart
# from the worker tick.
ARCHIVE_TASK_ID = "archive-outbox"

# Retention window — sized to PLAN line 168-178. Surface as a constant so
# ops can dial it from a single place (and tests can assert the value).
ARCHIVE_RETENTION_DAYS = 90


@celery_app.task(name="archive_outbox_dispatched_task")
def archive_outbox_dispatched_task() -> dict:
    """Move dispatched outbox rows older than ``ARCHIVE_RETENTION_DAYS``
    into ``_archived_notification_outbox``.

    Beat fires this with zero args (Sunday 02:00 VN). Returns a structured
    result so monitoring can count archived rows per tick.
    """
    return run_async_task(
        async_func=_archive_dispatched,
        task_name="archive_outbox_dispatched_task",
        task_log=archive_log,
        validate_keys=["status", "archived_count", "task_id"],
    )


async def _archive_dispatched() -> dict:
    """Async body — single-statement atomic move per PLAN line 170-176."""
    async with task_db_session() as session:
        async with session.begin():
            result = await session.execute(
                text(
                    """
                    WITH archived AS (
                        DELETE FROM notification_outbox
                        WHERE dispatched_at IS NOT NULL
                          AND dispatched_at < NOW() - make_interval(days => :retention_days)
                        RETURNING id, event_code, payload, idempotency_key,
                                  created_at, dispatched_at, attempts,
                                  last_error, claimed_at, claimed_until
                    )
                    INSERT INTO _archived_notification_outbox (
                        id, event_code, payload, idempotency_key,
                        created_at, dispatched_at, attempts, last_error,
                        claimed_at, claimed_until
                    )
                    SELECT * FROM archived
                    RETURNING id
                    """
                ),
                {"retention_days": ARCHIVE_RETENTION_DAYS},
            )
            archived_ids = [row[0] for row in result.fetchall()]

    archive_log.info(
        "archive_outbox_dispatched_task: tick complete",
        extra={
            "task_id": ARCHIVE_TASK_ID,
            "archived_count": len(archived_ids),
            "retention_days": ARCHIVE_RETENTION_DAYS,
        },
    )
    return {
        "status": "ok",
        "archived_count": len(archived_ids),
        "task_id": ARCHIVE_TASK_ID,
    }
