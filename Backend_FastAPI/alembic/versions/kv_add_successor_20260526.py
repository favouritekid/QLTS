"""kv: add successor_ward_code to administrative_nodes + identity backfill

PR-2 cross-era lineage for legacy→current commune resolution. Adds a nullable
``successor_ward_code`` on administrative_nodes = the CURRENT-era commune code a
WARD resolves to.

Identity backfill (deterministic, NO external data): any WARD whose own ``code``
is still a current-era ward (valid_to IS NULL) → successor = own code. Covers
all current wards + every legacy ward that kept its code through the merger.
Merged-away legacy wards (code retired) stay NULL until the per-province
merger-edge data is loaded (separate bulk import).

Revision ID: kv_add_successor_20260526
Revises: kv_smoke_cleanup_20260526
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "kv_add_successor_20260526"
down_revision: Union[str, None] = "kv_smoke_cleanup_20260526"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "administrative_nodes",
        sa.Column("successor_ward_code", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "idx_successor_ward_code",
        "administrative_nodes",
        ["successor_ward_code"],
    )
    # Identity backfill: WARD whose code is still a current-era ward → self.
    op.get_bind().execute(
        sa.text(
            """
            UPDATE administrative_nodes a
            SET successor_ward_code = a.code
            WHERE a.level = 'WARD'
              AND EXISTS (
                SELECT 1 FROM administrative_nodes c
                WHERE c.level = 'WARD'
                  AND c.valid_to IS NULL
                  AND c.is_active = true
                  AND c.code = a.code
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_index("idx_successor_ward_code", table_name="administrative_nodes")
    op.drop_column("administrative_nodes", "successor_ward_code")
