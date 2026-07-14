"""add casbin policy: officer GET /api/leads/my/appointments

Feature "Nhịp hẹn" (Trợ lý nhắc hẹn) added `GET /api/leads/my/appointments`
gated by CasbinAuth, but the matching officer policy was never added → officers
(the intended users) got 403 PERMISSION_DENIED. role:manager / role:accountant
inherit role:officer via g-policies, so this single officer row covers them;
role:admin already has broad access.

Insert WITH v3='allow' — every existing p-row carries an eft; a NULL eft makes
Casbin `load_policy` crash on next reload (see memory casbin-insert-must-include-eft).
Idempotent (WHERE NOT EXISTS) so re-runs are safe.

Revision ID: apptcasbin20260713
Revises: refundsrc20260711
Create Date: 2026-07-13
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "apptcasbin20260713"
down_revision = "refundsrc20260711"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # template_id='_legacy' khớp các row role:officer hiện có (core OFFICER_TEMPLATE)
    # → row mới không bị logic quản-lý-template coi là orphan.
    op.execute(
        """
        INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
        SELECT 'p', 'role:officer', '/api/leads/my/appointments', 'GET', 'allow', '_legacy'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:officer'
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
          AND v0 = 'role:officer'
          AND v1 = '/api/leads/my/appointments'
          AND v2 = 'GET'
        """
    )
