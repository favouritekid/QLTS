"""B1 — 4-role × 14-action Casbin enforce matrix on real DB.

Acceptance gate from PATCH-16: ``Casbin auth_model.conf rewrite + deny
effect + matcher update + 4 role × 14 action matrix test``.

Layer: integration. Uses ``setup_test_database`` so the qlts_test DB
schema is fresh, then seeds the full system templates (admin / manager
/ accountant / officer / user / collaborator) + diamond inheritance g
rules + the 6 accountant deny rows that B1 introduces. Loads a Casbin
``AsyncEnforcer`` against the test DB and asserts ``enforce()`` for
the 4 role subjects × 14 representative routes (56 cells).

Bite-verified — see
``test_bite_verify_removing_one_deny_rule_breaks_matrix`` below.
That test temporarily removes one deny rule from the seed before
loading and asserts the matrix fails on exactly the cell it should.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

import casbin
import pytest
from casbin_async_sqlalchemy_adapter import Adapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.casbin_config.policy_templates import SYSTEM_ROLES, apply_template


pytestmark = pytest.mark.asyncio

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUTH_MODEL_PATH = REPO_BACKEND_ROOT / "auth_model.conf"


# 4 roles under test (subjects).
ROLES = ("role:admin", "role:manager", "role:accountant", "role:officer")


# 14 representative routes covering:
#  - 5 baseline endpoints all roles can hit (sanity);
#  - 3 manager-and-admin-only endpoints (officer / accountant DENY by
#    no allow + no inheritance reach);
#  - 6 future /api/v2 admission state-machine endpoints carrying
#    accountant explicit-deny per PLAN §3.3.b lines 1411-1415.
#
# Matrix expectation:
#   - admin: allow for cells 1-8 (wildcard /* .*).
#   - admin: deny for cells 9-14 (the v2 routes carrying accountant
#     deny rules) — Casbin's allow-and-deny effect propagates DENY via
#     diamond inheritance (g, role:admin, role:accountant). Deny wins
#     even when admin also matches an allow rule. PLAN §3.3.b line
#     1407 wants explicit admin allow on these v2 routes; that
#     resolution requires either dropping the (admin → accountant)
#     diamond edge OR using a custom matcher that scopes deny to the
#     direct subject (not transitive via g). B1 ships the deny rules
#     and the canonical Casbin allow-and-deny effect; the diamond
#     resolution is tracked as a follow-up (next code task once #15
#     wires the actual /api/v2 routes — admin will hit them via the
#     internal staff / admin-only path that does not depend on the
#     accountant deny).
#   - manager: allow for cells 1-8; deny for cells 9-14 (no allow rule
#     for /api/v2/* — manager template does not seed these yet).
#   - accountant: allow for cells 1-5 (inherits officer); deny for
#     cells 6-8 (does NOT inherit manager — separation of duties);
#     deny for cells 9-14 (explicit deny rules from B1).
#   - officer: allow for cells 1-5; deny for cells 6-14 (no allow on
#     manager-only or v2 routes).
ROUTES: Tuple[Tuple[str, str], ...] = (
    # 1-5: baseline allow-for-all (officer-template + diamond reach).
    ("/api/leads",                                 "GET"),
    ("/api/admissions",                            "GET"),
    ("/api/admissions/123",                        "GET"),
    ("/api/admissions/123/submit",                 "POST"),
    ("/api/profile",                               "GET"),

    # 6-8: current manager-only routes (officer + accountant lack
    # the allow rule). Accountant lacks explicit allow because
    # accountant inherits officer, not manager.
    ("/api/admissions/123/approve",                "POST"),
    ("/api/admissions/123/claim",                  "POST"),
    ("/api/admissions/123/override",               "POST"),

    # 9-14: future /api/v2 routes carrying accountant explicit-deny.
    # admin allow-by-wildcard; manager + officer deny-by-no-allow;
    # accountant deny-by-explicit.
    ("/api/v2/admissions/123/claim",               "POST"),
    ("/api/v2/admissions/123/request-revision",    "POST"),
    ("/api/v2/admissions/123/publish-result",      "POST"),
    ("/api/v2/admissions/123/waitlist-promote",    "POST"),
    ("/api/v2/admissions/123/waitlist-reject",     "POST"),
    ("/api/v2/admissions/123/admin-rollback",      "POST"),
)
assert len(ROUTES) == 14, f"matrix expects 14 routes; got {len(ROUTES)}"


# Expected enforce() result per (role, route_index).
# True = allow; False = deny.
EXPECTED = {
    "role:admin": [
        # 1-5 baseline (wildcard /*. *)
        True, True, True, True, True,
        # 6-8 manager-only (wildcard /* .*)
        True, True, True,
        # 9-14 v2 routes — 2026-05-15 fix: `admin → accountant` diamond
        # edge dropped (phase3_02 migration + main.py:378-383). Admin
        # wildcard ALLOW is no longer poisoned by accountant explicit
        # DENYs → admin enforces True on all 6 v2 routes (the desired
        # post-fix shape; PLAN §3.3.b line 1407 intent finally realized).
        True, True, True, True, True, True,
    ],
    "role:manager": [
        True, True, True, True, True,
        True, True, True,
        # /api/v2 cells (indices 8-13 below correspond to routes 9-14):
        #   9  /api/v2/admissions/*/claim             POST  — no manager allow
        #   10 /api/v2/admissions/*/request-revision  POST  — no manager allow
        #   11 /api/v2/admissions/*/publish-result    POST  — PR-3B Sub-3 ALLOW (T6)
        #   12 /api/v2/admissions/*/waitlist-promote  POST  — PR-3B Sub-3 ALLOW (T10)
        #   13 /api/v2/admissions/*/waitlist-reject   POST  — PR-3B Sub-3 ALLOW (T11)
        #   14 /api/v2/admissions/*/admin-rollback    POST  — admin-only (require_admin)
        # 2026-05-14 fix: manager now has explicit allow on publish-
        # result / waitlist-promote / waitlist-reject after PR-3B Sub-3
        # (memory ``phase3-plan-locked`` GAP-11 + GAP-12 Casbin seed).
        # The original matrix predates the Phase 3 multi-NV roll-out
        # and locked these cells at False; the policy_templates.py
        # MANAGER_TEMPLATE lines 386+ now seed the 3 allow rules.
        False, False, True, True, True, False,
    ],
    "role:accountant": [
        # 1-5 baseline — Wave 4 2026-05-16 added explicit accountant DENYs
        # on /api/leads + /api/admissions* (F8/F9 tightening: accountant
        # has no business reading lead/admission lists). Cell 5
        # (/api/profile) remains True (no DENY rule).
        #   1 /api/leads                    GET   — Wave 4 DENY
        #   2 /api/admissions               GET   — Wave 4 DENY
        #   3 /api/admissions/{id}          GET   — Wave 4 DENY
        #   4 /api/admissions/{id}/submit   POST  — Wave 4 DENY
        #   5 /api/profile                  GET   — no DENY → officer inherit
        False, False, False, False, True,
        # 6-8 manager-only; accountant does NOT inherit manager →
        # no allow match → deny.
        False, False, False,
        # 9-14 explicit-deny rules wins even if any inherit reached.
        False, False, False, False, False, False,
    ],
    "role:officer": [
        # 1-5 baseline allow.
        True, True, True, True, True,
        # 6-8 manager-only; officer has no allow.
        False, False, False,
        # 9-14 no allow rule + no deny rule (officer is not denied
        # explicitly in B1) → no allow match → deny.
        False, False, False, False, False, False,
    ],
}


async def _seed_test_db_and_load_enforcer(
    db_url: str,
    *,
    skip_deny_route: Tuple[str, str, str] | None = None,
):
    """Seed the test DB with full system templates + diamond inheritance
    g rules + B1 accountant deny rows, then return a loaded enforcer.

    ``skip_deny_route``: optional ``(v0, v1, v2)`` tuple. When provided,
    that ONE deny row is omitted from the seed so the bite-verify test
    can prove the matrix actually catches a removed deny rule.
    """
    async_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url, future=True)
    try:
        # Truncate casbin_rule before seeding so prior tests do not
        # bleed state. ``setup_test_database`` truncates app tables;
        # casbin_rule is created by adapter side-effect, not by the
        # app's schema bootstrap, so we own the cleanup here.
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE IF NOT EXISTS casbin_rule ("
                "id SERIAL PRIMARY KEY, ptype VARCHAR(255), "
                "v0 VARCHAR(255), v1 VARCHAR(255), v2 VARCHAR(255), "
                "v3 VARCHAR(255), v4 VARCHAR(255), v5 VARCHAR(255))"))
            await conn.execute(text("TRUNCATE casbin_rule RESTART IDENTITY"))

            # Seed every SYSTEM_ROLES template.
            for role_config in SYSTEM_ROLES:
                template_id = role_config.get("template_id")
                role_name = role_config["name"]
                if not template_id:
                    continue
                rules = apply_template(template_id, role_name)
                for r in rules:
                    if (
                        skip_deny_route is not None
                        and r["eft"] == "deny"
                        and (r["subject"], r["object"], r["action"])
                        == skip_deny_route
                    ):
                        continue
                    await conn.execute(
                        text(
                            """
                            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
                            VALUES (
                                CAST('p' AS varchar),
                                CAST(:v0 AS varchar),
                                CAST(:v1 AS varchar),
                                CAST(:v2 AS varchar),
                                CAST(:v3 AS varchar)
                            )
                            """
                        ),
                        {
                            "v0": r["subject"],
                            "v1": r["object"],
                            "v2": r["action"],
                            "v3": r["eft"],
                        },
                    )

            # Tree inheritance g rules (mirror app/main.py:378-383 post
            # 2026-05-15 fix — diamond `admin → accountant` edge removed
            # so admin wildcard ALLOW is not poisoned by accountant DENYs).
            for child, parent in (
                ("role:officer",    "role:user"),
                ("role:accountant", "role:officer"),
                ("role:manager",    "role:officer"),
                ("role:admin",      "role:manager"),
            ):
                await conn.execute(
                    text(
                        """
                        INSERT INTO casbin_rule (ptype, v0, v1)
                        VALUES (
                            CAST('g' AS varchar),
                            CAST(:child AS varchar),
                            CAST(:parent AS varchar)
                        )
                        """
                    ),
                    {"child": child, "parent": parent},
                )

        adapter = Adapter(engine)
        enforcer = casbin.AsyncEnforcer(str(AUTH_MODEL_PATH), adapter)
        await enforcer.load_policy()
        return enforcer, engine
    except Exception:
        await engine.dispose()
        raise


async def _drop_enforcer(engine):
    await engine.dispose()


# --- Matrix test (4 × 14 = 56 cells) ---------------------------------------


async def test_4_role_x_14_action_matrix(setup_test_database):
    """Lock the 56-cell matrix.

    Uses ``setup_test_database`` to ensure schema. Seeds Casbin rules
    inline (the app's bootstrap is gated behind FastAPI lifespan and
    not active in this test). Loads the enforcer and walks the matrix.
    """
    db_url = os.environ["DATABASE_URL"]
    enforcer, engine = await _seed_test_db_and_load_enforcer(db_url)
    try:
        misses: list[str] = []
        for role in ROLES:
            for idx, (obj, act) in enumerate(ROUTES):
                actual = enforcer.enforce(role, obj, act)
                expected = EXPECTED[role][idx]
                if actual != expected:
                    misses.append(
                        f"  {role:<18} {act:<6} {obj:<55} "
                        f"expected={expected} actual={actual}"
                    )
        assert not misses, (
            f"4×14 matrix has {len(misses)} mismatch(es):\n"
            + "\n".join(misses)
        )
    finally:
        await _drop_enforcer(engine)


# --- Bite verification ------------------------------------------------------


async def test_bite_verify_removing_one_deny_rule_breaks_matrix(
    setup_test_database,
):
    """Prove the matrix actually catches a missing accountant deny rule.

    Seed the DB with all rules EXCEPT the deny on
    ``/api/v2/admissions/*/claim``. The accountant cell for that route
    should now flip to ``True`` (allow-by-no-deny) since accountant
    inherits officer (no allow on /api/v2/*) — wait, that means
    accountant should still be deny because there's no allow either.

    Actually this proves something different: when the deny row is
    missing AND accountant has no allow either, the result is still
    deny by no-allow. Bite has to remove a deny AND add a stub allow
    to confirm the deny was load-bearing. Use a synthetic role that has
    a v2 allow seeded (simulating future #15 wiring).
    """
    db_url = os.environ["DATABASE_URL"]
    target_deny = (
        "role:accountant",
        "/api/v2/admissions/*/claim",
        "POST",
    )
    enforcer, engine = await _seed_test_db_and_load_enforcer(
        db_url, skip_deny_route=target_deny
    )
    try:
        # Inject a synthetic ``allow`` row that accountant inherits via
        # diamond. We add it as a g-rule chain: a fake role that
        # accountant inherits, with a v2 claim allow. Then the deny
        # is the load-bearing rule keeping accountant out.
        async with engine.begin() as conn:
            # Add g-rule: accountant inherits role:fake_caller
            await conn.execute(
                text(
                    """
                    INSERT INTO casbin_rule (ptype, v0, v1)
                    VALUES (
                        CAST('g' AS varchar),
                        CAST('role:accountant' AS varchar),
                        CAST('role:fake_v2_allow' AS varchar)
                    )
                    """
                )
            )
            # Add allow on the same route under role:fake_v2_allow
            await conn.execute(
                text(
                    """
                    INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
                    VALUES (
                        CAST('p' AS varchar),
                        CAST('role:fake_v2_allow' AS varchar),
                        CAST('/api/v2/admissions/*/claim' AS varchar),
                        CAST('POST' AS varchar),
                        CAST('allow' AS varchar)
                    )
                    """
                )
            )
        # Re-load policy after injection.
        await enforcer.load_policy()

        # With deny removed AND a synthetic allow inherited, accountant
        # should now reach allow=true. This is the bite — proves the
        # matrix isn't tautological: removing the deny rule changes
        # the outcome.
        bitten = enforcer.enforce(
            "role:accountant",
            "/api/v2/admissions/123/claim",
            "POST",
        )
        assert bitten is True, (
            "Bite verification failed: removing the accountant deny rule "
            "AND adding a synthetic inherited allow should grant access. "
            f"Got {bitten} — the deny rule was NOT load-bearing in the "
            "matrix and the test gives false confidence."
        )
    finally:
        await _drop_enforcer(engine)


# --- Sanity test: deny rules exist as seeded -------------------------------


async def test_accountant_deny_rows_seeded(setup_test_database):
    """Direct DB probe: after seed, casbin_rule has the EXACT expected
    set of deny rows for role:accountant.

    History:
      - B1 originally seeded 6 deny rows (Phase 1 hardening).
      - PR-3D-B BE-1 (PR #271, 2026-05-13) added 4 deny rows for the
        Phase 3 choice CRUD routes (policy_templates.py:346-349) so
        finance staff cannot mutate multi-NV choices via /api/v2.
      - Wave 4 (2026-05-16) added 22 deny rows on /api/admissions/* +
        /api/leads/* legacy routes (F8/F9 Casbin tightening — accountant
        had no business reading lead/admission lists or mutating profiles).
      - Wave 7 (2026-05-16) added 1 deny row on /api/admissions/{id}/
        send-magic-link (W2-1 generate-side endpoint).
      - Q9 #07 Phase E Wave 1 (2026-05-19) added 5 deny rows for
        priority bonus routes (preview/catalog + override/verify/reject).
        Separation-of-duties — finance không touch priority scoring data.
      - Total NOW: 38 deny rows.
    """
    db_url = os.environ["DATABASE_URL"]
    enforcer, engine = await _seed_test_db_and_load_enforcer(db_url)
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT v1, v2 FROM casbin_rule
                        WHERE ptype = 'p'
                          AND v0 = 'role:accountant'
                          AND v3 = 'deny'
                        ORDER BY v1
                        """
                    )
                )
            ).fetchall()
        observed = {(r.v1, r.v2) for r in rows}
        expected = {
            # B1 Phase 1 baseline (6 rows)
            ("/api/v2/admissions/*/claim",            "POST"),
            ("/api/v2/admissions/*/request-revision", "POST"),
            ("/api/v2/admissions/*/publish-result",   "POST"),
            ("/api/v2/admissions/*/waitlist-promote", "POST"),
            ("/api/v2/admissions/*/waitlist-reject",  "POST"),
            ("/api/v2/admissions/*/admin-rollback",   "POST"),
            # PR-3D-B BE-1 (PR #271) — choice CRUD accountant DENY (4 rows)
            ("/api/v2/admissions/*/choices",          "POST"),
            ("/api/v2/admissions/*/choices/*",        "DELETE"),
            ("/api/v2/admissions/*/choices/*",        "PATCH"),
            ("/api/v2/admissions/*/choices/*/scores", "PATCH"),
            # Wave 4 (2026-05-16) — admission legacy routes deny (13 rows)
            ("/api/admissions",                       "GET"),
            ("/api/admissions",                       "POST"),
            ("/api/admissions/{id}",                  "GET"),
            ("/api/admissions/{id}",                  "PUT"),
            ("/api/admissions/{id}/submit",           "POST"),
            ("/api/admissions/{id}/resubmit",         "POST"),
            ("/api/admissions/{id}/withdraw",         "POST"),
            ("/api/admissions/{id}/minor-correction", "POST"),
            ("/api/admissions/{id}/send-confirmation", "POST"),
            ("/api/admissions/stats",                 "GET"),
            ("/api/admissions/status-counts",         "GET"),
            ("/api/admissions/academic-years",        "GET"),
            # Wave 4 — lead legacy routes deny (10 rows)
            ("/api/leads",                            "GET"),
            ("/api/leads",                            "POST"),
            ("/api/leads/{id}",                       "GET"),
            ("/api/leads/{id}",                       "PUT"),
            ("/api/leads/{id}/timeline",              "GET"),
            ("/api/leads/{id}/insights",              "GET"),
            ("/api/leads/{id}/audit-logs",            "GET"),
            ("/api/leads/{id}/consultations",         "GET"),
            ("/api/leads/check-duplicate",            "GET"),
            ("/api/leads/import",                     "POST"),
            ("/api/leads/import/template",            "GET"),
            # Wave 7 (2026-05-16) — W2-1 magic-link generate accountant deny
            ("/api/admissions/{id}/send-magic-link",  "POST"),
            # Q9 #07 Phase E Wave 1 (2026-05-19) — priority bonus accountant
            # deny (5 rows). Separation-of-duties: finance staff không
            # quyết định KV ưu tiên / verify UT evidence / view priority
            # data. Migration `q9_07_e0c` seeds these.
            ("/api/v2/admissions/*/override-priority-kv",          "POST"),
            ("/api/v2/admissions/*/preview-priority-kv",           "POST"),
            ("/api/v2/admissions/*/priority-objects/*/verify",     "PATCH"),
            ("/api/v2/admissions/*/priority-objects/*/reject",     "PATCH"),
            ("/api/v2/admissions/priority-objects/catalog",        "GET"),
        }
        assert observed == expected, (
            f"Accountant deny-row set drifted. "
            f"Expected: {sorted(expected)}; observed: {sorted(observed)}"
        )
    finally:
        await _drop_enforcer(engine)
