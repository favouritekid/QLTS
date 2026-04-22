"""retire application_documents_updated notification_rule row

Revision ID: nn20260422001
Revises: 2297e303be04
Create Date: 2026-04-22

Event ``application_documents_updated`` was retired from
``SystemEvents`` enum + ``EVENT_CATALOG`` + frontend in PR #93
(commit ``b3871edc chore: complete Application legacy cleanup``)
along with the rest of the legacy Application module. The cleanup
correctly removed every dispatch site, but the ``notification_rule``
row that had been seeded earlier (id=14, created 2026-03-16) was
left behind on prod, with one ``notification_action`` row attached
(channel=browser).

The post-Wave-4b coverage script
(``app.scripts.check_notification_event_coverage``) surfaces this
row as an orphan because the event is no longer in the enum. There
is no live caller and no current way for the rule to fire, so the
row is dead weight that confuses the audit / coverage tooling.

This migration removes it. FK behaviour:
 - ``notification_action`` → ON DELETE CASCADE (action row goes
   with the rule)
 - ``notification_delivery`` → ON DELETE SET NULL (delivery /
   audit rows are preserved with rule_id=NULL)
 - ``notification`` table has no FK to ``notification_rule``
   (snapshot copy of title/message/data at dispatch time), so user
   notification history is untouched.

Downgrade is intentionally a no-op: the rule body and action config
are not retained anywhere, so a faithful rollback is impossible. If
the event is ever revived, a future migration should re-seed it via
``sync_notification_rules`` against a restored catalog entry.
"""
from alembic import op


revision = "nn20260422001"
down_revision = "2297e303be04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM notification_rule WHERE event = 'application_documents_updated'"
    )


def downgrade() -> None:
    # No-op: the original rule body cannot be reconstructed from this
    # migration alone. See module docstring.
    pass
