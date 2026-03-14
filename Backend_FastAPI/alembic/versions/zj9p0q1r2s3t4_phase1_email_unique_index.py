"""phase1: add partial unique index for email per unit (active leads)

Revision ID: zj9p0q1r2s3t4
Revises: zi8o9p0q1r2s3
Create Date: 2026-03-14 12:00:00.000000

P0 safe-hardening: Enforce email uniqueness per (unit_id) for active leads
at the database level. This prevents TOCTOU race conditions where two
concurrent requests could create leads with the same email in the same unit.

The index is PARTIAL:
  - Only applies when email IS NOT NULL (email is optional)
  - Only applies when deleted_at IS NULL (soft-deleted leads excluded)

Data cleanup:
  Before creating the index, this migration soft-deletes duplicate rows,
  keeping only the most recently created lead for each (email, unit_id) pair.
  Soft-deleted duplicates are marked with a specific reason in deleted_at.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "zj9p0q1r2s3t4"
down_revision: Union[str, None] = "zi8o9p0q1r2s3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Soft-delete duplicate (email, unit_id) rows, keeping the newest.
    # Uses a CTE to find duplicates and mark older ones as deleted.
    op.execute(
        text(
            """
            UPDATE lead SET deleted_at = NOW()
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY lower(email), unit_id
                               ORDER BY created_at DESC NULLS LAST, id DESC
                           ) AS rn
                    FROM lead
                    WHERE email IS NOT NULL AND deleted_at IS NULL
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )

    # Step 2: Create the partial unique index
    op.execute(
        text(
            "CREATE UNIQUE INDEX uq_lead_email_unit_active "
            "ON lead (lower(email), unit_id) "
            "WHERE email IS NOT NULL AND deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_lead_email_unit_active"))
