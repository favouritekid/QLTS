"""Phase 3 PR-3B Sub-3 — Casbin policy lock for multi-NV transition routes.

Tests the NEW allow rules on OFFICER + MANAGER templates that ship with
Sub-3, anchored against memory `pattern-change-impact-audit` to be
non-tautological: load the actual templates + in-memory Casbin enforcer +
assert enforce() decisions per (role, route, action) cell.

Routes under test (5 total):
- ``/api/v2/admissions/*/publish-result``   POST  — T6 manager allow
- ``/api/v2/admissions/*/waitlist-promote`` POST  — T10 manager allow
- ``/api/v2/admissions/*/waitlist-reject``  POST  — T11 manager allow
- ``/api/v2/admissions/*/choices``          GET   — officer + manager allow (read)
- ``/api/v2/admissions/*/publish-result``   GET   — officer + manager allow (read)

T17 ``/api/v2/admissions/*/admin-rollback`` POST is admin-only via
``require_admin`` dependency (FastAPI layer, NOT Casbin) — admin would be
denied here at Casbin level via diamond inheritance of accountant deny
(documented in ``test_casbin_b1_4x14_matrix.py:108-117``).

Accountant DENY rules from Phase 1 B1 (lines 319-324 in policy_templates)
still apply: accountant explicitly denied on these v2 routes.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import casbin
import pytest

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    MANAGER_TEMPLATE,
    OFFICER_TEMPLATE,
    apply_template,
)


REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUTH_MODEL_PATH = REPO_BACKEND_ROOT / "auth_model.conf"


# Routes (object, action) parametrized for matrix
ROUTE_PUBLISH_POST = ("/api/v2/admissions/123/publish-result", "POST")
ROUTE_PROMOTE_POST = ("/api/v2/admissions/123/waitlist-promote", "POST")
ROUTE_REJECT_POST = ("/api/v2/admissions/123/waitlist-reject", "POST")
ROUTE_CHOICES_GET = ("/api/v2/admissions/123/choices", "GET")
ROUTE_PUBLISH_GET = ("/api/v2/admissions/123/publish-result", "GET")


# ----------------------------------------------------------------------
# Template-level locks (cheap — no Casbin runtime)
# ----------------------------------------------------------------------


def test_manager_template_has_phase3_write_rules():
    """MANAGER_TEMPLATE must contain 3 NEW Phase 3 POST allow rules.

    Drift guard: if any rule renamed/removed without updating this
    test, fail loud — runtime enforce() would silently degrade.
    """
    rules = apply_template("manager", "role:manager")
    objects = {(r["object"], r["action"]) for r in rules}
    assert ("/api/v2/admissions/*/publish-result", "POST") in objects
    assert ("/api/v2/admissions/*/waitlist-promote", "POST") in objects
    assert ("/api/v2/admissions/*/waitlist-reject", "POST") in objects


def test_officer_template_has_phase3_read_rules():
    """OFFICER_TEMPLATE must contain 2 NEW Phase 3 GET allow rules
    (read-only view of choices + publish-result).
    """
    rules = apply_template("officer", "role:officer")
    objects = {(r["object"], r["action"]) for r in rules}
    assert ("/api/v2/admissions/*/choices", "GET") in objects
    assert ("/api/v2/admissions/*/publish-result", "GET") in objects


def test_accountant_phase3_deny_rules_still_present():
    """Phase 1 B1 accountant DENY rules MUST stay intact — Sub-3 only
    ADDS allow rules, never removes the deny side.
    """
    rules = apply_template("accountant", "role:accountant")
    deny_objects = {
        (r["object"], r["action"]) for r in rules if r.get("eft") == "deny"
    }
    assert ("/api/v2/admissions/*/publish-result", "POST") in deny_objects
    assert ("/api/v2/admissions/*/waitlist-promote", "POST") in deny_objects
    assert ("/api/v2/admissions/*/waitlist-reject", "POST") in deny_objects
    assert ("/api/v2/admissions/*/admin-rollback", "POST") in deny_objects


def test_phase3_routes_not_in_admin_template():
    """ADMIN_TEMPLATE uses wildcard `/* .*` — must NOT have explicit
    Phase 3 route entries (would be redundant). Admin routes are
    handled via `require_admin` FastAPI dependency, NOT Casbin allow.
    """
    rules = apply_template("admin", "role:admin")
    # Admin wildcard rule is the canonical entry
    admin_rules = [(r["object"], r["action"]) for r in rules]
    assert ("/*", ".*") in admin_rules
    # No explicit Phase 3 v2 route allow rule (would be redundant noise)
    phase3_explicit = [
        (obj, act) for obj, act in admin_rules
        if obj.startswith("/api/v2/admissions/") and act in ("POST", "GET")
    ]
    assert phase3_explicit == [], (
        f"Admin template should rely on wildcard `/*` for Phase 3 routes; "
        f"found explicit entries: {phase3_explicit}"
    )


# ----------------------------------------------------------------------
# Enforce() runtime check via in-memory Casbin (manager + officer)
# ----------------------------------------------------------------------


def _build_enforcer_from_templates(roles_to_seed):
    """Build a Casbin Enforcer with policy + g rules loaded inline.

    Uses file model + StringAdapter via temp .csv to seed both p (policy)
    rules + g (grouping) rules so diamond inheritance applies.
    """
    # Build policy file content (CSV format: p, sub, obj, act, eft)
    lines = []
    for template_name, template_dict in roles_to_seed.items():
        role_subject = f"role:{template_name}"
        rules = apply_template(template_name, role_subject)
        for r in rules:
            eft = r.get("eft", "allow")
            lines.append(f"p, {r['subject']}, {r['object']}, {r['action']}, {eft}")

    # Diamond inheritance per Phase 1 B1 (admin → manager → officer; admin →
    # accountant → officer). Add only edges relevant to roles seeded.
    # For this test seed manager + officer + accountant — manager inherits
    # officer per the diamond.
    if "manager" in roles_to_seed and "officer" in roles_to_seed:
        lines.append("g, role:manager, role:officer")
    if "accountant" in roles_to_seed and "officer" in roles_to_seed:
        lines.append("g, role:accountant, role:officer")

    policy_text = "\n".join(lines) + "\n"
    tmp_policy = NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    tmp_policy.write(policy_text)
    tmp_policy.close()

    enforcer = casbin.Enforcer(str(AUTH_MODEL_PATH), tmp_policy.name)
    return enforcer


@pytest.fixture
def enforcer():
    """Enforcer loaded with manager + officer + accountant templates."""
    roles = {
        "manager": MANAGER_TEMPLATE,
        "officer": OFFICER_TEMPLATE,
        "accountant": ACCOUNTANT_TEMPLATE,
    }
    return _build_enforcer_from_templates(roles)


@pytest.mark.parametrize(
    "role,route,expected",
    [
        # Manager allow on 3 POST routes (T6/T10/T11)
        ("role:manager", ROUTE_PUBLISH_POST, True),
        ("role:manager", ROUTE_PROMOTE_POST, True),
        ("role:manager", ROUTE_REJECT_POST, True),
        # Manager inherits officer GET reads
        ("role:manager", ROUTE_CHOICES_GET, True),
        ("role:manager", ROUTE_PUBLISH_GET, True),
        # Officer denied on POST (no allow rule, no inheritance reach)
        ("role:officer", ROUTE_PUBLISH_POST, False),
        ("role:officer", ROUTE_PROMOTE_POST, False),
        ("role:officer", ROUTE_REJECT_POST, False),
        # Officer allow on GET reads (NEW)
        ("role:officer", ROUTE_CHOICES_GET, True),
        ("role:officer", ROUTE_PUBLISH_GET, True),
        # Accountant explicit DENY on 3 POST routes (Phase 1 B1)
        ("role:accountant", ROUTE_PUBLISH_POST, False),
        ("role:accountant", ROUTE_PROMOTE_POST, False),
        ("role:accountant", ROUTE_REJECT_POST, False),
        # Accountant inherits officer GET reads (per diamond)
        ("role:accountant", ROUTE_CHOICES_GET, True),
        ("role:accountant", ROUTE_PUBLISH_GET, True),
    ],
)
def test_phase3_route_enforce_matrix(enforcer, role, route, expected):
    """Anchor matrix: 3 roles × 5 routes = 15 cells covering
    Phase 3 multi-NV transitions + reads.

    Manager: 3 POST allow + 2 GET inherit allow = 5 True
    Officer: 3 POST deny (no allow) + 2 GET allow = 3 True / 2 False inverted → 2 True / 3 False
    Accountant: 3 POST explicit deny + 2 GET inherit allow = 2 True / 3 False
    """
    obj, action = route
    result = enforcer.enforce(role, obj, action)
    assert result is expected, (
        f"Casbin enforce drift: ({role}, {obj}, {action}) expected "
        f"{expected}, got {result}"
    )
