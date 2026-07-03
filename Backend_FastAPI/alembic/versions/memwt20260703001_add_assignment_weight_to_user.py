"""add_assignment_weight_to_user

Revision ID: memwt20260703001
Revises: smsp2consultcasbin20260702003
Create Date: 2026-07-03 00:00:00.000000

Member-weighted lead assignment: per-officer weight column on ``user``.

    eff_util = workload / (capacity * assignment_weight)

A higher weight makes an officer look "emptier", so the auto-assign balancer
(``assignment_service.automatically_assign_lead`` BƯỚC 5, gated by
``ENABLE_MEMBER_WEIGHTED_ASSIGNMENT``) hands them proportionally more leads.
The safety gate (real utilization >= SAFETY_THRESHOLD) is never bent by weight.

Existing rows get weight 1 via ``server_default='1'`` so deploying this
migration changes NO behavior until an admin raises a weight AND the flag is
flipped. Range 1–100 enforced by a CHECK constraint (DB backstop; the API
also validates at the request layer).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "memwt20260703001"
down_revision: Union[str, Sequence[str], None] = "smsp2consultcasbin20260702003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ``assignment_weight`` (NOT NULL, default 1) + range CHECK to ``user``."""
    op.add_column(
        "user",
        sa.Column(
            "assignment_weight",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="Officer lead-assignment weight (1-100). Higher = more leads.",
        ),
    )
    op.create_check_constraint(
        "ck_user_assignment_weight_range",
        "user",
        "assignment_weight BETWEEN 1 AND 100",
    )


def downgrade() -> None:
    """Drop the CHECK constraint then the column."""
    op.drop_constraint(
        "ck_user_assignment_weight_range", "user", type_="check"
    )
    op.drop_column("user", "assignment_weight")
