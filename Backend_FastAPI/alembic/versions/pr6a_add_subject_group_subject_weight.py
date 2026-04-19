"""add weight column to subject_group_subject

Revision ID: pr6a_subject_weight
Revises: st20260412001
Create Date: 2026-04-19

PR6 Step 1 — backend contract for per-subject weighted scoring.

Scope: schema-only. Adds `weight` column so `AdmissionCriteria` can express
per-subject coefficients (e.g. Toán x2, Lý x1, Hóa x1). No scoring logic
change in this migration — that's Step 2 (extend _calculate_final_score).

Design decisions (session 2026-04-19):
- Per-subject granularity (not per-group): nghiệp vụ là "Toán nhân 2",
  không phải "tổ hợp A00 nhân 1.2".
- Raw coefficients (not normalized): BA/ops nhập `2` dễ hiểu hơn `0.5`.
- Default 1.0 = no-op: all existing rows backfill to 1.0 so plain sum
  behavior persists until an admin explicitly sets a weight ≠ 1.
- No retroactive backfill: profile snapshots already taken before this
  migration keep their plain-sum applied_rules forever. The weight column
  only starts mattering when a snapshot is regenerated after this lands.

NUMERIC(3,2) range 0.01–9.99: enough room for typical "x2", "x1.5",
"x0.5" multipliers without pretending to need finer precision.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "pr6a_subject_weight"
down_revision = "st20260412001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add weight column with server_default so the NOT NULL constraint
    # holds during the column add for existing rows. The server_default
    # stays on the column definition (per Alembic convention for this
    # codebase); ORM default stays at 1.0 as well.
    op.add_column(
        "subject_group_subject",
        sa.Column(
            "weight",
            sa.Numeric(precision=3, scale=2),
            nullable=False,
            server_default=sa.text("1.0"),
            comment=(
                "Per-subject weight coefficient (raw, not normalized). "
                "Default 1.0 = no weighting (plain sum)."
            ),
        ),
    )

    # Sanity check: coefficient must be positive. Zero-weight subjects
    # are not a sensible configuration; if ops really wants to exclude a
    # subject, they should remove it from the group, not weight-zero it.
    op.create_check_constraint(
        "ck_subject_group_subject_weight_positive",
        "subject_group_subject",
        "weight > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_subject_group_subject_weight_positive",
        "subject_group_subject",
        type_="check",
    )
    op.drop_column("subject_group_subject", "weight")
