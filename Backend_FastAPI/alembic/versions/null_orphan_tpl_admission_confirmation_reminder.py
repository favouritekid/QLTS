"""null orphan TPL_ADMISSION_CONFIRMATION_REMINDER_*_V1 template_codes

PR #327 ``cleanup_uppercase_orphan_notification_rows`` (2026-05-23) removed
the UPPERCASE notification_template rows but left 2 ``notification_action``
rows still referencing the now-non-existent template codes::

    id=92, rule_id=51 (admission_confirmation_reminder_24h), channel=email,
      template_code='TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1'

    id=94, rule_id=52 (admission_confirmation_reminder_6h), channel=email,
      template_code='TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1'

Behavior pre-fix: when the celery-beat reminder scan fires (every night
for profiles approaching their confirmation deadline), the dispatcher
queries the missing template_code, logs::

    "template_code not resolved, using rule defaults"

and falls back to the rule's ``base_snapshot`` for title/body. Users still
receive the reminder — just with the default rule snapshot content rather
than the (intended-but-now-missing) tuned template. So the bug is

* user-impact: low (notification still sent, content slightly less tuned)
* log noise: medium (nightly warning spam during reminder window)

This migration sets ``template_code = NULL`` on those 2 rows so the
dispatcher silently uses the rule defaults without the warning log. If
admin later wants tuned templates for these reminders, they can seed
new templates + UPDATE action rows to reference them.

Verified prod state 2026-05-25 via SSH read-only:

    SELECT na.id, na.rule_id, na.channel, na.template_code, nr.event
    FROM notification_action na
    JOIN notification_rule nr ON na.rule_id = nr.id
    WHERE na.template_code LIKE 'TPL_ADMISSION_CONFIRMATION_REMINDER%';

    id | rule_id | channel | template_code                              | event
    92 |      51 | email   | TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1 | admission_confirmation_reminder_24h
    94 |      52 | email   | TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1  | admission_confirmation_reminder_6h

Predicate is strict (full string match) per ``migration-predicate-safety``
memory. Idempotent — re-run matches 0 rows.

Revision ID: null_orphan_admission_reminder_tpl
Revises: sl20260524_canonical
Create Date: 2026-05-25
"""
from typing import Sequence, Union

from alembic import op


revision: str = "null_orphan_admission_reminder_tpl"
down_revision: Union[str, None] = "sl20260524_canonical"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE notification_action
        SET template_code = NULL,
            updated_at = NOW()
        WHERE template_code IN (
            'TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1',
            'TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1'
        )
        """
    )


def downgrade() -> None:
    # Restore the exact rule_id → template_code mapping. If a future migration
    # introduces new actions for these rules the restore could over-write —
    # but at the time of this fix only the original 2 rows existed (verified
    # prod 2026-05-25). Predicate uses rule_id + channel to scope.
    op.execute(
        """
        UPDATE notification_action
        SET template_code = 'TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1',
            updated_at = NOW()
        WHERE rule_id = 51 AND channel = 'email' AND template_code IS NULL
        """
    )
    op.execute(
        """
        UPDATE notification_action
        SET template_code = 'TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1',
            updated_at = NOW()
        WHERE rule_id = 52 AND channel = 'email' AND template_code IS NULL
        """
    )
