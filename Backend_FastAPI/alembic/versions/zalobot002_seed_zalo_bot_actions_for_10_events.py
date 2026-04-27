"""Seed zalo_bot NotificationAction rows for 10 v5-pilot events.

Revision ID: zalobot002
Revises: zalobot001
Create Date: 2026-04-27

Adds a ``channel='zalo_bot'`` action to up to 10 notification rules so
the v5 pilot events dispatch through the Zalo Bot channel for any user
whose preferences allow it.

Pilot scope (Tier 1 + Tier 2 — see project_zalo_bot_plan_audit memory):

| Event                       | Recipient            |
|-----------------------------|----------------------|
| lead_assigned               | officer              |
| lead_reassigned             | old + new officer    |
| lead_assignment_failed      | unit manager         |
| consultation_reminder       | officer              |
| application_created         | unit manager + own.  |
| application_status_changed  | profile owner        |
| application_fee_paid        | officer + accountant |
| payment_overdue             | accountant           |
| suspicious_login            | affected user        |
| system_alert                | admin                |

Idempotency
-----------
Insert is gated by ``WHERE NOT EXISTS`` on the same (rule, channel)
pair, so re-running the migration is a no-op. ``content_mode`` is
``inherit_default`` so the bot reuses the rule's existing title /
message templates — per-bot template overrides are deferred until the
operator decides whether each event needs a bot-friendly multi-line
layout.

Marker / safe downgrade
-----------------------
Each row inserted by THIS migration is tagged via
``config = {"seeded_by": "zalobot002"}``. ``downgrade()`` deletes only
rows carrying this marker. Pre-existing ``zalo_bot`` actions added by
hand earlier (rule #1 ``lead_assigned`` was seeded via SQL during the
2026-04-27 smoke session, BEFORE this migration was written) carry
no marker and are therefore preserved across a downgrade. Likewise,
any zalo_bot action added later by an admin via the
``/admin/notification-rules`` wizard is not touched.

This guarantees a downgrade of zalobot002 is reversible without
collateral damage to operator-curated rule state.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "zalobot002"
down_revision: Union[str, None] = "zalobot001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Events that should dispatch through Zalo Bot for v5 pilot.
# Lookup is by ``event`` (string) so this works on any DB regardless
# of auto-increment id assignment.
PILOT_EVENTS = [
    "lead_assigned",
    "lead_reassigned",
    "lead_assignment_failed",
    "consultation_reminder",
    "application_created",
    "application_status_changed",
    "application_fee_paid",
    "payment_overdue",
    "suspicious_login",
    "system_alert",
]


# Marker stamped onto every row inserted by this migration. Downgrade
# deletes only rows carrying this exact value, so rows created outside
# this migration (manual SQL, admin wizard, future migrations) are
# preserved.
MARKER_CONFIG_JSON = '{"seeded_by": "zalobot002"}'


def upgrade() -> None:
    for event in PILOT_EVENTS:
        op.execute(
            f"""
            INSERT INTO notification_action (
                rule_id, step, channel, delay_minutes, content_mode,
                branch_key, config, created_at, updated_at
            )
            SELECT
                nr.id,
                COALESCE(MAX(na.step), 0) + 1,
                'zalo_bot',
                0,
                'inherit_default',
                'group_' || (COALESCE(MAX(na.step), 0) + 1) || '_zalo_bot',
                '{MARKER_CONFIG_JSON}'::json,
                now(),
                now()
            FROM notification_rule nr
            LEFT JOIN notification_action na ON na.rule_id = nr.id
            WHERE nr.event = '{event}'
              AND NOT EXISTS (
                  SELECT 1 FROM notification_action
                  WHERE rule_id = nr.id AND channel = 'zalo_bot'
              )
            GROUP BY nr.id;
            """
        )


def downgrade() -> None:
    # Only rows tagged with our marker are removed. ``config->>'seeded_by'``
    # extracts the marker value as text; rows without the marker (or
    # with NULL config) keep config->>'seeded_by' = NULL → not matched.
    op.execute(
        """
        DELETE FROM notification_action
        WHERE channel = 'zalo_bot'
          AND config IS NOT NULL
          AND config->>'seeded_by' = 'zalobot002';
        """
    )
