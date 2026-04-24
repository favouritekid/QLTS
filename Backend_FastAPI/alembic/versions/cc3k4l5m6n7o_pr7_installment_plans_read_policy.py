"""PR #7 review: seed Casbin read policy for /api/installment-plans

Revision ID: cc3k4l5m6n7o
Revises: bb2j3k4l5m6n
Create Date: 2026-04-24

The CalculateFeeDialog (PR #7) populates its installment-plan Select
from GET /api/installment-plans so the UI reflects the real seed
(FULL / TWO_TERM / QUARTERLY) instead of hard-coded codes. That
route was only admitted to admin via the wildcard row; officer,
manager, and accountant all received 403, so a non-admin opening the
dialog saw an empty plan list and a permanently disabled submit
button.

Seed the read policy for role:officer (and /{plan_id} detail) so
manager/accountant inherit via the diamond, and admin stays covered
by its /* wildcard.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "cc3k4l5m6n7o"
down_revision: Union[str, None] = "bb2j3k4l5m6n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_POLICIES = [
    ("role:officer", "/api/installment-plans", "GET"),
    ("role:officer", "/api/installment-plans/{plan_id}", "GET"),
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
