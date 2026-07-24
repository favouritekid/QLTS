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
from app.utils.datetime_helpers import today_vn
from app.utils.exceptions import BusinessRuleViolation, ValidationError

pytestmark = pytest.mark.asyncio

_seq = itertools.count(1)
_year_seq = itertools.count(2050)


def _admin() -> models.User:
    return models.User(role="admin", unit_id=None)


def _manager(unit_id: int) -> models.User:
    return models.User(role="manager", unit_id=unit_id)


async def _seed_catalog(
    db: AsyncSession, year: int, unit_id: int, *, quota=None, active=True
):
    n = next(_seq)
    major = models.MajorProgram(
        name=f"Ngành {n}",
        code=f"RPT{n:05d}",
        degree_level="Cao đẳng",
        unit_id=unit_id,
        is_active=active,
    )
    db.add(major)
    await db.flush()
    offering = models.ProgramOffering(
        offering_type="Chính quy", program_id=major.id, is_active=active
    )
    db.add(offering)
    await db.flush()
    db.add(
        models.OfferingAcademicInfo(
            academic_year=year, offering_id=offering.id, annual_admission_quota=quota
        )
    )
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


async def test_quota_and_conversion_attached(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)

    major, offering = await _seed_catalog(db, year, unit_id, quota=100)
    # 4 submitted; of those 2 admitted (approved); of those 1 enrolled
    for i in range(4):
        _, p = await _seed_lead_profile(
            db,
            seeded_dependencies,
            year,
            offering.id,
            officer_id,
            created_at=win.start + timedelta(days=1),
        )
        await _seed_history(db, p.id, "submitted", win.start + timedelta(days=1))
        if i < 2:
            await _seed_history(
                db,
                p.id,
                "approved",
                win.start + timedelta(days=2),
                from_status="submitted",
            )
        if i < 1:
            await _seed_history(
                db,
                p.id,
                "enrolled",
                win.start + timedelta(days=3),
                from_status="approved",
            )

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.admission.quota == 100
    assert row.admission.submitted_cumulative == 4
    assert row.admission.admitted_cumulative == 2
    assert row.admission.enrolled_cumulative == 1
    assert row.conversion.submit_to_admit == 0.5  # 2/4
    assert row.conversion.admit_to_enroll == 0.5  # 1/2
    assert resp.totals.admission.quota == 100


async def test_quota_none_for_officer_grouping(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    _, offering = await _seed_catalog(db, year, unit_id, quota=50)
    _, p = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
    )
    await _seed_history(db, p.id, "submitted", win.start + timedelta(days=1))
    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="officer",
        week_start=anchor,
    )
    # officer grouping never carries a major quota
    assert all(r.admission.quota is None for r in resp.rows)
    assert resp.totals.admission.quota is None


async def test_quota_major_with_no_activity_appears(
    db: AsyncSession, seeded_dependencies: dict
):
    # A major with a quota but ZERO leads/profiles MUST still appear (0%, top of
    # the cockpit) — it is exactly the behind-target ngành a manager needs to see.
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    major, _ = await _seed_catalog(db, year, unit_id, quota=120)
    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=date(year, 6, 17),
    )
    row = _find(resp.rows, major.id)
    assert row is not None, "quota major with no activity must not vanish"
    assert row.admission.quota == 120
    assert row.admission.submitted_cumulative == 0
    assert row.admission.profiles_total == 0
    assert resp.totals.admission.quota == 120


async def test_quota_hidden_when_round_filtered(
    db: AsyncSession, seeded_dependencies: dict
):
    # Year quota as the denominator only makes sense across the whole year. When a
    # single đợt is filtered, quota is omitted (FE then hides the progress).
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    major, _ = await _seed_catalog(db, year, unit_id, quota=80)
    svc = AdmissionReportService(db)
    full = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=date(year, 6, 17),
    )
    assert full.totals.admission.quota == 80
    assert _find(full.rows, major.id) is not None
    filtered = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=date(year, 6, 17),
        round_code="DOT_TEST",
    )
    assert filtered.totals.admission.quota is None
    assert all(r.admission.quota is None for r in filtered.rows)


async def test_quota_admin_only_hidden_for_unit_scope(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    # Quota is a whole-school per-offering target → shown to admin (scope toàn
    # trường) but hidden for a unit-scoped manager (no per-unit quota split).
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id, quota=100)
    _, p = await _seed_lead_profile(
        db,
        seeded_dependencies,
        year,
        offering.id,
        officer_id,
        created_at=win.start + timedelta(days=1),
    )
    await _seed_history(db, p.id, "submitted", win.start + timedelta(days=1))
    svc = AdmissionReportService(db)
    admin_resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    assert _find(admin_resp.rows, major.id).admission.quota == 100
    # Manager, KHÔNG lọc đợt (round_code=None ⇒ "Tất cả đợt"): quota vẫn phải ẩn
    # vì lý do là SCOPE ĐƠN VỊ, không phải lọc đợt. FE dựa vào đúng contract này
    # để hiện copy "Lát cắt theo đơn vị chưa có chỉ tiêu được phân bổ riêng".
    mgr_resp = await svc.get_weekly_report(
        current_user=_manager(unit_id),
        academic_year=year,
        group_by="major",
        round_code=None,
        week_start=anchor,
    )
    row = _find(mgr_resp.rows, major.id)
    assert row is not None  # manager has the activity
    assert row.admission.quota is None  # whole-school metric hidden for unit scope
    assert mgr_resp.totals.admission.quota is None
    # NO row may carry a quota under unit scope (not just the seeded major).
    assert all(r.admission.quota is None for r in mgr_resp.rows)
    # Scope is echoed so the FE can tell "unit scope" from "round filter".
    assert mgr_resp.scope_unit_id == unit_id


async def test_quota_excludes_archived_major(
    db: AsyncSession, seeded_dependencies: dict
):
    # An archived (is_active=False) major must not surface a live quota row.
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    await _seed_catalog(db, year, unit_id, quota=100, active=False)
    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(),
        academic_year=year,
        group_by="major",
        week_start=date(year, 6, 17),
    )
    assert resp.totals.admission.quota is None
    assert resp.rows == []


async def test_past_year_implicit_week_defaults_in_year(
    db: AsyncSession, seeded_dependencies: dict
):
    # Past year + no week_start → anchor inside that year (last ISO week), not
    # today's week (which would compute week/cumulative cutoffs outside the year).
    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=2020, group_by="major"
    )
    assert resp.week.iso_year == 2020
    assert resp.academic_year == 2020


async def test_report_years_include_live_profile_only_year(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    # A year with a LIVE-lead profile but no config IS selectable; a year that
    # exists only via a soft-deleted lead is NOT.
    live_year = next(_year_seq)
    del_year = next(_year_seq)
    officer_id = officer_user_in_db["id"]
    await _seed_lead_profile(
        db,
        seeded_dependencies,
        live_year,
        None,
        officer_id,
        created_at=datetime(live_year, 6, 1, tzinfo=timezone.utc),
    )
    await _seed_lead_profile(
        db,
        seeded_dependencies,
        del_year,
        None,
        officer_id,
        created_at=datetime(del_year, 6, 1, tzinfo=timezone.utc),
        deleted=True,
    )
    repo = AdmissionReportRepository(db)
    years = await repo.list_report_years()
    assert live_year in years
    assert del_year not in years


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


async def test_application_paid_without_submit_counts_prepay_draft(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """fee_paid_not_submitted = đã đóng lệ phí XÉT TUYỂN nhưng CHƯA có milestone
    submitted (nhóm prepay-draft cần nhắc hoàn tất). Một hồ sơ đã submit — dù
    cũng đóng lệ phí — KHÔNG tính; lệ phí 'tuition' không tính (chỉ application)."""
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    anchor, win = _week(year)
    major, offering = await _seed_catalog(db, year, unit_id)

    # (1) prepay-draft: application paid, NO submitted history → counted
    _, p_draft = await _seed_lead_profile(
        db, seeded_dependencies, year, offering.id, officer_id,
        created_at=win.start + timedelta(days=1),
    )
    fee_d = await _seed_fee(db, p_draft.id, year)  # application
    await _add_txn(db, fee_d.id, "payment", "1000000", win.start + timedelta(days=2))

    # (2) submitted + application paid → NOT prepay-draft (already nộp)
    _, p_sub = await _seed_lead_profile(
        db, seeded_dependencies, year, offering.id, officer_id,
        created_at=win.start + timedelta(days=1),
    )
    await _seed_history(db, p_sub.id, "submitted", win.start + timedelta(days=2))
    fee_s = await _seed_fee(db, p_sub.id, year)
    await _add_txn(db, fee_s.id, "payment", "1000000", win.start + timedelta(days=2))

    # (3) tuition paid only (no application, no submit) → NOT counted
    _, p_tui = await _seed_lead_profile(
        db, seeded_dependencies, year, offering.id, officer_id,
        created_at=win.start + timedelta(days=1),
    )
    fee_t = await _seed_fee(db, p_tui.id, year, fee_type="tuition")
    await _add_txn(db, fee_t.id, "payment", "1000000", win.start + timedelta(days=2))

    svc = AdmissionReportService(db)
    resp = await svc.get_weekly_report(
        current_user=_admin(), academic_year=year, group_by="major", week_start=anchor
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.admission.fee_paid_not_submitted == 1  # only p_draft
    assert row.admission.submitted_cumulative == 1  # only p_sub (milestone)
    assert resp.totals.admission.fee_paid_not_submitted == 1


async def test_officer_major_matrix_five_metrics_end_to_end(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """Ô matrix đếm 5 chỉ số: submitted/enrolled (milestone) · draft (status hồ
    sơ HIỆN TẠI) · fee_partial/fee_full (học phí HK1). Năm tương lai → cutoff
    cumulative ≈ tuần đầu tháng 1, nên mốc submit/enroll seed vào 04/01 để được
    đếm; draft & học phí không phụ thuộc thời gian.
    """
    year = next(_year_seq)
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    at = datetime(year, 1, 4, 12, tzinfo=VN_TZ)  # trong tuần cutoff (năm tương lai)
    major, offering = await _seed_catalog(db, year, unit_id)

    async def _profile(status="submitted"):
        _, p = await _seed_lead_profile(
            db, seeded_dependencies, year, offering.id, officer_id, created_at=at
        )
        if status != "submitted":
            p.status = status
            await db.flush()
        return p

    # (1) đã nộp
    p_sub = await _profile()
    await _seed_history(db, p_sub.id, "submitted", at)
    # (2) nháp — status='draft', KHÔNG có mốc submitted
    await _profile(status="draft")
    # (3) học phí HK1 một phần (paid>0, còn nợ) + đã nộp
    p_part = await _profile()
    await _seed_history(db, p_part.id, "submitted", at)
    f_part = await _seed_fee(db, p_part.id, year, fee_type="tuition")
    f_part.paid_amount = Decimal("400000")  # final 1,000,000 → remaining 600,000
    await db.flush()
    # (4) đóng đủ HK1 (remaining<=0) + đã nộp + nhập học
    p_full = await _profile()
    await _seed_history(db, p_full.id, "submitted", at)
    await _seed_history(db, p_full.id, "enrolled", at, from_status="submitted")
    f_full = await _seed_fee(db, p_full.id, year, fee_type="tuition")
    f_full.paid_amount = Decimal("1000000")  # remaining 0 → đóng đủ
    await db.flush()
    # (5) MIỄN 100% học phí HK1 (final=0 do chiết khấu hết base) + đã nộp — nghĩa
    # vụ đã tất toán nên tính "đóng đủ" (fee_full), không phải "chưa đóng".
    p_waived = await _profile()
    await _seed_history(db, p_waived.id, "submitted", at)
    f_waived = await _seed_fee(db, p_waived.id, year, fee_type="tuition")
    f_waived.total_discount = Decimal("1000000")
    f_waived.final_amount = Decimal("0")  # base 1.000.000 − chiết khấu 1.000.000
    await db.flush()

    svc = AdmissionReportService(db)
    resp = await svc.get_officer_major_matrix(current_user=_admin(), academic_year=year)

    cell = next(
        c for c in resp.cells if c.officer_id == officer_id and c.major_id == major.id
    )
    assert cell.submitted == 4  # p_sub, p_part, p_full, p_waived (đều có mốc submitted)
    assert cell.draft == 1  # chỉ hồ sơ status='draft'
    assert cell.fee_partial == 1  # p_part
    assert cell.fee_full == 2  # p_full (đóng đủ) + p_waived (miễn 100%)
    assert cell.enrolled == 1  # p_full


# --------------------------------------------------------- pipeline funnel (DB)
async def _seed_pstage(db, *, is_final=False):
    n = next(_seq)
    sid = f"rptfst{n}"
    db.add(
        models.PipelineStage(
            id=sid, name=f"FStage {n}", order=900000 + n, is_final_stage=is_final
        )
    )
    await db.flush()
    return sid


async def _seed_funnel_status(
    db, *, stage_id, outcome="neutral", is_final=False, counts_for_funnel=True
):
    n = next(_seq)
    cs = models.ConsultationStatus(
        id=f"rptfcs{n}",
        name=f"FCS {n}",
        color_code="#123456",
        stage_id=stage_id,
        outcome_type=models.OutcomeTypeEnum(outcome),
        is_final=is_final,
        counts_for_funnel=counts_for_funnel,
    )
    db.add(cs)
    await db.flush()
    return cs.id


async def _seed_funnel_lead(
    db, deps, year, *, stage_id, cs_id, created_at, offering_id=None, with_profile=False
):
    n = next(_seq)
    lead = models.Lead(
        full_name=f"RPT FN {n}",
        phone=f"08{n:08d}",
        email=f"rptfn_{n}@t.com",
        source="website",
        unit_id=deps["unit_id"],
        consultation_status_id=cs_id,
        pipeline_stage_id=stage_id,
        status="new",
        offering_id=offering_id,
        created_at=created_at,
    )
    db.add(lead)
    await db.flush()
    if with_profile:
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
    return lead


async def test_pipeline_funnel_leak_by_outcome_counts_for_funnel_and_walk_in(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """Funnel aggregation contract exercised WITH data (not the empty-year early
    return at repository.py). Covers three review findings at once:
      • early exit by OUTCOME: a lead with a final+negative status at a NON-terminal
        stage → leaked, NOT inflating the success path;
      • counts_for_funnel=false (activity status) → excluded entirely;
      • walk-in: a lead created OUTSIDE the round window but holding an in-scope
        profile → pulled into the cohort via profile_lead_ids.
    """
    year = next(_year_seq)
    deps = seeded_dependencies
    _, offering = await _seed_catalog(db, year, deps["unit_id"])  # round covers year
    in_win = datetime(year, 6, 1, tzinfo=VN_TZ)

    stg_a = await _seed_pstage(db)  # progress
    stg_b = await _seed_pstage(db)  # progress (mid — a rejection can happen here)
    stg_neg = await _seed_pstage(db, is_final=True)  # negative terminal stage
    cs_ok = await _seed_funnel_status(db, stage_id=stg_a)  # neutral → on-path
    cs_reject = await _seed_funnel_status(
        db, stage_id=stg_b, outcome="negative", is_final=True
    )  # rejected at a NON-terminal stage
    cs_activity = await _seed_funnel_status(
        db, stage_id=stg_a, counts_for_funnel=False
    )  # activity status → excluded from the funnel
    cs_dropped = await _seed_funnel_status(
        db, stage_id=stg_neg, outcome="negative", is_final=True
    )

    await _seed_funnel_lead(
        db, deps, year, stage_id=stg_a, cs_id=cs_ok, created_at=in_win
    )
    await _seed_funnel_lead(
        db, deps, year, stage_id=stg_b, cs_id=cs_reject, created_at=in_win
    )
    await _seed_funnel_lead(
        db, deps, year, stage_id=stg_a, cs_id=cs_activity, created_at=in_win
    )
    await _seed_funnel_lead(
        db, deps, year, stage_id=stg_neg, cs_id=cs_dropped, created_at=in_win
    )
    # walk-in: created BEFORE the round window but holds an in-scope profile
    await _seed_funnel_lead(
        db,
        deps,
        year,
        stage_id=stg_a,
        cs_id=cs_ok,
        created_at=datetime(year - 1, 3, 1, tzinfo=VN_TZ),
        offering_id=offering.id,
        with_profile=True,
    )

    svc = AdmissionReportService(db)
    resp = await svc.get_pipeline_funnel(current_user=_admin(), academic_year=year)
    by_id = {s.stage_id: s for s in resp.stages}

    # activity status (counts_for_funnel=false) excluded; leaked = rejected + dropped
    # (by OUTCOME); on-path = 2 at stg_a (one in-window + the walk-in via profile).
    assert resp.total_leads == 4  # 5 seeded − 1 activity-excluded
    assert resp.leaked == 2  # rejected-mid-stage + negative-terminal
    assert by_id[stg_a].current == 2 and by_id[stg_a].reached == 2
    assert by_id[stg_a].is_leak is False
    assert by_id[stg_b].current == 0  # rejected lead is leaked, not on-path here
    assert by_id[stg_b].is_leak is False  # mid stage, not a leak STAGE
    assert by_id[stg_neg].is_leak is True  # all-negative final stage → leak stage
    assert by_id[stg_neg].current == 0


# ----------------------------------------------------------- week-over-week (WoW)
# WoW so 2 tuần ISO ĐÃ HOÀN TẤT gần nhất, LOẠI tuần đang chạy. Chỉ có nghĩa khi có
# "tuần đang chạy" thật = NĂM HIỆN TẠI → các test giá trị dùng ``today_vn().year``
# (khác các test khác dùng năm tương lai 2050+). Cách ly bằng MAJOR riêng + reconcile
# totals theo cấu trúc (bền với data năm-hiện-tại khác trong qlts_test).


def _wow_weeks():
    """Tuần đang chạy (loại) + W-1/W-2 (2 tuần hoàn tất), anchored trên hôm nay (VN)."""
    end_meta, run = AdmissionReportService._compute_week(today_vn())
    _m1, w1 = AdmissionReportService._compute_week(
        end_meta.week_start - timedelta(weeks=1)
    )
    _m2, w2 = AdmissionReportService._compute_week(
        end_meta.week_start - timedelta(weeks=2)
    )
    return end_meta, run, w1, w2


async def test_wow_buckets_two_complete_weeks_and_excludes_running_week(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """W-1 → count_current, W-2 → count_previous, tuần đang chạy → LOẠI. current=1,
    previous=2 → delta=-1, delta_pct=-50%. Tổng dimension khớp tổng chung."""
    year = today_vn().year
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    end_meta, run, w1, w2 = _wow_weeks()

    major, offering = await _seed_catalog(db, year, unit_id)

    async def _submit_at(occurred_at):
        _, p = await _seed_lead_profile(
            db, seeded_dependencies, year, offering.id, officer_id,
            created_at=occurred_at,
        )
        await _seed_history(db, p.id, "submitted", occurred_at)
        return p

    await _submit_at(w1.start + timedelta(days=2))  # W-1 → current
    await _submit_at(w2.start + timedelta(days=1))  # W-2 → previous
    await _submit_at(w2.start + timedelta(days=3))  # W-2 → previous
    await _submit_at(run.start + timedelta(minutes=30))  # tuần đang chạy → LOẠI

    svc = AdmissionReportService(db)
    resp = await svc.get_week_over_week(
        current_user=_admin(), academic_year=year, group_by="major"
    )
    assert resp.insufficient_data is False
    assert resp.comparison is not None
    # 2 tuần hoàn tất, đều TRƯỚC tuần đang chạy; previous < latest.
    assert resp.comparison.latest_complete_week.week_start < run.start.date()
    assert (
        resp.comparison.previous_complete_week.week_start
        < resp.comparison.latest_complete_week.week_start
    )

    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.submitted.count_current == 1  # chỉ W-1 (tuần đang chạy bị loại)
    assert row.submitted.count_previous == 2  # cả hai W-2
    assert row.submitted.delta == -1
    assert row.submitted.delta_pct == -50.0

    # tổng dimension khớp tổng chung (structural — bền với data khác trong qlts_test).
    for milestone in ("submitted", "admitted", "enrolled"):
        tot = getattr(resp.totals, milestone)
        assert tot.count_current == sum(
            getattr(r, milestone).count_current for r in resp.rows
        )
        assert tot.count_previous == sum(
            getattr(r, milestone).count_previous for r in resp.rows
        )
        assert tot.delta == tot.count_current - tot.count_previous


async def test_wow_previous_zero_delta_pct_is_none(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """Tuần trước = 0 (mẫu số 0) → delta_pct=None (ưu tiên số tuyệt đối)."""
    year = today_vn().year
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    _end, _run, w1, _w2 = _wow_weeks()
    major, offering = await _seed_catalog(db, year, unit_id)
    _, p = await _seed_lead_profile(
        db, seeded_dependencies, year, offering.id, officer_id,
        created_at=w1.start + timedelta(days=2),
    )
    await _seed_history(db, p.id, "submitted", w1.start + timedelta(days=2))

    svc = AdmissionReportService(db)
    resp = await svc.get_week_over_week(
        current_user=_admin(), academic_year=year, group_by="major"
    )
    row = _find(resp.rows, major.id)
    assert row is not None
    assert row.submitted.count_current == 1
    assert row.submitted.count_previous == 0
    assert row.submitted.delta == 1
    assert row.submitted.delta_pct is None  # mẫu số 0


async def test_wow_group_by_officer_manager_scope(
    db: AsyncSession, seeded_dependencies: dict, officer_user_in_db: dict
):
    """group_by=officer + manager bị ép về đơn vị của mình (scope_unit_id)."""
    year = today_vn().year
    unit_id = seeded_dependencies["unit_id"]
    officer_id = officer_user_in_db["id"]
    _end, _run, w1, _w2 = _wow_weeks()
    _, offering = await _seed_catalog(db, year, unit_id)
    _, p = await _seed_lead_profile(
        db, seeded_dependencies, year, offering.id, officer_id,
        created_at=w1.start + timedelta(days=2),
    )
    await _seed_history(db, p.id, "submitted", w1.start + timedelta(days=2))

    svc = AdmissionReportService(db)
    resp = await svc.get_week_over_week(
        current_user=_manager(unit_id), academic_year=year, group_by="officer"
    )
    assert resp.scope_unit_id == unit_id  # manager ép về đơn vị của mình
    row = _find(resp.rows, officer_id)
    assert row is not None and not row.is_bucket
    assert row.submitted.count_current == 1


async def test_wow_future_year_insufficient_data(
    db: AsyncSession, seeded_dependencies: dict
):
    """Năm tương lai → chưa bắt đầu → insufficient_data (không bịa 2 tuần 0 giả)."""
    svc = AdmissionReportService(db)
    resp = await svc.get_week_over_week(current_user=_admin(), academic_year=2200)
    assert resp.insufficient_data is True
    assert resp.comparison is None
    assert resp.rows == []


async def test_wow_past_year_insufficient_data(
    db: AsyncSession, seeded_dependencies: dict
):
    """Năm quá khứ → không có tuần đang chạy thật → insufficient_data."""
    svc = AdmissionReportService(db)
    resp = await svc.get_week_over_week(current_user=_admin(), academic_year=2020)
    assert resp.insufficient_data is True
    assert resp.comparison is None
