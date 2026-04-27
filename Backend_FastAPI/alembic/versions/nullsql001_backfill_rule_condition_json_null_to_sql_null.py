"""Backfill notification_rule.condition: JSON literal 'null' → SQL NULL.

Revision ID: nullsql001
Revises: zalobot002
Create Date: 2026-04-27

The model column was `Column(JSON, nullable=True)` without
`none_as_null=True`, so SQLAlchemy persisted Python `None` as the JSON
literal `'null'` instead of SQL NULL. This made `WHERE condition IS NULL`
queries miss those rows and prevented index correctness.

Audit on dev DB 2026-04-27 (worktree QLTS): 48/49 rows held JSON
literal `'null'`, 1 row had a real condition object, 0 rows were SQL
NULL.

PR #147 changes the model to `JSON(none_as_null=True)` so future writes
persist correctly. This migration backfills existing rows.

Idempotency
-----------
Predicate `condition::text = 'null'` matches only rows holding the JSON
literal. Re-running this migration is a no-op:
- Rows already at SQL NULL: filtered out by `condition::text = 'null'`
  (NULL::text returns NULL, so the predicate is unknown → row skipped).
- Rows with real condition (e.g. `{"field": "is_self_action", ...}`):
  filtered out because their `::text` value is not the literal `'null'`.

Safe downgrade
--------------
Downgrade restores the JSON literal `'null'` for any row currently at
SQL NULL. This is reversible only in shape — once application code uses
`none_as_null=True`, new writes will produce SQL NULL again, so a
downgrade-then-upgrade roundtrip is safe.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "nullsql001"
down_revision: Union[str, None] = "zalobot002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notification_rule
        SET condition = NULL
        WHERE condition::text = 'null'
        """
    )


def downgrade() -> None:
    # Only revert rows that are SQL NULL back to JSON literal 'null'.
    # Real-condition rows are not touched.
    op.execute(
        """
        UPDATE notification_rule
        SET condition = 'null'::json
        WHERE condition IS NULL
        """
    )
