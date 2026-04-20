# app/tasks/admission_tasks.py
"""Admission Celery tasks — post-approval survey scheduler (Phase E).

Daily beat task that finds profiles approved ≥30 days ago and fires
APPLICATION_SURVEY_DUE so the Zalo channel (ZNS 426903) can deliver
the "Khảo sát dịch vụ tư vấn" template to the applicant's phone.

Dedupe is DB-side: ``admission_profile.survey_sent_at IS NULL`` is the
primary filter, updated in the same transaction as the dispatch so a
re-run within the same batch cycle cannot double-fire. ``tracking_id``
is persisted on the profile so the ``user_feedback`` webhook (E.5)
can correlate Zalo's echo back to the originating row.

Baseline cutoff (``settings.ADMISSION_SURVEY_BASELINE_DATE``) is there
to prevent a first-run flood on the entire back-catalogue of past
approvals. Set the env to the deploy date before enabling the beat
schedule in production.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from ..celery_app import celery_app
from .utils import run_async_task, task_db_session


@celery_app.task(
    name="check_admission_surveys_due_task",
    bind=True,
    autoretry_for=(Exception,),
    max_retries=2,
    default_retry_delay=180,
)
def check_admission_surveys_due_task(self):
    """Daily Celery Beat task: dispatch APPLICATION_SURVEY_DUE for
    profiles approved ≥30 days ago and not yet surveyed.

    Per-profile savepoint so one payload-resolution failure does not
    block the batch. Returns a summary dict that callers can log.
    """
    task_name = "check_admission_surveys_due_task"
    task_log = logging.getLogger(task_name)
    task_log.info("Starting admission survey due check...")

    async def _run() -> dict:
        from ..config import settings
        from ..core.events import SystemEvents
        from ..models import AdmissionProfile
        from ..models.lead import Lead
        from ..models.program_offering import ProgramOffering
        from ..services import notification_dispatcher
        from ..services.notification_payloads import EventPayload

        result = {"checked": 0, "sent": 0, "failed": 0, "skipped_no_phone": 0}

        # Rollout gate — beat schedule stays registered (so /the next deploy
        # can't silently drop it) but the task is an early-return until ops
        # flips ENABLED=true. Two-step rollout: set BASELINE_DATE first, then
        # flip this flag, so a stale env or misconfigured baseline can't
        # flood the past catalogue on first run.
        if not settings.ADMISSION_SURVEY_ENABLED:
            task_log.info(
                "ADMISSION_SURVEY_ENABLED=false, skipping survey scan"
            )
            return result

        post_commit_callbacks = []

        cutoff_now = datetime.now(timezone.utc)
        due_before = cutoff_now - timedelta(days=30)

        baseline: Optional[datetime] = None
        if settings.ADMISSION_SURVEY_BASELINE_DATE:
            try:
                baseline = datetime.fromisoformat(
                    settings.ADMISSION_SURVEY_BASELINE_DATE
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                task_log.warning(
                    "ADMISSION_SURVEY_BASELINE_DATE is not ISO-8601, ignoring",
                    extra={"value": settings.ADMISSION_SURVEY_BASELINE_DATE},
                )

        async with task_db_session() as session:
            conditions = [
                AdmissionProfile.status == "approved",
                AdmissionProfile.approved_at.isnot(None),
                AdmissionProfile.approved_at <= due_before,
                AdmissionProfile.survey_sent_at.is_(None),
            ]
            if baseline is not None:
                conditions.append(AdmissionProfile.approved_at >= baseline)

            query = (
                select(AdmissionProfile)
                .options(
                    # Eager-load the lead → offering → program chain so the
                    # payload builder stays pure (never touches relationships).
                    selectinload(AdmissionProfile.lead)
                    .selectinload(Lead.offering)
                    .selectinload(ProgramOffering.program),
                )
                .where(and_(*conditions))
                .order_by(AdmissionProfile.approved_at.asc())
                .limit(settings.ADMISSION_SURVEY_BATCH_SIZE)
            )

            profiles = (await session.execute(query)).scalars().all()
            result["checked"] = len(profiles)

            for profile in profiles:
                # Real savepoint per profile — if dispatch or flush throws a
                # DB error, the nested transaction rolls back and the outer
                # transaction stays clean so the batch continues. Without
                # this, a single failed row poisons the session and the
                # final commit() would take the whole batch down with it.
                try:
                    async with session.begin_nested():
                        lead = profile.lead
                        if not lead or not getattr(lead, "phone", None):
                            # No phone = Zalo delivery impossible. Mark as
                            # sent_at=now to drop out of future scans — a
                            # daily re-scan never fixes a missing phone, and
                            # tracking_id stays NULL so the webhook never
                            # tries to map a nonexistent delivery.
                            profile.survey_sent_at = cutoff_now
                            result["skipped_no_phone"] += 1
                            continue

                        # Resolve program name upstream so the builder receives
                        # primitives only.
                        program_name = None
                        offering = getattr(lead, "offering", None)
                        if offering is not None:
                            program = getattr(offering, "program", None)
                            if program is not None:
                                program_name = getattr(program, "name", None)

                        tracking_id = f"survey_{uuid.uuid4().hex[:16]}"

                        # NOTE (2026-04-20): admission_profile lacks a
                        # dedicated submitted_at column — transition
                        # draft→submitted is only captured in
                        # entity_audit_log. Using created_at as proxy here
                        # is close enough for the Zalo display slot (gap
                        # between draft creation and submit is typically
                        # <1 day) and avoids a second hot-path query per
                        # scheduler row.
                        submitted_ref = getattr(profile, "created_at", None)

                        _, notif_cb = await notification_dispatcher.dispatch(
                            db=session,
                            event=SystemEvents.APPLICATION_SURVEY_DUE,
                            payload=EventPayload.for_application_survey_due(
                                profile,
                                lead_id=lead.id,
                                full_name=getattr(lead, "full_name", None)
                                or getattr(profile, "full_name", None),
                                program_name=program_name,
                                submitted_at=submitted_ref,
                                tracking_id=tracking_id,
                            ),
                        )
                        if notif_cb:
                            post_commit_callbacks.append(notif_cb)

                        profile.survey_sent_at = cutoff_now
                        profile.survey_tracking_id = tracking_id
                        result["sent"] += 1

                except Exception:
                    task_log.exception(
                        "Failed to dispatch survey for profile %s", profile.id
                    )
                    result["failed"] += 1

            await session.commit()
            for cb in post_commit_callbacks:
                try:
                    await cb()
                except Exception:
                    task_log.exception("post_commit callback failed")

        return result

    result = run_async_task(
        async_func=_run,
        task_name=task_name,
        task_log=task_log,
        validate_keys=["checked", "sent", "failed", "skipped_no_phone"],
    )

    task_log.info(
        "Admission survey check completed: checked=%s sent=%s failed=%s skipped_no_phone=%s",
        result["checked"], result["sent"], result["failed"], result["skipped_no_phone"],
    )
    return result
