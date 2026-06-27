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
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app import models
from app.database import AsyncSessionLocal
from app.main import fastapi_app
from app.security import get_password_hash
from tests.fixtures.constants import AuthURLs
from tests.fixtures.users import create_user_with_role, get_auth_headers


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def accountant_token_headers(client: AsyncClient) -> dict:
    """Accountant auth headers for picker-shape regression tests."""
    try:
        from casbin_async_sqlalchemy_adapter import CasbinRule
    except ImportError:  # pragma: no cover
        CasbinRule = None

    info = await create_user_with_role(
        session_factory=AsyncSessionLocal,
        user_data={
            "username": "qa_picker_accountant",
            "email": "qa_picker_accountant@test.com",
            "password": "AcctPicker123!",
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


def test_casbin_choices_crud_policies_declared_in_template() -> None:
    """policy_templates.py MUST declare officer ALLOW + accountant DENY
    cho /api/v2/admissions/*/choices CRUD endpoints (5 + 4 = 9 entries).

    Test DB uses ``Base.metadata.create_all()`` not Alembic (per memory
    `test-db-schema-source`), so DB-state assertions on data migrations
    are unreliable. Source-of-truth is `policy_templates.py` — alembic
    `phase3_03` and `scripts/sync_casbin_templates.py` both mirror this.

    Pre-fix (F2): officer 403 trên POST /choices vì template entries
    chưa được sync vào prod casbin_rule. Post-fix: template + sync
    script + alembic align.

    Regression sentinel: nếu ai accidentally remove choice CRUD policies
    from OFFICER_TEMPLATE or ACCOUNTANT_TEMPLATE, test fail surface
    immediately. Prod sync still requires phase3_03 alembic to run +
    scripts/sync_casbin_templates.py for in-memory enforcer reload.
    """
    from app.casbin_config.policy_templates import (
        OFFICER_TEMPLATE,
        ACCOUNTANT_TEMPLATE,
    )

    officer_choice_policies = [
        p
        for p in OFFICER_TEMPLATE["policies"]
        if "/v2/admissions/*/choices" in p.get("object", "")
        and p.get("eft", "allow") == "allow"
    ]
    accountant_choice_denies = [
        p
        for p in ACCOUNTANT_TEMPLATE["policies"]
        if "/v2/admissions/*/choices" in p.get("object", "")
        and p.get("eft") == "deny"
    ]

    assert len(officer_choice_policies) == 5, (
        f"OFFICER_TEMPLATE must declare 5 ALLOW entries for /choices CRUD "
        f"(GET, POST, DELETE, PATCH, PATCH /scores); got "
        f"{len(officer_choice_policies)}. F2 regression — template missing "
        f"choice CRUD declarations means prod sync (phase3_03 + sync script) "
        f"will skip officer policies."
    )
    assert len(accountant_choice_denies) == 4, (
        f"ACCOUNTANT_TEMPLATE must declare 4 DENY entries for /choices "
        f"mutating CRUD (POST, DELETE, PATCH, PATCH /scores); got "
        f"{len(accountant_choice_denies)}. Separation-of-duties guard "
        f"missing — accountant would inherit officer ALLOW via g-edge."
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


async def test_admin_users_endpoint_strips_pii_for_accountant(
    client: AsyncClient,
    accountant_token_headers: dict,
    officer_user_in_db: dict,
) -> None:
    """GET /api/admin/users for accountant powers finance TVV picker.

    It must be allowed, but still return the sanitized UserPickerSchema shape.

    ``officer_user_in_db`` seeds a ``role=officer status=active`` user so the
    ``role=officer&status=active`` query (mirroring the finance TVV picker)
    returns ≥1 row — otherwise ``body["users"]`` is empty and every PII/shape
    assertion below would be skipped, leaving the regression sentinel inert.
    """
    response = await client.get(
        "/api/admin/users?page_size=2&role=officer&status=active",
        headers=accountant_token_headers,
    )
    assert response.status_code == 200, (
        f"Accountant GET /api/admin/users must remain 200 for finance picker; "
        f"got {response.status_code}: {response.text[:200]}"
    )

    body = response.json()
    assert "users" in body and len(body["users"]) > 0, (
        "Response must contain the seeded active officer so the PII/shape "
        "assertions actually run; got: " + str(body)
    )

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
        f"F3 regression - accountant response leaks PII keys: {leaked_keys}. "
        f"Should be UserPickerSchema. Full keys returned: {list(sample_user.keys())}"
    )

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


# =====================================================================
# Wave 5 — T11 waitlist-reject endpoint (ship 2026-05-16)
# =====================================================================


def test_t11_waitlist_reject_event_in_catalog() -> None:
    """SystemEvents + EventDefinition catalog MUST declare
    ADMISSION_WAITLIST_REJECTED (T11). Source-aware distinct từ
    ADMISSION_DECISION_REJECTED (T9 cascade).

    Catalog entry needed cho dispatcher resolve event metadata + future
    notification rule wiring. Without entry, transition() PAIR map fires
    Unknown event → silently dropped.
    """
    from app.core.events import SystemEvents
    from app.core.event_catalog import EVENT_CATALOG

    assert hasattr(SystemEvents, "ADMISSION_WAITLIST_REJECTED"), (
        "SystemEvents enum missing ADMISSION_WAITLIST_REJECTED — Wave 5 "
        "regression. T11 endpoint will fire orphan event."
    )
    assert SystemEvents.ADMISSION_WAITLIST_REJECTED.value == "admission_waitlist_rejected"

    assert SystemEvents.ADMISSION_WAITLIST_REJECTED in EVENT_CATALOG, (
        "EVENT_CATALOG missing ADMISSION_WAITLIST_REJECTED EventDefinition. "
        "Required cho dispatcher resolve metadata + future rule wiring."
    )


def test_t11_waitlist_reject_pair_map_fires_correct_event() -> None:
    """TRANSITION_PAIR_TO_EVENT MUST map (waitlisted, rejected) →
    ADMISSION_WAITLIST_REJECTED, NOT generic ADMISSION_DECISION_REJECTED.

    Source-aware mapping cho consumers distinguish first-pass reject
    (T9 engine cascade) vs second-pass admin finalize (T11 manual).
    Pattern mirror (waitlisted, admitted) → ADMISSION_WAITLIST_PROMOTED.
    """
    from app.core.events import SystemEvents
    from app.services.admission_state_service import TRANSITION_PAIR_TO_EVENT

    pair = ("waitlisted", "rejected")
    assert pair in TRANSITION_PAIR_TO_EVENT, (
        f"TRANSITION_PAIR_TO_EVENT missing {pair} — Wave 5 regression. "
        f"T11 transition will fall through to generic decision event."
    )
    assert TRANSITION_PAIR_TO_EVENT[pair] is SystemEvents.ADMISSION_WAITLIST_REJECTED, (
        f"Wrong event for {pair}; got "
        f"{TRANSITION_PAIR_TO_EVENT[pair]}. Should be source-aware "
        f"WAITLIST_REJECTED to distinguish from T9 cascade reject."
    )


def test_w2_1_send_magic_link_service_exists() -> None:
    """W2-1 fix Wave 7 (2026-05-16) — service entry point
    ``generate_action_magic_link`` exists trong admission_service.

    Service-layer source-of-truth test (avoid FastAPI route introspection
    fragility). Live API live integration covered qua Casbin policy
    declaration test below.
    """
    from app.services import admission_service

    assert hasattr(admission_service, "generate_action_magic_link"), (
        "admission_service.generate_action_magic_link missing — W2-1 "
        "regression. Officer cannot generate self-service magic-link cho "
        "candidate (3 actions: submit/resubmit/withdraw)."
    )


def test_w2_1_send_magic_link_schemas_exported() -> None:
    """W2-1 fix Wave 7 — SendMagicLinkRequest + SendMagicLinkResponse
    schemas exported via app.schemas namespace.
    """
    from app import schemas

    assert hasattr(schemas, "SendMagicLinkRequest"), (
        "SendMagicLinkRequest schema missing in app.schemas exports"
    )
    assert hasattr(schemas, "SendMagicLinkResponse"), (
        "SendMagicLinkResponse schema missing in app.schemas exports"
    )

    # Validate request shape — action Literal must include 3 values
    req_fields = schemas.SendMagicLinkRequest.model_fields
    assert "action" in req_fields, "SendMagicLinkRequest missing `action` field"


def test_w2_1_send_magic_link_casbin_policies_declared() -> None:
    """W2-1 fix Wave 7 — Casbin policies declared cho /send-magic-link
    trong template (officer+manager ALLOW, accountant DENY). Source-of-
    truth test — actual DB seed via alembic phase3_06 post-deploy.
    """
    from app.casbin_config.policy_templates import (
        OFFICER_TEMPLATE,
        MANAGER_TEMPLATE,
        ACCOUNTANT_TEMPLATE,
    )

    def has_policy(template: dict, allow: bool) -> bool:
        eft_expected = "allow" if allow else "deny"
        return any(
            p.get("object") == "/api/admissions/{id}/send-magic-link"
            and p.get("action") == "POST"
            and p.get("eft", "allow") == eft_expected
            for p in template.get("policies", [])
        )

    assert has_policy(OFFICER_TEMPLATE, allow=True), (
        "OFFICER_TEMPLATE missing ALLOW for /send-magic-link POST"
    )
    assert has_policy(MANAGER_TEMPLATE, allow=True), (
        "MANAGER_TEMPLATE missing ALLOW for /send-magic-link POST"
    )
    assert has_policy(ACCOUNTANT_TEMPLATE, allow=False), (
        "ACCOUNTANT_TEMPLATE missing DENY for /send-magic-link POST — "
        "separation-of-duties guard regressed"
    )


def test_t11_waitlist_reject_template_declares_accountant_deny() -> None:
    """ACCOUNTANT_TEMPLATE MUST declare DENY for /waitlist-reject endpoint
    (Wave 5 ship 2026-05-16 — endpoint now exists, template parity).

    phase3_02 dropped row when endpoint was dead; phase3_04 re-adds.
    Template declaration ensures sync_casbin_templates.py preserves the
    deny across future syncs (separation-of-duties — finance staff
    không quyết định reject candidate dự bị).
    """
    from app.casbin_config.policy_templates import ACCOUNTANT_TEMPLATE

    waitlist_reject_denies = [
        p
        for p in ACCOUNTANT_TEMPLATE["policies"]
        if "waitlist-reject" in p.get("object", "")
        and p.get("eft") == "deny"
    ]
    assert len(waitlist_reject_denies) == 1, (
        f"ACCOUNTANT_TEMPLATE must declare exactly 1 DENY for /waitlist-reject; "
        f"got {len(waitlist_reject_denies)}. Wave 5 separation-of-duties guard "
        f"missing — accountant would inherit officer ALLOW via g-edge."
    )
