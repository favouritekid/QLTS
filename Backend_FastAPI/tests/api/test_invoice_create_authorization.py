"""Authorization + behaviour for POST /api/invoices (PR-A).

Matrix:
* manager on a fee in their unit              → 201 (create installment)
* officer on the same fee                     → 403 (RequireManager gate)
* manager in a DIFFERENT unit                 → 404 (IDOR convention)
* manager re-creating an ACTIVE installment   → 400 (pre-check duplicate guard)

The concurrent-race path (pre-check passes, the partial-unique index then
rejects the INSERT → DuplicateResourceError → 409) is verified deterministically
at the service layer in
``tests/services/test_invoice_service.py::TestInvoiceRecreateAfterCancelPRA``.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app import models
from app.database import AsyncSessionLocal
from app.models.finance import FeeTypeEnum
from app.services.fee_calculation_service import FeeCalculationService
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import get_auth_headers

pytestmark = pytest.mark.asyncio

INVOICES = "/api/invoices"


def _body(fee_id: int, installment_no: int = 1, amount: int = 900000) -> dict:
    return {
        "fee_id": fee_id,
        "installment_no": installment_no,
        "amount": amount,
        "due_date": (date.today() + timedelta(days=30)).isoformat(),
    }


@pytest_asyncio.fixture
async def invoice_api_fee(seed_lead_dependencies: dict, admin_user_in_db: dict) -> dict:
    """Seed a calculated application fee (900000, single payment) in the default
    unit so POST /api/invoices has a target. Returns {fee_id, unit_id}."""
    unit_id = seed_lead_dependencies["unit_id"]
    async with AsyncSessionLocal() as s:
        lead = models.Lead(
            full_name="Invoice API Student",
            phone="0901330001",
            source="test",
            unit_id=unit_id,
            consultation_status_id=seed_lead_dependencies["initial_status_id"],
        )
        s.add(lead)
        await s.flush()

        profile = models.AdmissionProfile(
            lead_id=lead.id,
            status="submitted",
            academic_year=2025,
            applied_rules={},
        )
        s.add(profile)
        await s.flush()

        fee_service = FeeCalculationService(s)
        fee, _ = await fee_service.calculate_fee(
            admission_profile_id=profile.id,
            fee_type=FeeTypeEnum.application,
            base_amount=Decimal("900000"),
            academic_year=2025,
            user_id=admin_user_in_db["id"],
            unit_id=unit_id,
        )
        await s.commit()
        return {"fee_id": fee.id, "unit_id": unit_id}


class TestCreateInvoiceAuthorization:
    async def test_manager_creates_invoice_201(
        self, client: AsyncClient, manager_token_headers: dict, invoice_api_fee: dict
    ):
        r = await client.post(
            INVOICES, json=_body(invoice_api_fee["fee_id"]),
            headers=manager_token_headers,
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["fee_id"] == invoice_api_fee["fee_id"]
        assert data["installment_no"] == 1
        assert data["status"] == "draft"
        assert Decimal(str(data["amount"])) == Decimal("900000")

    async def test_officer_forbidden_403(
        self, client: AsyncClient, officer_token_headers: dict, invoice_api_fee: dict
    ):
        # RequireManager blocks before any DB work; a real fee_id just proves the
        # only reason for non-201 is the role gate.
        r = await client.post(
            INVOICES, json=_body(invoice_api_fee["fee_id"]),
            headers=officer_token_headers,
        )
        assert r.status_code == 403, r.text

    async def test_cross_unit_manager_404(
        self,
        client: AsyncClient,
        manager_other_unit_user_in_db: dict,
        invoice_api_fee: dict,
    ):
        headers = await get_auth_headers(
            client, manager_other_unit_user_in_db, AuthURLs.LOGIN
        )
        # Manager passes RequireManager but the fee lives in another unit → 404
        # (no existence leak), per the IDOR convention.
        r = await client.post(
            INVOICES, json=_body(invoice_api_fee["fee_id"]), headers=headers
        )
        assert r.status_code == 404, r.text

    async def test_duplicate_active_installment_400(
        self, client: AsyncClient, manager_token_headers: dict, invoice_api_fee: dict
    ):
        body = _body(invoice_api_fee["fee_id"], installment_no=1)
        r1 = await client.post(INVOICES, json=body, headers=manager_token_headers)
        assert r1.status_code == 201, r1.text
        # Sequential duplicate: the active_only pre-check sees the live row and
        # rejects with a domain BadRequest → 400 (the 409 path is the concurrent
        # race backstop, service-tested).
        r2 = await client.post(INVOICES, json=body, headers=manager_token_headers)
        assert r2.status_code == 400, r2.text
