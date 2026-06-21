# tests/repositories/test_profile_collection.py
"""
DB-backed tests for the PR2 "Thu học phí" collection drawer + maker-checker queue.

Real-DB (not mocked) tests over a Lead → AdmissionProfile → Fee → Invoice →
Payment chain seeded in two units. They assert:

  - ``FeeCalculationService.get_profile_collection`` IDOR: a profile outside the
    caller's unit resolves to ``None`` (the router then 404s) — the access
    decision is made BEFORE any identity/collection is built, so an out-of-unit
    profile leaks nothing. The empty-collection case is never the gate.
  - the bounded eager-load: fees → invoices → payments → (method, created_by)
    are all reachable WITHOUT a lazy load (a lazy load would raise
    MissingGreenlet in async) — i.e. no per-row N+1.
  - the manual-pending maker-checker queue (``PaymentRepository.
    get_pending_verification``) excludes ONLINE pending payments (intent_id set).
  - ``_build_payment_list_item`` enrichment (reference_code / payer_name /
    is_online) + role-aware maker-checker can_verify/can_reject (no self-approval).
  - the drawer summary's DERIVED overdue count (issued/partial past due), which
    must agree with the workspace spine, not the lagging enum bucket.

Everything is seeded + queried in the SAME session (flush-visible, rolled back
at session close) so no committed state leaks between tests.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio

from app import models
from app.models.finance import (
    Fee,
    Invoice,
    Payment,
    PaymentIntent,
    PaymentMethod,
    InvoiceStatusEnum,
    FeeStatusEnum,
    PaymentStatusEnum,
)
from app.repositories.payment_repository import PaymentRepository
from app.services.fee_calculation_service import FeeCalculationService
from app.routers.invoices import _build_invoice_list_item, _invoice_is_overdue
from app.routers.payments import _build_payment_list_item
from app.routers.fees import _fee_can_waive, _total_remaining_with_penalty
from app.utils.id_helpers import format_profile_code

pytestmark = pytest.mark.asyncio

YESTERDAY = date.today() - timedelta(days=3)
TOMORROW = date.today() + timedelta(days=10)
IS = InvoiceStatusEnum
FS = FeeStatusEnum
PS = PaymentStatusEnum


async def _make_lead(db, deps, full_name, unit_id, officer_id=None, suffix="0"):
    lead = models.Lead(
        full_name=full_name,
        phone=f"09091{suffix:0>5}"[:15],
        email=f"coll_{suffix}@test.com",
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
        citizen_id=f"78{citizen_suffix:0>10}"[:12],
        status="submitted",
        applied_rules={},
        academic_year=2026,
        uses_choice_engine=False,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _make_fee(db, profile_id, fee_type, status, final="1000000",
                    paid="0", waived="0", semester_no=None):
    fee = Fee(
        admission_profile_id=profile_id,
        fee_type=fee_type,
        academic_year=2026,
        semester_no=semester_no,
        base_amount=Decimal(final),
        total_discount=Decimal("0"),
        final_amount=Decimal(final),
        paid_amount=Decimal(paid),
        waived_amount=Decimal(waived),
        status=status,
        version=1,
    )
    db.add(fee)
    await db.flush()
    return fee


async def _make_invoice(db, fee_id, number, status, due_date,
                        amount="1000000", paid="0", installment=1):
    inv = Invoice(
        fee_id=fee_id,
        invoice_number=number,
        installment_no=installment,
        amount=Decimal(amount),
        paid_amount=Decimal(paid),
        status=status,
        due_date=due_date,
    )
    db.add(inv)
    await db.flush()
    return inv


async def _make_payment(db, invoice_id, method_id, created_by_id, status,
                        amount="200000", intent_id=None, reference_code=None,
                        payer_name=None):
    pmt = Payment(
        invoice_id=invoice_id,
        method_id=method_id,
        intent_id=intent_id,
        amount=Decimal(amount),
        status=status,
        reference_code=reference_code,
        payer_name=payer_name,
        created_by_id=created_by_id,
        payment_date=datetime.now(timezone.utc),
    )
    db.add(pmt)
    await db.flush()
    return pmt


@pytest_asyncio.fixture
async def seeded_collection(db, seeded_dependencies, officer_user_in_db,
                            admin_user_in_db):
    """Seed a unit-A profile with the full 3-tier chain + a unit-B profile.

    maker = officer (records the manual payments); verifier = admin (different
    user, so maker-checker can_verify is True for admin/manager/accountant).
    """
    deps = seeded_dependencies
    unit_a = deps["unit_id"]
    officer_id = officer_user_in_db["id"]
    admin_id = admin_user_in_db["id"]

    unit_b_obj = models.OrganizationUnit(name="Coll Test Unit B", type="department")
    db.add(unit_b_obj)
    await db.flush()
    unit_b = unit_b_obj.id

    method_cash = PaymentMethod(code="coll_cash", name="Tiền mặt", is_online=False)
    method_online = PaymentMethod(
        code="coll_vnpay", name="VNPay", is_online=True, gateway_code="vnpay"
    )
    db.add_all([method_cash, method_online])
    await db.flush()

    # ── Unit A: profile with tuition (partial, overdue) + application (paid) ──
    lead_a = await _make_lead(db, deps, "Đặng Thu Hà", unit_a, officer_id, "11")
    prof_a = await _make_profile(db, lead_a.id, 211)

    fee_tuition = await _make_fee(
        db, prof_a.id, "tuition", FS.partial.value,
        final="1000000", paid="200000", semester_no=1,
    )
    fee_app = await _make_fee(
        db, prof_a.id, "application", FS.paid.value, final="300000", paid="300000",
    )

    # Tuition invoice 1: issued + past due → DERIVED overdue (enum still 'issued').
    inv_overdue = await _make_invoice(
        db, fee_tuition.id, "COLL-T-OVDUE", IS.issued.value, YESTERDAY,
        amount="1000000", paid="200000",
    )
    # Tuition invoice 2: issued, future due → not overdue.
    inv_future = await _make_invoice(
        db, fee_tuition.id, "COLL-T-FUTURE", IS.issued.value, TOMORROW,
        amount="500000", installment=2,
    )
    # Application invoice: paid.
    await _make_invoice(
        db, fee_app.id, "COLL-APP-PAID", IS.paid.value, YESTERDAY,
        amount="300000", paid="300000",
    )

    # Manual pending payment (officer maker) → belongs in the maker-checker queue.
    pmt_manual_pending = await _make_payment(
        db, inv_overdue.id, method_cash.id, officer_id, PS.pending.value,
        amount="200000", reference_code="BANK-REF-001", payer_name="Phụ huynh Hà",
    )
    # Manual verified payment (history, not in queue).
    pmt_manual_verified = await _make_payment(
        db, inv_overdue.id, method_cash.id, officer_id, PS.verified.value,
        amount="200000", reference_code="BANK-REF-000",
    )

    # ONLINE pending payment (has intent_id) → must NOT appear in the manual queue.
    intent = PaymentIntent(
        invoice_id=inv_future.id,
        method_id=method_online.id,
        amount=Decimal("500000"),
        idempotency_key="coll-idem-001",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(intent)
    await db.flush()
    pmt_online_pending = await _make_payment(
        db, inv_future.id, method_online.id, officer_id, PS.pending.value,
        amount="500000", intent_id=intent.id,
    )

    # ── Unit B: a separate profile for the IDOR assertion ──
    lead_b = await _make_lead(db, deps, "Ngoài Đơn Vị", unit_b, None, "21")
    prof_b = await _make_profile(db, lead_b.id, 221)
    fee_b = await _make_fee(db, prof_b.id, "tuition", FS.invoiced.value, semester_no=1)
    await _make_invoice(db, fee_b.id, "COLL-UNITB", IS.issued.value, YESTERDAY)

    return {
        "unit_a": unit_a, "unit_b": unit_b,
        "officer_id": officer_id, "admin_id": admin_id,
        "prof_a_id": prof_a.id, "prof_b_id": prof_b.id,
        "fee_tuition_id": fee_tuition.id, "fee_app_id": fee_app.id,
        "manual_pending_id": pmt_manual_pending.id,
        "manual_verified_id": pmt_manual_verified.id,
        "online_pending_id": pmt_online_pending.id,
    }


# =============================================================================
# get_profile_collection — IDOR + bounded eager-load
# =============================================================================

async def test_collection_idor_out_of_unit_returns_none(db, seeded_collection):
    """A profile outside the caller's unit resolves to None → router 404s with
    NO identity built (resolve-first gate, not "empty collection")."""
    service = FeeCalculationService(db)

    # Unit-A caller cannot resolve the unit-B profile (and vice versa).
    assert await service.get_profile_collection(
        seeded_collection["prof_b_id"], unit_id=seeded_collection["unit_a"]
    ) is None
    assert await service.get_profile_collection(
        seeded_collection["prof_a_id"], unit_id=seeded_collection["unit_b"]
    ) is None
    # A non-existent id is also None (not an exception).
    assert await service.get_profile_collection(
        9_999_999, unit_id=seeded_collection["unit_a"]
    ) is None


async def test_collection_loads_full_graph_without_lazy(db, seeded_collection):
    """The bounded eager-load reaches every tier; accessing nested relations
    raises NO MissingGreenlet → no per-row N+1."""
    service = FeeCalculationService(db)
    profile = await service.get_profile_collection(
        seeded_collection["prof_a_id"], unit_id=seeded_collection["unit_a"]
    )
    assert profile is not None

    # Identity chain (lead → officer; offering is unseeded → None, no crash).
    assert profile.lead.full_name == "Đặng Thu Hà"
    assert profile.lead.assigned_officer is not None
    assert profile.lead.offering is None  # unseeded, eager-loaded as None

    # Tiers: fees → invoices → payments → (method, created_by) all reachable.
    fees = list(profile.fees)
    assert len(fees) == 2
    invoices = [inv for f in fees for inv in f.invoices]
    assert len(invoices) == 3
    payments = [p for inv in invoices for p in inv.payments]
    assert len(payments) == 3
    for p in payments:
        # These attribute reads would raise MissingGreenlet if not eager-loaded.
        _ = p.method.name
        _ = p.created_by.full_name if p.created_by else None
        _ = p.invoice.fee.admission_profile.lead.full_name


async def test_collection_identity_and_derived_summary(db, seeded_collection):
    """Identity uses the HS-code; the summary's overdue count is DERIVED
    (issued/partial past due), agreeing with the spine — not the enum bucket."""
    service = FeeCalculationService(db)
    today = date.today()
    profile = await service.get_profile_collection(
        seeded_collection["prof_a_id"], unit_id=seeded_collection["unit_a"]
    )

    assert format_profile_code(profile.id) == f"HS-{profile.id:06d}"

    fees = list(profile.fees)
    all_invoices = [inv for f in fees for inv in f.invoices]

    total_fees = sum((f.final_amount for f in fees), Decimal("0"))
    total_paid = sum((f.paid_amount for f in fees), Decimal("0"))
    assert total_fees == Decimal("1300000")  # 1,000,000 tuition + 300,000 app
    assert total_paid == Decimal("500000")   # 200,000 + 300,000

    # total_remaining = Σ fee.remaining (final-paid-waived) + Σ non-terminal
    # invoice penalty — NOT Σ invoice.remaining. Here: tuition 800k + app 0
    # (no waiver, no penalty) = 800k. (Σ invoice.remaining would wrongly give
    # 1.3M — the tuition fee is over-invoiced 1M+500k against a 1M final.)
    assert _total_remaining_with_penalty(fees, all_invoices) == Decimal("800000")

    # DERIVED overdue: only the issued-past-due tuition invoice (NOT the future
    # issued one, NOT the paid one). The enum 'overdue' bucket here is 0.
    overdue_derived = sum(
        1 for inv in all_invoices if _invoice_is_overdue(inv, today)
    )
    assert overdue_derived == 1
    # Invoice.status is a plain str column → compare directly.
    enum_overdue = sum(1 for inv in all_invoices if inv.status == "overdue")
    assert enum_overdue == 0


async def test_total_remaining_excludes_waived_includes_penalty():
    """Regression (PR2 review): a waive AFTER an invoice is issued bumps
    fee.waived but leaves invoice.amount untouched, so total_remaining must be
    Σ fee.remaining (reflects the waiver) + Σ non-terminal invoice penalty —
    NEVER Σ invoice.remaining (which ignores the waiver and over-states)."""
    from types import SimpleNamespace as NS

    # Fee waived 400k of 1M (paid 0) → fee.remaining 600k; its issued invoice
    # still shows the full 1M (waive_fee never touches the invoice).
    fee_waived = NS(remaining_amount=Decimal("600000"))
    inv_waived = NS(
        remaining_amount=Decimal("1000000"),  # stale: ignores the waiver
        penalty_amount=Decimal("0"), status="issued",
    )
    # Overdue fee whose invoice carries a 50k penalty (penalty ∉ the fee).
    fee_overdue = NS(remaining_amount=Decimal("200000"))
    inv_overdue = NS(
        remaining_amount=Decimal("250000"),
        penalty_amount=Decimal("50000"), status="overdue",
    )
    # A cancelled invoice's penalty must NOT count.
    inv_cancelled = NS(
        remaining_amount=Decimal("999"),
        penalty_amount=Decimal("999"), status="cancelled",
    )

    total = _total_remaining_with_penalty(
        [fee_waived, fee_overdue], [inv_waived, inv_overdue, inv_cancelled]
    )
    # 600k + 200k principal + 50k penalty = 850k. The regressed Σ invoice.remaining
    # would give 1,000,000 + 250,000 = 1,250,000 — 400k too high (dropped waiver).
    assert total == Decimal("850000")


async def test_collection_invoice_items_enriched_and_role_aware(db, seeded_collection):
    """Drawer invoice rows reuse the list-item builder: enriched identity +
    is_overdue + role-aware can_*."""
    service = FeeCalculationService(db)
    today = date.today()
    profile = await service.get_profile_collection(
        seeded_collection["prof_a_id"], unit_id=seeded_collection["unit_a"]
    )
    all_invoices = [inv for f in profile.fees for inv in f.invoices]
    built = [_build_invoice_list_item(inv, "accountant", today) for inv in all_invoices]
    items = {it.invoice_number: it for it in built}

    overdue = items["COLL-T-OVDUE"]
    assert overdue.is_overdue is True
    assert overdue.profile_name == "Đặng Thu Hà"
    assert overdue.semester_no == 1
    # accountant holds POST /api/payments → can record on a payable invoice.
    assert overdue.can_record_payment is True
    # accountant does NOT hold cancel (manager+) → flag false (no dead button).
    assert overdue.can_cancel is False
    assert items["COLL-T-FUTURE"].is_overdue is False
    assert items["COLL-APP-PAID"].is_overdue is False


async def test_collection_fee_can_waive_role_aware(db, seeded_collection):
    """The drawer's fee "Miễn giảm" gate is BE-owned (route: RequireManager →
    admin/manager only; not terminal; remaining > 0) — never re-derived on the FE.
    """
    service = FeeCalculationService(db)
    profile = await service.get_profile_collection(
        seeded_collection["prof_a_id"], unit_id=seeded_collection["unit_a"]
    )
    by_type = {f.fee_type: f for f in profile.fees}
    tuition = by_type["tuition"]   # partial, remaining 800k → waivable
    application = by_type["application"]  # paid (terminal) → never waivable

    # admin/manager may waive a non-terminal fee with remaining > 0…
    assert _fee_can_waive(tuition, "admin") is True
    assert _fee_can_waive(tuition, "manager") is True
    # …accountant may NOT (separation of duties — RequireManager route gate)…
    assert _fee_can_waive(tuition, "accountant") is False
    # …and a fully-paid (terminal) fee is never waivable, even for admin.
    assert _fee_can_waive(application, "admin") is False


# =============================================================================
# Maker-checker queue — manual-only (intent_id IS NULL)
# =============================================================================

async def test_pending_queue_excludes_online(db, seeded_collection):
    """The verification queue returns ONLY manual pending payments — an online
    (gateway, intent_id set) pending payment must never leak in."""
    repo = PaymentRepository(db)
    payments, total = await repo.get_pending_verification(
        unit_id=seeded_collection["unit_a"]
    )
    ids = {p.id for p in payments}

    assert seeded_collection["manual_pending_id"] in ids
    assert seeded_collection["online_pending_id"] not in ids   # online excluded
    assert seeded_collection["manual_verified_id"] not in ids  # not pending
    assert total == 1
    assert all(p.intent_id is None for p in payments)
    assert all(p.status == PS.pending.value for p in payments)


async def test_pending_queue_idor_scoped(db, seeded_collection):
    """Unit-B has no manual pending payments of unit-A."""
    repo = PaymentRepository(db)
    _, total = await repo.get_pending_verification(unit_id=seeded_collection["unit_b"])
    assert total == 0


# =============================================================================
# _build_payment_list_item — enrichment + maker-checker
# =============================================================================

async def test_payment_list_item_enrichment(db, seeded_collection):
    """reference_code / payer_name surface for reconciliation; is_online tells
    a manual payment apart from a gateway one; profile_name resolves."""
    repo = PaymentRepository(db)
    payments, _ = await repo.get_pending_verification(
        unit_id=seeded_collection["unit_a"]
    )
    manual = next(p for p in payments if p.id == seeded_collection["manual_pending_id"])

    item = _build_payment_list_item(manual, seeded_collection["admin_id"], "admin")
    assert item.reference_code == "BANK-REF-001"
    assert item.payer_name == "Phụ huynh Hà"
    assert item.is_online is False
    assert item.profile_name == "Đặng Thu Hà"
    assert item.method_name == "Tiền mặt"


async def test_payment_list_item_maker_checker(db, seeded_collection):
    """A finance reviewer who is NOT the maker can verify; the maker themselves
    cannot (no self-approval); the verified payment is never verifiable."""
    repo = PaymentRepository(db)
    payments, _ = await repo.get_pending_verification(
        unit_id=seeded_collection["unit_a"]
    )
    manual = next(p for p in payments if p.id == seeded_collection["manual_pending_id"])

    # Admin (different user) → can verify/reject; not the maker.
    as_admin = _build_payment_list_item(manual, seeded_collection["admin_id"], "admin")
    assert as_admin.can_verify is True
    assert as_admin.can_reject is True
    assert as_admin.is_own is False

    # The maker (officer who created it) → cannot verify their own payment, and
    # is flagged is_own so the queue can explain WHY (vs a non-reviewer).
    officer_id = seeded_collection["officer_id"]
    as_maker = _build_payment_list_item(manual, officer_id, "officer")
    assert as_maker.can_verify is False
    assert as_maker.can_reject is False
    assert as_maker.is_own is True


async def test_payment_list_item_online_flag(db, seeded_collection):
    """An online payment (intent_id set) carries is_online=True — surfaced via the
    collection (the drawer lists ALL payments) even though it is correctly
    excluded from the manual verification queue."""
    service = FeeCalculationService(db)
    profile = await service.get_profile_collection(
        seeded_collection["prof_a_id"], unit_id=seeded_collection["unit_a"]
    )
    payments = [p for f in profile.fees for inv in f.invoices for p in inv.payments]
    online = next(p for p in payments if p.id == seeded_collection["online_pending_id"])
    item = _build_payment_list_item(online, seeded_collection["admin_id"], "admin")
    assert item.is_online is True
    assert item.profile_name == "Đặng Thu Hà"
