"""Add ``refund_request.source`` — distinguish withdrawal-auto-filed refunds.

Issue 2 (PR-B follow-up). ``cancel_withdrawal``/rollback previously rejected
EVERY open (pending/approved) refund on a profile via
``reject_open_refunds_for_profile``, indiscriminately killing a pre-existing
manual (finance-created) or overpayment refund that had nothing to do with the
withdrawal. This adds a structured ``source`` so the rollback can target only
``source='withdrawal'`` refunds.

Additive column:
* ``source VARCHAR(20) NOT NULL DEFAULT 'manual'`` + CHECK
  (``withdrawal``|``manual``|``overpayment``) + index.

Backfill: existing rows are reclassified best-effort from their ``reason`` text
(the only prior discriminator) — the withdraw orchestrator wrote
``"Rút hồ sơ #<id>"`` and overpayment refunds ``"Refund overpayment <id>"``.
Everything else stays ``manual``. Terminal (rejected/refunded) rows are
reclassified too for reporting consistency; it is harmless as the rollback only
inspects pending/approved.

Revision ID: refundsrc20260711
Revises: wpend20260710
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "refundsrc20260711"
down_revision: Union[str, None] = "wpend20260710"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "refund_request"
COLUMN = "source"
CHECK_NAME = "chk_refund_request_source_valid"
INDEX_NAME = "ix_refund_request_source"


def upgrade() -> None:
    # 1. Add the column NOT NULL with a server default so existing rows fill in.
    op.add_column(
        TABLE,
        sa.Column(
            COLUMN,
            sa.String(length=20),
            nullable=False,
            server_default="manual",
            comment="Origin: withdrawal|manual|overpayment",
        ),
    )

    # 2. Best-effort reclassification of historical rows from the reason text
    #    (the only discriminator that existed before this column).
    op.execute(
        """
        UPDATE refund_request
        SET source = 'withdrawal'
        WHERE reason LIKE 'Rút hồ sơ #%'
        """
    )
    op.execute(
        """
        UPDATE refund_request
        SET source = 'overpayment'
        WHERE reason LIKE 'Refund overpayment %'
        """
    )

    # 3. Guard rails: value CHECK + lookup index (rollback targets it by source).
    op.create_check_constraint(
        CHECK_NAME,
        TABLE,
        "source IN ('withdrawal', 'manual', 'overpayment')",
    )
    op.create_index(INDEX_NAME, TABLE, [COLUMN])


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE)
    op.drop_constraint(CHECK_NAME, TABLE, type_="check")
    op.drop_column(TABLE, COLUMN)
