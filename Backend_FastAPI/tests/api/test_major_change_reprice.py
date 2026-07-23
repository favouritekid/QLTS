"""Phase 8 — tests cho feature "đổi ngành có khấu trừ phiếu thu + kế toán xác nhận".

Bao trùm (theo test plan review):
- REGRESSION chống tái phát 2 blocker:
  * B1 drift-gate desync: reprice PHẢI dựa priced_from_academic_info_id, KHÔNG
    resolved_academic_info_id (resnapshot desync sớm ở add/delete_choice). Test
    dựng đúng cảnh: priced_from=A nhưng resolved_academic_info_id=B (đã desync) +
    choice=B → reprice PHẢI đổi giá + bật awaiting (nếu ai đổi drift gate về
    resolved_* → test đỏ ngay).
  * B2 quota resubmit: _apply_major_change_snapshot(increment_new_path=True) PHẢI
    tự +1 path mới (resubmit không có downstream +1) → path cũ giữ tổng, path mới +1.
- GUARD suite reprice (fail-closed): manual_discount / admitted / miễn-phí /
  sinh-dư / multi-invoice / pending-payment / pending-intent / single-cycle.
- confirm_major_change: happy / 409 idempotent / invariant lệch → raise.
- flag OFF → no-op.
- casbin endpoint: accountant allow, manager/officer deny.

Test DB dùng create_all() (KHÔNG có trigger applied_rules — memory
test-db-schema-source), nên quota/applied_rules test không dựa vào trigger; ghi
applied_rules trực tiếp OK trong test.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app import models
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.finance import (
    Fee,
    FeeAppliedDiscount,
    Invoice,
    Payment,
)
from app.services.fee_calculation_service import FeeCalculationService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Flag toggle
# ---------------------------------------------------------------------------
@pytest.fixture
def major_change_on(monkeypatch):
    """Bật MAJOR_CHANGE_REPRICE_ENABLED cho các test reprice."""
    monkeypatch.setattr(settings, "MAJOR_CHANGE_REPRICE_ENABLED", True)
    yield


@pytest_asyncio.fixture
async def accountant_user_in_db(seed_lead_dependencies: dict) -> dict:
    """Accountant cùng unit với hồ sơ seed (mold test_tuition_prepay_flow)."""
    from tests.conftest import _create_user_and_role
    return await _create_user_and_role(
        {
            "username": "mjc_accountant_u1",
            "email": "mjc_accountant_u1@example.com",
            "password": "AccountantPass!345",
            "role": "accountant",
            "status": "active",
        },
        "role:accountant",
        unit_id=seed_lead_dependencies["unit_id"],
    )


@pytest_asyncio.fixture
async def accountant_token_headers(client: AsyncClient, accountant_user_in_db) -> dict:
    from tests.conftest import _get_token_headers
    return await _get_token_headers(client, accountant_user_in_db)


# ---------------------------------------------------------------------------
# Seed helpers — choice-engine profile + 2 ngành (A rẻ, B đắt) + HK1 fee + invoice
# ---------------------------------------------------------------------------
async def _seed_two_majors(
    seed_lead_dependencies: dict, *, price_a: Decimal, price_b: Decimal
) -> dict:
    """2 academic_info (A,B) + OfferingSemesterTuition HK1 + 2 path + config,
    chung round + method + subject_group. Trả ids."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 100000
    prog_id = seed_lead_dependencies["major_program_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            from tests.fixtures.builders import AdmissionRoundBuilder
            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                s, academic_year=2026
            )
            round_obj = await s.get(models.OfferingAdmissionRound, round_id)
            round_obj.allow_multi_nv = True

            method = models.AdmissionMethod(
                code=f"MJC{ts}"[:20],
                name=f"MajorChange method {ts}",
                requires_subject_scores=True,
                is_active=True,
            )
            s.add(method)
            await s.flush()

            sg = models.SubjectGroup(code=f"GJC{ts}"[:20], name=f"SG {ts}")
            s.add(sg)
            await s.flush()
            subj = models.Subject(
                code=f"SJC{ts}"[:20],
                name_vi=f"Subj {ts}",
                max_score=Decimal("10.00"),
                min_possible_score=Decimal("0.00"),
            )
            s.add(subj)
            await s.flush()
            s.add(models.SubjectGroupSubject(
                subject_group_id=sg.id, subject_id=subj.id,
                position=1, weight=Decimal("1.00"),
            ))
            await s.flush()

            ids = {}
            for tag, price in (("a", price_a), ("b", price_b)):
                offering = models.ProgramOffering(
                    program_id=prog_id,
                    offering_type=f"ft_{tag}_{ts}"[:30],
                    duration_semesters=8,
                )
                s.add(offering)
                await s.flush()
                ai = models.OfferingAcademicInfo(
                    offering_id=offering.id,
                    academic_year=2026,
                    annual_admission_quota=20,
                    tuition_fee_per_year=price,
                )
                s.add(ai)
                await s.flush()
                s.add(models.OfferingSemesterTuition(
                    academic_info_id=ai.id, semester_no=1, amount=price,
                ))
                path = models.AdmissionPath(
                    academic_info_id=ai.id,
                    admission_method_id=method.id,
                    admission_round_id=round_id,
                    status="active",
                )
                s.add(path)
                await s.flush()
                config = models.PathSubjectGroupConfig(
                    admission_path_id=path.id,
                    subject_group_id=sg.id,
                    min_score=Decimal("18.00"),
                )
                s.add(config)
                await s.flush()
                ids[f"ai_{tag}"] = ai.id
                ids[f"path_{tag}"] = path.id
                ids[f"config_{tag}"] = config.id
            ids["round_id"] = round_id
            ids["subject_id"] = subj.id
            return ids


async def _seed_profile_fee_invoice(
    seed_lead_dependencies: dict,
    majors: dict,
    *,
    choice_tag: str = "b",              # ngành officer đã đổi sang (choice trỏ path này)
    choice_decision: str = "pending",
    priced_from_tag: str = "a",          # ngành fee ĐÃ định giá
    resolved_tag: str = "b",             # resolved_academic_info_id (mô phỏng resnapshot desync)
    price_a: Decimal = Decimal("6500000"),
    paid: Decimal = Decimal("3000000"),
    waived: Decimal = Decimal("0"),
    fee_status: str = "partial",
    major_change_requested: bool = True,
    awaiting: bool = False,
    n_invoices: int = 1,
    invoice_paid: Decimal | None = None,
) -> dict:
    """Dựng profile submitted (choice-engine, major_change_requested) + 1 choice +
    HK1 tuition fee (base/final = price ngành priced_from, priced_from + resolved
    tách biệt để test desync) + n_invoices hoá đơn active."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 100000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            lead = models.Lead(
                full_name=f"MJC Lead {ts}",
                phone=f"098{ts:07d}"[:10],
                unit_id=seed_lead_dependencies["unit_id"],
                source="walkin",
            )
            s.add(lead)
            await s.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                citizen_id=f"9{ts:08d}1"[:12],
                status="submitted",
                applied_rules={"admission_path_id": majors[f"path_{priced_from_tag}"]},
                academic_year=2026,
                uses_choice_engine=True,
                major_change_requested=major_change_requested,
            )
            s.add(profile)
            await s.flush()
            s.add(models.AdmissionProfileChoice(
                admission_profile_id=profile.id,
                admission_path_id=majors[f"path_{choice_tag}"],
                path_subject_group_config_id=majors[f"config_{choice_tag}"],
                display_order=1,
                decision=choice_decision,
            ))
            fee = Fee(
                admission_profile_id=profile.id,
                fee_type="tuition",
                academic_year=2026,
                semester_no=1,
                base_amount=price_a,
                total_discount=Decimal("0"),
                final_amount=price_a,
                paid_amount=paid,
                waived_amount=waived,
                status=fee_status,
                version=1,
                priced_from_academic_info_id=majors[f"ai_{priced_from_tag}"],
                resolved_academic_info_id=majors[f"ai_{resolved_tag}"],
                awaiting_accountant_confirmation=awaiting,
            )
            s.add(fee)
            await s.flush()
            inv_paid = invoice_paid if invoice_paid is not None else paid
            inv_ids = []
            for i in range(n_invoices):
                inv = Invoice(
                    fee_id=fee.id,
                    invoice_number=f"INV-{ts}-{i}",
                    installment_no=i + 1,
                    amount=price_a if n_invoices == 1 else (price_a / n_invoices),
                    paid_amount=inv_paid if i == 0 else Decimal("0"),
                    penalty_amount=Decimal("0"),
                    status="partial" if inv_paid > 0 else "issued",
                    due_date=date(2026, 9, 30),
                    issued_at=datetime.now(timezone.utc),
                )
                s.add(inv)
                await s.flush()
                inv_ids.append(inv.id)
            return {
                "profile_id": profile.id,
                "lead_id": lead.id,
                "fee_id": fee.id,
                "invoice_ids": inv_ids,
            }


async def _load_profile(pid: int) -> models.AdmissionProfile:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(models.AdmissionProfile)
                .options(selectinload(models.AdmissionProfile.lead))
                .where(models.AdmissionProfile.id == pid)
            )
        ).scalar_one()


async def _reprice(pid: int, actor_id: int | None = None):
    async with AsyncSessionLocal() as db:
        profile = (
            await db.execute(
                select(models.AdmissionProfile)
                .options(selectinload(models.AdmissionProfile.lead))
                .where(models.AdmissionProfile.id == pid)
            )
        ).scalar_one()
        svc = FeeCalculationService(db)
        fee, changed = await svc.reprice_for_major_change(profile, actor_id=actor_id)
        await db.commit()
        return (fee.id if fee else None), changed


async def _fee(fee_id: int) -> Fee:
    async with AsyncSessionLocal() as s:
        return await s.get(Fee, fee_id)


async def _path_count(path_id: int) -> int:
    async with AsyncSessionLocal() as s:
        p = await s.get(models.AdmissionPath, path_id)
        return int(p.submission_count or 0)


# ===========================================================================
# REGRESSION — Blocker 1: drift gate desync
# ===========================================================================
async def test_reprice_single_nv_after_choice_edit(
    seed_lead_dependencies, major_change_on
):
    """B1 REGRESSION: đơn-NV, fee priced_from=A (6.5tr) nhưng resolved_academic_
    info_id=B (đã bị resnapshot desync ở add/delete_choice) + choice=B (9.2tr).
    reprice PHẢI đổi final→9.2tr + bật awaiting. Nếu ai đổi drift gate về
    resolved_* → thấy B==B → no-op → test đỏ."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="a", resolved_tag="b",
        price_a=Decimal("6500000"), paid=Decimal("3000000"),
    )
    fee_id, changed = await _reprice(ids["profile_id"])

    assert changed is True, "reprice bị no-op oan (drift gate desync — Blocker 1 tái phát!)"
    fee = await _fee(fee_id)
    assert fee.final_amount == Decimal("9200000"), "final chưa đổi sang giá ngành mới"
    assert fee.base_amount == Decimal("9200000")
    assert fee.awaiting_accountant_confirmation is True
    assert fee.priced_from_academic_info_id == majors["ai_b"]
    # invoice.amount ghi luôn (CẮT 1)
    inv = None
    async with AsyncSessionLocal() as s:
        inv = await s.get(Invoice, ids["invoice_ids"][0])
    assert inv.amount == Decimal("9200000")


async def test_reprice_drift_gate_true_noop(
    seed_lead_dependencies, major_change_on
):
    """priced_from ĐÃ = ngành hiện tại (B) → no-op (fee, False), awaiting giữ False."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="b", resolved_tag="b",
        price_a=Decimal("9200000"), paid=Decimal("3000000"),
    )
    fee_id, changed = await _reprice(ids["profile_id"])
    assert changed is False
    fee = await _fee(fee_id)
    assert fee.awaiting_accountant_confirmation is False


# ===========================================================================
# REGRESSION — Blocker 2: quota resubmit +1
# ===========================================================================
async def test_quota_snapshot_resubmit_increments_new_path(
    seed_lead_dependencies, major_change_on
):
    """B2 REGRESSION: _apply_major_change_snapshot(increment_new_path=True) —
    path cũ A −1, path mới B +1 (resubmit KHÔNG có downstream +1)."""
    from app.services.admission_service import _apply_major_change_snapshot
    from app.repositories import AdmissionRepository

    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    # profile ở revision_requested, applied_rules path=A, choice=B
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="a", resolved_tag="a",
        price_a=Decimal("6500000"), paid=Decimal("3000000"),
    )
    # đặt submission_count ban đầu: A=5 (gồm hồ sơ này), B=0
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(update(models.AdmissionPath)
                .where(models.AdmissionPath.id == majors["path_a"])
                .values(submission_count=5))
            await s.execute(update(models.AdmissionPath)
                .where(models.AdmissionPath.id == majors["path_b"])
                .values(submission_count=0))
            await s.execute(update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == ids["profile_id"])
                .values(status="revision_requested"))

    async with AsyncSessionLocal() as db:
        profile = (await db.execute(
            select(models.AdmissionProfile)
            .options(selectinload(models.AdmissionProfile.lead))
            .where(models.AdmissionProfile.id == ids["profile_id"])
        )).scalar_one()
        await _apply_major_change_snapshot(
            db, profile, AdmissionRepository(db), None, increment_new_path=True,
        )
        await db.commit()

    assert await _path_count(majors["path_a"]) == 4, "path cũ chưa −1"
    assert await _path_count(majors["path_b"]) == 1, "path mới chưa +1 (Blocker 2 tái phát!)"


async def test_quota_snapshot_submit_defers_increment(
    seed_lead_dependencies, major_change_on
):
    """Nhánh submit (increment_new_path=False): chỉ −1 path cũ (downstream :else +1
    ở submit_and_evaluate mới +1 path mới — KHÔNG test ở đây). Xác nhận KHÔNG
    tự +1 để tránh double-count."""
    from app.services.admission_service import _apply_major_change_snapshot
    from app.repositories import AdmissionRepository

    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="a", resolved_tag="a",
        price_a=Decimal("6500000"), paid=Decimal("3000000"),
    )
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(update(models.AdmissionPath)
                .where(models.AdmissionPath.id == majors["path_a"])
                .values(submission_count=5))
            await s.execute(update(models.AdmissionPath)
                .where(models.AdmissionPath.id == majors["path_b"])
                .values(submission_count=0))

    async with AsyncSessionLocal() as db:
        profile = (await db.execute(
            select(models.AdmissionProfile)
            .options(selectinload(models.AdmissionProfile.lead))
            .where(models.AdmissionProfile.id == ids["profile_id"])
        )).scalar_one()
        await _apply_major_change_snapshot(
            db, profile, AdmissionRepository(db), None, increment_new_path=False,
        )
        await db.commit()

    assert await _path_count(majors["path_a"]) == 4, "path cũ chưa −1"
    assert await _path_count(majors["path_b"]) == 0, "submit nhánh KHÔNG được tự +1 (double-count)"


# ===========================================================================
# GUARD suite reprice — fail-closed
# ===========================================================================
async def _reprice_expect_block(pid: int):
    from app.utils.exceptions import BusinessRuleViolation
    with pytest.raises(BusinessRuleViolation):
        await _reprice(pid)


async def test_guard_manual_discount(seed_lead_dependencies, major_change_on):
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(seed_lead_dependencies, majors)
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(FeeAppliedDiscount(
                fee_id=ids["fee_id"], policy_id=None,
                discount_amount=Decimal("100000"),
                calculation_snapshot={"source": "manual_discount"},
                application_order=1,
            ))
    await _reprice_expect_block(ids["profile_id"])


async def test_guard_admitted_choice(seed_lead_dependencies, major_change_on):
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors, choice_decision="admitted",
    )
    await _reprice_expect_block(ids["profile_id"])


async def test_guard_overpay_sinh_du(seed_lead_dependencies, major_change_on):
    """paid > final ngành mới → chặn (CẮT 2, không sinh dư). Ngành mới rẻ (6.5),
    đã đóng 8tr > 6.5 → block."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("9200000"), price_b=Decimal("6500000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="a", resolved_tag="a",
        price_a=Decimal("9200000"), paid=Decimal("8000000"),
    )
    await _reprice_expect_block(ids["profile_id"])


async def test_guard_mien_phi_zero(seed_lead_dependencies, major_change_on):
    """final − waived <= 0 → chặn (CHECK invoice amount>0). waived = full price mới."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="a", resolved_tag="a",
        price_a=Decimal("6500000"), paid=Decimal("0"),
        waived=Decimal("9200000"),  # = giá ngành mới → target 0
    )
    await _reprice_expect_block(ids["profile_id"])


async def test_guard_multi_invoice(seed_lead_dependencies, major_change_on):
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors, n_invoices=2,
    )
    await _reprice_expect_block(ids["profile_id"])


async def _ensure_cash_method() -> int:
    from app.models.finance import PaymentMethod
    async with AsyncSessionLocal() as s:
        async with s.begin():
            m = (await s.execute(
                select(PaymentMethod).where(PaymentMethod.code == "cash")
            )).scalar_one_or_none()
            if m is None:
                m = PaymentMethod(
                    code="cash", name="Tiền mặt", is_online=False, is_active=True
                )
                s.add(m)
                await s.flush()
            return m.id


async def test_guard_pending_payment(
    seed_lead_dependencies, officer_user_in_db, major_change_on
):
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(seed_lead_dependencies, majors)
    method_id = await _ensure_cash_method()
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(Payment(
                invoice_id=ids["invoice_ids"][0],
                amount=Decimal("500000"),
                method_id=method_id,
                status="pending",
                created_by_id=officer_user_in_db["id"],
            ))
    await _reprice_expect_block(ids["profile_id"])


async def test_guard_single_cycle_already_awaiting(
    seed_lead_dependencies, major_change_on
):
    """fee đã awaiting=True → chặn (single-cycle lock)."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors, awaiting=True,
    )
    await _reprice_expect_block(ids["profile_id"])


async def test_flag_off_noop(seed_lead_dependencies):
    """Flag OFF → reprice trả (None, False) ngay, KHÔNG đụng gì."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(seed_lead_dependencies, majors)
    fee_id, changed = await _reprice(ids["profile_id"])
    assert fee_id is None and changed is False


# ===========================================================================
# confirm_major_change
# ===========================================================================
async def _confirm(fee_id: int, actor_id: int | None = None):
    async with AsyncSessionLocal() as db:
        svc = FeeCalculationService(db)
        fee, cb = await svc.confirm_major_change(fee_id, actor_id=actor_id)
        await db.commit()
        if cb:
            await cb()
        return fee.id


async def test_confirm_happy_clears_flag(seed_lead_dependencies, major_change_on):
    """fee awaiting + invoice.amount == final−waived → confirm clear cờ."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    # dựng fee đã ở trạng thái sau-reprice: final=9.2, invoice.amount=9.2, awaiting=True
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="b", resolved_tag="b",
        price_a=Decimal("9200000"), paid=Decimal("3000000"),
        awaiting=True, invoice_paid=Decimal("3000000"),
    )
    await _confirm(ids["fee_id"])
    fee = await _fee(ids["fee_id"])
    assert fee.awaiting_accountant_confirmation is False


async def test_confirm_idempotent_409(seed_lead_dependencies, major_change_on):
    """fee KHÔNG awaiting → ConflictError."""
    from app.utils.exceptions import ConflictError
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        price_a=Decimal("9200000"), awaiting=False,
        invoice_paid=Decimal("3000000"), paid=Decimal("3000000"),
    )
    with pytest.raises(ConflictError):
        await _confirm(ids["fee_id"])


async def test_confirm_invariant_mismatch_raises(
    seed_lead_dependencies, major_change_on
):
    """invoice.amount != final−waived → chặn (không tự sửa)."""
    from app.utils.exceptions import BusinessRuleViolation
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        price_a=Decimal("9200000"), awaiting=True,
        invoice_paid=Decimal("3000000"), paid=Decimal("3000000"),
    )
    # cố ý làm lệch invoice.amount
    async with AsyncSessionLocal() as s:
        async with s.begin():
            await s.execute(update(Invoice)
                .where(Invoice.id == ids["invoice_ids"][0])
                .values(amount=Decimal("5000000")))
    with pytest.raises(BusinessRuleViolation):
        await _confirm(ids["fee_id"])


# ===========================================================================
# Casbin — endpoint confirm-major-change
# ===========================================================================
async def test_endpoint_manager_denied(
    client: AsyncClient, manager_token_headers: dict,
    seed_lead_dependencies, major_change_on,
):
    """Manager KHÔNG được grant → 403 (deny-by-default)."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        price_a=Decimal("9200000"), awaiting=True,
        invoice_paid=Decimal("3000000"), paid=Decimal("3000000"),
    )
    res = await client.put(
        f"/api/fees/{ids['fee_id']}/confirm-major-change",
        headers=manager_token_headers,
    )
    assert res.status_code == 403, f"manager phải bị deny; got {res.status_code}: {res.text}"


async def test_endpoint_officer_denied(
    client: AsyncClient, officer_token_headers: dict,
    seed_lead_dependencies, major_change_on,
):
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        price_a=Decimal("9200000"), awaiting=True,
        invoice_paid=Decimal("3000000"), paid=Decimal("3000000"),
    )
    res = await client.put(
        f"/api/fees/{ids['fee_id']}/confirm-major-change",
        headers=officer_token_headers,
    )
    assert res.status_code == 403, f"officer phải bị deny; got {res.status_code}: {res.text}"


async def test_endpoint_accountant_confirms(
    client: AsyncClient, accountant_token_headers: dict,
    seed_lead_dependencies, major_change_on,
):
    """Accountant được grant → PUT confirm 200 + clear cờ."""
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(
        seed_lead_dependencies, majors,
        choice_tag="b", priced_from_tag="b", resolved_tag="b",
        price_a=Decimal("9200000"), awaiting=True,
        invoice_paid=Decimal("3000000"), paid=Decimal("3000000"),
    )
    res = await client.put(
        f"/api/fees/{ids['fee_id']}/confirm-major-change",
        headers=accountant_token_headers,
    )
    assert res.status_code == 200, f"accountant phải pass; got {res.status_code}: {res.text}"
    fee = await _fee(ids["fee_id"])
    assert fee.awaiting_accountant_confirmation is False


async def test_guard_pending_intent(
    seed_lead_dependencies, officer_user_in_db, major_change_on
):
    """PaymentIntent online còn sống trên invoice → chặn reprice."""
    from app.models.finance import PaymentIntent
    majors = await _seed_two_majors(
        seed_lead_dependencies,
        price_a=Decimal("6500000"), price_b=Decimal("9200000"),
    )
    ids = await _seed_profile_fee_invoice(seed_lead_dependencies, majors)
    method_id = await _ensure_cash_method()
    ts = int(datetime.now(timezone.utc).timestamp() * 1_000_000) % 100000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            s.add(PaymentIntent(
                invoice_id=ids["invoice_ids"][0],
                method_id=method_id,
                amount=Decimal("500000"),
                currency="VND",
                idempotency_key=f"idem-{ts}",
                status="created",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
    await _reprice_expect_block(ids["profile_id"])
