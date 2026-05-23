"""Lead static-route Casbin enforce matrix — PR #324 Commit 5.

Pins the 4-route × 4-role × verb matrix for the 4 lead static
endpoints. Without this anchor, a future template edit that drops a
related DENY row (or relaxes keyMatch4 to a stricter matcher) would
silently restore the bypass — first signal would be a downstream Lead
UI bug or a security-team finding, too late.

Architecture context:
    casbin matcher: `m = g(r.sub, p.sub) && keyMatch4(r.obj, p.obj)
                        && regexMatch(r.act, p.act)`
    role tree:       admin -> manager -> officer -> user
                     accountant -> officer

    Key consequence: `g(manager, officer)` and `g(accountant, officer)`
    are BOTH IS-A edges. A DENY at the officer subject would propagate
    UP to manager + admin AND DOWN to accountant via policy expansion.
    Verified empirically 2026-05-23 (officer DENY broke 11/16 cells).
    Officer-level DENY therefore CANNOT be used. The keyMatch4 fix for
    officer-side bypass needs a custom matcher
    (`keyMatchPriority` / `keyMatch4Numeric`) that respects
    `{token:[regex]}` constraints — tracked separately per memory
    `lead-keymatch4-collision-followup`.

Matrix expectations (4 routes × 4 roles = 16 cells):

    admin   ALLOW all 4  (wildcard `/*.*`)
    manager ALLOW 3 (export, bulk-assign, distribution-preview);
            DENY 1 (bulk-delete — no manager allow, admin-only by
            design)
    accountant DENY all 4. GET routes (export, distribution-preview)
            are denied via the EXISTING `/api/leads/{id} GET deny`
            rule (line ~425 in ACCOUNTANT_TEMPLATE) that
            keyMatch4-collides with the static path. The new explicit
            DENY rows added by qa20260522_tighten_lead_denies are
            defence-in-depth — redundant under the current matcher
            but lock the intent if the matcher is ever tightened.
            POST routes (bulk-*) are 403 by no-allow.
    officer ALLOW 2 (export GET, distribution-preview GET — leaked via
            officer's `/api/leads/{id}` GET ALLOW + keyMatch4
            collision). DENY 2 (bulk-assign POST, bulk-delete POST —
            no officer allow for /api/leads POST or /{id} POST).
            KNOWN LIMITATION on the 2 leaks — FE LeadDialog.tsx:285
            gates the UI surface; direct API call still works.

Plus 1 regression test: officer GET /api/leads/123 must STILL succeed
(non-collision numeric ID — verifies we didn't accidentally break the
legitimate /{id} lookup path).
"""
from __future__ import annotations

import os
from pathlib import Path

import casbin
import pytest
from casbin_async_sqlalchemy_adapter import Adapter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.casbin_config.policy_templates import SYSTEM_ROLES, apply_template


pytestmark = pytest.mark.asyncio

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUTH_MODEL_PATH = REPO_BACKEND_ROOT / "auth_model.conf"


# 4 lead static routes + verbs.
ROUTES: tuple[tuple[str, str], ...] = (
    ("/api/leads/export",               "GET"),
    ("/api/leads/bulk-assign",          "POST"),
    ("/api/leads/bulk-delete",          "POST"),
    ("/api/leads/distribution-preview", "GET"),
)


# Expected matrix. True = allow, False = deny.
# Index 0=export GET, 1=bulk-assign POST, 2=bulk-delete POST, 3=distribution-preview GET.
EXPECTED: dict[str, list[bool]] = {
    # Admin wildcard /*. * allows everything.
    "role:admin":      [True,  True,  True,  True],
    # Manager: explicit ALLOW for export/bulk-assign/distribution-preview
    # (policy_templates.py:463-468). No allow for /bulk-delete (admin-only
    # by matrix design) → False on that cell.
    "role:manager":    [True,  True,  False, True],
    # Accountant: ALL DENY.
    #   - GET cells (0, 3): existing `/api/leads/{id} GET deny` rule
    #     in ACCOUNTANT_TEMPLATE collides with /export and
    #     /distribution-preview via keyMatch4 → DENY wins. Commit 5's
    #     new explicit /export GET + /distribution-preview GET denies
    #     are defence-in-depth (redundant under current matcher).
    #   - POST cells (1, 2): no accountant or officer ALLOW for
    #     /api/leads POST or /{id} POST → False by no-allow. Commit 5's
    #     new explicit POST denies are belt-and-suspenders.
    "role:accountant": [False, False, False, False],
    # Officer: GET routes leak via keyMatch4 collision with `/api/leads/{id}`
    # GET ALLOW (officer template line ~119). POST routes have no officer
    # allow → 403 by no-allow.
    # KNOWN LIMITATION — officer GETs /export + /distribution-preview
    # leak; FE LeadDialog.tsx:285 gates the UI but a direct API call
    # still works. Pending custom-matcher security PR.
    "role:officer":    [True,  False, False, True],
}


async def _seed_test_db_and_load_enforcer(
    db_url: str,
    *,
    skip_deny_route: tuple[str, str, str] | None = None,
):
    """Seed casbin_rule with full SYSTEM_ROLES templates + diamond g
    rules, optionally skipping ONE deny row (for bite-verify).
    """
    async_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(async_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE IF NOT EXISTS casbin_rule ("
                "id SERIAL PRIMARY KEY, ptype VARCHAR(255), "
                "v0 VARCHAR(255), v1 VARCHAR(255), v2 VARCHAR(255), "
                "v3 VARCHAR(255), v4 VARCHAR(255), v5 VARCHAR(255))"))
            await conn.execute(text("TRUNCATE casbin_rule RESTART IDENTITY"))

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

            # Diamond g-tree (mirror app/main.py:378-383 — admin→accountant
            # edge dropped 2026-05-15).
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


async def test_lead_static_routes_4role_x_4route_matrix(setup_test_database):
    """16-cell matrix lock. Use ROLE constant order for stable diffs."""
    db_url = os.environ["DATABASE_URL"]
    enforcer, engine = await _seed_test_db_and_load_enforcer(db_url)
    try:
        misses: list[str] = []
        for role, expected_row in EXPECTED.items():
            for idx, (obj, act) in enumerate(ROUTES):
                actual = enforcer.enforce(role, obj, act)
                expected = expected_row[idx]
                if actual != expected:
                    misses.append(
                        f"  {role:<18} {act:<6} {obj:<40} "
                        f"expected={expected} actual={actual}"
                    )
        assert not misses, (
            f"Lead static-route matrix has {len(misses)} mismatch(es):\n"
            + "\n".join(misses)
        )
    finally:
        await engine.dispose()


async def test_officer_can_still_read_lead_by_numeric_id(setup_test_database):
    """Regression guard: the legitimate /api/leads/{id} ALLOW for officer
    must still work for numeric IDs. We only added DENY rows for the
    4 static routes; the existing wildcard allow on `/{id}` is untouched.
    """
    db_url = os.environ["DATABASE_URL"]
    enforcer, engine = await _seed_test_db_and_load_enforcer(db_url)
    try:
        assert enforcer.enforce("role:officer", "/api/leads/123", "GET"), (
            "officer must still be able to GET /api/leads/123 (the legitimate "
            "lead-detail path). If this fails, the DENY rows are over-broad."
        )
        assert enforcer.enforce("role:officer", "/api/leads/123", "PUT"), (
            "officer must still be able to PUT /api/leads/123."
        )
    finally:
        await engine.dispose()


async def test_bite_verify_removing_existing_id_deny_breaks_accountant(
    setup_test_database,
):
    """Bite-verify the load-bearing rule.

    The NEW Commit 5 explicit DENYs on /api/leads/export (etc.) are
    redundant under the current keyMatch4 matcher — the EXISTING
    `/api/leads/{id} GET deny` rule in ACCOUNTANT_TEMPLATE is what
    actually keeps accountant out of /export today (keyMatch4 collides
    /{id} with /export and the deny matches). Pin THAT rule by
    removing it from the seed and asserting accountant flips to ALLOW.

    If a future refactor moves /{id} to a stricter matcher (or drops
    the rule entirely) WITHOUT also adding an explicit accountant DENY
    on /export, this test catches the regression.
    """
    db_url = os.environ["DATABASE_URL"]
    target = ("role:accountant", "/api/leads/{id}", "GET")
    enforcer, engine = await _seed_test_db_and_load_enforcer(
        db_url, skip_deny_route=target
    )
    try:
        # Removing accountant's /{id} GET deny → /export GET via
        # keyMatch4 should also no longer be denied. The new explicit
        # /export DENY (from Commit 5) keeps the cell False — proving
        # Commit 5's defence-in-depth role.
        assert not enforcer.enforce(
            "role:accountant", "/api/leads/export", "GET"
        ), (
            "Belt-and-suspenders contract: the new explicit accountant "
            "DENY on /api/leads/export GET must keep accountant out "
            "even when the /{id} keyMatch4-colliding DENY is missing. "
            "If this returns True, the defence-in-depth has regressed."
        )
        # The genuinely-removed cell (/{id} on a numeric ID) DOES flip
        # to allow — accountant inherits officer's /{id} GET ALLOW.
        assert enforcer.enforce(
            "role:accountant", "/api/leads/123", "GET"
        ), (
            "Bite control: removing accountant's /{id} GET DENY must "
            "let accountant through to /api/leads/123 via inherited "
            "officer ALLOW. If this still denies, something else "
            "blocks accountant (the test isn't probing what we think)."
        )
    finally:
        await engine.dispose()
