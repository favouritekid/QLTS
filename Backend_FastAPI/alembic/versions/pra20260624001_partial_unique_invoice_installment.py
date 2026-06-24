"""PR-A: partial unique index on invoice (fee_id, installment_no) excluding cancelled

Replaces the hard UNIQUE constraint ``uq_invoice_fee_installment`` with a partial
unique index ``uq_invoice_fee_installment_active`` (``WHERE status <> 'cancelled'``)
so a cancelled invoice no longer reserves the installment slot — enabling
re-creation of an installment after cancellation (PR-A).

Revision ID: pra20260624001
Revises: feepicker_casbin_20260621
Create Date: 2026-06-24

Downgrade safety
----------------
Recreating the old UNIQUE constraint will FAIL if any ``(fee_id, installment_no)``
pair now has BOTH a cancelled and an active row — a state PR-A intentionally
allows once an installment is re-created after cancellation. Such duplicates
must be resolved (merge/remove the stale cancelled rows) BEFORE downgrading.
The migration is otherwise idempotent at the DDL level.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "pra20260624001"
down_revision = "feepicker_casbin_20260621"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_invoice_fee_installment", "invoice", type_="unique")
    op.create_index(
        "uq_invoice_fee_installment_active",
        "invoice",
        ["fee_id", "installment_no"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )


def downgrade() -> None:
    op.drop_index("uq_invoice_fee_installment_active", table_name="invoice")
    op.create_unique_constraint(
        "uq_invoice_fee_installment",
        "invoice",
        ["fee_id", "installment_no"],
    )
