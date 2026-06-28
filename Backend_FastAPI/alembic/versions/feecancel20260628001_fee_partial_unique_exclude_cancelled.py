"""PR-2: fee partial unique indexes exclude cancelled (allow re-calc after cancel)

Narrows the two fee uniqueness partial indexes to ``AND status <> 'cancelled'``:
  * ``uq_fee_profile_type_year_nontuition`` (non-tuition, by academic_year)
  * ``uq_fee_profile_type_semester_tuition`` (tuition, by semester_no)

so a CANCELLED fee (e.g. tính nhầm rồi huỷ qua ``cancel_fee``) no longer reserves
its uniqueness slot — enabling re-calculation of a correct fee without a hard
DELETE. Pairs with ``FeeRepository.check_duplicate`` (also excludes cancelled).

These are partial ``Index(...)`` objects (NOT a UNIQUE constraint), so upgrade
uses ``op.drop_index`` (NOT ``op.drop_constraint``).

Revision ID: feecancel20260628001
Revises: tcf20260627002
Create Date: 2026-06-28

Upgrade safety
--------------
Narrowing the predicate (``WHERE ... AND status <> 'cancelled'``) is a SUBSET of
the existing index population — every slot was already unique, so creating the
narrower unique index cannot collide.

Downgrade safety
----------------
Widening back to include cancelled rows will FAIL if any uniqueness tuple now
has BOTH a cancelled and an active fee (a state this migration intentionally
allows once a fee is re-calculated after cancellation). Resolve such duplicates
(remove/merge the stale cancelled rows) BEFORE downgrading.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "feecancel20260628001"
down_revision = "tcf20260627002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_fee_profile_type_year_nontuition", table_name="fee")
    op.create_index(
        "uq_fee_profile_type_year_nontuition",
        "fee",
        ["admission_profile_id", "fee_type", "academic_year"],
        unique=True,
        postgresql_where=sa.text("fee_type <> 'tuition' AND status <> 'cancelled'"),
    )

    op.drop_index("uq_fee_profile_type_semester_tuition", table_name="fee")
    op.create_index(
        "uq_fee_profile_type_semester_tuition",
        "fee",
        ["admission_profile_id", "fee_type", "semester_no"],
        unique=True,
        postgresql_where=sa.text("fee_type = 'tuition' AND status <> 'cancelled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_fee_profile_type_year_nontuition", table_name="fee")
    op.create_index(
        "uq_fee_profile_type_year_nontuition",
        "fee",
        ["admission_profile_id", "fee_type", "academic_year"],
        unique=True,
        postgresql_where=sa.text("fee_type <> 'tuition'"),
    )

    op.drop_index("uq_fee_profile_type_semester_tuition", table_name="fee")
    op.create_index(
        "uq_fee_profile_type_semester_tuition",
        "fee",
        ["admission_profile_id", "fee_type", "semester_no"],
        unique=True,
        postgresql_where=sa.text("fee_type = 'tuition'"),
    )
