"""Drop 4 DEAD accountant Casbin grants (separation-of-duties hardening).

Follow-up to PR #413 (accountant finance scope fix). ACCOUNTANT_TEMPLATE
still granted role:accountant four finance mutation routes that the route
layer gates with RequireManager (= require_admin_or_manager, which EXCLUDES
accountant). The Casbin grant is therefore never consulted — the route
dependency rejects accountant before CasbinAuth runs — so removing it has
ZERO behavioural impact today. It is removed to (a) make the stored policy
reflect the documented separation of duties and (b) close the foot-gun
where flipping any of these routes to CasbinAuth would silently hand
accountant waive / cancel / penalty powers.

Paired with the matching removal from `policy_templates.py` so a future
`sync_casbin_templates.py` run does not re-add them.

Scoped to role:accountant ONLY — manager keeps these grants (it legitimately
passes the RequireManager gate). Idempotent: upgrade deletes only matching
rows, downgrade re-inserts only when absent.

Revision ID: accdead_casbin_20260621
Revises: fincollect_casbin_20260621
Create Date: 2026-06-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "accdead_casbin_20260621"
down_revision: Union[str, None] = "fincollect_casbin_20260621"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (v0=sub, v1=obj, v2=act, v3=eft) — accountant-only; manager rows untouched.
_DEAD_GRANTS = [
    ("role:accountant", "/api/fees/{id}/waive", "POST", "allow"),
    ("role:accountant", "/api/fees/{id}/recalculate", "POST", "allow"),
    ("role:accountant", "/api/invoices/{id}/cancel", "PUT", "allow"),
    ("role:accountant", "/api/invoices/{id}/apply-penalty", "POST", "allow"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _DEAD_GRANTS:
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


def downgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _DEAD_GRANTS:
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
                       '_accdead_casbin_20260621_rollback',
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
