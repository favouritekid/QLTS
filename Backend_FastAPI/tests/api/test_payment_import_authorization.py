"""API/Casbin authorization cho route import thu học phí hàng loạt (BV-2).

Matrix (gate = CasbinAuth route-grant + require_finance_staff):
* officer / user  → 403 (không có grant + không phải finance staff)
* accountant / manager / admin → cho qua gate (template GET → 200; preview POST
  với file rỗng → 400, chứng tỏ qua gate chứ không 403)

Grant seed: dev-test auto-seed từ policy_templates.py (ACCOUNTANT/MANAGER template);
prod seed qua migration bvg20260624001. admin có wildcard /* .*.
"""

from __future__ import annotations

import pytest_asyncio

from app import models
from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.security import get_password_hash
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import create_user_with_role, get_auth_headers

# asyncio_mode=auto (pytest.ini) tự nhận async test; KHÔNG đặt pytestmark asyncio
# ở module (sẽ áp nhầm lên test sync test_migration_seeds_eft_v3 → warning).

TEMPLATE_URL = "/api/payments/import/template"
PREVIEW_URL = "/api/payments/import/preview"


@pytest_asyncio.fixture
async def accountant_token_headers(client) -> dict:
    """Accountant user + auth headers (không có fixture sẵn trong conftest)."""
    try:
        from casbin_async_sqlalchemy_adapter import CasbinRule
    except ImportError:  # pragma: no cover
        CasbinRule = None
    info = await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "acct_import_test",
            "email": "acct_import_test@test.com",
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


# ---------------------------------------------------------------------------
# GET /import/template — CSRF-safe (GET), thuần Casbin
# ---------------------------------------------------------------------------
class TestTemplateAuthz:
    async def test_officer_denied(self, client, officer_token_headers):
        r = await client.get(TEMPLATE_URL, headers=officer_token_headers)
        assert r.status_code == 403

    async def test_regular_user_denied(self, client, regular_user_token_headers):
        r = await client.get(TEMPLATE_URL, headers=regular_user_token_headers)
        assert r.status_code == 403

    async def test_accountant_allowed(self, client, accountant_token_headers):
        r = await client.get(TEMPLATE_URL, headers=accountant_token_headers)
        assert r.status_code == 200
        assert "spreadsheet" in r.headers.get("content-type", "")

    async def test_manager_allowed(self, client, manager_token_headers):
        r = await client.get(TEMPLATE_URL, headers=manager_token_headers)
        assert r.status_code == 200

    async def test_admin_allowed(self, client, admin_token_headers):
        # admin qua wildcard /* .*
        r = await client.get(TEMPLATE_URL, headers=admin_token_headers)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /import/preview — CSRF skip trong test env; gate chặn TRƯỚC body
# ---------------------------------------------------------------------------
class TestPreviewAuthz:
    async def test_officer_denied(self, client, officer_token_headers):
        # Gate (dependency) chặn trước khi đọc body → 403 dù có gửi file.
        r = await client.post(
            PREVIEW_URL,
            data={"academic_year": "2026", "semester_no": "1"},
            files={"file": ("t.csv", b"x", "text/csv")},
            headers=officer_token_headers,
        )
        assert r.status_code == 403

    async def test_accountant_passes_gate(self, client, accountant_token_headers):
        # Accountant qua gate → KHÔNG 403. File rỗng → 400 (chứng tỏ body chạy).
        r = await client.post(
            PREVIEW_URL,
            data={"academic_year": "2026", "semester_no": "1"},
            files={"file": ("t.csv", b"", "text/csv")},
            headers=accountant_token_headers,
        )
        assert r.status_code != 403  # qua gate (authz pass)
        assert r.status_code in (400, 422)  # file rỗng → lỗi validate, KHÔNG 403


def test_migration_seeds_eft_v3():
    """Regression guard (bug qae2e02): migration casbin_rule p-row PHẢI ghi v3 (eft).

    auth_model.conf ``p = sub, obj, act, eft`` → row p thiếu v3 bị bỏ khi
    load_policy() / "invalid policy size" → grant vô hiệu trên prod. Test thường
    dùng template-seed (apply_template tự thêm eft) nên KHÔNG bắt được lỗi migration
    → phải kiểm TĨNH nội dung file migration.
    """
    import pathlib

    mig = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "bvg20260624001_casbin_payment_import_grants.py"
    )
    content = mig.read_text(encoding="utf-8")
    assert "v2, v3, template_id" in content  # INSERT có cột v3 (eft)
    assert "'allow'" in content  # giá trị eft
