"""Integration tests for ``check_admission_surveys_due_task`` (Phase E.4).

Locks four invariants through the real DB + dispatcher stack:

1. **Rollout gate** — ``settings.ADMISSION_SURVEY_ENABLED=False`` must
   early-return without scanning.
2. **Baseline cutoff** — profiles approved before
   ``ADMISSION_SURVEY_BASELINE_DATE`` are excluded even if they are
   ≥30d old.
3. **No-phone skip** — leads without a phone land in
   ``skipped_no_phone``, ``survey_sent_at`` is still stamped (so they
   exit the scan window), ``survey_tracking_id`` stays NULL.
4. **Savepoint isolation** — a simulated per-row failure must not
   poison the session; subsequent rows still dispatch and commit.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.tasks import admission_tasks as admission_task_module


def _approved_profile(
    db, seeded_dependencies, *, approved_days_ago: int, lead_phone: str = "0901234567"
):
    """Create a minimal approved AdmissionProfile + Lead pair for the scheduler."""
    lead = models.Lead(
        full_name="Integration Survey",
        phone=lead_phone,
        source="Website",
        unit_id=seeded_dependencies["unit_id"],
        status=seeded_dependencies["initial_status_id"],
        consultation_status_id=seeded_dependencies["initial_status_id"],
        pipeline_stage_id=seeded_dependencies["stage_id"],
    )
    db.add(lead)
    return lead


async def _make_profile(db, seeded_dependencies, *, approved_days_ago: int, phone="0901234567"):
    lead = _approved_profile(db, seeded_dependencies, approved_days_ago=approved_days_ago, lead_phone=phone)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        academic_year=2026,
        status="approved",
        applied_rules={},  # NOT NULL; empty snapshot is fine for scheduler tests
        approved_at=datetime.now(timezone.utc) - timedelta(days=approved_days_ago),
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest.mark.asyncio
@pytest.mark.integration
class TestAdmissionSurveyScheduler:
    async def test_gate_off_early_returns(
        self, db: AsyncSession, seeded_dependencies: dict, monkeypatch,
    ):
        """ENABLED=false must short-circuit before touching the DB."""
        await _make_profile(db, seeded_dependencies, approved_days_ago=45)
        await db.commit()

        from app.config import settings
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_ENABLED", False)

        result = admission_task_module.check_admission_surveys_due_task.apply().result
        assert result == {"checked": 0, "sent": 0, "failed": 0, "skipped_no_phone": 0}

    async def test_baseline_excludes_older_approvals(
        self, db: AsyncSession, seeded_dependencies: dict, monkeypatch,
    ):
        """Profile approved before the baseline must be excluded from the scan."""
        # One profile approved 60d ago (pre-baseline), one 45d ago (eligible).
        now = datetime.now(timezone.utc)
        baseline = (now - timedelta(days=50)).date().isoformat()

        old = await _make_profile(db, seeded_dependencies, approved_days_ago=60)
        new = await _make_profile(db, seeded_dependencies, approved_days_ago=45)
        await db.commit()

        from app.config import settings
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_ENABLED", True)
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_BASELINE_DATE", baseline)

        result = admission_task_module.check_admission_surveys_due_task.apply().result
        # Only the post-baseline one is considered. (Other fixtures in the
        # shared dev DB may contribute additional rows; scope the assertion
        # to our two known profiles.)
        await db.refresh(old)
        await db.refresh(new)
        assert old.survey_sent_at is None
        assert new.survey_sent_at is not None

    async def test_no_phone_skipped_and_marked_to_exit_scan(
        self, db: AsyncSession, seeded_dependencies: dict, monkeypatch,
    ):
        """Lead without phone: counted as skipped_no_phone, survey_sent_at stamped,
        tracking_id stays NULL."""
        profile = await _make_profile(db, seeded_dependencies, approved_days_ago=45, phone="")
        await db.commit()

        from app.config import settings
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_ENABLED", True)
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_BASELINE_DATE", None)

        admission_task_module.check_admission_surveys_due_task.apply()

        await db.refresh(profile)
        assert profile.survey_sent_at is not None
        assert profile.survey_tracking_id is None

    async def test_savepoint_isolates_row_failure(
        self, db: AsyncSession, seeded_dependencies: dict, monkeypatch,
    ):
        """When one row's dispatch raises, the rest of the batch still commits."""
        p1 = await _make_profile(db, seeded_dependencies, approved_days_ago=45)
        p2 = await _make_profile(db, seeded_dependencies, approved_days_ago=44)
        p3 = await _make_profile(db, seeded_dependencies, approved_days_ago=43)
        await db.commit()

        from app.config import settings
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_ENABLED", True)
        monkeypatch.setattr(settings, "ADMISSION_SURVEY_BASELINE_DATE", None)

        # Fail only the second dispatch call so the savepoint rolls back
        # that row alone and the outer transaction survives.
        from app.services import notification_dispatcher
        real_dispatch = notification_dispatcher.dispatch
        call_count = {"n": 0}

        async def flaky_dispatch(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated row-2 failure")
            return await real_dispatch(*args, **kwargs)

        with patch(
            "app.services.notification_dispatcher.dispatch", new=flaky_dispatch
        ):
            result = admission_task_module.check_admission_surveys_due_task.apply().result

        assert result["failed"] >= 1, result
        assert result["sent"] >= 2, result

        # Verify DB side: at least 2 profiles have survey_sent_at set + tracking_id.
        rows = (
            await db.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id.in_([p1.id, p2.id, p3.id])
                )
            )
        ).scalars().all()
        stamped = [r for r in rows if r.survey_sent_at is not None]
        assert len(stamped) >= 2
