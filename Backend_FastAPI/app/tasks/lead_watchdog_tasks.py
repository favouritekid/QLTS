"""
Watchdog: website leads that nobody picked up.

WHAT IT ACTUALLY COVERS
-----------------------
This task is scheduled by Celery Beat and executed by the Celery worker, so it
lives in the SAME failure domain as the assignment task it backstops. Be precise
about what that buys:

* Business failures are caught LIVE: assignment ran, returned FAILED (no
  officers, pool exhausted, a reason nobody escalates), and the lead is still
  sitting there. ``assignment_tasks`` only logs a warning in that case.
* Recipient failures are caught LIVE: assignment_service does dispatch
  ``LEAD_ASSIGNMENT_FAILED``, but its recipients resolve through the unit's
  managers, and a unit with no manager/admin resolves to an EMPTY list
  (measured on production: unit 14, where website leads land, has zero).
* A Celery outage is caught only AFTER RECOVERY. If the worker or beat is down,
  this task is down with them. It will report the backlog once Celery comes
  back, which is worth having, but it is NOT live detection of an ongoing
  outage and must never be described as such.

⚠️ Detecting "Celery itself is dead, right now" needs a monitor OUTSIDE Celery
(external heartbeat / uptime check on worker and beat). Until that exists, E1
activation still has an observability hole that this task does not close.

DESIGN NOTES
------------
* Reuses the existing ``LEAD_ASSIGNMENT_FAILED`` event, so the recipient rule
  (and its manager -> admin fallback) is configured in exactly one place.
* Calls ``dispatch()`` directly, like assignment_service. The event is NOT
  ``requires_outbox``, so this never touches the outbox and cannot aggravate the
  outbox lease/attempts debt.
* Mute filtering happens in SQL, correlated per lead, so LIMIT applies to leads
  that are actually due. Filtering afterwards in Python starves the tail.
* Every candidate is re-locked and re-checked immediately before dispatch: the
  assignment task can claim the same lead in between, and a false "assignment
  failed" is how an alert channel gets ignored.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from sqlalchemy.exc import SQLAlchemyError

from ..celery_app import celery_app
from ..core.events import SystemEvents
from ..repositories.lead_repository import LeadRepository
from ..services.notification_payloads import EventPayload
from ..utils.redis_lock import acquire_redis_lock
from .utils import task_db_session, run_async_task

# ``notification_dispatcher`` is imported lazily inside the call, mirroring
# assignment_service: importing it at module scope pulls the whole notification
# stack into every Celery worker import and risks a cycle.

_default_log = logging.getLogger(__name__)

# Grace period before a still-unassigned website lead is considered a problem.
UNASSIGNED_GRACE = timedelta(hours=2)
# Minimum gap between two alerts about the SAME lead.
REALERT_INTERVAL = timedelta(hours=6)
# Hard cap on alerts emitted per tick. NOTIFICATION_RATE_LIMIT_PER_HOUR is 50
# per user and is SHARED by every event type, so an unbounded burst here would
# silently eat the hourly budget of every admin and drop unrelated (security,
# finance) notifications for the rest of the hour. Better to alert about a few
# leads and keep the channel usable than to alert about all of them once and
# then go deaf.
MAX_ALERTS_PER_TICK = 10
# Candidates fetched before priority ordering. The mute test already ran in SQL,
# so every row here is genuinely due and the pool only has to be large enough to
# choose between "never alerted" and "due for a repeat" - it is NOT a scan cap,
# and no backlog size can push a due lead out of reach.
CANDIDATE_POOL = MAX_ALERTS_PER_TICK * 3
# Prefix kept DISTINCT from the keys assignment_service already uses
# ("lead_assignment_failed:{id}:no_officers" / ":capacity"). Those carry no time
# component, so dedupe against them is permanent — reusing them would mute the
# watchdog forever for precisely the leads that already failed once, which is
# the population it exists to catch.
DEDUPE_PREFIX = "lead_watchdog_unassigned"
WATCHDOG_REASON = "watchdog_unassigned_over_grace"

TASK_NAME = "lead_unassigned_watchdog_task"
LOCK_KEY = "lead_unassigned_watchdog"
# Beat fires every 900s. A TTL below that leaves a window where the lock has
# expired while the previous sweep is still running, so two sweeps overlap and
# race on the same re-alert window. TTL is therefore ABOVE the interval, and the
# task carries a hard time limit BELOW the TTL so a hung sweep is killed rather
# than silently outliving its own lock.
LOCK_TTL_SECONDS = 1200
TASK_TIME_LIMIT_SECONDS = 900
TASK_SOFT_TIME_LIMIT_SECONDS = 840


def _window_bucket(now: datetime) -> datetime:
    """6h-aligned bucket used only to make each alert's dedupe key distinct."""
    floored = now.replace(minute=0, second=0, microsecond=0)
    return floored - timedelta(hours=floored.hour % 6)


def dedupe_key_for(lead_id: int, bucket: datetime) -> str:
    """Single source of truth for the watchdog dedupe key — task AND tests."""
    return f"{DEDUPE_PREFIX}:{lead_id}:{bucket.isoformat()}"


def dedupe_prefix_for(lead_id: int) -> str:
    """Everything the watchdog has ever sent about this lead.

    dispatch() appends ":step{n}" to whatever key it is given, so the stored key
    is never the one we passed. Matching has to be by prefix.
    """
    return f"{DEDUPE_PREFIX}:{lead_id}:"


def _age_bucket(age: timedelta) -> str:
    """Coarse age label for logs. Never log timestamps tied to a person."""
    hours = age.total_seconds() / 3600.0
    if hours < 4:
        return "2-4h"
    if hours < 12:
        return "4-12h"
    if hours < 24:
        return "12-24h"
    return "24h+"


async def find_leads_needing_alert(db, *, now, task_log):
    """Leads due for an alert, already in priority order.

    Returns ``(leads, pool_size)``. Both the mute window and the "never alerted
    before" priority are decided by the database BEFORE the LIMIT. Doing either
    afterwards in Python puts it after the cut: a newer never-alerted lead would
    be crowded out of the pool by older repeat candidates and could never be
    promoted, no matter how the Python sort was written.
    """
    lead_repo = LeadRepository(db)
    rows = await lead_repo.find_unalerted_stale_website_leads(
        cutoff=now - UNASSIGNED_GRACE,
        alert_prefix=f"{DEDUPE_PREFIX}:",
        since=now - REALERT_INTERVAL,
        limit=CANDIDATE_POOL,
    )
    if not rows:
        return [], 0

    leads = [lead for lead, _ever in rows]
    task_log.info(
        "watchdog scan complete",
        extra={
            "candidates": len(rows),
            "never_alerted": sum(1 for _lead, ever in rows if not ever),
            "pool_full": len(rows) == CANDIDATE_POOL,
        },
    )
    return leads, len(rows)


async def alert_unassigned_website_leads(db, *, now, task_log):
    """Core, testable body. Commits per lead so one bad lead cannot roll back
    alerts already produced for the others."""
    due, pool = await find_leads_needing_alert(db, now=now, task_log=task_log)
    cutoff = now - UNASSIGNED_GRACE
    lead_repo = LeadRepository(db)

    alerted = 0
    no_recipient = 0
    errors = 0
    skipped_changed = 0
    capped = max(0, len(due) - MAX_ALERTS_PER_TICK)

    # Plain ints, captured BEFORE the loop. A rollback on one lead expires every
    # ORM object still attached to this session, so reading an id on a later
    # iteration would trigger a lazy refresh outside the async context. Only the
    # id is carried over; everything the alert is built from comes from the
    # freshly locked row below.
    candidate_ids = [lead.id for lead in due[:MAX_ALERTS_PER_TICK]]

    for candidate_id in candidate_ids:
        # Re-lock and re-test RIGHT BEFORE telling anyone. Deliberately OUTSIDE
        # the try below: this call raises on real database failures, and those
        # must reach Celery so the task retries. Folding them into the error
        # counter would let the task finish SUCCESS while silently skipping
        # leads it never actually examined.
        fresh = await lead_repo.lock_and_recheck_unassigned(
            candidate_id, cutoff=cutoff
        )
        if fresh is None:
            skipped_changed += 1
            task_log.info(
                "watchdog skipped a lead that changed under it",
                extra={"lead_id": candidate_id},
            )
            await db.rollback()
            continue

        # Everything below uses FRESH, never the candidate snapshot: unit_id can
        # have changed since selection, and routing the alert by a stale unit
        # would send it to the wrong managers.
        lead_id = fresh.id
        unit_id = fresh.unit_id
        age = now - fresh.created_at if fresh.created_at else None
        key = dedupe_key_for(lead_id, _window_bucket(now))

        try:
            from ..services.notification_dispatcher import dispatch, rooms_for_lead

            recipients, notif_cb = await dispatch(
                db=db,
                event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
                payload=EventPayload.for_lead_assignment_failed(
                    fresh, unit_id, WATCHDOG_REASON
                ),
                dedupe_key=key,
                rooms=rooms_for_lead(fresh),
            )
            # Commit BEFORE the post-commit side effect, and never record "this
            # lead was alerted" anywhere that survives a rollback: the internal
            # cooldown path in this repo learned that the hard way, where a
            # Redis flag set before the durable write left users muted with no
            # notification behind it.
            await db.commit()
            if notif_cb:
                await notif_cb()

            if recipients:
                alerted += 1
            else:
                no_recipient += 1
                task_log.error(
                    "watchdog alert resolved to NO recipients",
                    extra={
                        "lead_id": lead_id,
                        "unit_id": unit_id,
                        "age_bucket": _age_bucket(age) if age else "unknown",
                    },
                )
        except SQLAlchemyError:
            # Infrastructure, not "this lead is awkward". SQLAlchemyError, not
            # DBAPIError: the latter only covers driver-level failures, while
            # InvalidRequestError / PendingRollbackError come from the session
            # layer and are NOT its subclasses. This repository has already been
            # bitten by exactly that — the outbox incident was an
            # InvalidRequestError — and the dispatcher itself handles
            # PendingRollbackError. Counting it would let
            # the task finish SUCCESS with leads silently unexamined and Celery
            # never retrying — the same fail-open the re-check above refuses.
            # Rollback is best effort and must never replace the original
            # exception: losing it would hide WHY the sweep aborted.
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001 - keep the original error
                task_log.warning(
                    "watchdog rollback failed while unwinding a database error",
                    extra={"lead_id": lead_id},
                )
            raise
        except Exception as exc:  # noqa: BLE001 - one bad lead must not stop the sweep
            await db.rollback()
            errors += 1
            task_log.warning(
                "watchdog alert failed for a lead",
                extra={"lead_id": lead_id, "error": str(exc)},
            )

    return {
        "candidates": pool,
        "alerted": alerted,
        "no_recipient": no_recipient,
        "skipped_changed": skipped_changed,
        "capped": capped,
        "errors": errors,
    }


@celery_app.task(
    name=TASK_NAME,
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=120,
    time_limit=TASK_TIME_LIMIT_SECONDS,
    soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
)
def lead_unassigned_watchdog_task(self):
    """Celery Beat task (every 15 minutes) — thin wrapper only.

    Guarded by a Redis lock: the sweep can outlive its 15 minute slot on a slow
    database, and two overlapping sweeps would race on the same dedupe window.
    """
    task_log = logging.getLogger(TASK_NAME)

    async def _run():
        async with acquire_redis_lock(LOCK_KEY, timeout=LOCK_TTL_SECONDS) as acquired:
            if not acquired:
                task_log.info("watchdog lock held by another worker, skipping")
                return {
                    "candidates": 0, "alerted": 0, "no_recipient": 0,
                    "skipped_changed": 0, "capped": 0, "errors": 0,
                    "skipped_lock": True,
                }
            async with task_db_session() as session:
                return await alert_unassigned_website_leads(
                    session, now=datetime.now(timezone.utc), task_log=task_log
                )

    return run_async_task(_run, TASK_NAME, task_log)
