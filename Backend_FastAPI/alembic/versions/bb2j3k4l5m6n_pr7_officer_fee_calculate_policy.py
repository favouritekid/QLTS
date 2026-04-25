"""PR #7: seed Casbin policy for officer POST /api/fees/calculate

Revision ID: bb2j3k4l5m6n
Revises: aa1i2j3k4l5m
Create Date: 2026-04-24

Before PR #7, only admin/manager/accountant could hit
``POST /api/fees/calculate``. PR #7 moves the officially-approved-fee
creation into the admission detail page so an officer can calculate
tuition for their own assigned profile without handing off to finance.
Router-level ``_fee_calc_authorized`` + admission_service
``_compute_permissions['calculate_fee']`` keep the per-profile scope
tight (officer must own the assignment + unit); this migration just
adds the role-level gate that Casbin needs to admit the route.

Admin wildcard row covers admin already, so only the officer entry
is seeded. Manager/accountant were already covered via their
finance templates.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "bb2j3k4l5m6n"
down_revision: Union[str, None] = "aa1i2j3k4l5m"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_POLICIES = [
    ("role:officer", "/api/fees/calculate", "POST"),
]


def upgrade() -> None:
    for subject, obj, action in NEW_POLICIES:
        op.execute(
            f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', '{subject}', '{obj}', '{action}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = '{subject}'
                  AND v1 = '{obj}'
                  AND v2 = '{action}'
            )
            """
        )


def downgrade() -> None:
    for subject, obj, action in NEW_POLICIES:
        op.execute(
            f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{subject}'
              AND v1 = '{obj}'
              AND v2 = '{action}'
            """
        )
