"""kv: cleanup SMOKE_* placeholder rows from vn_commune_area_map

The 3-province commune-KV PoC left 32 ``SMOKE_DLK_*`` placeholder rows in
``vn_commune_area_map`` (fake commune_code, not real GSO codes). They must NOT
flow into a prod import or pollute KV lookups. This migration deletes every
``commune_code LIKE 'SMOKE%'`` row and asserts zero remain.

Idempotent: re-running deletes nothing once clean. Safe on prod (where the
table had no SMOKE rows) — a no-op DELETE.

Revision ID: kv_smoke_cleanup_20260526
Revises: null_orphan_admin_reminder_tpl
Create Date: 2026-05-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "kv_smoke_cleanup_20260526"
down_revision: Union[str, None] = "null_orphan_admin_reminder_tpl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SMOKE_PREDICATE = "commune_code LIKE 'SMOKE%'"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(f"DELETE FROM vn_commune_area_map WHERE {_SMOKE_PREDICATE}")
    )
    # Fail-closed assertion: no SMOKE rows may survive cleanup.
    remaining = conn.execute(
        sa.text(
            f"SELECT count(*) FROM vn_commune_area_map WHERE {_SMOKE_PREDICATE}"
        )
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"SMOKE cleanup failed: {remaining} SMOKE_* rows still present "
            "in vn_commune_area_map"
        )


def downgrade() -> None:
    # Irreversible: SMOKE_* rows were throwaway PoC placeholders with fake
    # commune_code — nothing meaningful to restore.
    pass
