"""Seed zalo_bot NotificationAction rows for 10 v5-pilot events.

Revision ID: zalobot002
Revises: zalobot001
Create Date: 2026-04-27

Adds a ``channel='zalo_bot'`` action to 9 notification rules (rule #1
``lead_assigned`` already had one added by hand in the smoke session, so
this migration is idempotent and skips it). After this lands, every event
in the pilot scope dispatches through the Zalo Bot channel for any user
whose preferences allow it.

Pilot scope (Tier 1 + Tier 2):

| Event                       | Recipient            | Self-condition needed? |
|-----------------------------|----------------------|------------------------|
| lead_assigned (already had) | officer              | yes (admin via wizard) |
| lead_reassigned             | old + new officer    | (deferred)             |
| lead_assignment_failed      | unit manager         | no                     |
| consultation_reminder       | officer              | no                     |
| application_created         | unit manager + own.  | (deferred)             |
| application_status_changed  | profile owner        | (deferred)             |
| application_fee_paid        | officer + accountant | (deferred)             |
| payment_overdue             | accountant           | no                     |
| suspicious_login            | affected user        | no                     |
| system_alert                | admin                | no                     |

Each row is inserted with ``content_mode='inherit_default'`` so the bot
reuses the rule's existing title/message templates (browser/email shape).
We deliberately do NOT override per-channel templates yet — that's a
follow-up after the operator decides which event needs a bot-friendly
multi-line layout.

The migration uses ``INSERT ... WHERE NOT EXISTS`` so re-running is
safe. ``step`` is computed as ``MAX(step) + 1`` per rule so we don't
collide with existing actions; ``branch_key`` follows the existing
convention ``group_<step>_<channel>`` used by the wizard.

Downgrade removes only the rows this migration inserted (matched on
rule + channel = 'zalo_bot'). Other zalo_bot actions added later by an
admin via the wizard are left intact.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "zalobot002"
down_revision: Union[str, None] = "zalobot001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Events that should dispatch through Zalo Bot for v5 pilot.
# Order matches the user-confirmed Tier 1 + Tier 2 list. Rule lookup is
# by ``event`` (string) so this works even if a fresh DB has different
# auto-increment ids than prod.
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


def upgrade() -> None:
    for event in PILOT_EVENTS:
        op.execute(
            f"""
            INSERT INTO notification_action (
                rule_id, step, channel, delay_minutes, content_mode,
                branch_key, created_at, updated_at
            )
            SELECT
                nr.id,
                COALESCE(MAX(na.step), 0) + 1,
                'zalo_bot',
                0,
                'inherit_default',
                'group_' || (COALESCE(MAX(na.step), 0) + 1) || '_zalo_bot',
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
    # Only delete rows that match (event in PILOT_EVENTS, channel='zalo_bot').
    # Any zalo_bot action added by an admin via the wizard for a different
    # event is left untouched.
    event_list = ", ".join(f"'{e}'" for e in PILOT_EVENTS)
    op.execute(
        f"""
        DELETE FROM notification_action
        WHERE channel = 'zalo_bot'
          AND rule_id IN (
              SELECT id FROM notification_rule
              WHERE event IN ({event_list})
          );
        """
    )
