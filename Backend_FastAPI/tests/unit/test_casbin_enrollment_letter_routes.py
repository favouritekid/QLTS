"""Casbin policy lock for the 3 enrollment-letter routes.

Non-tautological (memory ``pattern-change-impact-audit``): loads the ACTUAL
templates + an in-memory Casbin enforcer wired with the REAL production diamond
edges (queried from casbin_rule ptype='g'):

    role:admin      -> role:manager
    role:manager    -> role:officer
    role:accountant -> role:officer
    role:officer    -> role:user

There is NO ``role:admin -> role:accountant`` edge in prod, so the accountant
DENY rows do NOT bounce admin — admin reaches ALLOW via admin→manager→officer.

Matrix (3 routes × 5 roles):
    officer     ALLOW  (direct allow rules)
    manager     ALLOW  (inherits officer)
    admin       ALLOW  (inherits manager → officer; NOT accountant)
    accountant  DENY   (explicit deny overrides inherited officer allow)
    user        DENY   (no allow; officer inherits user, not vice-versa)
"""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import casbin
import pytest

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    ADMIN_TEMPLATE,
    MANAGER_TEMPLATE,
    OFFICER_TEMPLATE,
    apply_template,
)

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUTH_MODEL_PATH = REPO_BACKEND_ROOT / "auth_model.conf"

# (object, action) — the template objects keep {id}/{lid} placeholders; the
# enforce() calls below use concrete ids that keyMatch4 collapses per segment.
LETTER_ROUTES = [
    ("/api/admissions/{id}/enrollment-letter", "POST"),
    ("/api/admissions/{id}/enrollment-letter/{lid}/download", "GET"),
    ("/api/admissions/{id}/enrollment-letters", "GET"),
]
CONCRETE_ROUTES = [
    ("/api/admissions/123/enrollment-letter", "POST"),
    ("/api/admissions/123/enrollment-letter/456/download", "GET"),
    ("/api/admissions/123/enrollment-letters", "GET"),
]


# ----------------------------------------------------------------------
# Template-level locks (cheap — no Casbin runtime)
# ----------------------------------------------------------------------


def test_officer_template_has_enrollment_letter_grants():
    """OFFICER_TEMPLATE must carry the 3 enrollment-letter ALLOW rules
    (manager/admin inherit them). Drift guard: rename/remove → fail loud."""
    objects = {
        (r["object"], r["action"])
        for r in apply_template("officer", "role:officer")
    }
    for route in LETTER_ROUTES:
        assert route in objects, f"OFFICER_TEMPLATE missing allow for {route}"


def test_accountant_template_has_enrollment_letter_denies():
    """ACCOUNTANT_TEMPLATE must carry the 3 explicit DENY rows — without them
    accountant would reach the routes via inherited officer allow."""
    deny_objects = {
        (r["object"], r["action"])
        for r in apply_template("accountant", "role:accountant")
        if r.get("eft") == "deny"
    }
    for route in LETTER_ROUTES:
        assert route in deny_objects, f"ACCOUNTANT_TEMPLATE missing deny for {route}"


# ----------------------------------------------------------------------
# Enforce() runtime matrix via in-memory Casbin (real diamond)
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def enforcer():
    """Enforcer with admin+manager+officer+accountant templates + the REAL
    production diamond edges (module-scoped; read-only enforce calls)."""
    lines = []
    for name, tmpl in (
        ("admin", ADMIN_TEMPLATE),
        ("manager", MANAGER_TEMPLATE),
        ("officer", OFFICER_TEMPLATE),
        ("accountant", ACCOUNTANT_TEMPLATE),
    ):
        for r in apply_template(name, f"role:{name}"):
            lines.append(
                f"p, {r['subject']}, {r['object']}, {r['action']}, "
                f"{r.get('eft', 'allow')}"
            )
    # Real diamond (matches casbin_rule ptype='g'); NO admin→accountant.
    lines += [
        "g, role:admin, role:manager",
        "g, role:manager, role:officer",
        "g, role:accountant, role:officer",
        "g, role:officer, role:user",
    ]
    tmp = NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return casbin.Enforcer(str(AUTH_MODEL_PATH), tmp.name)


@pytest.mark.parametrize(
    "role,expected",
    [
        ("role:officer", True),
        ("role:manager", True),
        ("role:admin", True),
        ("role:accountant", False),
        ("role:user", False),
    ],
)
@pytest.mark.parametrize("obj,action", CONCRETE_ROUTES)
def test_enrollment_letter_enforce_matrix(enforcer, role, expected, obj, action):
    """15-cell anchor (3 routes × 5 roles). officer/manager/admin ALLOW;
    accountant DENY (explicit); user DENY (no allow)."""
    result = enforcer.enforce(role, obj, action)
    assert result is expected, (
        f"Casbin enforce drift: ({role}, {obj}, {action}) "
        f"expected {expected}, got {result}"
    )
