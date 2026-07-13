"""deny accountant GET /api/leads/my/appointments (separation-of-duties)

Feature "Nhịp hẹn" added `GET /api/leads/my/appointments` granted to
role:officer (migration apptcasbin20260713). Because role:accountant inherits
role:officer (g, role:accountant, role:officer), that single officer allow-row
ALSO reaches accountant → finance staff could read lead name/phone + assigned
officer name from the appointments feed. This breaks the separation-of-duties
contract enforced for every other lead endpoint (see ACCOUNTANT_TEMPLATE deny
block: /api/leads, /api/leads/{id}, export, bulk-*, ...).

Fix: insert an explicit accountant DENY row. Casbin's effect policy
(deny overrides allow) bounces the inherited officer allow → clean 403 at the
Casbin gateway, mirroring the existing /api/leads accountant denies.

Insert WITH v3='deny' — every existing p-row carries an eft; a NULL eft makes
Casbin `load_policy` crash on next reload (memory casbin-insert-must-include-eft).
Idempotent (WHERE NOT EXISTS) so re-runs are safe.

Revision ID: apptacctdeny20260713
Revises: apptcasbin20260713
Create Date: 2026-07-13
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "apptacctdeny20260713"
down_revision = "apptcasbin20260713"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # template_id='_legacy' khớp row officer appointments cùng feature
    # (apptcasbin20260713) → không bị coi orphan bởi logic tracking template.
    op.execute(
        """
        INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
        SELECT 'p', 'role:accountant', '/api/leads/my/appointments', 'GET', 'deny', '_legacy'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:accountant'
              AND v1 = '/api/leads/my/appointments'
              AND v2 = 'GET'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v0 = 'role:accountant'
          AND v1 = '/api/leads/my/appointments'
          AND v2 = 'GET'
          AND v3 = 'deny'
        """
    )
