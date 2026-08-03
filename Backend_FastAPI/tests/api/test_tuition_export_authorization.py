"""Authz + route-order cho `GET /api/invoices/export` (PR-A / H1).

Ma trận: admin (wildcard) · accountant · manager → QUA gate; officer · user → 403.

Ca quan trọng nhất là ``test_export_not_shadowed_by_invoice_id``: nếu ai đó dời
khai báo route xuống dưới ``/{invoice_id}`` thì FastAPI ép "export" thành int và
trả **422**, không phải 404 — triệu chứng không ai đoán ra. Cùng bẫy đã có tiền
lệ ở payments.py (/import/batches).
"""

from __future__ import annotations

import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.security import get_password_hash
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import create_user_with_role, get_auth_headers

EXPORT_URL = "/api/invoices/export"
DEBT_EXPORT_URL = "/api/finance/debt-report/export"


@pytest_asyncio.fixture
async def accountant_token_headers(client) -> dict:
    """Accountant + headers (conftest KHÔNG có sẵn fixture này)."""
    try:
        from casbin_async_sqlalchemy_adapter import CasbinRule
    except ImportError:  # pragma: no cover
        CasbinRule = None
    info = await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "acct_export_test",
            "email": "acct_export_test@test.com",
            "password": "AcctPass123!",
            "role": "accountant",
            "status": "active",
        },
        casbin_role="role:accountant",
        unit_id=None,
        models=models,
        get_password_hash=get_password_hash,
        CasbinRule=CasbinRule,
        app=fastapi_app,
    )
    return await get_auth_headers(client, info, AuthURLs.LOGIN)


class TestExportAuthz:
    async def test_officer_denied(self, client, officer_token_headers):
        r = await client.get(EXPORT_URL, headers=officer_token_headers)
        assert r.status_code == 403

    async def test_regular_user_denied(self, client, regular_user_token_headers):
        r = await client.get(EXPORT_URL, headers=regular_user_token_headers)
        assert r.status_code == 403

    async def test_accountant_passes_gate(self, client, accountant_token_headers):
        r = await client.get(EXPORT_URL, headers=accountant_token_headers)
        assert r.status_code != 403, r.text
        assert r.status_code == 200

    async def test_manager_passes_gate(self, client, manager_token_headers):
        r = await client.get(EXPORT_URL, headers=manager_token_headers)
        assert r.status_code != 403, r.text
        assert r.status_code == 200

    async def test_admin_passes_gate(self, client, admin_token_headers):
        r = await client.get(EXPORT_URL, headers=admin_token_headers)
        assert r.status_code == 200, r.text


class TestExportRouteShape:
    async def test_export_not_shadowed_by_invoice_id(
        self, client, admin_token_headers
    ):
        """[N] /export KHÔNG bị /{invoice_id} nuốt.

        Nếu bị nuốt: FastAPI ép "export" thành int → 422. Test này đỏ đúng lúc
        ai đó dời thứ tự khai báo route.
        """
        r = await client.get(EXPORT_URL, headers=admin_token_headers)
        assert r.status_code != 422, "route /export đang bị /{invoice_id} nuốt"

    async def test_invalid_format_rejected(self, client, admin_token_headers):
        r = await client.get(
            EXPORT_URL, params={"format": "pdf"}, headers=admin_token_headers
        )
        assert r.status_code == 422

    async def test_default_format_is_xlsx(self, client, admin_token_headers):
        r = await client.get(EXPORT_URL, headers=admin_token_headers)
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert "danh_sach_khoan_phi_" in r.headers["content-disposition"]

    async def test_csv_format_has_bom(self, client, admin_token_headers):
        r = await client.get(
            EXPORT_URL, params={"format": "csv"}, headers=admin_token_headers
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert r.content.startswith("﻿".encode("utf-8"))


class TestDebtReportExportAuthz:
    """`GET /api/finance/debt-report/export` — quyền qua Casbin THẬT.

    🔴 Route này KHÁC /api/invoices/export: policy sẵn có cho báo cáo công nợ là
    literal '/api/finance/debt-report', thêm một segment là **hết khớp
    keyMatch4** ⇒ không có va chạm nào che, thiếu grant là accountant/manager
    403 thật. Vì vậy phải kiểm bằng request thật qua ASGI, không chỉ test
    service.
    """

    async def test_officer_denied(self, client, officer_token_headers):
        r = await client.get(DEBT_EXPORT_URL, headers=officer_token_headers)
        assert r.status_code == 403

    async def test_regular_user_denied(self, client, regular_user_token_headers):
        r = await client.get(DEBT_EXPORT_URL, headers=regular_user_token_headers)
        assert r.status_code == 403

    async def test_accountant_passes_gate(self, client, accountant_token_headers):
        """[N] Bỏ grant accountant khỏi template là ca này đỏ."""
        r = await client.get(DEBT_EXPORT_URL, headers=accountant_token_headers)
        assert r.status_code != 403, r.text
        assert r.status_code == 200

    async def test_manager_passes_gate(self, client, manager_token_headers):
        r = await client.get(DEBT_EXPORT_URL, headers=manager_token_headers)
        assert r.status_code != 403, r.text
        assert r.status_code == 200

    async def test_admin_passes_gate(self, client, admin_token_headers):
        r = await client.get(DEBT_EXPORT_URL, headers=admin_token_headers)
        assert r.status_code == 200, r.text

    async def test_not_shadowed_by_debt_report_route(
        self, client, admin_token_headers
    ):
        """/debt-report/export không bị /debt-report nuốt (trả JSON thay vì tệp)."""
        r = await client.get(DEBT_EXPORT_URL, headers=admin_token_headers)
        assert r.status_code == 200
        assert "spreadsheetml" in r.headers["content-type"]
        assert "bao_cao_cong_no_" in r.headers["content-disposition"]

    async def test_csv_has_bom_and_vietnamese_header(
        self, client, admin_token_headers
    ):
        r = await client.get(
            DEBT_EXPORT_URL, params={"format": "csv"}, headers=admin_token_headers
        )
        assert r.status_code == 200
        assert r.content.startswith("﻿".encode("utf-8"))
        head_line = r.content.decode("utf-8").splitlines()[0]
        assert "Mã hồ sơ" in head_line
        assert "total_outstanding" not in head_line  # hết khoá kỹ thuật

    async def test_invalid_format_rejected(self, client, admin_token_headers):
        r = await client.get(
            DEBT_EXPORT_URL,
            params={"format": "pdf"},
            headers=admin_token_headers,
        )
        assert r.status_code == 422
