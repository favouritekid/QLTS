"""Integration tests for ``delete_profile``'s lead-status revert DERIVATION.

The pure-policy unit tests in ``tests/unit/test_delete_profile_file_cleanup.py``
pin ``_resolve_lead_revert_status`` in isolation — they feed it
``prev_consultation_status_id`` / ``prev_is_terminal_or_negative`` directly.
What they do NOT cover is how ``delete_profile`` *derives* those values from
``LeadStatusHistory``: the "most-recent row must be THIS profile's
``profile_created`` bump" rule plus the terminal/negative guard. That
derivation is exactly where the review's finding #1 (an independent ``sts06``
being mis-attributed to profile creation and silently demoting the lead) lived.

These tests drive the real service against the DB so the history lookup, the
``"profile_created" in reason`` attribution, the other-profile gate, the
terminal/negative guard, the returned revert-delta and the deletion-record
stamping are all exercised end-to-end. ``delete_profile`` flushes but does not
commit; the function-scoped ``db`` fixture rolls back per test.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select

from app import models
from app.models.pipeline import OutcomeTypeEnum
from app.services import admission_service


pytestmark = pytest.mark.asyncio


# Mirrors the reason written by ``_create_admission_milestone_consultation``
# (``reason=f"Admission event: {event}"`` with ``event="profile_created"``).
# ``delete_profile`` keys the revert on ``"profile_created" in reason``.
PROFILE_CREATED_REASON = "Admission event: profile_created"

# Per-test sequence so leads/profiles get unique phone/email/citizen_id.
_seq = 0


def _next() -> int:
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Seed: consultation statuses + stages the revert logic needs, with the
# outcome_type / is_final flags set EXACTLY (the policy reads them).
# ---------------------------------------------------------------------------
async def _seed_revert_statuses(db) -> None:
    for stage_id, name, order in (
        ("stg02", "Đang tư vấn", 1002),
        ("stg03", "Đã nộp hồ sơ", 1003),
    ):
        if await db.get(models.PipelineStage, stage_id) is None:
            db.add(models.PipelineStage(id=stage_id, name=name, order=order))
    await db.flush()

    # id,      stage,    outcome,                   is_final
    rows = [
        ("sts03", "stg02", OutcomeTypeEnum.neutral, False),   # Có nhu cầu tìm hiểu
        ("sts04", "stg02", OutcomeTypeEnum.negative, False),  # Từ chối tư vấn (negative)
        ("sts05", "stg02", OutcomeTypeEnum.neutral, False),   # Hẹn liên hệ lại
        ("sts06", "stg02", OutcomeTypeEnum.positive, False),  # Đồng ý tư vấn (create target)
        ("sts07", "stg03", OutcomeTypeEnum.neutral, False),   # Đã tiếp nhận hồ sơ
        ("sts20", "stg02", OutcomeTypeEnum.negative, True),   # Đã ngừng tư vấn (terminal)
    ]
    for sid, stage_id, outcome, is_final in rows:
        if await db.get(models.ConsultationStatus, sid) is None:
            db.add(
                models.ConsultationStatus(
                    id=sid,
                    name=sid,
                    color_code="#123456",
                    stage_id=stage_id,
                    outcome_type=outcome,
                    is_final=is_final,
                )
            )
    await db.flush()


@pytest_asyncio.fixture
async def revert_statuses(db):
    await _seed_revert_statuses(db)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
async def _make_lead(db, unit_id, officer_id, cs_id, stage_id):
    n = _next()
    lead = models.Lead(
        full_name=f"Revert Lead {n}",
        phone=f"09{n:08d}",
        email=f"revert_{n}@test.com",
        source="website",
        unit_id=unit_id,
        assigned_officer_id=officer_id,
        consultation_status_id=cs_id,
        pipeline_stage_id=stage_id,
        consultation_count=1,
        status="qualified",
    )
    db.add(lead)
    await db.flush()
    return lead


async def _make_draft(db, lead_id, academic_year=2026):
    n = _next()
    profile = models.AdmissionProfile(
        lead_id=lead_id,
        status="draft",
        citizen_id=f"{n:012d}",
        version=1,
        applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
        academic_year=academic_year,
        full_name="Revert Applicant",
        phone="0901234567",
    )
    db.add(profile)
    await db.flush()
    return profile


async def _add_history(db, lead_id, *, old_cs, new_cs, reason, user_id,
                       old_stage="stg02", new_stage="stg02"):
    """Append a LeadStatusHistory row. Insertion order == id order, so the
    LAST row added is the one ``delete_profile`` treats as 'most recent'.

    ``new_status`` (legacy lead.status) is NOT NULL; the revert derivation
    never reads it, so a valid placeholder is fine."""
    db.add(
        models.LeadStatusHistory(
            lead_id=lead_id,
            old_status="qualified",
            new_status="qualified",
            old_consultation_status_id=old_cs,
            new_consultation_status_id=new_cs,
            old_pipeline_stage_id=old_stage,
            new_pipeline_stage_id=new_stage,
            reason=reason,
            changed_by_user_id=user_id,
        )
    )
    await db.flush()


async def _latest_history(db, lead_id):
    return (
        await db.execute(
            select(models.LeadStatusHistory)
            .where(models.LeadStatusHistory.lead_id == lead_id)
            .order_by(models.LeadStatusHistory.id.desc())
        )
    ).scalars().first()


async def _system_consultation(db, lead_id):
    return (
        await db.execute(
            select(models.Consultation)
            .where(
                models.Consultation.lead_id == lead_id,
                models.Consultation.method == "system",
            )
            .order_by(models.Consultation.id.desc())
        )
    ).scalars().first()


# ===========================================================================
# TESTS
# ===========================================================================
class TestDeleteProfileLeadRevert:
    async def test_reverts_to_prev_when_create_bump_is_latest(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """Happy path: lead was sts03, profile creation bumped it to sts06 and
        that bump is the most-recent history row → deleting the draft reverts
        the lead to sts03 and surfaces the delta to the router."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts06", "stg02"
        )
        await _add_history(
            db, lead.id, old_cs="sts03", new_cs="sts06",
            reason=PROFILE_CREATED_REASON, user_id=officer_user.id,
        )
        profile = await _make_draft(db, lead.id)

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=profile.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts03"
        assert lead.pipeline_stage_id == "stg02"
        # profile is gone
        assert await db.get(models.AdmissionProfile, profile.id) is None
        # delta surfaced so the router can dispatch LEAD_STATUS_CHANGED
        assert delta == {
            "old_status": "sts06",
            "new_status": "sts03",
            "old_stage": "stg02",
            "new_stage": "stg02",
        }
        # a revert history row was written
        latest = await _latest_history(db, lead.id)
        assert latest.new_consultation_status_id == "sts03"
        assert "Hoàn trạng thái" in (latest.reason or "")
        # finding #9: deletion record stamped with status AT delete (sts06),
        # NOT the reverted sts03
        consult = await _system_consultation(db, lead.id)
        assert consult is not None
        assert consult.consultation_status_id == "sts06"
        # best-effort cleanup callback is awaitable and never raises
        await cleanup()

    async def test_no_revert_when_sts06_not_from_profile(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """Finding #1: the lead reached sts06 independently (officer "Đồng ý
        tư vấn" / lead_agrees), then a profile was created while ALREADY at
        sts06 (so creation wrote no history row). Deleting the draft must NOT
        demote the lead — the latest history row is not a profile_created bump."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts06", "stg02"
        )
        await _add_history(
            db, lead.id, old_cs="sts03", new_cs="sts06",
            reason="Admission event: lead_agrees", user_id=officer_user.id,
        )
        profile = await _make_draft(db, lead.id)

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=profile.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts06"  # preserved, NOT sts03
        assert delta is None
        await cleanup()

    async def test_no_revert_when_status_changed_after_create_bump(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """An intervening status change after the create bump makes the bump no
        longer the latest row → no revert (the lead's later state is real)."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts06", "stg02"
        )
        # create bump first ...
        await _add_history(
            db, lead.id, old_cs="sts03", new_cs="sts06",
            reason=PROFILE_CREATED_REASON, user_id=officer_user.id,
        )
        profile = await _make_draft(db, lead.id)
        # ... then an officer re-touches the lead (newer, non-profile_created row)
        await _add_history(
            db, lead.id, old_cs="sts05", new_cs="sts06",
            reason="Cập nhật thủ công trạng thái tư vấn", user_id=officer_user.id,
        )

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=profile.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts06"
        assert delta is None
        await cleanup()

    async def test_no_revert_when_other_profile_exists(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """A second profile justifies the lead's sts06 → deleting one draft
        leaves the lead untouched and the other profile intact."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts06", "stg02"
        )
        await _add_history(
            db, lead.id, old_cs="sts03", new_cs="sts06",
            reason=PROFILE_CREATED_REASON, user_id=officer_user.id,
        )
        p1 = await _make_draft(db, lead.id, academic_year=2026)
        p2 = await _make_draft(db, lead.id, academic_year=2027)

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=p1.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts06"
        assert delta is None
        assert await db.get(models.AdmissionProfile, p2.id) is not None
        await cleanup()

    async def test_no_revert_to_terminal_prev(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """Finding #2: a lost lead (sts20, terminal) reopened to sts06 by
        creating a draft must NOT be re-closed to sts20 when the draft is
        deleted — the revert refuses a terminal/negative target."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts06", "stg02"
        )
        await _add_history(
            db, lead.id, old_cs="sts20", new_cs="sts06",
            reason=PROFILE_CREATED_REASON, user_id=officer_user.id,
        )
        profile = await _make_draft(db, lead.id)

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=profile.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts06"  # NOT re-closed to sts20
        assert delta is None
        await cleanup()

    async def test_no_revert_to_negative_prev(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """A negative (but non-terminal) prior status (sts04 "Từ chối tư vấn")
        must also be refused — deleting a draft never regresses a lead into a
        negative consultation outcome."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts06", "stg02"
        )
        await _add_history(
            db, lead.id, old_cs="sts04", new_cs="sts06",
            reason=PROFILE_CREATED_REASON, user_id=officer_user.id,
        )
        profile = await _make_draft(db, lead.id)

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=profile.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts06"
        assert delta is None
        await cleanup()

    async def test_no_revert_when_lead_advanced_past_sts06(
        self, db, seeded_dependencies, officer_user, revert_statuses
    ):
        """The lead has advanced past sts06 (e.g. another profile submitted →
        sts07). The latest history row's new status is not sts06 → no revert."""
        lead = await _make_lead(
            db, seeded_dependencies["unit_id"], officer_user.id, "sts07", "stg03"
        )
        await _add_history(
            db, lead.id, old_cs="sts06", new_cs="sts07",
            reason="Admission event: profile_submitted", user_id=officer_user.id,
            old_stage="stg02", new_stage="stg03",
        )
        profile = await _make_draft(db, lead.id)

        ok, cleanup, delta = await admission_service.delete_profile(
            db=db, profile_id=profile.id, current_user=officer_user
        )

        assert ok is True
        await db.refresh(lead)
        assert lead.consultation_status_id == "sts07"
        assert delta is None
        await cleanup()
