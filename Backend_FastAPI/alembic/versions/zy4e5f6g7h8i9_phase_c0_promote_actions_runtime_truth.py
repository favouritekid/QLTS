"""Phase C0: promote NotificationAction as runtime truth

Revision ID: zy4e5f6g7h8i9
Revises: zx3d4e5f6g7h8
Create Date: 2026-03-25

Phase C0:
  - Add rule_id, action_step, template_code to notification_delivery
  - Backfill notification_action for rules that only have channels
  - Sync channels from actions for consistency
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'zy4e5f6g7h8i9'
down_revision: Union[str, None] = 'zx3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Canonical channel order for backfill
CHANNEL_ORDER = ["browser", "email", "zalo", "sms"]


def upgrade() -> None:
    # --- 1. Add columns to notification_delivery ---
    op.add_column('notification_delivery', sa.Column(
        'rule_id', sa.Integer(),
        sa.ForeignKey('notification_rule.id', ondelete='SET NULL'),
        nullable=True,
        comment='FK to the rule that triggered this delivery',
    ))
    op.add_column('notification_delivery', sa.Column(
        'action_step', sa.Integer(),
        nullable=True,
        comment='Step number from NotificationAction (1-based)',
    ))
    op.add_column('notification_delivery', sa.Column(
        'template_code', sa.String(100),
        nullable=True,
        comment='Template code used for this delivery (from action or rule)',
    ))

    # Indexes for new columns
    op.create_index(
        'ix_delivery_rule_step_created',
        'notification_delivery',
        ['rule_id', 'action_step', sa.text('created_at DESC')],
    )
    op.create_index(
        'ix_delivery_rule_status_created',
        'notification_delivery',
        ['rule_id', 'status', sa.text('created_at DESC')],
    )

    # --- 2. Backfill notification_action for rules with channels but no actions ---
    conn = op.get_bind()

    # Find rules that have channels but no actions yet
    rules_without_actions = conn.execute(sa.text("""
        SELECT r.id, r.channels
        FROM notification_rule r
        LEFT JOIN notification_action a ON a.rule_id = r.id
        WHERE a.id IS NULL
          AND r.channels IS NOT NULL
          AND r.channels != '[]'::jsonb
          AND r.channels != 'null'::jsonb
    """)).fetchall()

    for rule_id, channels_json in rules_without_actions:
        if not channels_json:
            continue

        # channels is stored as JSON array
        if isinstance(channels_json, str):
            import json
            channels = json.loads(channels_json)
        elif isinstance(channels_json, list):
            channels = channels_json
        else:
            continue

        # Normalize socket -> browser
        channels = ["browser" if c == "socket" else c for c in channels]
        # Dedupe preserving canonical order
        seen = set()
        ordered = []
        for ch in CHANNEL_ORDER:
            if ch in channels and ch not in seen:
                ordered.append(ch)
                seen.add(ch)
        # Add any remaining channels not in canonical order
        for ch in channels:
            if ch not in seen:
                ordered.append(ch)
                seen.add(ch)

        # Insert actions
        for step, channel in enumerate(ordered, start=1):
            conn.execute(sa.text("""
                INSERT INTO notification_action (rule_id, step, channel, delay_minutes, created_at, updated_at)
                VALUES (:rule_id, :step, :channel, 0, NOW(), NOW())
            """), {"rule_id": rule_id, "step": step, "channel": channel})

    # --- 3. Sync channels from actions for rules that already have actions ---
    rules_with_actions = conn.execute(sa.text("""
        SELECT DISTINCT r.id
        FROM notification_rule r
        JOIN notification_action a ON a.rule_id = r.id
    """)).fetchall()

    for (rule_id,) in rules_with_actions:
        # Derive channels from actions in step order
        action_channels = conn.execute(sa.text("""
            SELECT channel, MIN(step) AS first_step
            FROM notification_action
            WHERE rule_id = :rule_id
            GROUP BY channel
            ORDER BY first_step
        """), {"rule_id": rule_id}).fetchall()

        import json
        derived_channels = [row[0] for row in action_channels]
        conn.execute(sa.text("""
            UPDATE notification_rule
            SET channels = :channels::jsonb
            WHERE id = :rule_id
        """), {"rule_id": rule_id, "channels": json.dumps(derived_channels)})


def downgrade() -> None:
    op.drop_index('ix_delivery_rule_status_created', table_name='notification_delivery')
    op.drop_index('ix_delivery_rule_step_created', table_name='notification_delivery')
    op.drop_column('notification_delivery', 'template_code')
    op.drop_column('notification_delivery', 'action_step')
    op.drop_column('notification_delivery', 'rule_id')
    # Note: backfilled notification_action rows are NOT removed on downgrade
    # to avoid data loss. They can coexist with channels-based runtime.
