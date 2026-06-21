"""Finance collection workspace ("Thu học phí") Casbin policies.

Seeds the casbin_rule rows for the routes introduced by the collection
workspace PRs (PR1 list redesign + PR2 drawer/queue/badges). The deploy
entrypoint runs `alembic upgrade head` but does NOT run
`scripts/sync_casbin_templates.py`, so without this migration the new
policies added to `policy_templates.py` never reach the prod casbin_rule
table and the enforcer DENIES accountant/manager on the new routes
(admin still works via its wildcard `/*` grant). Symptom: workspace list /
drawer / tab-badge / maker-checker-queue calls return 403 for the very
roles the feature targets.

Mirrors the `policy_templates.py` delta on this branch:
  ACCOUNTANT_TEMPLATE +2, MANAGER_TEMPLATE +5.

Idempotent (WHERE NOT EXISTS) so it is a no-op anywhere the templates were
already hand-synced (e.g. local dev where sync_casbin_templates.py was run).
Stays consistent with the templates, so a future manual sync reconciles to
the same set rather than removing these rows.

Revision ID: fincollect_casbin_20260621
Revises: docdebt01
Create Date: 2026-06-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fincollect_casbin_20260621"
down_revision: Union[str, None] = "docdebt01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (v0=sub, v1=obj, v2=act, v3=eft) — eft MUST be present; a NULL v3 makes
# load_policy() read a 3-field row against the 4-field model and crash 500.
_POLICIES = [
    # ACCOUNTANT — collection workspace drawer + invoice tab badges.
    # (drawer is also gated by require_finance_staff at the route layer.)
    ("role:accountant", "/api/fees/collection/{profile_id}", "GET", "allow"),
    ("role:accountant", "/api/invoices/status-counts", "GET", "allow"),
    # MANAGER — manager is in the FE FINANCE_ROLES but does NOT inherit
    # accountant, so the workspace list + tab badges + drawer + the
    # maker-checker queue read must be granted explicitly or each 403s.
    ("role:manager", "/api/invoices", "GET", "allow"),
    ("role:manager", "/api/invoices/status-counts", "GET", "allow"),
    ("role:manager", "/api/fees/collection/{profile_id}", "GET", "allow"),
    ("role:manager", "/api/payments", "GET", "allow"),
    ("role:manager", "/api/payments/{id}", "GET", "allow"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _POLICIES:
        conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule
                    (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_fincollect_casbin_20260621',
                       NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype='p'
                      AND v0=CAST(:v0 AS VARCHAR)
                      AND v1=CAST(:v1 AS VARCHAR)
                      AND v2=CAST(:v2 AS VARCHAR)
                      AND v3=CAST(:v3 AS VARCHAR)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _POLICIES:
        conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
