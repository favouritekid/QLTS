"""Anchor tests cho QA E2E findings F1+F5, F2, F3 — 2026-05-16.

Background — Wave 3 fix bundle for issues found via Chrome MCP E2E
testing 2026-05-15 → documented in
`Documents/QA_E2E_FINDINGS_2026-05-15.md`.

3 critical anchors per memory `pattern-change-impact-audit` non-tautological:

  1. **F1+F5** — `applied_rules.admission_round_id` exposed trong API
     response. Pre-fix: AppliedRulesSchema strip 9 keys silently
     (model_config extra="ignore"). Post-fix: 9 keys exposed.
     Regression sentinel: drop key from schema → test fail.

  2. **F2** — Officer Casbin policy `/api/v2/admissions/*/choices`
     present trong DB sau alembic phase3_03. Pre-fix: zero rows for
     officer → 403 PERMISSION_DENIED. Post-fix: 5 ALLOW rows officer
     + 4 DENY rows accountant.

  3. **F3** — Officer/accountant GET /api/admin/users response shape
     uses UserPickerSchema (no PII). Pre-fix: full UserAdminResponse
     leaks email/phone/mfa_enabled. Post-fix: response keys ⊂
     UserPickerSchema fields only.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.database import AsyncSessionLocal


pytestmark = pytest.mark.asyncio


# =====================================================================
# F1+F5 — AppliedRulesSchema exposes 9 previously-stripped keys
# =====================================================================


def test_applied_rules_schema_includes_phase2_round_keys() -> None:
    """AppliedRulesSchema MUST expose 9 keys snapshot từ JSONB:
    admission_round_id, round_code, fee_status, method_quota,
    applicable_to, application_fee, subject_weights,
    bonus_rule_override, requires_application_fee.

    Without these, FE AddChoiceDialog cannot resolve round_id từ
    applied_rules khi profile chưa có NV (E2E #6 root cause).

    Pure schema test — no DB hit. Catches regression nếu ai accidentally
    revert the schema additions OR adds back ConfigDict(extra="ignore")
    without listing fields explicitly.
    """
    from app.schemas.admission import AppliedRulesSchema

    fields = set(AppliedRulesSchema.model_fields.keys())
    required_keys = {
        "admission_round_id",
        "round_code",
        "fee_status",
        "method_quota",
        "applicable_to",
        "application_fee",
        "subject_weights",
        "bonus_rule_override",
        "requires_application_fee",
    }
    missing = required_keys - fields
    assert not missing, (
        f"AppliedRulesSchema missing {missing} — F1+F5 regression. "
        f"These keys MUST surface from JSONB snapshot. Current fields: {fields}"
    )


# =====================================================================
# F2 — Casbin policies seeded for /api/v2/admissions/*/choices
# =====================================================================


async def test_casbin_choices_crud_policies_seeded_for_officer() -> None:
    """alembic phase3_03 MUST seed officer ALLOW + accountant DENY
    cho /api/v2/admissions/*/choices CRUD endpoints (5 + 4 = 9 rows).

    Pre-fix: officer 403 trên POST /choices vì policy chưa seed dù
    template declared. Post-fix: officer can reach endpoint (BE precheck
    handles business rules separately).

    Regression sentinel: nếu sync drift again hoặc alembic rolled back
    without re-seed, test fails surface immediately.
    """
    async with AsyncSessionLocal() as s:
        result = await s.execute(
            text(
                """
                SELECT v0, v2, v3
                FROM casbin_rule
                WHERE ptype='p'
                  AND v1 LIKE '/api/v2/admissions/%/choices%'
                ORDER BY v0, v2, v3
                """
            )
        )
        rows = list(result.all())

    # Expected exactly: 5 officer ALLOW + 4 accountant DENY = 9 rows
    officer_allow_count = sum(
        1 for r in rows if r.v0 == "role:officer" and r.v3 == "allow"
    )
    accountant_deny_count = sum(
        1 for r in rows if r.v0 == "role:accountant" and r.v3 == "deny"
    )

    assert officer_allow_count == 5, (
        f"Officer must have 5 ALLOW rows for /choices CRUD; "
        f"got {officer_allow_count}. F2 regression — phase3_03 may not "
        f"have run OR sync drift again."
    )
    assert accountant_deny_count == 4, (
        f"Accountant must have 4 DENY rows for /choices CRUD; "
        f"got {accountant_deny_count}. F2 regression — separation-of-duties "
        f"guard missing on prod."
    )


# =====================================================================
# F3 — Officer/accountant GET /api/admin/users response shape sanitized
# =====================================================================


async def test_admin_users_endpoint_strips_pii_for_officer(
    client: AsyncClient,
    officer_token_headers: dict,
) -> None:
    """GET /api/admin/users for officer MUST return UserPickerSchema
    shape (no email, phone_number, mfa_enabled, password_reset_required,
    max_capacity).

    Pre-fix: officer received UserAdminResponse với full PII for all 18
    users — security-info exposure (mfa_enabled useful for targeted
    attacks).

    Casbin allow GET cho officer (intentional cho user-picker UI) —
    only response shape narrows. Endpoint URL + 200 status preserved
    for FE compatibility.
    """
    response = await client.get(
        "/api/admin/users?page_size=2",
        headers=officer_token_headers,
    )
    assert response.status_code == 200, (
        f"Officer GET /api/admin/users must remain 200 (Casbin allow "
        f"intentional for user-picker); got {response.status_code}: "
        f"{response.text[:200]}"
    )

    body = response.json()
    assert "users" in body and len(body["users"]) > 0, (
        "Response must contain users list; got: " + str(body)
    )

    # PII keys MUST NOT appear trong officer response
    forbidden_keys = {
        "email",
        "phone_number",
        "mfa_enabled",
        "password_reset_required",
        "max_capacity",
    }
    sample_user = body["users"][0]
    leaked_keys = forbidden_keys & set(sample_user.keys())
    assert not leaked_keys, (
        f"F3 regression — officer response leaks PII keys: {leaked_keys}. "
        f"Should be UserPickerSchema (no PII). Full keys returned: "
        f"{list(sample_user.keys())}"
    )

    # Required UserPickerSchema fields MUST present (positive contract)
    required_keys = {"id", "username", "full_name", "role", "status"}
    missing = required_keys - set(sample_user.keys())
    assert not missing, (
        f"UserPickerSchema missing required fields: {missing}. "
        f"Got: {list(sample_user.keys())}"
    )


async def test_admin_users_endpoint_returns_full_shape_for_admin(
    client: AsyncClient,
    admin_token_headers: dict,
) -> None:
    """GET /api/admin/users for admin MUST return full UserAdminResponse
    shape (with email, phone_number, mfa_enabled — admin needs these
    for security audit + lead-routing context).

    Anchor pair với officer test to catch regression on admin path:
    nếu we accidentally narrow shape cho admin, lead-routing UI breaks.
    """
    response = await client.get(
        "/api/admin/users?page_size=2",
        headers=admin_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["users"]) > 0

    # Admin response MUST include PII fields (Optional[str] — present even
    # if value is None for some users)
    sample_user = body["users"][0]
    expected_admin_keys = {
        "email",  # admin needs for audit
        "phone_number",  # admin needs for contact
        "mfa_enabled",  # admin needs for security review
        "max_capacity",  # admin needs for lead-routing
    }
    missing = expected_admin_keys - set(sample_user.keys())
    assert not missing, (
        f"Admin response missing expected fields: {missing}. "
        f"UserAdminResponse shape regressed. Got: {list(sample_user.keys())}"
    )
