"""Integration tests for the weekly admission report (service + repository + DB).

Resolution here uses the **offering fallback** tier (lead.offering → major) so the
seed stays light — no admission_path / method / criteria / subject-group chain.
The deep multi-NV resolver tiers are covered by the pure unit tests.

Each test uses a UNIQUE academic_year so a ``report(year)`` call never sees another
test's rows (the shared test DB is not rolled back per-test).
"""

import itertools
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories.admission_report_repository import (
    UNRESOLVED,
    AdmissionReportRepository,
)
from app.services.admission_report_service import VN_TZ, AdmissionReportService
from app.utils.exceptions import BusinessRuleViolation, ValidationError

pytestmark = pytest.mark.asyncio

_seq = itertools.count(1)
_year_seq = itertools.count(2050)


def _admin() -> models.User:
    return models.User(role="admin", unit_id=None)


async def _seed_catalog(db: AsyncSession, year: int, unit_id: int):
    n = next(_seq)
    major = models.MajorProgram(
        name=f"Ngành {n}", code=f"RPT{n:05d}", degree_level="Cao đẳng", unit_id=unit_id
    )
    db.add(major)
    await db.flush()
    offering = models.ProgramOffering(offering_type="Chính quy", program_id=major.id)
    db.add(offering)
    await db.flush()
    db.add(models.OfferingAcademicInfo(academic_year=year, offering_id=offering.id))
    db.add(
        models.OfferingAdmissionRound(
            academic_year=year,
            round_code="DOT_TEST",
            round_name="Đợt test",
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
            is_active=True,
        )
    )
    await db.flush()
    return major, offering


async def _seed_lead_profile(
    db, deps, year, offering_id, officer_id, *, created_at, deleted=False, unit_id=None
):
    n = next(_seq)
    lead = models.Lead(
        full_name=f"RPT Lead {n}",
        phone=f"08{n:08d}",
        email=f"rpt_{n}@t.com",
        source="website",
        unit_id=unit_id or deps["unit_id"],
        consultation_status_id=deps["initial_status_id"],
        status="new",
        offering_id=offering_id,
        assigned_officer_id=officer_id,
        created_at=created_at,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db.add(lead)
    await db.flush()
    profile = models.AdmissionProfile(
        lead_id=lead.id,
        status="submitted",
        citizen_id=f"{n:012d}",
        version=1,
        applied_rules={},
        academic_year=year,
        uses_choice_engine=False,
    )
    db.add(profile)
    await db.flush()
    return lead, profile


async def _seed_history(db, profile_id, to_status, occurred_at, from_status="draft"):
    db.add(
        models.AdmissionProfileStatusHistory(
            profile_id=profile_id,
            from_status=from_status,
            to_status=to_status,
            occurred_at=occurred_at,
            transitioned_by_role="system",
            actor_actual_role="system",
            effective_transition_role="system",
        )
    )
    await db.flush()


async def _seed_fee(db, profile_id, year, fee_type="application"):
    fee = models.Fee(
        admission_profile_id=profile_id,
        fee_type=fee_type,
        academic_year=year,
        base_amount=Decimal("1000000"),
        final_amount=Decimal("1000000"),
        semester_no=(1 if fee_type == "tuition" else None),
        calculated_at=datetime.now(timezone.utc),
    )
    db.add(fee)
    await db.flush()
    return fee


async def _add_txn(db, fee_id, ttype, amount, created_at):
    db.add(
        models.PaymentTransaction(
            fee_id=fee_id,
            transaction_type=ttype,
            amount=Decimal(amount),
            balance_before=Decimal("0"),
            balance_after=Decimal("0"),
            created_at=created_at,
        )
    )
    await db.flush()


def _week(year: int):
    anchor = date(year, 6, 17)
    _, win = AdmissionReportService._compute_week(anchor)
    return anchor, win


def _find(rows, key):
    return next((r for r in rows if r.group_key == key), None)


async def test_weekly_report_major_end_to_end(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)

    major, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=2),
    )
    await _seed_history(db, profile.id, "submitted", win.start + timedelta(days=2))
    fee = await _seed_fee(db, profile.id, year)
    await _add_txn(db, fee.id, "payment", "1000000", win.start + timedelta(days=3))
    await _add_txn(db, fee.id, "refund", "-200000", win.start + timedelta(days=3))

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )

    row = _find(resp.rows, major.id)
    assert row is not None, "major row must be present"
    assert row.lead.new_in_week == 1
    assert row.admission.submitted_in_week == 1
    assert row.admission.submitted_cumulative == 1
    assert row.finance.gross_in_week == Decimal("1000000")
    assert row.finance.refund_in_week == Decimal("200000")
    assert row.finance.net_in_week == Decimal("800000")
    assert row.finance.application_net_in_week == Decimal("800000")
    assert row.finance.net_cumulative == Decimal("800000")
    assert row.admission.profiles_total == 1
    assert row.finance.profiles_paid == 1
    assert resp.data_quality.total_profiles == 1
    assert resp.totals.finance.net_in_week == Decimal("800000")
    assert resp.week.week_start == win.start.date()


async def test_soft_deleted_lead_excluded_from_report(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)

    major, offering = await _seed_catalog(db, year, unit_id)
    # active
    _, p_active = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
    )
    fee_a = await _seed_fee(db, p_active.id, year)
    await _add_txn(db, fee_a.id, "payment", "1000000", win.start + timedelta(days=1))
    # soft-deleted lead — must contribute nothing
    _, p_del = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
        deleted=True,
    )
    fee_d = await _seed_fee(db, p_del.id, year)
    await _add_txn(db, fee_d.id, "payment", "5000000", win.start + timedelta(days=1))

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.lead.new_in_week == 1, "deleted lead must not be counted"
    assert row.finance.gross_in_week == Decimal(
        "1000000"
    ), "deleted lead's 5M must be excluded"


async def test_group_by_officer(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)

    _, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=2),
    )
    await _seed_history(db, profile.id, "submitted", win.start + timedelta(days=2))

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="officer", week_start=anchor
    )
    row = _find(resp.rows, officer_id)
    assert row is not None, "officer row must be present"
    assert row.lead.new_in_week == 1
    assert row.admission.submitted_in_week == 1
    assert row.label and not row.is_bucket


async def test_lead_without_offering_goes_to_unresolved_bucket(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    anchor, win = _week(year)

    # need a round for the cohort window even though the lead has no offering
    await _seed_catalog(db, year, unit_id)
    n = next(_seq)
    db.add(
        models.Lead(
            full_name=f"RPT NoOff {n}",
            phone=f"08{n:08d}",
            email=f"rptno_{n}@t.com",
            source="website",
            unit_id=unit_id,
            consultation_status_id=seeded_dependencies["initial_status_id"],
            status="new",
            offering_id=None,
            created_at=win.start + timedelta(days=2),
        )
    )
    await db.flush()

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    bucket = next((r for r in resp.rows if r.bucket_kind == UNRESOLVED), None)
    assert (
        bucket is not None
    ), "lead without offering must land in the unresolved bucket"
    assert bucket.is_bucket and bucket.lead.new_in_week >= 1


async def test_payment_before_week_counts_cumulative_not_in_week(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)

    major, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
    )
    fee = await _seed_fee(db, profile.id, year)
    # payment 10 days BEFORE the week → cumulative only
    await _add_txn(db, fee.id, "payment", "300000", win.start - timedelta(days=10))

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.finance.net_in_week == Decimal("0")
    assert row.finance.net_cumulative == Decimal("300000")


async def _seed_consult_status(
    db, *, outcome="positive", phase="consultation", is_final=False
):
    n = next(_seq)
    cs = models.ConsultationStatus(
        id=f"rptcs{n}",
        name=f"CS {n}",
        color_code="#00AA00",
        phase=phase,
        outcome_type=models.OutcomeTypeEnum(outcome),
        is_final=is_final,
    )
    db.add(cs)
    await db.flush()
    return cs.id


async def test_consulting_positive_stock(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)
    cs_id = await _seed_consult_status(db)  # phase=consultation, outcome=positive
    n = next(_seq)
    db.add(
        models.Lead(
            full_name=f"RPT CP {n}",
            phone=f"08{n:08d}",
            email=f"rptcp_{n}@t.com",
            source="website",
            unit_id=unit_id,
            consultation_status_id=cs_id,
            status="new",
            offering_id=offering.id,
            created_at=win.start + timedelta(days=2),
        )
    )
    await db.flush()

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.lead.consulting_positive_current == 1
    assert row.lead.active_current == 1  # not final


async def test_admission_first_transition_not_double_counted(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    _, win_a = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win_a.start + timedelta(days=1),
    )
    await _seed_history(db, profile.id, "submitted", win_a.start + timedelta(days=1))
    await _seed_history(db, profile.id, "resubmitted", win_a.start + timedelta(days=40))

    later_anchor = (win_a.start + timedelta(days=40)).date()
    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=later_anchor,
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.admission.submitted_in_week == 0  # first transition was in week A
    assert row.admission.submitted_cumulative == 1


async def test_cohort_overlapping_rounds_dedup_lead(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)
    db.add(
        models.OfferingAdmissionRound(
            academic_year=year,
            round_code="DOT_TEST2",
            round_name="Đợt 2",
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
            is_active=True,
        )
    )
    await db.flush()
    await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=2),
    )

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.lead.new_in_week == 1  # not 2 despite overlapping round windows


async def test_round_missing_dates_fails_closed(
    db: AsyncSession, seeded_dependencies: dict
):
    year = next(_year_seq)
    db.add(
        models.OfferingAdmissionRound(
            academic_year=year,
            round_code="DOT_BAD",
            round_name="Bad",
            start_date=None,
            end_date=None,
            is_active=True,
        )
    )
    await db.flush()
    svc = AdmissionReportService(db)
    with pytest.raises(BusinessRuleViolation):
        await svc.get_weekly_report(
            current_user=_admin(),
            academic_year=year,
            group_by="major",
            round_code="DOT_BAD",
            week_start=date(year, 6, 17),  # in-year week → reaches cohort validation
        )


async def test_round_filter_keeps_unresolved_profile_bucket(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    anchor, win = _week(year)
    await _seed_catalog(db, year, unit_id)  # seeds round DOT_TEST with valid dates
    n = next(_seq)
    lead = models.Lead(
        full_name=f"RPT UR {n}",
        phone=f"08{n:08d}",
        email=f"rptur_{n}@t.com",
        source="website",
        unit_id=unit_id,
        consultation_status_id=seeded_dependencies["initial_status_id"],
        status="new",
        offering_id=None,
        created_at=win.start + timedelta(days=2),
    )
    db.add(lead)
    await db.flush()
    db.add(
        models.AdmissionProfile(
            lead_id=lead.id,
            status="submitted",
            citizen_id=f"{n:012d}",
            version=1,
            applied_rules={},
            academic_year=year,
            uses_choice_engine=False,
        )
    )
    await db.flush()

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=anchor,
        round_code="DOT_TEST",
    )
    bucket = next((r for r in resp.rows if r.bucket_kind == UNRESOLVED), None)
    assert bucket is not None, "unresolved profile must survive round filter"
    assert bucket.admission.profiles_total == 1
    assert resp.data_quality.unresolved_profiles == 1


async def test_funnel_monotone_admitted_without_submitted_history(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """A profile with only an 'admitted' history row (override bypassed submitted)
    must still count as submitted — funnel stays monotone (submitted ≥ admitted)."""
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
    )
    await _seed_history(db, profile.id, "admitted", win.start + timedelta(days=2))

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.admission.admitted_cumulative == 1
    assert row.admission.submitted_cumulative == 1  # derived (monotone)
    assert row.admission.submitted_in_week >= row.admission.admitted_in_week


async def test_walk_in_lead_outside_window_aligned_via_profile(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """A lead created OUTSIDE the round window but holding an in-scope profile is
    still part of the lead population (admission never exceeds lead)."""
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=datetime(year - 1, 3, 1, tzinfo=VN_TZ),  # before the round window
    )

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.admission.profiles_total == 1
    assert row.lead.active_current == 1  # included despite created outside window
    assert row.lead.new_in_week == 0  # but NOT a "new this week" lead


async def test_week_start_before_academic_year_rejected(
    db: AsyncSession, seeded_dependencies: dict
):
    year = next(_year_seq)
    svc = AdmissionReportService(db)
    with pytest.raises(ValidationError):
        await svc.get_weekly_report(
            current_user=_admin(),
            academic_year=year,
            group_by="major",
            week_start=date(year - 1, 6, 1),
        )


async def test_future_year_implicit_week_defaults_in_year(
    db: AsyncSession, seeded_dependencies: dict
):
    # FUTURE academic year + no week_start: anchor to that year's ISO week 1 instead
    # of silently returning the current calendar year's week metadata.
    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=2200, group_by="major"
    )
    assert resp.week.iso_year == 2200
    assert resp.academic_year == 2200


async def test_report_years_include_config_only_year(
    db: AsyncSession, seeded_dependencies: dict
):
    # A year with a round configured but NO profiles must still be listable
    # (config ∪ data) — unlike the profile-only get_distinct_academic_years.
    year = next(_year_seq)
    db.add(
        models.OfferingAdmissionRound(
            academic_year=year,
            round_code="DOT_1",
            round_name="Đợt 1",
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31),
            is_active=True,
        )
    )
    await db.flush()
    repo = AdmissionReportRepository(db)
    assert year in await repo.list_report_years()
    assert await repo.list_report_rounds(year) == ["DOT_1"]


async def test_synthetic_backfill_row_excluded_from_milestones(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """A phase1_10 synthetic initial-state row (from_status=None → status @
    created_at) must NOT be counted as a milestone (it mis-dates legacy events)."""
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)
    _, profile = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
    )
    # synthetic backfill row — from_status=None, mis-dated at the creation week
    await _seed_history(
        db, profile.id, "enrolled", win.start + timedelta(days=1), from_status=None
    )

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.admission.profiles_total == 1  # profile still present
    assert row.admission.enrolled_cumulative == 0  # synthetic row excluded
    assert row.admission.submitted_cumulative == 0


async def test_iso_week1_monday_in_prior_year_not_rejected(
    db: AsyncSession, seeded_dependencies: dict
):
    """ISO week 1's Monday can fall in the prior calendar year; sending that
    canonical Monday back for the same academic_year must NOT be rejected."""
    year = next(_year_seq)
    jan4 = date(year, 1, 4)  # ISO week 1 always contains Jan 4
    monday_w1 = jan4 - timedelta(days=jan4.isocalendar()[2] - 1)  # Monday of ISO week 1

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=monday_w1,
    )
    assert resp.week.iso_year == year
    assert resp.week.week_start == monday_w1  # refetch-stable, not rejected
