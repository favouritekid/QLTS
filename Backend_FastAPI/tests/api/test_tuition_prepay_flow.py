"""C3 — end-to-end smoke for the tuition prepay / hold-spot fast-track.

Covers TUITION_PREPAY_FASTTRACK_PLAN.md §C3 + §6 (C3/C4) + §2 flow. This
file writes NO new business logic — it proves that the EXISTING infra
(submit-with-document-debt from C1/C1.5 + fee@submitted+auto-issue from C2 +
the unchanged Finance Phase 1 partial-payment / HK1-cleared-sync / refund
maker-checker) composes into the advertised "giữ chỗ = học phí trả trước"
journey when driven through the real HTTP endpoints.

Scenarios:

1. Happy path (full journey): academically-eligible profile that is MISSING a
   mandatory doc → officer submit-with-debt (acknowledge + reason) → status
   ``submitted`` + ``document_debt`` snapshot recorded → officer calculates
   tuition at ``submitted`` → invoice **auto-issued** (status ``issued``) →
   accountant records a PARTIAL prepay (3,000,000 / 9,200,000) → manager
   verifies → invoice + fee go ``partial`` with the right ``paid_amount`` AND
   the lead STAYS at ``sts14`` (Chưa hoàn tất học phí) — a partial payment is
   NOT settled, so ``is_hk1_settled`` keeps the lead off sts10 →
   accountant records the remaining 6,200,000 → manager verifies → invoice +
   fee go ``paid`` AND the lead now advances to TUITION_PAID_STATUS / sts10
   (the ``sync_lead_tuition_paid`` projection fires only on FULL settlement).

2. Approve gate in the integrated flow (cross-check C1.5 end-to-end): while the
   document debt is outstanding ``approve`` is blocked (400); after the owed doc
   is verified (outstanding empties) ``approve`` succeeds.

3. Refund (cross-check C4): refund one verified prepay through the standard
   maker-checker chain (accountant request → manager approve → accountant
   process) → fee ``paid_amount`` drops by the refunded amount, refund row
   ends ``refunded``.

4. Non-regression: a profile submitted WITHOUT a document debt runs the exact
   same calculate→prepay→verify path — the C1/C1.5 gates are no-ops when
   ``document_debt`` is NULL.

The fee/payment/refund infra is unit/service tested in
``tests/integration/test_finance_workflow.py`` + ``tests/services/
test_payment_service.py`` + ``tests/integration/test_lead_admission_sync.py``;
the per-gate contracts are in ``tests/api/test_admission_submit_document_debt.py``
(C1/C1.5) + ``tests/api/test_fees_calculate_authorization.py`` (C2). This file
is the glue smoke that exercises them together via ``/api/...`` routes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import (
    FeeStatusEnum,
    InstallmentPlan,
    InvoiceStatusEnum,
    PaymentMethod,
    PaymentStatusEnum,
    RefundStatusEnum,
)
from tests.fixtures.builders import (
    ensure_submittable_ward,
    seed_submittable_offering_config,
    submittable_profile_fields,
)

pytestmark = pytest.mark.asyncio

ADMISSIONS = "/api/admissions"

# Plan §2 example figures: HK1 tuition 9,200,000; prepay/hold-spot 3,000,000.
HK1_TUITION = Decimal("9200000")
PREPAY = Decimal("3000000")
REMAINDER = HK1_TUITION - PREPAY  # 6,200,000


# ---------------------------------------------------------------------------
# Auth + low-level helpers
# ---------------------------------------------------------------------------

async def _auth(client: AsyncClient, user: dict) -> dict:
    """Login → Bearer header. Clears the shared cookie jar so a later login
    by a different role doesn't ride the previous user's access_token cookie
    (memory ``test-httpx-cookie-jar-contamination``)."""
    res = await client.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert res.status_code == 200, f"login failed for {user['username']}: {res.text}"
    token = res.cookies.get("access_token")
    client.cookies.delete("access_token")
    return {"Authorization": f"Bearer {token}"}


async def _get(client: AsyncClient, headers: dict, pid: int) -> dict:
    res = await client.get(f"{ADMISSIONS}/{pid}", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()


async def _load_profile(profile_id: int) -> models.AdmissionProfile:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(models.AdmissionProfile).where(
                    models.AdmissionProfile.id == profile_id
                )
            )
        ).scalar_one()


async def _load_lead(lead_id: int) -> models.Lead:
    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(models.Lead).where(models.Lead.id == lead_id)
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# Seed helpers (test DB uses create_all() — NO prod seed; fixtures self-seed)
# ---------------------------------------------------------------------------

def _submittable_applied_rules(
    mandatory_docs: list[str],
    *,
    allow_unverified: bool = False,
) -> dict:
    """applied_rules that clear scoring + carry the given mandatory docs.

    Mirrors ``test_admission_submit_document_debt.py`` so the ONLY submit gate
    left is the document one. ``allow_unverified=False`` (strict) by default so
    an uploaded-but-unverified doc still counts as outstanding for the debt /
    approve-gate cross-checks.
    """
    return {
        "min_gpa": 0,
        "mandatory_docs": list(mandatory_docs),
        "allowed_subject_codes": ["TOAN"],
        "scoring_method": "sum",
        "required_subject_count": 1,
        "subject_selection_mode": "fixed",
        "schema_version": 2,
        "allow_unverified_submission": allow_unverified,
    }


async def _ensure_subject_toan() -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            subj = (
                await session.execute(
                    select(models.Subject).where(models.Subject.code == "TOAN")
                )
            ).scalar_one_or_none()
            if subj is None:
                subj = models.Subject(code="TOAN", name_vi="Toan", is_active=True)
                session.add(subj)
                await session.flush()
            return subj.id


async def _create_doc_type(label: str) -> tuple[int, str]:
    ts = uuid.uuid4().hex[:10]
    code = f"{label}_{ts}"
    async with AsyncSessionLocal() as session:
        async with session.begin():
            dt = models.ConfigDocumentType(
                code=code, name=f"DOC {code}", display_order=99
            )
            session.add(dt)
            await session.flush()
            return dt.id, code


async def _ensure_cash_method() -> int:
    """Get-or-create a single offline ``cash`` payment method.

    Tolerates parallel-module collisions (UNIQUE code) the same way
    ``fee_calc_config`` get-or-creates the FULL plan.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            method = (
                await session.execute(
                    select(PaymentMethod).where(PaymentMethod.code == "cash")
                )
            ).scalar_one_or_none()
            if method is None:
                method = PaymentMethod(
                    code="cash", name="Tiền mặt", is_online=False, is_active=True
                )
                session.add(method)
                await session.flush()
            return method.id


async def _ensure_full_plan() -> None:
    """Get-or-create the canonical single-payment ``FULL`` installment plan."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            existing = (
                await session.execute(
                    select(InstallmentPlan).where(InstallmentPlan.code == "FULL")
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    InstallmentPlan(
                        code="FULL",
                        name="Thanh toán 1 lần",
                        installment_count=1,
                        schedule=[
                            {
                                "installment_no": 1,
                                "due_days_offset": 0,
                                "percent": 100.0,
                                "description": "Toàn bộ",
                            }
                        ],
                        is_active=True,
                    )
                )
                await session.flush()


async def _seed_hk1_tuition_for_config(oac_id: int, amount: Decimal) -> None:
    """Attach an OfferingSemesterTuition HK1 row to the academic_info behind a
    given OfferingAdmissionConfig so ``calculate_fee(tuition)`` resolves the
    canonical amount (ADR-002: tuition reads offering_semester_tuition, NOT
    tuition_fee_per_year). Without this the service raises
    ``Chưa cấu hình học phí cho HK1`` → 400.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            oac = await session.get(models.OfferingAdmissionConfig, oac_id)
            assert oac is not None and oac.academic_info_id is not None
            existing = (
                await session.execute(
                    select(models.OfferingSemesterTuition).where(
                        models.OfferingSemesterTuition.academic_info_id
                        == oac.academic_info_id,
                        models.OfferingSemesterTuition.semester_no == 1,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(
                    models.OfferingSemesterTuition(
                        academic_info_id=oac.academic_info_id,
                        semester_no=1,
                        amount=amount,
                    )
                )
                await session.flush()


async def _create_lead(unit_id: int, officer_id: int) -> int:
    unique = uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name=f"Prepay Applicant {unique}",
                phone=f"09{unique[:8]}",
                email=f"prepay_{unique}@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
            )
            session.add(lead)
            await session.flush()
            return lead.id


async def _build_draft_profile(
    lead_id: int,
    *,
    mandatory_docs: list[str],
    allow_unverified: bool = False,
) -> tuple[int, int]:
    """Build a draft profile that is submittable EXCEPT for the mandatory docs.

    Also seeds the HK1 tuition + FULL plan against the profile's offering so a
    tuition fee can be calculated at ``submitted``. Returns
    ``(profile_id, oac_id)``.
    """
    await ensure_submittable_ward()
    subj_id = await _ensure_subject_toan()
    cid = f"0{datetime.now().timestamp():.0f}"[:12]
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = await session.get(models.Lead, lead_id)
            seed = await seed_submittable_offering_config(session, lead.unit_id)
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status="draft",
                citizen_id=cid,
                version=1,
                applied_rules=_submittable_applied_rules(
                    mandatory_docs, allow_unverified=allow_unverified
                ),
                academic_year=seed["academic_year"],
                family_info=[
                    {
                        "relationship": "Cha",
                        "full_name": "Test Father",
                        "phone": "0901234567",
                    }
                ],
                **submittable_profile_fields(seed),
            )
            session.add(profile)
            await session.flush()
            session.add(
                models.ProfileSubjectScore(
                    profile_id=profile.id, subject_id=subj_id, score=8.0
                )
            )
            await session.flush()
            pid = profile.id
            oac_id = seed["offering_admission_config_id"]

    await _seed_hk1_tuition_for_config(oac_id, HK1_TUITION)
    await _ensure_full_plan()
    await _ensure_cash_method()
    return pid, oac_id


async def _add_uploaded_doc(profile_id: int, doc_type_id: int) -> None:
    """Attach an uploaded-but-unverified ProfileDocument (file present,
    status='uploaded')."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                models.ProfileDocument(
                    profile_id=profile_id,
                    document_type_id=doc_type_id,
                    category="path",
                    status="uploaded",
                    file_path=f"uploads/admissions/{profile_id}/doc.pdf",
                    uploaded_at=datetime.now(timezone.utc),
                )
            )


async def _verify_doc(profile_id: int, doc_type_id: int) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            pd = (
                await session.execute(
                    select(models.ProfileDocument).where(
                        models.ProfileDocument.profile_id == profile_id,
                        models.ProfileDocument.document_type_id == doc_type_id,
                    )
                )
            ).scalar_one()
            pd.status = "verified"
            pd.verified_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Flow-level helpers (drive the real endpoints)
# ---------------------------------------------------------------------------

async def _submit_with_debt(
    client: AsyncClient, officer_headers: dict, pid: int, reason: str
) -> dict:
    res = await client.post(
        f"{ADMISSIONS}/{pid}/submit",
        headers=officer_headers,
        json={"acknowledge_missing_docs": True, "document_debt_reason": reason},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "submitted", body
    return body


async def _calculate_tuition(
    client: AsyncClient, headers: dict, pid: int
) -> dict:
    """Calculate the tuition fee (FULL plan, HK1). Returns the fee detail
    response (with nested ``invoices``). The C2 route auto-issues tuition."""
    res = await client.post(
        "/api/fees/calculate",
        json={
            "admission_profile_id": pid,
            "fee_type": "tuition",
            "installment_plan_code": "FULL",
            "semester_no": 1,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _ensure_consultation_status(
    status_id: str, name: str, stage_id: str, color_code: str = "#888888"
) -> None:
    """Get-or-create a ConsultationStatus row.

    ``seed_lead_dependencies`` (conftest) seeds most statuses but NOT ``sts08``
    (withdrawn → "Từ chối tư vấn"), so the withdraw lead-sync 404s without it.
    Idempotent so parallel modules don't collide on the PK.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            existing = await session.get(models.ConsultationStatus, status_id)
            if existing is None:
                session.add(
                    models.ConsultationStatus(
                        id=status_id,
                        name=name,
                        color_code=color_code,
                        stage_id=stage_id,
                    )
                )


async def _reject(
    client: AsyncClient, manager_headers: dict, pid: int, reason: str
) -> dict:
    """Reject a submitted profile (manager). Reads the live version first."""
    body = await _get(client, manager_headers, pid)
    res = await client.post(
        f"{ADMISSIONS}/{pid}/reject",
        headers=manager_headers,
        json={"reason": reason, "version": body["version"]},
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == "rejected", out
    return out


async def _withdraw(
    client: AsyncClient, headers: dict, pid: int, reason: str
) -> dict:
    """Withdraw a profile (officer/manager). Reads the live version first."""
    body = await _get(client, headers, pid)
    res = await client.post(
        f"{ADMISSIONS}/{pid}/withdraw",
        headers=headers,
        json={"reason": reason, "version": body["version"]},
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["status"] == "withdrawn", out
    return out


async def _record_and_verify_payment(
    client: AsyncClient,
    accountant_headers: dict,
    manager_headers: dict,
    invoice_id: int,
    amount: Decimal,
) -> dict:
    """Standard manual-payment maker-checker: accountant records → manager
    verifies. Returns the verified payment response."""
    rec = await client.post(
        "/api/payments",
        json={
            "invoice_id": invoice_id,
            "method_id": await _ensure_cash_method(),
            "amount": str(amount),
            "reference_code": f"CASH-{uuid.uuid4().hex[:8]}",
            "payer_name": "Prepay Student",
        },
        headers=accountant_headers,
    )
    assert rec.status_code == 201, rec.text
    payment = rec.json()
    assert payment["status"] == PaymentStatusEnum.pending.value, payment

    ver = await client.put(
        f"/api/payments/{payment['id']}/verify", headers=manager_headers
    )
    assert ver.status_code == 200, ver.text
    verified = ver.json()
    assert verified["status"] == PaymentStatusEnum.verified.value, verified
    return verified


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def accountant_user_in_db(seed_lead_dependencies: dict) -> dict:
    """Accountant in the SAME unit as the seeded leads/profiles (records +
    requests/processes refunds). Built inline via the canonical helper — there
    is no shared ACCOUNTANT fixture in conftest (mirrors the C2
    ``accountant_same_unit`` fixture)."""
    from tests.conftest import _create_user_and_role

    return await _create_user_and_role(
        {
            "username": "prepay_accountant_u1",
            "email": "prepay_accountant_u1@example.com",
            "password": "AccountantPass!345",
            "role": "accountant",
            "status": "active",
        },
        "role:accountant",
        unit_id=seed_lead_dependencies["unit_id"],
    )


# ===========================================================================
# Scenario 1 — Happy path: submit-with-debt → fee@submitted → auto-issue →
#              partial prepay (+HK1 sync) → paid
# ===========================================================================

class TestPrepayHappyPath:
    async def test_full_prepay_journey_debt_to_paid(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("hocba")
        lead_id = await _create_lead(unit_id, officer_user_in_db["id"])
        pid, _oac = await _build_draft_profile(lead_id, mandatory_docs=[doc_code])

        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        # --- Step 1: submit-with-document-debt (officer) ---------------------
        await _submit_with_debt(
            client, officer, pid, "HS xin cấp lại học bạ, hẹn 30/06"
        )
        profile = await _load_profile(pid)
        assert profile.status == "submitted"
        assert profile.document_debt is not None
        assert profile.document_debt["codes"] == [doc_code]
        assert profile.document_debt["by_user_id"] == officer_user_in_db["id"]
        # Snapshot must NOT leak into applied_rules (immutability trigger).
        assert "document_debt" not in (profile.applied_rules or {})

        detail = await _get(client, officer, pid)
        assert detail["outstanding_debt_codes"] == [doc_code]

        # --- Step 2: calculate tuition at submitted → auto-issued -----------
        fee_detail = await _calculate_tuition(client, officer, pid)
        assert Decimal(str(fee_detail["final_amount"])) == HK1_TUITION
        invoices = fee_detail["invoices"]
        assert len(invoices) == 1, invoices
        invoice = invoices[0]
        assert invoice["status"] == InvoiceStatusEnum.issued.value, invoice
        assert Decimal(str(invoice["amount"])) == HK1_TUITION
        invoice_id = invoice["id"]
        fee_id = fee_detail["id"]

        # --- Step 3: partial prepay (3,000,000) → partial + HK1 sync --------
        await _record_and_verify_payment(
            client, accountant, manager, invoice_id, PREPAY
        )

        inv = (
            await client.get(f"/api/invoices/{invoice_id}", headers=accountant)
        ).json()
        assert inv["status"] == InvoiceStatusEnum.partial.value, inv
        assert Decimal(str(inv["paid_amount"])) == PREPAY

        fee = (await client.get(f"/api/fees/{fee_id}", headers=accountant)).json()
        assert fee["status"] == FeeStatusEnum.partial.value, fee
        assert Decimal(str(fee["paid_amount"])) == PREPAY

        # A PARTIAL prepay is NOT settled → the lead must STAY at sts14
        # (Chưa hoàn tất học phí). It must NOT jump to sts10 — that is the
        # bug this change fixes (is_hk1_settled requires remaining <= 0).
        from app.services.lead_admission_sync import (
            TUITION_CALCULATED_STATUS,
            TUITION_PAID_STATUS,
        )

        lead = await _load_lead(lead_id)
        assert lead.consultation_status_id == TUITION_CALCULATED_STATUS, (
            f"Partial prepay must keep lead at {TUITION_CALCULATED_STATUS} "
            f"(chưa hoàn tất), got {lead.consultation_status_id}"
        )

        # --- Step 4: pay the remainder (6,200,000) → paid + sts10 ----------
        await _record_and_verify_payment(
            client, accountant, manager, invoice_id, REMAINDER
        )

        inv2 = (
            await client.get(f"/api/invoices/{invoice_id}", headers=accountant)
        ).json()
        assert inv2["status"] == InvoiceStatusEnum.paid.value, inv2
        assert Decimal(str(inv2["paid_amount"])) == HK1_TUITION

        fee2 = (await client.get(f"/api/fees/{fee_id}", headers=accountant)).json()
        assert fee2["status"] == FeeStatusEnum.paid.value, fee2
        assert Decimal(str(fee2["paid_amount"])) == HK1_TUITION

        # Now fully settled → lead advances to sts10 (Đã hoàn tất học phí).
        lead2 = await _load_lead(lead_id)
        assert lead2.consultation_status_id == TUITION_PAID_STATUS, (
            f"Full settlement should advance lead to {TUITION_PAID_STATUS}, "
            f"got {lead2.consultation_status_id}"
        )


# ===========================================================================
# Scenario 2 — Approve gate inside the integrated flow (cross-check C1.5)
# ===========================================================================

class TestApproveGateInFlow:
    async def test_approve_blocked_then_ok_after_docs_verified(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("hocba")
        lead_id = await _create_lead(unit_id, officer_user_in_db["id"])
        pid, _oac = await _build_draft_profile(lead_id, mandatory_docs=[doc_code])

        officer = await _auth(client, officer_user_in_db)
        await _submit_with_debt(client, officer, pid, "cho nợ giấy tờ")

        manager = await _auth(client, manager_user_in_db)

        # Debt outstanding → approve flag off + server gate rejects.
        body = await _get(client, manager, pid)
        assert body["outstanding_debt_codes"] == [doc_code]
        assert body["permissions"].get("approve") is False, body["permissions"]
        rej = await client.post(
            f"{ADMISSIONS}/{pid}/approve",
            headers=manager,
            json={"notes": "duyệt", "version": body["version"]},
        )
        assert rej.status_code == 400, rej.text
        assert "nợ giấy tờ" in rej.json()["detail"], rej.json()
        assert (await _load_profile(pid)).status == "submitted"

        # Officer supplies + reviewer verifies the owed doc → outstanding
        # empties (verified-based) → approve succeeds.
        await _add_uploaded_doc(pid, doc_type_id)
        await _verify_doc(pid, doc_type_id)

        body2 = await _get(client, manager, pid)
        assert body2["outstanding_debt_codes"] == []
        assert body2["permissions"].get("approve") is True, body2["permissions"]
        ok = await client.post(
            f"{ADMISSIONS}/{pid}/approve",
            headers=manager,
            json={"notes": "đủ giấy tờ", "version": body2["version"]},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "approved", ok.json()


# ===========================================================================
# Scenario 3 — Refund the prepay through the maker-checker chain (cross-check C4)
# ===========================================================================

class TestRefundPrepay:
    async def test_refund_prepay_reduces_paid_amount(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("hocba")
        lead_id = await _create_lead(unit_id, officer_user_in_db["id"])
        pid, _oac = await _build_draft_profile(lead_id, mandatory_docs=[doc_code])

        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        await _submit_with_debt(client, officer, pid, "cho nợ")
        fee_detail = await _calculate_tuition(client, officer, pid)
        invoice_id = fee_detail["invoices"][0]["id"]
        fee_id = fee_detail["id"]

        # Collect a prepay then verify it (this is the payment we refund).
        verified = await _record_and_verify_payment(
            client, accountant, manager, invoice_id, PREPAY
        )
        payment_id = verified["id"]

        # Refund maker-checker chain: accountant request → manager approve →
        # accountant process (standard Finance Phase 1 flow).
        req = await client.post(
            "/api/refunds",
            json={
                "payment_id": payment_id,
                "amount": str(PREPAY),
                "reason": "Học sinh rút hồ sơ — hoàn khoản trả trước",
            },
            headers=accountant,
        )
        assert req.status_code == 201, req.text
        refund = req.json()
        assert refund["status"] == RefundStatusEnum.pending.value, refund
        refund_id = refund["id"]

        appr = await client.post(
            f"/api/refunds/{refund_id}/approve", headers=manager
        )
        assert appr.status_code == 200, appr.text
        assert appr.json()["status"] == RefundStatusEnum.approved.value, appr.json()

        proc = await client.post(
            f"/api/refunds/{refund_id}/process",
            json={"refund_id": refund_id, "refund_reference": "BANK-REF-001"},
            headers=accountant,
        )
        assert proc.status_code == 200, proc.text
        processed = proc.json()
        assert processed["status"] == RefundStatusEnum.refunded.value, processed
        assert processed["refund_reference"] == "BANK-REF-001"

        # Fee paid_amount dropped back to 0 (the single prepay was refunded).
        fee = (await client.get(f"/api/fees/{fee_id}", headers=accountant)).json()
        assert Decimal(str(fee["paid_amount"])) == Decimal("0"), fee


# ===========================================================================
# Scenario 4 — Non-regression: NO document debt → same calc/prepay path
# ===========================================================================

class TestNoDebtNonRegression:
    async def test_clean_profile_prepay_unaffected_by_debt_gates(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """A profile whose mandatory doc is present submits WITHOUT a debt, and
        the calculate→prepay→verify path behaves exactly as before — the C1/C1.5
        gates are inert when ``document_debt`` is NULL."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("hocba")
        lead_id = await _create_lead(unit_id, officer_user_in_db["id"])
        # Lax mode + an uploaded doc → a plain submit (no body) passes with no debt.
        pid, _oac = await _build_draft_profile(
            lead_id, mandatory_docs=[doc_code], allow_unverified=True
        )
        await _add_uploaded_doc(pid, doc_type_id)

        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        # Plain submit (no debt body).
        sub = await client.post(f"{ADMISSIONS}/{pid}/submit", headers=officer)
        assert sub.status_code == 200, sub.text
        assert sub.json()["status"] == "submitted", sub.json()

        profile = await _load_profile(pid)
        assert profile.document_debt is None
        detail = await _get(client, officer, pid)
        assert detail["outstanding_debt_codes"] == []

        # Same calculate→prepay→verify path works.
        fee_detail = await _calculate_tuition(client, officer, pid)
        invoice = fee_detail["invoices"][0]
        assert invoice["status"] == InvoiceStatusEnum.issued.value, invoice
        invoice_id = invoice["id"]
        fee_id = fee_detail["id"]

        await _record_and_verify_payment(
            client, accountant, manager, invoice_id, PREPAY
        )
        fee = (await client.get(f"/api/fees/{fee_id}", headers=accountant)).json()
        assert fee["status"] == FeeStatusEnum.partial.value, fee
        assert Decimal(str(fee["paid_amount"])) == PREPAY


# ===========================================================================
# Scenario 5 — finding #1: has_unrefunded_payment flag + log.warning on
#              reject/withdraw of a hold-spot profile that prepaid tuition.
# ===========================================================================

async def _submit_and_prepay(
    client: AsyncClient,
    officer: dict,
    manager: dict,
    accountant: dict,
    unit_id: int,
    officer_id: int,
) -> int:
    """Build → submit-with-debt → calculate tuition → record+verify a PARTIAL
    prepay so the profile is ``submitted`` with ``SUM(fee.paid_amount) > 0``.
    Returns the profile id."""
    _doc_id, doc_code = await _create_doc_type("hocba")
    lead_id = await _create_lead(unit_id, officer_id)
    pid, _oac = await _build_draft_profile(lead_id, mandatory_docs=[doc_code])
    await _submit_with_debt(client, officer, pid, "giữ chỗ — chờ học bạ")
    fee_detail = await _calculate_tuition(client, officer, pid)
    invoice_id = fee_detail["invoices"][0]["id"]
    await _record_and_verify_payment(client, accountant, manager, invoice_id, PREPAY)
    return pid


async def _lead_status_of(profile_id: int) -> str | None:
    """Consultation status of the lead behind a profile (lead-sync asserts)."""
    async with AsyncSessionLocal() as session:
        row = await session.execute(
            select(models.Lead.consultation_status_id)
            .join(
                models.AdmissionProfile,
                models.AdmissionProfile.lead_id == models.Lead.id,
            )
            .where(models.AdmissionProfile.id == profile_id)
        )
        return row.scalar_one_or_none()


class TestUnrefundedPaymentFlag:
    async def test_reject_with_prepay_sets_flag_and_warns(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """(a) Reject a profile that holds a verified prepay → response +
        subsequent GET both carry ``has_unrefunded_payment=True`` (parity).
        Reject is NOT blocked; the flag being True proves the warning branch
        (``if has_unrefunded_payment: log.warning(...)``) was reached — the log
        line itself is trivial and structlog routing is config-dependent, so we
        assert the contract (the flag) rather than the caplog text."""
        unit_id = seed_lead_dependencies["unit_id"]
        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        pid = await _submit_and_prepay(
            client, officer, manager, accountant, unit_id, officer_user_in_db["id"]
        )

        # Before the terminal transition the flag is False (submitted holds
        # money but is not rejected/withdrawn → no warning, no query cost).
        pre = await _get(client, manager, pid)
        assert pre["has_unrefunded_payment"] is False, pre

        rejected = await _reject(client, manager, pid, "Không đủ điều kiện xét tuyển")

        # Mutation response parity.
        assert rejected["has_unrefunded_payment"] is True, rejected
        # GET parity (get_profile sets the flag independently).
        after = await _get(client, manager, pid)
        assert after["has_unrefunded_payment"] is True, after

    async def test_reject_without_prepay_flag_false(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """(b) Reject a submitted profile with NO collected fee → flag False."""
        unit_id = seed_lead_dependencies["unit_id"]
        _doc_id, doc_code = await _create_doc_type("hocba")
        lead_id = await _create_lead(unit_id, officer_user_in_db["id"])
        pid, _oac = await _build_draft_profile(lead_id, mandatory_docs=[doc_code])

        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        await _submit_with_debt(client, officer, pid, "giữ chỗ không trả trước")

        rejected = await _reject(client, manager, pid, "Hồ sơ không hợp lệ lần này")
        assert rejected["has_unrefunded_payment"] is False, rejected
        after = await _get(client, manager, pid)
        assert after["has_unrefunded_payment"] is False, after

    async def test_withdraw_with_prepay_sets_flag(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """(c) PR-B: withdraw a profile holding a verified TUITION prepay →
        the orchestrator AUTO-FILES a refund request and parks the profile in
        ``withdrawal_pending`` (NOT ``withdrawn``); it settles to ``withdrawn``
        only once the refund is processed. The refundable money is still held
        (refund is 'pending'), so ``has_unrefunded_payment`` is True on both the
        mutation response and a subsequent GET."""
        unit_id = seed_lead_dependencies["unit_id"]
        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        pid = await _submit_and_prepay(
            client, officer, manager, accountant, unit_id, officer_user_in_db["id"]
        )

        # withdraw finalize lead-sync advances the lead to sts08 (not in the
        # conftest seed list) — seed it so the sync resolves.
        await _ensure_consultation_status(
            "sts08", "Tu choi tu van", "stg07", "#CC0000"
        )

        # Withdraw with collected refundable tuition → withdrawal_pending.
        body = await _get(client, manager, pid)
        res = await client.post(
            f"{ADMISSIONS}/{pid}/withdraw",
            headers=manager,
            json={"reason": "Học sinh đổi nguyện vọng", "version": body["version"]},
        )
        assert res.status_code == 200, res.text
        withdrawn = res.json()
        assert withdrawn["status"] == "withdrawal_pending", withdrawn
        assert withdrawn["has_unrefunded_payment"] is True, withdrawn
        after = await _get(client, manager, pid)
        assert after["status"] == "withdrawal_pending", after
        assert after["has_unrefunded_payment"] is True, after

    async def test_nonterminal_statuses_flag_false(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """(d) submitted (with money) and approved both keep the flag False —
        the flag is gated on terminal rejected/withdrawn only (no DB cost on
        the hot read path)."""
        unit_id = seed_lead_dependencies["unit_id"]
        doc_type_id, doc_code = await _create_doc_type("hocba")
        lead_id = await _create_lead(unit_id, officer_user_in_db["id"])
        pid, _oac = await _build_draft_profile(lead_id, mandatory_docs=[doc_code])

        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        await _submit_with_debt(client, officer, pid, "giữ chỗ — chờ học bạ")
        fee_detail = await _calculate_tuition(client, officer, pid)
        invoice_id = fee_detail["invoices"][0]["id"]
        await _record_and_verify_payment(
            client, accountant, manager, invoice_id, PREPAY
        )

        # submitted + holds money → still False (not terminal).
        submitted = await _get(client, manager, pid)
        assert submitted["status"] == "submitted", submitted
        assert submitted["has_unrefunded_payment"] is False, submitted

        # Verify the owed doc so approve is allowed, then approve → False.
        await _add_uploaded_doc(pid, doc_type_id)
        await _verify_doc(pid, doc_type_id)
        body = await _get(client, manager, pid)
        ok = await client.post(
            f"{ADMISSIONS}/{pid}/approve",
            headers=manager,
            json={"notes": "đủ giấy tờ", "version": body["version"]},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["status"] == "approved", ok.json()
        assert ok.json()["has_unrefunded_payment"] is False, ok.json()


# ===========================================================================
# PR-B §2.10 — withdrawal_pending finalize + cancel-withdrawal
# ===========================================================================


class TestWithdrawalPendingFlow:
    """Withdraw with collected refundable tuition → withdrawal_pending, then
    either finalize (refund processed → withdrawn) or cancel (admin → draft)."""

    async def test_finalize_on_last_refund(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """Scenario (e): withdraw parks the profile in withdrawal_pending and
        auto-files a refund; processing that refund self-settles the profile to
        ``withdrawn`` (finalize hook) + lead → sts08."""
        unit_id = seed_lead_dependencies["unit_id"]
        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)
        await _ensure_consultation_status(
            "sts08", "Tu choi tu van", "stg07", "#CC0000"
        )

        pid = await _submit_and_prepay(
            client, officer, manager, accountant, unit_id, officer_user_in_db["id"]
        )

        # Withdraw → withdrawal_pending (BE auto-files a refund request whose
        # requester is the withdrawing actor). Withdraw as the OFFICER so the
        # auto-filed refund's maker (officer) differs from its approver
        # (manager) — otherwise the approve step self-approves and 400s.
        body = await _get(client, officer, pid)
        res = await client.post(
            f"{ADMISSIONS}/{pid}/withdraw",
            headers=officer,
            json={"reason": "Học sinh rút hồ sơ", "version": body["version"]},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "withdrawal_pending", res.json()

        # Find the auto-filed pending refund for THIS profile by reason (NOT
        # items[0] — the pending list is unit-wide and other tests leave pending
        # refunds behind). Assert exactly one, for the collected tuition amount.
        refunds = await client.get(
            "/api/refunds", params={"status": "pending"}, headers=manager
        )
        assert refunds.status_code == 200, refunds.text
        mine = [
            r for r in refunds.json()["items"]
            if f"#{pid}" in (r.get("reason") or "")
        ]
        assert len(mine) == 1, mine
        refund = mine[0]
        refund_id = refund["id"]
        assert Decimal(refund["amount"]) == PREPAY, refund

        appr = await client.post(
            f"/api/refunds/{refund_id}/approve", headers=manager
        )
        assert appr.status_code == 200, appr.text
        proc = await client.post(
            f"/api/refunds/{refund_id}/process",
            json={"refund_id": refund_id, "refund_reference": "BANK-REF-FIN"},
            headers=accountant,
        )
        assert proc.status_code == 200, proc.text

        # Finalize hook fired: profile self-settled to withdrawn + lead → sts08.
        after = await _get(client, manager, pid)
        assert after["status"] == "withdrawn", after
        assert after["has_unrefunded_payment"] is False, after
        assert await _lead_status_of(pid) == "sts08"

    async def test_admin_cancel_withdrawal_back_to_draft(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        admin_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """§2.4: admin cancels a pending withdrawal → draft; a non-admin
        (manager) is blocked by ``require_admin`` (403)."""
        unit_id = seed_lead_dependencies["unit_id"]
        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)
        admin = await _auth(client, admin_user_in_db)

        pid = await _submit_and_prepay(
            client, officer, manager, accountant, unit_id, officer_user_in_db["id"]
        )
        body = await _get(client, manager, pid)
        res = await client.post(
            f"{ADMISSIONS}/{pid}/withdraw",
            headers=manager,
            json={"reason": "Rút hồ sơ chờ hoàn", "version": body["version"]},
        )
        assert res.status_code == 200 and res.json()["status"] == "withdrawal_pending"

        # Non-admin (manager) cannot cancel → 403.
        forbidden = await client.post(
            f"{ADMISSIONS}/{pid}/cancel-withdrawal",
            headers=manager,
            json={"reason": "Manager thử hủy — phải bị chặn"},
        )
        assert forbidden.status_code == 403, forbidden.text

        # Admin cancels → draft.
        cancel = await client.post(
            f"{ADMISSIONS}/{pid}/cancel-withdrawal",
            headers=admin,
            json={"reason": "Hoàn tiền bị từ chối — đưa hồ sơ về nháp"},
        )
        assert cancel.status_code == 200, cancel.text
        assert cancel.json()["status"] == "draft", cancel.json()

        # F1: the refund the withdraw auto-filed must now be REJECTED — so it can
        # never be processed and return money on this re-activated profile.
        rejected = await client.get(
            "/api/refunds", params={"status": "rejected"}, headers=admin
        )
        assert rejected.status_code == 200, rejected.text
        assert any(
            f"#{pid}" in (r.get("reason") or "")
            for r in rejected.json()["items"]
        ), rejected.json()

    async def test_cannot_rewithdraw_pending(
        self,
        client: AsyncClient,
        officer_user_in_db: dict,
        manager_user_in_db: dict,
        accountant_user_in_db: dict,
        seed_lead_dependencies: dict,
    ):
        """F6: a profile already in withdrawal_pending rejects a second withdraw
        cleanly (400) instead of running STEP 1/2 then dying at STEP 3."""
        unit_id = seed_lead_dependencies["unit_id"]
        officer = await _auth(client, officer_user_in_db)
        manager = await _auth(client, manager_user_in_db)
        accountant = await _auth(client, accountant_user_in_db)

        pid = await _submit_and_prepay(
            client, officer, manager, accountant, unit_id, officer_user_in_db["id"]
        )
        body = await _get(client, manager, pid)
        r1 = await client.post(
            f"{ADMISSIONS}/{pid}/withdraw",
            headers=manager,
            json={"reason": "Rút lần một", "version": body["version"]},
        )
        assert r1.status_code == 200 and r1.json()["status"] == "withdrawal_pending"

        body2 = await _get(client, manager, pid)
        r2 = await client.post(
            f"{ADMISSIONS}/{pid}/withdraw",
            headers=manager,
            json={"reason": "Rút lần hai", "version": body2["version"]},
        )
        assert r2.status_code == 400, r2.text
