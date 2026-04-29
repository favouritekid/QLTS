"""ADM-023+028: magic-link cooldown ladder + reminder columns.

Adds the 4 columns that drive the hybrid cooldown ladder + reminder
beat task on ``admission_confirmation_token``:

- ``lock_until``           — sliding cooldown end (different from
  ``locked_at`` which is the hard-lock marker; ``lock_until`` is set
  every failed attempt while ``locked_at`` only fires at the hard-lock
  threshold).
- ``lock_count``           — how many times this token has been hard-
  locked. Cumulative; ≥1 means an admin must reset.
- ``reminder_24h_sent_at`` — beat task marks once the 24h-before-
  expiry reminder has been dispatched. Idempotent guard.
- ``reminder_6h_sent_at``  — same, for the 6h reminder.

Q9 decision (2026-04-28, memory ``admission-audit-wave2-2026-04-28``):
A3 + B1 + C2.

Idempotent: ``IF NOT EXISTS`` on every ALTER + index. Safe to re-run
after partial application.

Revision ID: mlharden01
Revises: zbaudit001
Create Date: 2026-04-29
"""
from alembic import op


revision = "mlharden01"
down_revision = "zbaudit001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE admission_confirmation_token
            ADD COLUMN IF NOT EXISTS lock_until TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS lock_count INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS reminder_24h_sent_at TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS reminder_6h_sent_at TIMESTAMPTZ NULL
        """
    )

    # Beat-scan index: covers tokens that may need a reminder.
    # Filter by ``confirmed_at IS NULL`` because confirmed tokens are
    # done; partial index keeps the rebuild small.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_admission_confirmation_token_reminder_scan
            ON admission_confirmation_token (expires_at, locked_at)
            WHERE confirmed_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_admission_confirmation_token_reminder_scan"
    )
    op.execute(
        """
        ALTER TABLE admission_confirmation_token
            DROP COLUMN IF EXISTS reminder_6h_sent_at,
            DROP COLUMN IF EXISTS reminder_24h_sent_at,
            DROP COLUMN IF EXISTS lock_count,
            DROP COLUMN IF EXISTS lock_until
        """
    )
