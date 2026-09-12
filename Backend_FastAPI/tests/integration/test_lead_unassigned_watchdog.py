"""Watchdog for website leads nobody picked up.

Selection and the re-alert window are tested against a real database because
both are built from conditions that are easy to get subtly wrong: an inner join
silently drops leads with no consultation status (which is every brand new
lead), a LIMIT applied before the mute filter starves the tail, and a calendar
bucket double-fires at boundaries.
"""
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, type_coerce, update
from sqlalchemy.exc import (
    InvalidRequestError,
    OperationalError,
    PendingRollbackError,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.events import SystemEvents
from app.services.notification_payloads import EventPayload
from app.tasks import lead_watchdog_tasks as wd

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 12, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
async def _clear_notification_redis_state():
    """Redis is NOT rolled back with the database transaction.

    dispatch() writes a per-recipient cooldown key derived from the dedupe key,
    and tables are truncated between tests so lead ids restart at 1. Two tests
    that alert about "lead 1" inside the same 6h bucket therefore produce the
    SAME cooldown key, and the second dispatch is silently suppressed by the
    first test's leftover — the notification never lands and the assertion fails
    for a reason that has nothing to do with the code under test.
    """
    from app.utils.redis_lock import get_redis_client

    client = get_redis_client()
    for pattern in ("notif:cooldown:*", "notif:rate:*"):
        keys = await client.keys(pattern)
        if keys:
            await client.delete(*keys)
    yield


async def _lead(
    db: AsyncSession,
    seeded: dict,
    *,
    age: timedelta,
    source: str = "website",
    officer_id=None,
    deleted: bool = False,
    status_id=None,
    phone_suffix: str = "0001",
) -> models.Lead:
    lead = models.Lead(
        full_name="Watchdog Fixture",
        phone=f"090000{phone_suffix}",
        source=source,
        unit_id=seeded["unit_id"],
        pipeline_stage_id=seeded["stage_id"],
        consultation_status_id=status_id,
        assigned_officer_id=officer_id,
        created_at=NOW - age,
        deleted_at=NOW if deleted else None,
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return lead


async def _terminal_status(db: AsyncSession, seeded: dict) -> str:
    status = models.ConsultationStatus(
        id="wd_final",
        name="Watchdog Terminal",
        color_code="#000000",
        stage_id=seeded["stage_id"],
        is_final=True,
    )
    db.add(status)
    await db.flush()
    return status.id


def _key_col():
    return type_coerce(models.Notification.data, JSONB)["dedupe_key"].astext


async def _mark_alerted(db, admin_id: int, lead_id: int, at: datetime):
    """Insert a prior alert using the REAL stored key shape (with :stepN)."""
    db.add(
        models.Notification(
            user_id=admin_id,
            type="warning",
            title="prior watchdog alert",
            message="prior",
            data={
                "dedupe_key": wd.dedupe_key_for(lead_id, wd._window_bucket(at))
                + ":step1"
            },
            created_at=at,
        )
    )
    await db.flush()


async def _seen(db, seeded):
    """Ids the watchdog would alert about, plus the candidate pool size.

    The mute window is applied by the DATABASE now, so a muted lead simply never
    appears in the result - there is no separate "muted" counter to assert on,
    and a test that expected one would be asserting on bookkeeping rather than
    on behaviour."""
    leads, pool = await wd.find_leads_needing_alert(
        db, now=NOW, task_log=logging.getLogger("wd-test")
    )
    return {lead.id for lead in leads}, pool


class TestSelectionBoundary:
    async def test_lead_exactly_at_grace_is_selected(self, db, seeded_dependencies):
        lead = await _lead(db, seeded_dependencies, age=wd.UNASSIGNED_GRACE, phone_suffix="1000")
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id in ids

    async def test_lead_one_second_short_of_grace_is_not_selected(
        self, db, seeded_dependencies
    ):
        """119m59s — the off-by-one that would make the guard fire early."""
        lead = await _lead(
            db, seeded_dependencies,
            age=wd.UNASSIGNED_GRACE - timedelta(seconds=1),
            phone_suffix="1001",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id not in ids


class TestSelectionExclusions:
    async def test_assigned_lead_excluded(self, db, seeded_dependencies, officer_user):
        lead = await _lead(
            db, seeded_dependencies, age=timedelta(hours=5),
            officer_id=officer_user.id, phone_suffix="2000",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id not in ids

    async def test_other_source_excluded(self, db, seeded_dependencies):
        lead = await _lead(
            db, seeded_dependencies, age=timedelta(hours=5),
            source="facebook", phone_suffix="2001",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id not in ids

    async def test_soft_deleted_excluded(self, db, seeded_dependencies):
        lead = await _lead(
            db, seeded_dependencies, age=timedelta(hours=5),
            deleted=True, phone_suffix="2002",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id not in ids

    async def test_terminal_status_excluded(self, db, seeded_dependencies):
        final_id = await _terminal_status(db, seeded_dependencies)
        lead = await _lead(
            db, seeded_dependencies, age=timedelta(hours=5),
            status_id=final_id, phone_suffix="2003",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id not in ids

    async def test_lead_with_no_consultation_status_is_still_selected(
        self, db, seeded_dependencies
    ):
        """A brand new website lead has consultation_status_id NULL. An inner
        join would drop exactly the population this watchdog exists for, and
        every exclusion test above would still pass."""
        lead = await _lead(
            db, seeded_dependencies, age=timedelta(hours=5),
            status_id=None, phone_suffix="2004",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id in ids

    async def test_caught_even_though_assignment_task_never_ran(
        self, db, seeded_dependencies
    ):
        """No decision log, no failed status — the worker was simply down. The
        watchdog must not depend on any artefact that task would have left."""
        lead = await _lead(
            db, seeded_dependencies, age=timedelta(hours=3), phone_suffix="2005",
        )
        assert lead.assignment_status in (None, "pending")
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id in ids


class TestRealertWindowUsesRealDispatchKeys:
    """Dedupe must recognise what dispatch() ACTUALLY stores.

    An earlier version of these tests inserted rows carrying the bare key the
    watchdog passes in. dispatch() never stores that key — it appends
    ":step{n}" per action — so those rows were data production never creates
    and the tests were green against fiction.
    """

    async def _real_alert(self, db, lead, *, at):
        from app.services.notification_dispatcher import dispatch, rooms_for_lead

        recipients, _cb = await dispatch(
            db=db,
            event=SystemEvents.LEAD_ASSIGNMENT_FAILED,
            payload=EventPayload.for_lead_assignment_failed(
                lead, lead.unit_id, wd.WATCHDOG_REASON
            ),
            dedupe_key=wd.dedupe_key_for(lead.id, wd._window_bucket(at)),
            rooms=rooms_for_lead(lead),
        )
        assert recipients, (
            "dispatch produced no recipient — a leftover cooldown or a missing "
            "rule would make every mute assertion below meaningless"
        )
        await db.flush()
        await db.execute(
            update(models.Notification)
            .where(_key_col().like(f"{wd.DEDUPE_PREFIX}:{lead.id}:%"))
            .values(created_at=at)
        )
        await db.flush()
        return recipients

    async def test_stored_key_carries_the_action_step_suffix(
        self, db, seeded_dependencies, admin_user
    ):
        """Pins the exact fact the first implementation got wrong."""
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="3100")
        at = NOW - timedelta(minutes=10)
        recipients = await self._real_alert(db, lead, at=at)
        assert recipients, "dispatch produced no recipient — the test proves nothing"

        stored = (
            await db.execute(
                select(_key_col()).where(_key_col().like(f"{wd.DEDUPE_PREFIX}:%"))
            )
        ).scalars().all()
        assert stored, "no notification row was stored"

        bare = wd.dedupe_key_for(lead.id, wd._window_bucket(at))
        assert all(k != bare for k in stored), (
            "stored key equals the bare key — the suffix assumption changed"
        )
        assert any(k.startswith(bare + ":step") for k in stored), (
            f"expected an action-step suffix, stored: {stored}"
        )

    async def test_muted_after_a_real_dispatch_inside_the_window(
        self, db, seeded_dependencies, admin_user
    ):
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="3101")
        await self._real_alert(db, lead, at=NOW - timedelta(hours=1))
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id not in ids

    async def test_still_muted_ten_minutes_after_a_bucket_boundary(
        self, db, seeded_dependencies, admin_user
    ):
        """Alert at 11:55, 'now' is 12:05 — different 6h buckets, ten minutes
        apart. A bucket-only rule re-fires here; a sliding window must not."""
        boundary_now = datetime(2026, 9, 12, 12, 5, 0, tzinfo=timezone.utc)
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=9), phone_suffix="3102")
        await self._real_alert(db, lead, at=boundary_now - timedelta(minutes=10))

        leads, _ = await wd.find_leads_needing_alert(
            db, now=boundary_now, task_log=logging.getLogger("wd-test")
        )
        assert lead.id not in {lead_.id for lead_ in leads}

    async def test_alerts_again_once_the_full_window_has_passed(
        self, db, seeded_dependencies, admin_user
    ):
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=20), phone_suffix="3103")
        await self._real_alert(
            db, lead, at=NOW - wd.REALERT_INTERVAL - timedelta(minutes=5)
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert lead.id in ids


class TestNoStarvation:
    async def _bulk_muted_backlog(self, db, seeded, admin_id, count):
        """Insert ``count`` OLD muted leads cheaply (bulk, not ORM per row)."""
        from sqlalchemy import insert

        base = NOW - timedelta(hours=40)
        lead_rows = [
            {
                "full_name": "Backlog Fixture",
                "phone": f"0911{i:06d}",
                "source": "website",
                "unit_id": seeded["unit_id"],
                "pipeline_stage_id": seeded["stage_id"],
                "consultation_status_id": None,
                "assigned_officer_id": None,
                "created_at": base - timedelta(seconds=i),
                "deleted_at": None,
            }
            for i in range(count)
        ]
        result = await db.execute(
            insert(models.Lead).returning(models.Lead.id), lead_rows
        )
        ids = [r[0] for r in result.fetchall()]
        bucket = wd._window_bucket(NOW - timedelta(hours=1))
        await db.execute(
            insert(models.Notification),
            [
                {
                    "user_id": admin_id,
                    "type": "warning",
                    "title": "prior",
                    "message": "prior",
                    "data": {"dedupe_key": wd.dedupe_key_for(i, bucket) + ":step1"},
                    "created_at": NOW - timedelta(hours=1),
                }
                for i in ids
            ],
        )
        await db.flush()
        return ids

    async def test_newcomer_is_found_behind_a_small_muted_backlog(
        self, db, seeded_dependencies, admin_user
    ):
        await self._bulk_muted_backlog(db, seeded_dependencies, admin_user.id, 205)
        newcomer = await _lead(
            db, seeded_dependencies, age=timedelta(hours=3), phone_suffix="69999",
        )
        ids, _ = await _seen(db, seeded_dependencies)
        assert newcomer.id in ids

    async def test_newcomer_is_found_behind_a_backlog_larger_than_the_old_scan_cap(
        self, db, seeded_dependencies, admin_user
    ):
        """2,005 muted leads — past the old SCAN_MAX=2000 stop.

        The previous implementation paged through candidates in Python and gave
        up at a fixed cap, so a lead sitting behind a big enough muted backlog
        was never even read. Muting now happens in SQL, so backlog size cannot
        push a due lead out of reach at ANY size; this pins that.
        """
        await self._bulk_muted_backlog(db, seeded_dependencies, admin_user.id, 2005)
        newcomer = await _lead(
            db, seeded_dependencies, age=timedelta(hours=3), phone_suffix="79999",
        )
        ids, pool = await _seen(db, seeded_dependencies)
        assert newcomer.id in ids, (
            "a due lead behind a 2,005-row muted backlog was not reachable"
        )
        assert pool <= wd.CANDIDATE_POOL, (
            "the query returned more than the candidate pool; the mute filter "
            "is not running in SQL"
        )

    async def test_never_alerted_outranks_a_repeat_candidate(
        self, db, seeded_dependencies, admin_user
    ):
        old_repeat = await _lead(
            db, seeded_dependencies, age=timedelta(hours=50), phone_suffix="7000",
        )
        fresh_new = await _lead(
            db, seeded_dependencies, age=timedelta(hours=3), phone_suffix="7001",
        )
        await _mark_alerted(db, admin_user.id, old_repeat.id, NOW - timedelta(hours=30))

        leads, _ = await wd.find_leads_needing_alert(
            db, now=NOW, task_log=logging.getLogger("wd-test")
        )
        order = [lead.id for lead in leads]
        assert order.index(fresh_new.id) < order.index(old_repeat.id), (
            "a never-alerted lead must outrank a repeat, or the per-tick cap "
            "spends every slot on reminders"
        )


class TestPriorityIsDecidedBeforeTheLimit:
    """A never-alerted lead must not be crowded out of the candidate pool.

    Ordering in Python happens AFTER the LIMIT, so it can only reorder leads
    that already survived the cut. If enough older repeat-due leads exist to
    fill the pool, a newer never-alerted lead never enters it and no amount of
    Python sorting can promote it.
    """

    async def test_newcomer_beats_a_full_pool_of_older_repeat_candidates(
        self, db, seeded_dependencies, admin_user
    ):
        from sqlalchemy import insert

        n = wd.CANDIDATE_POOL + 5
        base = NOW - timedelta(hours=60)
        rows = [
            {
                "full_name": "Repeat Fixture",
                "phone": f"0922{i:06d}",
                "source": "website",
                "unit_id": seeded_dependencies["unit_id"],
                "pipeline_stage_id": seeded_dependencies["stage_id"],
                "consultation_status_id": None,
                "assigned_officer_id": None,
                "created_at": base - timedelta(seconds=i),
                "deleted_at": None,
            }
            for i in range(n)
        ]
        result = await db.execute(insert(models.Lead).returning(models.Lead.id), rows)
        old_ids = [r[0] for r in result.fetchall()]

        # Each was alerted long ago -> eligible again, but a REPEAT.
        long_ago = NOW - wd.REALERT_INTERVAL - timedelta(hours=2)
        await db.execute(
            insert(models.Notification),
            [
                {
                    "user_id": admin_user.id,
                    "type": "warning",
                    "title": "prior",
                    "message": "prior",
                    "data": {
                        "dedupe_key": wd.dedupe_key_for(
                            i, wd._window_bucket(long_ago)
                        ) + ":step1"
                    },
                    "created_at": long_ago,
                }
                for i in old_ids
            ],
        )
        await db.flush()

        newcomer = await _lead(
            db, seeded_dependencies, age=timedelta(hours=3), phone_suffix="93999",
        )

        leads, pool = await wd.find_leads_needing_alert(
            db, now=NOW, task_log=logging.getLogger("wd-test")
        )
        ids = [lead.id for lead in leads]
        assert newcomer.id in ids, (
            "a never-alerted lead was crowded out of the pool by older repeats - "
            "priority is still being applied after the LIMIT"
        )
        assert ids[0] == newcomer.id, "never-alerted must sort first"
        assert pool <= wd.CANDIDATE_POOL


class TestRecheckIsComplete:
    async def _stale_then(self, db, lead, mutate):
        """Select while valid, mutate from another session, then run the loop."""
        from app.database import AsyncSessionLocal

        stale_due, _ = await wd.find_leads_needing_alert(
            db, now=NOW, task_log=logging.getLogger("wd-test")
        )
        assert lead.id in {l.id for l in stale_due}, "setup: not a candidate"

        async with AsyncSessionLocal() as other:
            victim = (
                await other.execute(
                    select(models.Lead).where(models.Lead.id == lead.id)
                )
            ).scalars().first()
            mutate(victim)
            await other.commit()

        sent = []

        async def _record(**kwargs):
            sent.append(kwargs)
            return ([1], None)

        async def _stale_selection(_db, *, now, task_log):
            return stale_due, len(stale_due)

        with patch("app.services.notification_dispatcher.dispatch", new=_record):
            with patch.object(wd, "find_leads_needing_alert", new=_stale_selection):
                result = await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )
        return sent, result

    async def test_source_changed_after_selection_is_not_alerted(
        self, db, seeded_dependencies, admin_user
    ):
        """``source`` is editable, so it has to be re-checked like the rest."""
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="8100")
        await db.commit()

        def _mutate(victim):
            victim.source = "facebook"

        sent, result = await self._stale_then(db, lead, _mutate)
        assert sent == [], "alerted about a lead that is no longer a website lead"
        assert result["skipped_changed"] == 1

    async def test_alert_routes_by_the_fresh_unit_not_the_snapshot(
        self, db, seeded_dependencies, admin_user
    ):
        """If the lead moved units, the alert must reach the NEW unit."""
        from app.database import AsyncSessionLocal

        other_unit = models.OrganizationUnit(name="Watchdog Other Unit", type="department")
        db.add(other_unit)
        await db.flush()
        new_unit_id = other_unit.id
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="8101")
        old_unit_id = lead.unit_id
        await db.commit()

        stale_due, _ = await wd.find_leads_needing_alert(
            db, now=NOW, task_log=logging.getLogger("wd-test")
        )
        assert lead.id in {l.id for l in stale_due}

        async with AsyncSessionLocal() as other:
            victim = (
                await other.execute(
                    select(models.Lead).where(models.Lead.id == lead.id)
                )
            ).scalars().first()
            victim.unit_id = new_unit_id
            await other.commit()

        sent = []

        async def _record(**kwargs):
            sent.append(kwargs)
            return ([1], None)

        async def _stale_selection(_db, *, now, task_log):
            return stale_due, len(stale_due)

        with patch("app.services.notification_dispatcher.dispatch", new=_record):
            with patch.object(wd, "find_leads_needing_alert", new=_stale_selection):
                await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )

        assert len(sent) == 1, "expected exactly one alert"
        assert sent[0]["payload"]["unit_id"] == new_unit_id, (
            "alert was routed by the stale snapshot unit"
        )
        assert f"unit_{new_unit_id}" in sent[0]["rooms"]
        assert f"unit_{old_unit_id}" not in sent[0]["rooms"]

    async def test_database_failure_propagates_instead_of_becoming_a_counter(
        self, db, seeded_dependencies, admin_user
    ):
        """An infrastructure error is not "the lead changed".

        Swallowing it would let the task return SUCCESS having silently skipped
        leads, and Celery would never retry.
        """
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="8102")
        await db.flush()

        from app.repositories.lead_repository import LeadRepository

        async def _boom(self, lead_id, *, cutoff):
            raise RuntimeError("database is on fire")

        with patch.object(LeadRepository, "lock_and_recheck_unassigned", new=_boom):
            with pytest.raises(RuntimeError, match="on fire"):
                await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )


class TestRaceWithAssignment:
    """A lead assigned between selection and dispatch must NOT be alerted.

    Auto-assignment locks the row with ``with_for_update(nowait=True)`` and then
    sets ``assigned_officer_id``. The watchdog picks candidates earlier, so
    without a re-check under lock it would tell an admin "assignment failed"
    about a lead that had just succeeded — and false alarms are how an alert
    channel gets ignored.

    The window is narrow in production, so the test opens it deliberately: the
    candidate list is captured while the lead is still free, the lead is then
    assigned from a SECOND session, and only then does the alert loop run. The
    selection step is fed that stale list on purpose — re-running selection would
    filter the lead out in SQL and prove nothing about the re-check.
    """

    async def test_lead_assigned_after_selection_is_not_alerted(
        self, db, seeded_dependencies, admin_user, officer_user
    ):
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="8000")
        await db.commit()

        from app.database import AsyncSessionLocal

        stale_due, _ = await wd.find_leads_needing_alert(
            db, now=NOW, task_log=logging.getLogger("wd-test")
        )
        assert lead.id in {l.id for l in stale_due}, "setup: lead was not a candidate"

        async with AsyncSessionLocal() as other:
            victim = (
                await other.execute(
                    select(models.Lead).where(models.Lead.id == lead.id)
                )
            ).scalars().first()
            victim.assigned_officer_id = officer_user.id
            await other.commit()

        sent = []

        async def _record(**kwargs):
            sent.append(kwargs)
            return ([admin_user.id], None)

        async def _stale_selection(_db, *, now, task_log):
            return stale_due, len(stale_due)

        with patch("app.services.notification_dispatcher.dispatch", new=_record):
            with patch.object(wd, "find_leads_needing_alert", new=_stale_selection):
                result = await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )

        assert sent == [], "alerted about a lead that had just been assigned"
        assert result["alerted"] == 0
        assert result["skipped_changed"] == 1, (
            "the re-check did not notice the lead changed under it"
        )

    async def test_deleted_between_selection_and_dispatch_is_not_alerted(
        self, db, seeded_dependencies, admin_user
    ):
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="8001")
        await db.commit()

        from app.database import AsyncSessionLocal

        stale_due, _ = await wd.find_leads_needing_alert(
            db, now=NOW, task_log=logging.getLogger("wd-test")
        )
        assert lead.id in {l.id for l in stale_due}

        async with AsyncSessionLocal() as other:
            victim = (
                await other.execute(
                    select(models.Lead).where(models.Lead.id == lead.id)
                )
            ).scalars().first()
            victim.deleted_at = NOW
            await other.commit()

        sent = []

        async def _record(**kwargs):
            sent.append(kwargs)
            return ([admin_user.id], None)

        async def _stale_selection(_db, *, now, task_log):
            return stale_due, len(stale_due)

        with patch("app.services.notification_dispatcher.dispatch", new=_record):
            with patch.object(wd, "find_leads_needing_alert", new=_stale_selection):
                result = await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )

        assert sent == []
        assert result["skipped_changed"] == 1


class TestDatabaseErrorsPropagate:
    """A database failure is not "this lead is awkward".

    The re-check before dispatch already refuses to swallow infrastructure
    errors. The dispatch and the commit that follow are the other half: if a
    DBAPIError there were folded into the error counter, the task would return
    SUCCESS having skipped leads it never examined, and Celery would never
    retry. An earlier version of this file only made the RE-CHECK fail — which
    happens outside the try block — so it passed while this path was wide open.
    """

    async def _one_due_lead(self, db, seeded):
        lead = await _lead(db, seeded, age=timedelta(hours=5), phone_suffix="8500")
        await db.flush()
        return lead

    async def test_dbapi_error_from_dispatch_propagates(
        self, db, seeded_dependencies, admin_user
    ):
        await self._one_due_lead(db, seeded_dependencies)

        async def _db_down(**kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection reset"))

        with patch("app.services.notification_dispatcher.dispatch", new=_db_down):
            with pytest.raises(OperationalError):
                await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )

    async def test_dbapi_error_from_commit_propagates(
        self, db, seeded_dependencies, admin_user
    ):
        await self._one_due_lead(db, seeded_dependencies)
        admin_id = admin_user.id

        async def _ok(**kwargs):
            return ([admin_id], None)

        real_commit = db.commit

        async def _commit_boom():
            raise OperationalError("COMMIT", {}, Exception("disk full"))

        with patch("app.services.notification_dispatcher.dispatch", new=_ok):
            db.commit = _commit_boom
            try:
                with pytest.raises(OperationalError):
                    await wd.alert_unassigned_website_leads(
                        db, now=NOW, task_log=logging.getLogger("wd-test")
                    )
            finally:
                db.commit = real_commit

    async def test_rollback_failure_does_not_mask_the_original_error(
        self, db, seeded_dependencies, admin_user
    ):
        """If unwinding also fails, the ORIGINAL cause must still surface —
        otherwise the logs say "rollback failed" and never say why."""
        await self._one_due_lead(db, seeded_dependencies)

        async def _db_down(**kwargs):
            raise OperationalError("SELECT 1", {}, Exception("original cause"))

        real_rollback = db.rollback

        async def _rollback_boom():
            raise RuntimeError("rollback also failed")

        with patch("app.services.notification_dispatcher.dispatch", new=_db_down):
            db.rollback = _rollback_boom
            try:
                with pytest.raises(OperationalError) as exc:
                    await wd.alert_unassigned_website_leads(
                        db, now=NOW, task_log=logging.getLogger("wd-test")
                    )
                assert "original cause" in str(exc.value)
            finally:
                db.rollback = real_rollback

    async def test_invalid_request_error_from_dispatch_propagates(
        self, db, seeded_dependencies, admin_user
    ):
        """InvalidRequestError is a session-layer failure, NOT a DBAPIError.

        Catching only DBAPIError leaves it falling through to the generic
        handler — and this repository has already lost notifications to exactly
        this class once, in the outbox incident.
        """
        await self._one_due_lead(db, seeded_dependencies)

        async def _session_broken(**kwargs):
            raise InvalidRequestError("session is in a bad state")

        with patch("app.services.notification_dispatcher.dispatch", new=_session_broken):
            with pytest.raises(InvalidRequestError):
                await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )

    async def test_pending_rollback_error_from_commit_propagates(
        self, db, seeded_dependencies, admin_user
    ):
        """PendingRollbackError likewise: the dispatcher already handles it
        elsewhere, so it is a shape this code really meets."""
        await self._one_due_lead(db, seeded_dependencies)
        admin_id = admin_user.id

        async def _ok(**kwargs):
            return ([admin_id], None)

        real_commit = db.commit

        async def _commit_pending():
            raise PendingRollbackError("this session must be rolled back first")

        with patch("app.services.notification_dispatcher.dispatch", new=_ok):
            db.commit = _commit_pending
            try:
                with pytest.raises(PendingRollbackError):
                    await wd.alert_unassigned_website_leads(
                        db, now=NOW, task_log=logging.getLogger("wd-test")
                    )
            finally:
                db.commit = real_commit

    def test_the_two_session_errors_are_not_dbapi_errors(self):
        """Pins WHY the handler widened. If these ever became DBAPIError
        subclasses the narrower catch would be sufficient again — and if they
        stopped being SQLAlchemyError, the handler would silently stop covering
        them."""
        from sqlalchemy.exc import DBAPIError, SQLAlchemyError

        for exc_type in (InvalidRequestError, PendingRollbackError):
            assert not issubclass(exc_type, DBAPIError)
            assert issubclass(exc_type, SQLAlchemyError)

    async def test_ordinary_application_error_is_still_counted_and_sweep_continues(
        self, db, seeded_dependencies, admin_user
    ):
        """The contract for NON-database failures is unchanged: count it and
        keep going, so one awkward lead cannot mute the rest."""
        await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="8501")
        await _lead(db, seeded_dependencies, age=timedelta(hours=6), phone_suffix="8502")
        admin_id = admin_user.id
        await db.commit()
        calls = {"n": 0}

        async def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("template blew up")
            return ([admin_id], None)

        with patch("app.services.notification_dispatcher.dispatch", new=_flaky):
            result = await wd.alert_unassigned_website_leads(
                db, now=NOW, task_log=logging.getLogger("wd-test")
            )
        assert result["errors"] == 1
        assert result["alerted"] == 1, "a plain application error must not abort the sweep"


class TestAlerting:
    async def test_alert_counts_and_no_pii_in_logs(
        self, db, seeded_dependencies, admin_user, caplog
    ):
        lead = await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="4000")
        with patch(
            "app.services.notification_dispatcher.dispatch",
            new_callable=AsyncMock,
            return_value=([admin_user.id], None),
        ):
            with caplog.at_level(logging.INFO):
                result = await wd.alert_unassigned_website_leads(
                    db, now=NOW, task_log=logging.getLogger("wd-test")
                )
        assert result["alerted"] == 1
        assert result["errors"] == 0
        blob = " ".join(r.getMessage() for r in caplog.records)
        assert lead.phone not in blob, "phone number leaked into logs"
        assert "Watchdog Fixture" not in blob, "lead name leaked into logs"

    async def test_empty_recipient_list_is_not_counted_as_success(
        self, db, seeded_dependencies
    ):
        await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="4001")
        with patch(
            "app.services.notification_dispatcher.dispatch",
            new_callable=AsyncMock,
            return_value=([], None),
        ):
            result = await wd.alert_unassigned_website_leads(
                db, now=NOW, task_log=logging.getLogger("wd-test")
            )
        assert result["alerted"] == 0
        assert result["no_recipient"] == 1

    async def test_dispatch_failure_is_counted_and_does_not_stop_the_sweep(
        self, db, seeded_dependencies, admin_user
    ):
        await _lead(db, seeded_dependencies, age=timedelta(hours=5), phone_suffix="4002")
        await _lead(db, seeded_dependencies, age=timedelta(hours=6), phone_suffix="4003")
        # COMMIT is required, not cosmetic: the loop rolls back after a failed
        # dispatch and then re-reads the next lead under a row lock. With rows
        # only flushed, that rollback would discard the fixtures themselves and
        # the second lead would look "changed" rather than alertable — the test
        # would fail for a reason production never sees.
        # Read the id BEFORE committing: commit expires every ORM object, and a
        # lazy refresh triggered from inside the patched dispatch would surface
        # as "the dispatch failed" and be miscounted as a second error.
        admin_id = admin_user.id
        await db.commit()
        calls = {"n": 0}

        async def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return ([admin_id], None)

        with patch("app.services.notification_dispatcher.dispatch", new=_flaky):
            result = await wd.alert_unassigned_website_leads(
                db, now=NOW, task_log=logging.getLogger("wd-test")
            )
        assert result["errors"] == 1
        assert result["alerted"] == 1, "one bad lead must not abort the rest"

    async def test_per_tick_cap_protects_the_shared_notification_quota(
        self, db, seeded_dependencies, admin_user
    ):
        """NOTIFICATION_RATE_LIMIT_PER_HOUR is shared across every event type,
        so an unbounded burst would spend every admin's hourly budget here and
        make unrelated alerts vanish for the rest of the hour."""
        for i in range(wd.MAX_ALERTS_PER_TICK + 3):
            await _lead(
                db, seeded_dependencies, age=timedelta(hours=5),
                phone_suffix=f"5{i:03d}",
            )
        with patch(
            "app.services.notification_dispatcher.dispatch",
            new_callable=AsyncMock,
            return_value=([admin_user.id], None),
        ) as sent:
            result = await wd.alert_unassigned_website_leads(
                db, now=NOW, task_log=logging.getLogger("wd-test")
            )
        assert sent.await_count == wd.MAX_ALERTS_PER_TICK
        assert result["capped"] == 3


class TestScheduleAndLockBudget:
    def test_task_is_registered_every_15_minutes_on_the_default_queue(self):
        """A task that is written but never scheduled is a guard that cannot
        see what it guards."""
        from app.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["lead-unassigned-watchdog"]
        assert entry["task"] == wd.TASK_NAME
        assert entry["options"]["queue"] == "default"
        # celery expands "*/15" into the concrete minute set
        assert entry["schedule"].minute == {0, 15, 30, 45}

    def test_lock_outlives_the_beat_interval_and_task_is_capped_below_it(self):
        """If the TTL were shorter than the interval, the lock would lapse while
        the previous sweep still ran and two sweeps would overlap."""
        assert wd.LOCK_TTL_SECONDS > 900, "lock expires before the next tick"
        assert wd.TASK_TIME_LIMIT_SECONDS < wd.LOCK_TTL_SECONDS, (
            "a sweep could outlive its own lock instead of being killed"
        )
        assert wd.TASK_SOFT_TIME_LIMIT_SECONDS < wd.TASK_TIME_LIMIT_SECONDS

    def test_task_is_importable_from_the_tasks_package(self):
        """celery_app only imports app.tasks; a module missing from the package
        __init__ registers no task and the beat entry fails at runtime."""
        from app import tasks

        assert hasattr(tasks, "lead_unassigned_watchdog_task")
