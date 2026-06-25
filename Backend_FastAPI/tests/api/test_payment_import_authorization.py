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
COMMIT_URL = "/api/payments/import/{}/commit"
VOID_URL = "/api/payments/import/{}/void"
BATCHES_URL = "/api/payments/import/batches"


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


# ---------------------------------------------------------------------------
# POST /import/{id}/commit (ghi tiền) — BV-3 dual-gate
# ---------------------------------------------------------------------------
class TestCommitAuthz:
    async def test_officer_denied(self, client, officer_token_headers):
        r = await client.post(COMMIT_URL.format(999999), headers=officer_token_headers)
        assert r.status_code == 403

    async def test_accountant_passes_gate(self, client, accountant_token_headers):
        # qua gate → commit lô không tồn tại → 404 (KHÔNG 403)
        r = await client.post(
            COMMIT_URL.format(999999), headers=accountant_token_headers
        )
        assert r.status_code != 403
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /import/batches (lịch sử) — BV-3 dual-gate
# ---------------------------------------------------------------------------
class TestBatchesAuthz:
    async def test_officer_denied(self, client, officer_token_headers):
        r = await client.get(BATCHES_URL, headers=officer_token_headers)
        assert r.status_code == 403

    async def test_accountant_allowed(self, client, accountant_token_headers):
        r = await client.get(BATCHES_URL, headers=accountant_token_headers)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /import/{id}/void (đảo lô) — BV-3.5: manager/admin ONLY (accountant DENY)
# ---------------------------------------------------------------------------
class TestVoidAuthz:
    _BODY = {"reason": "đảo lô do nhập sai"}

    async def test_officer_denied(self, client, officer_token_headers):
        r = await client.post(
            VOID_URL.format(999999), json=self._BODY, headers=officer_token_headers
        )
        assert r.status_code == 403

    async def test_accountant_denied(self, client, accountant_token_headers):
        # KHÁC commit/batches: accountant là finance staff NHƯNG void = manager/admin
        # → accountant PHẢI bị từ chối (Casbin không grant + require_admin_or_manager).
        r = await client.post(
            VOID_URL.format(999999), json=self._BODY, headers=accountant_token_headers
        )
        assert r.status_code == 403

    async def test_manager_passes_gate(self, client, manager_token_headers):
        r = await client.post(
            VOID_URL.format(999999), json=self._BODY, headers=manager_token_headers
        )
        assert r.status_code != 403  # qua gate
        assert r.status_code == 404  # lô không tồn tại

    async def test_admin_passes_gate(self, client, admin_token_headers):
        r = await client.post(
            VOID_URL.format(999999), json=self._BODY, headers=admin_token_headers
        )
        assert r.status_code != 403
        assert r.status_code == 404


def test_casbin_migrations_seed_eft_v3():
    """Regression guard (qae2e02): migration casbin_rule p-row PHẢI có v3 (eft).

    auth_model.conf ``p = sub, obj, act, eft`` → row p thiếu v3 bị bỏ khi
    load_policy() / "invalid policy size" → grant vô hiệu trên prod. Test thường
    dùng template-seed (apply_template tự thêm eft) nên KHÔNG bắt được lỗi migration
    → phải kiểm TĨNH nội dung file migration.
    """
    import pathlib

    versions = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for name in (
        "bvg20260624001_casbin_payment_import_grants.py",
        "bvh20260624001_casbin_payment_import_commit_grants.py",
        "bvj20260625001_casbin_payment_import_void_grant.py",
        "bvk20260626001_casbin_payment_import_read_grants.py",
    ):
        content = (versions / name).read_text(encoding="utf-8")
        assert "v2, v3, template_id" in content, f"{name} thiếu cột v3 (eft)"
        assert "'allow'" in content, f"{name} thiếu giá trị eft 'allow'"


# Route mới BV-5 R2/R1: chi tiết lô (per-row) + tải file kết quả. Đường con
# "/batches/{id}" → KHÔNG nuốt route danh sách "/batches".
DETAIL_URL = "/api/payments/import/batches/999999"
RESULT_URL = "/api/payments/import/batches/999999/result"


class TestBatchDetailAndResultAuthz:
    async def test_batches_list_still_200_not_shadowed(
        self, client, accountant_token_headers
    ):
        # 🔴 P2 regression: detail "/batches/{id}" KHÔNG shadow list "/batches" → 200 (≠ 422).
        r = await client.get(BATCHES_URL, headers=accountant_token_headers)
        assert r.status_code == 200

    async def test_detail_officer_denied(self, client, officer_token_headers):
        r = await client.get(DETAIL_URL, headers=officer_token_headers)
        assert r.status_code == 403

    async def test_detail_regular_user_denied(
        self, client, regular_user_token_headers
    ):
        r = await client.get(DETAIL_URL, headers=regular_user_token_headers)
        assert r.status_code == 403

    async def test_detail_accountant_passes_gate(
        self, client, accountant_token_headers
    ):
        # Qua Casbin → lô không tồn tại → 404 (KHÔNG 403, KHÔNG 422 route-order).
        r = await client.get(DETAIL_URL, headers=accountant_token_headers)
        assert r.status_code == 404

    async def test_detail_manager_passes_gate(self, client, manager_token_headers):
        r = await client.get(DETAIL_URL, headers=manager_token_headers)
        assert r.status_code == 404

    async def test_result_officer_denied(self, client, officer_token_headers):
        r = await client.get(RESULT_URL, headers=officer_token_headers)
        assert r.status_code == 403

    async def test_result_accountant_passes_gate(
        self, client, accountant_token_headers
    ):
        r = await client.get(RESULT_URL, headers=accountant_token_headers)
        assert r.status_code == 404


class TestBatchDetailContent:
    async def test_detail_returns_rows_no_missing_greenlet(
        self, client, admin_token_headers
    ):
        # 🐞 Regression: serialize PaymentImportBatchDetailOut KHÔNG được đọc batch.rows
        # (relationship lazy, chưa load) → MissingGreenlet → 500. Build từ summary.
        from decimal import Decimal

        from app.models.finance import PaymentImportBatch, PaymentImportRow

        async with AsyncSessionLocal() as db:
            batch = PaymentImportBatch(
                academic_year=2026,
                semester_no=1,
                file_name="reg.xlsx",
                file_sha256="sha-regression-detail-greenlet",
                status="committed",
                row_count=1,
                matched_count=1,
                warned_count=0,
                failed_count=0,
                total_amount=Decimal("1000000"),
                created_by_id=None,
            )
            db.add(batch)
            await db.flush()
            db.add(
                PaymentImportRow(
                    batch_id=batch.id,
                    row_no=2,
                    citizen_id="001234567890",
                    raw={"Số CCCD": "001234567890"},
                    status="matched",
                    amount=Decimal("1000000"),
                    message="ok",
                    payment_ids=[1],
                )
            )
            await db.commit()
            bid = batch.id

        r = await client.get(
            f"/api/payments/import/batches/{bid}", headers=admin_token_headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == bid
        assert len(body["rows"]) == 1
        assert body["rows"][0]["row_no"] == 2
        assert body["rows"][0]["citizen_id"] == "001234567890"
