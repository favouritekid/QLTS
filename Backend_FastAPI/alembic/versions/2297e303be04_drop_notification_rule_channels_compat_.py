"""drop_notification_rule_channels_compat_column

Revision ID: 2297e303be04
Revises: nn20260420001
Create Date: 2026-04-21 08:38:31.910038

Wave 4b (2026-04-21): `notification_rule.channels` was DEPRECATED in
Phase C1 (superseded by per-action rows in `notification_action`).
Runtime delivery has read from actions only since that phase; this
migration retires the compat column itself.

**Data migration (pre-drop)**: before dropping the column, backfill
`NotificationAction` rows for any enabled rule that has zero actions
today, using the values still in the compat column. Without this
backfill, post-Wave-4b the loader (which no longer synthesizes
actions from `channels`) would silently produce zero dispatches for
those rules after the column drop — observed on dev for
`payment_rejected`, `fee_fully_paid`, `invoice_issued`,
`application_fee_paid`, `refund_processed`.

The upgrade() function is idempotent: if the column was already
dropped by a prior run (e.g. on a dev DB that picked up the earlier
drop-only version of this migration), the backfill SQL is skipped
and the DROP COLUMN is a no-op. In that case, the companion
catalog-driven backfill in `app.scripts.sync_notification_rules` is
responsible for healing any orphaned rules at next startup.

Downgrade re-adds the column with the legacy `["browser"]` default
but cannot restore historical values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2297e303be04'
down_revision: Union[str, Sequence[str], None] = 'nn20260420001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_ACTIONS_FROM_CHANNELS_SQL = """
INSERT INTO notification_action (
    rule_id, step, channel, delay_minutes, content_mode,
    branch_key, created_at, updated_at
)
SELECT
    nr.id,
    j.ordinality::int AS step,
    j.value AS channel,
    0 AS delay_minutes,
    'inherit_default' AS content_mode,
    'wave4b_backfill_' || j.value AS branch_key,
    NOW() AS created_at,
    NOW() AS updated_at
FROM notification_rule nr
CROSS JOIN LATERAL
    json_array_elements_text(nr.channels) WITH ORDINALITY AS j(value, ordinality)
WHERE nr.enabled = true
  AND nr.channels IS NOT NULL
  AND json_array_length(nr.channels) > 0
  AND NOT EXISTS (
      SELECT 1 FROM notification_action na WHERE na.rule_id = nr.id
  )
"""


def upgrade() -> None:
    """Upgrade schema — backfill actions from compat column then drop it."""
    conn = op.get_bind()
    insp = inspect(conn)
    existing_cols = {c["name"] for c in insp.get_columns("notification_rule")}

    if "channels" in existing_cols:
        # Pre-drop backfill: synthesize NotificationAction rows for any
        # enabled rule that has zero actions today.
        op.execute(_BACKFILL_ACTIONS_FROM_CHANNELS_SQL)
        op.drop_column("notification_rule", "channels")
    # else: column already dropped by a prior run; sync script is the
    # fallback healer for any remaining orphan rules.


def downgrade() -> None:
    """Downgrade schema — re-add the column with legacy default.

    NOTE: historical per-row values cannot be restored; existing rows
    will all default to `["browser"]` until the old write-through is
    reinstated in code.
    """
    op.add_column(
        "notification_rule",
        sa.Column(
            "channels",
            postgresql.JSON(astext_type=sa.Text()),
            server_default=sa.text("'[\"browser\"]'::json"),
            nullable=False,
        ),
    )
