"""Tighten Casbin denies for 4 lead static routes — ACCOUNTANT ONLY.

**Idempotent**: safe to re-run; each INSERT is guarded by NOT EXISTS.

Casbin matcher `keyMatch4(r.obj, p.obj)` silently drops the `[regex]`
constraint inside `{token}` (casbin/util/builtin_operators.py:22, 167 —
`KEY_MATCH4_PATTERN = re.compile(r"{([^/]+)}")` then hard-replaces the
captured token with `([^/]+)` regardless of the regex hint). The
existing policy `/api/leads/{id}` therefore admits any 3-segment URL
under `/api/leads/`, including the 4 static routes below. Both officer
and accountant inherited de-facto access to:

  * GET  /api/leads/export
  * POST /api/leads/bulk-assign
  * POST /api/leads/bulk-delete
  * GET  /api/leads/distribution-preview

`AUTHORIZATION_MATRIX.md` says only manager (and admin via wildcard)
should reach these. This migration inserts 4 ACCOUNTANT DENY rows.

Why NOT officer DENY: officer is an inheritance PARENT in the role
tree (admin -> manager -> officer; accountant -> officer). A DENY at
the officer subject propagates UP to manager + admin via Casbin's
`g(r.sub, p.sub)` policy expansion AND DOWN to accountant. Verified
empirically with `test_casbin_lead_static_route_collision.py`
2026-05-23: officer DENY broke 11/16 matrix cells.

Officer's de-facto access is mitigated at the FE layer
(LeadDialog.tsx:285 `enabled: isAdmin || managerUsesDistribution`).
A proper BE fix needs a custom matcher that respects `{token:[regex]}`
constraints — tracked separately per memory
`lead-keymatch4-collision-followup`.

ACCOUNTANT is a LEAF role (only children, no descendants), so DENY at
accountant is contained: accountant gets 403; manager/admin/officer
are untouched. P2 prod audit (2026-05-22) confirmed 0 accountant
traffic on these 4 routes — no user-facing breakage.

Prod baseline verified 2026-05-22:
  * 0 DENY rows for accountant × any of the 4 routes
  * 0 ALLOW rows for accountant × any of the 4 routes
  * Manager has 3 ALLOWs (export, bulk-assign, distribution-preview);
    no /bulk-delete (admin-only by design)
  * No exotic policy on these paths — clean insertion target
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "qa20260522_tighten_lead_denies"
down_revision = "q9_07_e4f"
branch_labels = None
depends_on = None


# (object, action) pairs locked for accountant only. Officer-side
# tightening deferred — see module docstring above.
ACCOUNTANT_DENY_TARGETS = (
    ("/api/leads/export", "GET"),
    ("/api/leads/bulk-assign", "POST"),
    ("/api/leads/bulk-delete", "POST"),
    ("/api/leads/distribution-preview", "GET"),
)


def upgrade() -> None:
    """INSERT 4 accountant DENY rows, idempotent via NOT EXISTS per row.

    Memory `casbin-insert-must-include-eft`: v3 ('deny') MUST be
    present. NULL v3 → load_policy() crashes with "invalid policy
    size" → every enforce() returns 500. The CAST AS VARCHAR on each
    literal mirrors the qae2e01 pattern so asyncpg's bind-parameter
    type inference doesn't surprise us.
    """
    for obj, act in ACCOUNTANT_DENY_TARGETS:
        op.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3)
                SELECT CAST('p' AS VARCHAR), CAST('role:accountant' AS VARCHAR),
                       CAST(:v1 AS VARCHAR), CAST(:v2 AS VARCHAR),
                       CAST('deny' AS VARCHAR)
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p'
                      AND v0 = 'role:accountant'
                      AND v1 = :v1
                      AND v2 = :v2
                      AND v3 = 'deny'
                )
                """
            ).bindparams(v1=obj, v2=act)
        )


def downgrade() -> None:
    """Remove exactly the 4 DENY rows this migration would have inserted.

    Narrow predicate (ptype + v0='role:accountant' + v1 + v2 + v3='deny')
    so we don't accidentally delete an ALLOW row that someone added
    later for the same (route, verb) tuple.
    """
    for obj, act in ACCOUNTANT_DENY_TARGETS:
        op.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = 'role:accountant'
                  AND v1 = :v1
                  AND v2 = :v2
                  AND v3 = 'deny'
                """
            ).bindparams(v1=obj, v2=act)
        )
