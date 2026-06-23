"""Pure-logic unit tests for the weekly admission report (no DB).

Covers the trickiest, DB-free logic: the 5-tier major resolver (+ ambiguous/
unresolved buckets), ISO-week computation (VN), admin/manager scope, and totals.
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.repositories.admission_report_repository import (
    AMBIGUOUS,
    UNRESOLVED,
    AdmissionReportRepository,
    MajorInfo,
)
from app.schemas.admission_report import ReportRow
from app.services.admission_report_service import VN_TZ, AdmissionReportService
from app.utils.exceptions import PermissionDeniedError, ResourceNotFoundError

# path_id -> (MajorInfo, round_code)
_PATHS = {
    10: (MajorInfo(major_id=1, code="A", name="Ngành A", degree_level="CĐ"), "DOT_1"),
    20: (MajorInfo(major_id=2, code="B", name="Ngành B", degree_level="CĐ"), "DOT_2"),
}
# offering_id -> MajorInfo
_OFFERINGS = {100: MajorInfo(major_id=3, code="C", name="Ngành C", degree_level="TC")}

_R = AdmissionReportRepository._resolve_one


# --------------------------------------------------------------- resolver tiers
def test_resolver_single_admitted_wins():
    choices = {1: [(10, "admitted", 2), (20, "pending", 1)]}
    key, info, rnd = _R(1, None, None, choices, _PATHS, _OFFERINGS)
    assert key == 1 and info.code == "A" and rnd == "DOT_1"


def test_resolver_multiple_admitted_is_ambiguous():
    choices = {1: [(10, "admitted", 1), (20, "admitted", 2)]}
    key, info, rnd = _R(1, None, None, choices, _PATHS, _OFFERINGS)
    assert key == AMBIGUOUS and info is None and rnd is None


def test_resolver_nv1_when_no_admitted():
    # display_order 1 = NV1 → path 10, regardless of list order
    choices = {1: [(20, "pending", 2), (10, "pending", 1)]}
    key, info, rnd = _R(1, None, None, choices, _PATHS, _OFFERINGS)
    assert key == 1 and rnd == "DOT_1"


def test_resolver_legacy_applied_rules():
    key, info, rnd = _R(1, {"admission_path_id": 20}, None, {}, _PATHS, _OFFERINGS)
    assert key == 2 and rnd == "DOT_2"


def test_resolver_offering_fallback():
    key, info, rnd = _R(1, None, 100, {}, _PATHS, _OFFERINGS)
    assert key == 3 and info.code == "C" and rnd is None


def test_resolver_unresolved_when_nothing():
    key, info, rnd = _R(1, None, None, {}, _PATHS, _OFFERINGS)
    assert key == UNRESOLVED and info is None


def test_resolver_unknown_path_is_unresolved():
    choices = {1: [(999, "admitted", 1)]}
    key, info, rnd = _R(1, None, None, choices, _PATHS, _OFFERINGS)
    assert key == UNRESOLVED


def test_resolver_broken_choice_falls_through_to_legacy():
    # NV1 path is broken (unknown) but legacy applied_rules path is valid → legacy.
    choices = {1: [(999, "pending", 1)]}
    key, info, rnd = _R(1, {"admission_path_id": 20}, None, choices, _PATHS, _OFFERINGS)
    assert key == 2 and rnd == "DOT_2"


def test_resolver_broken_choice_falls_through_to_offering():
    # NV1 path broken, no legacy → fall through to lead.offering (not unresolved).
    choices = {1: [(999, "pending", 1)]}
    key, info, rnd = _R(1, None, 100, choices, _PATHS, _OFFERINGS)
    assert key == 3 and info.code == "C"


def test_resolver_non_dict_applied_rules_does_not_crash():
    # legacy/imported applied_rules can be a non-dict JSONB (list/str) → must not
    # raise AttributeError; just skip the legacy tier.
    key, info, rnd = _R(1, ["junk"], 100, {}, _PATHS, _OFFERINGS)
    assert key == 3  # falls through to offering
    assert _R(1, "weird", None, {}, _PATHS, _OFFERINGS)[0] == UNRESOLVED


# ------------------------------------------------------------------- ISO week
def test_compute_week_midweek_anchors_to_monday_sunday():
    meta, win = AdmissionReportService._compute_week(date(2026, 6, 17))  # Wednesday
    assert meta.week_start == date(2026, 6, 15)  # Monday
    assert meta.week_end == date(2026, 6, 21)  # Sunday
    assert win.start == datetime(2026, 6, 15, tzinfo=VN_TZ)
    assert win.end_excl == datetime(2026, 6, 22, tzinfo=VN_TZ)  # half-open
    iso = date(2026, 6, 17).isocalendar()
    assert meta.iso_year == iso[0] and meta.iso_week == iso[1]


def test_compute_week_sunday_stays_in_same_week():
    meta, _ = AdmissionReportService._compute_week(date(2026, 6, 21))  # Sunday
    assert meta.week_start == date(2026, 6, 15) and meta.week_end == date(2026, 6, 21)


def test_compute_week_monday_boundary():
    meta, win = AdmissionReportService._compute_week(date(2026, 6, 15))  # Monday
    assert meta.week_start == date(2026, 6, 15)
    assert win.end_excl == datetime(2026, 6, 22, tzinfo=VN_TZ)


# ---------------------------------------------------------------------- scope
class _FakeUser:
    def __init__(self, role: str, unit_id):
        self.role = role
        self.unit_id = unit_id


_S = AdmissionReportService._resolve_scope


def test_scope_admin_all_units():
    assert _S(_FakeUser("admin", None), None) is None


def test_scope_admin_can_choose_unit():
    assert _S(_FakeUser("admin", 1), 7) == 7


def test_scope_manager_forced_to_own_unit():
    assert _S(_FakeUser("manager", 5), None) == 5


def test_scope_manager_no_unit_fails_closed():
    with pytest.raises(PermissionDeniedError):
        _S(_FakeUser("manager", None), None)


def test_scope_manager_other_unit_is_404():
    with pytest.raises(ResourceNotFoundError):
        _S(_FakeUser("manager", 5), 9)


def test_scope_manager_own_unit_ok():
    assert _S(_FakeUser("manager", 5), 5) == 5


# --------------------------------------------------------------------- totals
def test_totals_sum_rows():
    r1 = ReportRow(label="x")
    r2 = ReportRow(label="y")
    r1.lead.new_in_week, r2.lead.new_in_week = 3, 4
    r1.admission.submitted_in_week, r2.admission.submitted_in_week = 1, 2
    r1.finance.net_in_week, r2.finance.net_in_week = Decimal("100"), Decimal("250.50")
    t = AdmissionReportService._totals([r1, r2])
    assert t.lead.new_in_week == 7
    assert t.admission.submitted_in_week == 3
    assert t.finance.net_in_week == Decimal("350.50")
