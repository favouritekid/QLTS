# tests/repositories/test_invoice_list_repository.py
"""
DB-backed tests for the "Thu học phí" collection-workspace invoice list
(``InvoiceRepository.get_filtered_with_count`` / ``get_status_counts``) plus the
router enrichment builder (``_build_invoice_list_item``).

These are real-DB repository tests (not mocks) — they seed a
Lead -> AdmissionProfile -> Fee -> Invoice chain in two units and assert:
  - enrichment fields (fee_id, profile_code, officer_name, semester_no, can_*)
  - DERIVED overdue (is_overdue / overdue_derived) catches past-due issued/
    partial invoices the lagging enum 'overdue' bucket misses
  - search (name unaccent + "HS-…" profile code), fee_type filter, priority sort
  - IDOR unit scoping (a unit only sees its own invoices)

Everything is seeded + queried in the SAME session (flush-visible, rolled back
at session close) so no committed state leaks between tests.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.models.finance import Fee, Invoice, InvoiceStatusEnum, FeeStatusEnum
from app.repositories.fee_repository import InvoiceRepository
from app.routers.invoices import _build_invoice_list_item

pytestmark = pytest.mark.asyncio

YESTERDAY = date.today() - timedelta(days=3)
TOMORROW = date.today() + timedelta(days=10)
IS = InvoiceStatusEnum
FS = FeeStatusEnum


async def _make_lead(db, deps, full_name, unit_id, officer_id=None, suffix="0"):
    lead = models.Lead(
        full_name=full_name,
        phone=f"09090{suffix:0>5}"[:15],
        email=f"inv_{suffix}@test.com",
        source="Website",
        unit_id=unit_id,
        status=deps["initial_status_id"],
        consultation_status_id=deps["initial_status_id"],
        pipeline_stage_id=deps["stage_id"],
        assigned_officer_id=officer_id,
        assigned_at=datetime.now(timezone.utc) if officer_id else None,
    )
    db.add(lead)
    await db.flush()
    return lead


async def _make_profile(db, lead_id, citizen_suffix):
    profile = models.AdmissionProfile(
        lead_id=lead_id,
        citizen_id=f"79{citizen_suffix:0>10}"[:12],
        status="submitted",
        applied_rules={},
        academic_year=2026,
        uses_choice_engine=False,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _make_fee(db, profile_id, fee_type, status, semester_no=None):
    fee = Fee(
        admission_profile_id=profile_id,
        fee_type=fee_type,
        academic_year=2026,
        semester_no=semester_no,
        base_amount=Decimal("1000000"),
        total_discount=Decimal("0"),
        final_amount=Decimal("1000000"),
        paid_amount=Decimal("0"),
        waived_amount=Decimal("0"),
        status=status,
        version=1,
    )
    db.add(fee)
    await db.flush()
    return fee


def _inv(fee_id, number, status, due_date, amount="1000000", paid="0", installment=1):
    return Invoice(
        fee_id=fee_id,
        invoice_number=number,
        installment_no=installment,
        amount=Decimal(amount),
        paid_amount=Decimal(paid),
        status=status,
        due_date=due_date,
    )


@pytest_asyncio.fixture
async def seeded_invoices(db, seeded_dependencies, officer_user_in_db):
    """Seed two units' worth of invoices covering every status + overdue case."""
    deps = seeded_dependencies
    unit_a = deps["unit_id"]
    officer_id = officer_user_in_db["id"]

    # Second unit for the IDOR assertion.
    unit_b_obj = models.OrganizationUnit(name="Repo Test Unit B", type="department")
    db.add(unit_b_obj)
    await db.flush()
    unit_b = unit_b_obj.id

    # Unit A: lead "Trần Quang Huy" (search target) + lead "Lê Thị Bình".
    lead_a1 = await _make_lead(db, deps, "Trần Quang Huy", unit_a, officer_id, "11")
    lead_a2 = await _make_lead(db, deps, "Lê Thị Bình", unit_a, officer_id, "12")
    lead_b1 = await _make_lead(db, deps, "Phạm Văn Ngoài", unit_b, None, "21")

    prof_a1 = await _make_profile(db, lead_a1.id, 111)
    prof_a2 = await _make_profile(db, lead_a2.id, 112)
    prof_b1 = await _make_profile(db, lead_b1.id, 121)

    fee_a1 = await _make_fee(db, prof_a1.id, "tuition", FS.partial.value, 1)
    fee_a2 = await _make_fee(db, prof_a2.id, "application", FS.paid.value)
    fee_b1 = await _make_fee(db, prof_b1.id, "tuition", FS.invoiced.value, 1)

    db.add_all([
        # Unit A — fee_a1 (tuition)
        _inv(fee_a1.id, "INV-T-OVDUE-ISS", IS.issued.value, YESTERDAY),
        _inv(fee_a1.id, "INV-T-OVDUE-PART", IS.partial.value, YESTERDAY,
             paid="200000", installment=2),
        _inv(fee_a1.id, "INV-T-FUTURE-ISS", IS.issued.value, TOMORROW,
             installment=3),
        # Unit A — fee_a2 (application)
        _inv(fee_a2.id, "APP-PAID", IS.paid.value, YESTERDAY, paid="1000000"),
        _inv(fee_a2.id, "APP-DRAFT-PASTDUE", IS.draft.value, YESTERDAY,
             installment=2),
        # Unit B — fee_b1 (IDOR: invisible to unit A)
        _inv(fee_b1.id, "INV-UNITB-ISS", IS.issued.value, YESTERDAY),
    ])
    await db.flush()

    return {
        "unit_a": unit_a, "unit_b": unit_b,
        "officer_id": officer_id,
        "officer_name": officer_user_in_db.get("full_name") or "Repo Test Officer",
        "prof_a1_id": prof_a1.id, "prof_a2_id": prof_a2.id,
        "fee_a1_id": fee_a1.id, "fee_a2_id": fee_a2.id,
    }


async def test_list_enrichment_and_idor(db, seeded_invoices):
    """List returns enriched, unit-scoped rows; the other unit's invoice is hidden."""
    repo = InvoiceRepository(db)
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"]
    )

    numbers = {inv.invoice_number for inv in invoices}
    assert "INV-UNITB-ISS" not in numbers  # IDOR: unit B hidden
    assert total == 5
    assert len(invoices) == 5

    items = [_build_invoice_list_item(inv, "admin") for inv in invoices]
    by_num = {it.invoice_number: it for it in items}

    # Enrichment present on every row.
    sample = by_num["INV-T-OVDUE-ISS"]
    assert sample.fee_id == seeded_invoices["fee_a1_id"]
    assert sample.profile_code == f"HS-{seeded_invoices['prof_a1_id']:06d}"
    assert sample.officer_name == "Repo Test Officer"
    assert sample.semester_no == 1
    assert sample.profile_name == "Trần Quang Huy"

    # Derived overdue: issued/partial past due -> True; future/draft/paid -> False.
    assert by_num["INV-T-OVDUE-ISS"].is_overdue is True
    assert by_num["INV-T-OVDUE-PART"].is_overdue is True
    assert by_num["INV-T-FUTURE-ISS"].is_overdue is False
    assert by_num["APP-DRAFT-PASTDUE"].is_overdue is False  # draft excluded
    assert by_num["APP-PAID"].is_overdue is False

    # can_record_payment aligned with PAYABLE (issued + partial, remaining > 0).
    assert by_num["INV-T-OVDUE-ISS"].can_record_payment is True
    assert by_num["INV-T-OVDUE-PART"].can_record_payment is True
    assert by_num["APP-PAID"].can_record_payment is False


async def test_status_counts_with_derived_overdue(db, seeded_invoices):
    """Per-status group-by + derived overdue count (enum 'overdue' bucket is 0)."""
    repo = InvoiceRepository(db)
    result = await repo.get_status_counts(unit_id=seeded_invoices["unit_a"])

    assert result["total"] == 5
    assert result["counts"]["issued"] == 2
    assert result["counts"]["partial"] == 1
    assert result["counts"]["paid"] == 1
    assert result["counts"]["draft"] == 1
    assert result["counts"]["overdue"] == 0  # no row carries the enum status
    # ...yet two rows (issued+partial past due) ARE overdue → derived catches them.
    assert result["overdue_derived"] == 2


async def test_overdue_only_filter_uses_derived(db, seeded_invoices):
    repo = InvoiceRepository(db)
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"], overdue_only=True
    )
    numbers = {inv.invoice_number for inv in invoices}
    assert numbers == {"INV-T-OVDUE-ISS", "INV-T-OVDUE-PART"}
    assert total == 2


async def test_search_by_name_unaccent(db, seeded_invoices):
    """Diacritic-insensitive name search: 'quang' matches 'Trần Quang Huy'."""
    repo = InvoiceRepository(db)
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"], search="quang"
    )
    assert total == 3  # the 3 invoices of fee_a1 (Trần Quang Huy)
    assert all(inv.invoice_number.startswith("INV-T-") for inv in invoices)


async def test_search_by_profile_code(db, seeded_invoices):
    """'HS-000xxx' resolves to the profile id."""
    repo = InvoiceRepository(db)
    code = f"HS-{seeded_invoices['prof_a1_id']:06d}"
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"], search=code
    )
    assert total == 3
    assert all(inv.invoice_number.startswith("INV-T-") for inv in invoices)


async def test_fee_type_filter(db, seeded_invoices):
    repo = InvoiceRepository(db)
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"], fee_type="application"
    )
    numbers = {inv.invoice_number for inv in invoices}
    assert numbers == {"APP-PAID", "APP-DRAFT-PASTDUE"}
    assert total == 2


async def test_profile_id_filter(db, seeded_invoices):
    """Deep-link scope (admission TuitionTab "xem hóa đơn của HS này")."""
    repo = InvoiceRepository(db)
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"], profile_id=seeded_invoices["prof_a1_id"]
    )
    # fee_a1 belongs to prof_a1 → its 3 invoices, nothing from prof_a2.
    assert total == 3
    assert all(inv.invoice_number.startswith("INV-T-") for inv in invoices)
    # status-counts honour the same scope.
    counts = await repo.get_status_counts(
        unit_id=seeded_invoices["unit_a"], profile_id=seeded_invoices["prof_a1_id"]
    )
    assert counts["total"] == 3


async def test_priority_sort_actionable_first(db, seeded_invoices):
    """Default priority sort floats overdue to the top, paid/draft to the bottom."""
    repo = InvoiceRepository(db)
    invoices, _ = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"], sort_by="priority"
    )
    items = [_build_invoice_list_item(inv, "admin") for inv in invoices]
    # First two rows are the derived-overdue ones.
    assert items[0].is_overdue is True
    assert items[1].is_overdue is True
    # Paid sinks to the bottom (priority paid=5 > draft=4 > partial=3 > ...).
    assert items[-1].invoice_number == "APP-PAID"


async def test_idor_unit_b_isolated(db, seeded_invoices):
    repo = InvoiceRepository(db)
    invoices, total = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_b"]
    )
    assert total == 1
    assert invoices[0].invoice_number == "INV-UNITB-ISS"

    counts = await repo.get_status_counts(unit_id=seeded_invoices["unit_b"])
    assert counts["total"] == 1
    assert counts["counts"]["issued"] == 1
    assert counts["overdue_derived"] == 1


async def test_enum_overdue_and_penalty(db, seeded_dependencies, officer_user_in_db):
    """A beat-transitioned enum 'overdue' invoice must stay overdue (the derived
    predicate is a SUPERSET, not a replacement) — flagged is_overdue, counted in
    overdue_derived, and sorted to the TOP (not dumped below cancelled). Also
    asserts the list item's remaining includes penalty_amount.
    """
    deps = seeded_dependencies
    lead = await _make_lead(db, deps, "Lê Văn Quá Hạn", deps["unit_id"],
                            officer_user_in_db["id"], "31")
    prof = await _make_profile(db, lead.id, 131)
    fee = await _make_fee(db, prof.id, "tuition", FS.overdue.value, 1)
    inv = _inv(fee.id, "INV-ENUM-OVERDUE", IS.overdue.value, YESTERDAY)
    inv.penalty_amount = Decimal("50000")  # late-payment penalty
    db.add(inv)
    await db.flush()

    repo = InvoiceRepository(db)
    invoices, _ = await repo.get_filtered_with_count(
        unit_id=deps["unit_id"], sort_by="priority"
    )
    items = [_build_invoice_list_item(i, "admin") for i in invoices]
    it = next(i for i in items if i.invoice_number == "INV-ENUM-OVERDUE")

    assert it.is_overdue is True            # SUPERSET includes the enum status
    assert items[0].is_overdue is True      # overdue sorts to the very top
    # remaining = amount + penalty - paid (1_000_000 + 50_000 - 0)
    assert it.remaining_amount == Decimal("1050000")

    counts = await repo.get_status_counts(unit_id=deps["unit_id"])
    assert counts["counts"]["overdue"] == 1   # enum bucket
    assert counts["overdue_derived"] == 1     # derived predicate catches it too


async def test_permission_flags_role_aligned_with_routes(db, seeded_invoices):
    """Each can_* flag is gated by the SAME roles that hold the route, so the
    workspace never shows a manager a button (issue/record) that 403s — and never
    shows an accountant cancel/penalty (separation of duties).
    """
    repo = InvoiceRepository(db)
    invoices, _ = await repo.get_filtered_with_count(
        unit_id=seeded_invoices["unit_a"]
    )
    by_num = {inv.invoice_number: inv for inv in invoices}
    draft = by_num["APP-DRAFT-PASTDUE"]
    payable = by_num["INV-T-OVDUE-ISS"]  # issued, remaining > 0

    def flags(inv, role):
        return _build_invoice_list_item(inv, role)

    # issue + record-payment → accountant/admin only (manager lacks the routes).
    assert flags(draft, "admin").can_issue is True
    assert flags(draft, "accountant").can_issue is True
    assert flags(draft, "manager").can_issue is False
    assert flags(payable, "accountant").can_record_payment is True
    assert flags(payable, "manager").can_record_payment is False
    # cancel → manager/admin only (accountant excluded for separation of duties).
    assert flags(payable, "manager").can_cancel is True
    assert flags(payable, "accountant").can_cancel is False
