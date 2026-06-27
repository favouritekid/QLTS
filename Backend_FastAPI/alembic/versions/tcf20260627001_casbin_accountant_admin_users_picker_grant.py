"""Grant accountant GET /api/admin/users for finance picker filters.

The endpoint intentionally returns the sanitized UserPickerSchema for
non-admin callers. Finance invoice filters need the officer picker, but
accountant did not have a direct runtime Casbin grant, so Chrome smoke hit
403 on /api/admin/users even though the UI route was otherwise accessible.

Revision ID: tcf20260627001
Revises: tcf20260626001
Create Date: 2026-06-27
"""

from alembic import op
from sqlalchemy import text


revision = "tcf20260627001"
down_revision = "tcf20260626001"
branch_labels = None
depends_on = None


_SUBJECT = "role:accountant"
_OBJECT = "/api/admin/users"
_ACTION = "GET"


def upgrade() -> None:
    op.execute(
        text(
            f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
            SELECT 'p', '{_SUBJECT}', '{_OBJECT}', '{_ACTION}', 'allow', 'accountant', NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = '{_SUBJECT}' AND v1 = '{_OBJECT}' AND v2 = '{_ACTION}'
            )
            """
        )
    )
    op.execute(
        text(
            f"""
            UPDATE casbin_rule SET v3 = CAST('allow' AS VARCHAR)
            WHERE ptype = 'p'
              AND v0 = '{_SUBJECT}'
              AND v1 = '{_OBJECT}'
              AND v2 = '{_ACTION}'
              AND v3 IS NULL
            """
        )
    )
    print(f"[tcf20260627001] Seeded {_SUBJECT} {_ACTION} {_OBJECT} (eft=allow)")


def downgrade() -> None:
    op.execute(
        text(
            f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{_SUBJECT}'
              AND v1 = '{_OBJECT}'
              AND v2 = '{_ACTION}'
            """
        )
    )
