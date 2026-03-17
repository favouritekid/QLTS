"""fix: sts02 legacy_status NULL -> 'contacted'

Revision ID: zs8y9z0a1b2c3
Revises: zr7x8y9z0a1b2
Create Date: 2026-03-16

sts02 (CONTACTED) and sts00 (NOT_CONTACTED) both sit at stg01.
derive_lead_status() maps stg01 -> "new" for both, which is wrong for sts02.
The only way to differentiate: set legacy_status='contacted' so the hybrid
derivation returns "contacted" via the priority-1 path.

Also fixes any existing leads stuck at sts02 with status='new'.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "zs8y9z0a1b2c3"
down_revision: Union[str, None] = "zr7x8y9z0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Part A: Fix consultation_status metadata
    result_cs = conn.execute(
        text(
            "UPDATE consultation_status "
            "SET legacy_status = 'contacted' "
            "WHERE id = 'sts02' AND (legacy_status IS NULL OR legacy_status != 'contacted')"
        )
    )

    # Part B: Fix existing leads with wrong lead.status
    result_leads = conn.execute(
        text(
            "UPDATE lead SET status = 'contacted' "
            "WHERE consultation_status_id = 'sts02' "
            "AND status = 'new' AND deleted_at IS NULL"
        )
    )

    print(
        f"  [fix] sts02 legacy_status → 'contacted' ({result_cs.rowcount} status row, "
        f"{result_leads.rowcount} lead rows fixed)"
    )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        text(
            "UPDATE consultation_status "
            "SET legacy_status = NULL "
            "WHERE id = 'sts02'"
        )
    )

    # Note: cannot safely revert lead.status because we can't distinguish
    # leads that were correctly "new" from those fixed by this migration.
    # Re-upgrading will fix them again.
