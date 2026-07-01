"""Integration tests — Admission List v2 (cột Học phí HK1 + filter điều phối).

Covers the BE additions in ``get_filtered_with_count`` / router:
  * HK1 tuition aggregate columns (paid / remaining / overdue / status) scoped to
    fee_type='tuition' AND semester_no=1 AND status != cancelled.
  * no-HK1 profile → status "none", paid/remaining 0, no 500.
  * payment_status=overdue filter.
  * sort_by=remaining_hk1 (with stable id tiebreaker).
  * coordination filters: assigned_officer_id / unassigned / assigned_reviewer_id.
  * query validation: non-int officer id → 400; new sort/payment values accepted.

conftest truncates all tables per test, so each test controls the full dataset.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import Fee, Invoice, FeeStatusEnum, InvoiceStatusEnum

pytestmark = pytest.mark.asyncio

_CCCD_SEQ = iter(range(1, 10_000))


def _next_cccd() -> str:
    return f"0790000{next(_CCCD_SEQ):05d}"


async def _make_profile(unit_id: int, *, officer_id=None, reviewer_id=None, status="submitted") -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="HK1 Test Lead",
                phone="0901234567",
                email=f"hk1_{_next_cccd()}@test.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=officer_id,
            )
            session.add(lead)
            await session.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                status=status,
                citizen_id=_next_cccd(),
                academic_year=2026,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                assigned_reviewer_id=reviewer_id,
            )
            session.add(profile)
            await session.flush()
            return profile.id


async def _add_fee(
    profile_id: int,
    *,
    fee_type="tuition",
    semester_no=1,
    final="9200000",
    paid="0",
    waived="0",
    status=FeeStatusEnum.invoiced.value,
    invoice_status=None,
    invoice_due=None,
) -> int:
    """Add a Fee (+ optional Invoice) to a profile. Returns fee id."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            fee = Fee(
                admission_profile_id=profile_id,
                fee_type=fee_type,
                academic_year=2026,
                semester_no=semester_no if fee_type == "tuition" else None,
                base_amount=Decimal(final),
                total_discount=Decimal("0"),
                final_amount=Decimal(final),
                paid_amount=Decimal(paid),
                waived_amount=Decimal(waived),
                status=status,
                version=1,
            )
            session.add(fee)
            await session.flush()
            if invoice_status is not None:
                session.add(
                    Invoice(
                        fee_id=fee.id,
                        invoice_number=f"INV-{fee.id}",
                        installment_no=1,
                        amount=Decimal(final),
                        paid_amount=Decimal(paid),
                        status=invoice_status,
                        due_date=invoice_due or date.today(),
                    )
                )
            return fee.id


def _find(body: dict, profile_id: int) -> dict:
    return next(p for p in body["profiles"] if p["id"] == profile_id)


class TestHk1Aggregate:
    async def test_only_hk1_tuition_counts(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """paid/remaining count ONLY HK1 tuition (HK2 + application excluded)."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        await _add_fee(pid, semester_no=1, final="9200000", paid="3000000",
                       status=FeeStatusEnum.partial.value)
        await _add_fee(pid, semester_no=2, final="5000000", paid="5000000",
                       status=FeeStatusEnum.paid.value)
        await _add_fee(pid, fee_type="application", final="70000", paid="70000",
                       status=FeeStatusEnum.paid.value)

        resp = await client.get("/api/admissions", headers=admin_token_headers)
        assert resp.status_code == 200, resp.text
        row = _find(resp.json(), pid)
        assert Decimal(row["tuition_paid_hk1"]) == Decimal("3000000")
        assert Decimal(row["tuition_remaining_hk1"]) == Decimal("6200000")
        assert row["tuition_hk1_status"] == "partial"
        assert row["tuition_overdue_hk1"] is False

    async def test_cancelled_hk1_excluded_status_none(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """A profile whose only HK1 fee is cancelled → treated as no-HK1 ("none")."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        await _add_fee(pid, semester_no=1, final="9200000", paid="0",
                       status=FeeStatusEnum.cancelled.value)

        resp = await client.get("/api/admissions", headers=admin_token_headers)
        row = _find(resp.json(), pid)
        assert Decimal(row["tuition_paid_hk1"]) == Decimal("0")
        assert Decimal(row["tuition_remaining_hk1"]) == Decimal("0")
        assert row["tuition_hk1_status"] == "none"

    async def test_no_fee_profile_status_none_no_500(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """Profile with NO fees at all → status none, paid/remaining 0, no crash."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)

        resp = await client.get("/api/admissions", headers=admin_token_headers)
        assert resp.status_code == 200, resp.text
        row = _find(resp.json(), pid)
        assert row["tuition_hk1_status"] == "none"
        assert Decimal(row["tuition_paid_hk1"]) == Decimal("0")
        assert Decimal(row["tuition_remaining_hk1"]) == Decimal("0")

    async def test_fully_waived_hk1_is_paid_not_none(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """HK1 miễn 100% (waived=final, paid=0, remaining=0) → 'paid', KHÔNG 'none'."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        await _add_fee(pid, semester_no=1, final="9200000", paid="0",
                       waived="9200000", status=FeeStatusEnum.waived.value)

        resp = await client.get("/api/admissions", headers=admin_token_headers)
        row = _find(resp.json(), pid)
        assert row["tuition_hk1_status"] == "paid"
        assert Decimal(row["tuition_remaining_hk1"]) == Decimal("0")


class TestOverdueFilter:
    async def test_overdue_filter_and_status(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        overdue_pid = await _make_profile(unit_id)
        await _add_fee(
            overdue_pid, semester_no=1, final="1000000", paid="0",
            status=FeeStatusEnum.invoiced.value,
            invoice_status=InvoiceStatusEnum.issued.value,
            invoice_due=date.today() - timedelta(days=3),
        )
        # A non-overdue profile (invoice due in the future) that must be filtered out.
        ok_pid = await _make_profile(unit_id)
        await _add_fee(
            ok_pid, semester_no=1, final="1000000", paid="0",
            status=FeeStatusEnum.invoiced.value,
            invoice_status=InvoiceStatusEnum.issued.value,
            invoice_due=date.today() + timedelta(days=30),
        )

        # status column flags overdue
        resp = await client.get("/api/admissions", headers=admin_token_headers)
        assert _find(resp.json(), overdue_pid)["tuition_overdue_hk1"] is True
        assert _find(resp.json(), overdue_pid)["tuition_hk1_status"] == "overdue"

        # filter returns only the overdue profile
        resp2 = await client.get(
            "/api/admissions?payment_status=overdue", headers=admin_token_headers
        )
        assert resp2.status_code == 200, resp2.text
        ids = {p["id"] for p in resp2.json()["profiles"]}
        assert overdue_pid in ids
        assert ok_pid not in ids

    async def test_overdue_counts_match_list(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """status-counts total with payment_status=overdue == list total_count."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        await _add_fee(
            pid, semester_no=1, final="1000000", paid="0",
            status=FeeStatusEnum.invoiced.value,
            invoice_status=InvoiceStatusEnum.issued.value,
            invoice_due=date.today() - timedelta(days=1),
        )
        list_resp = await client.get(
            "/api/admissions?payment_status=overdue", headers=admin_token_headers
        )
        counts_resp = await client.get(
            "/api/admissions/status-counts?payment_status=overdue", headers=admin_token_headers
        )
        assert list_resp.status_code == 200 and counts_resp.status_code == 200
        assert counts_resp.json()["total"] == list_resp.json()["total_count"]


class TestSortRemainingHk1:
    async def test_sort_desc_with_tiebreaker(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        big = await _make_profile(unit_id)
        await _add_fee(big, semester_no=1, final="9000000", paid="0",
                       status=FeeStatusEnum.invoiced.value)
        small = await _make_profile(unit_id)
        await _add_fee(small, semester_no=1, final="1000000", paid="700000",
                       status=FeeStatusEnum.partial.value)  # remaining 300k

        resp = await client.get(
            "/api/admissions?sort_by=remaining_hk1&order=desc", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        order = [p["id"] for p in resp.json()["profiles"]]
        # big (9M) before small (300k)
        assert order.index(big) < order.index(small)


class TestCoordinationFilters:
    async def test_officer_and_unassigned(
        self, client: AsyncClient, admin_token_headers: dict,
        officer_user_in_db: dict, seed_lead_dependencies: dict
    ):
        unit_id = seed_lead_dependencies["unit_id"]
        officer_id = officer_user_in_db["id"]
        assigned = await _make_profile(unit_id, officer_id=officer_id)
        free = await _make_profile(unit_id, officer_id=None)

        by_officer = await client.get(
            f"/api/admissions?assigned_officer_id={officer_id}", headers=admin_token_headers
        )
        ids = {p["id"] for p in by_officer.json()["profiles"]}
        assert assigned in ids and free not in ids

        unassigned = await client.get(
            "/api/admissions?unassigned=true", headers=admin_token_headers
        )
        ids2 = {p["id"] for p in unassigned.json()["profiles"]}
        assert free in ids2 and assigned not in ids2

    async def test_filter_by_admin_reviewer(
        self, client: AsyncClient, admin_token_headers: dict,
        admin_user_in_db: dict, seed_lead_dependencies: dict
    ):
        """Admin can be assigned_reviewer → filtering by that reviewer returns it."""
        unit_id = seed_lead_dependencies["unit_id"]
        reviewer_id = admin_user_in_db["id"]
        reviewed = await _make_profile(unit_id, reviewer_id=reviewer_id)
        other = await _make_profile(unit_id, reviewer_id=None)

        resp = await client.get(
            f"/api/admissions?assigned_reviewer_id={reviewer_id}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        ids = {p["id"] for p in resp.json()["profiles"]}
        assert reviewed in ids and other not in ids


class TestQueryValidation:
    async def test_non_int_officer_id_400(
        self, client: AsyncClient, admin_token_headers: dict
    ):
        resp = await client.get(
            "/api/admissions?assigned_officer_id=abc", headers=admin_token_headers
        )
        assert resp.status_code == 400, resp.text

    async def test_non_int_reviewer_id_400(
        self, client: AsyncClient, admin_token_headers: dict
    ):
        resp = await client.get(
            "/api/admissions?assigned_reviewer_id=x,y", headers=admin_token_headers
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.parametrize("payment_status", ["paid", "unpaid", "partial", "no_fee", "overdue"])
    async def test_payment_status_accepted(
        self, client: AsyncClient, admin_token_headers: dict, payment_status: str
    ):
        resp = await client.get(
            f"/api/admissions?payment_status={payment_status}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "sort_by", ["created_at", "updated_at", "full_name", "status", "remaining_hk1"]
    )
    async def test_sort_by_accepted(
        self, client: AsyncClient, admin_token_headers: dict, sort_by: str
    ):
        resp = await client.get(
            f"/api/admissions?sort_by={sort_by}", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
