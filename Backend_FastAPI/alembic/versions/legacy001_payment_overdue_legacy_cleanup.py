"""Legacy payment_overdue rule + inbox cleanup (disable+clean inbox).

Revision ID: legacy001
Revises: nullsql001
Create Date: 2026-04-27

Cleanup the leftover `payment_overdue` notification rule whose title is
prefixed `[LEGACY DISABLED]` (cosmetic flag added during a prior
notification reset). The rule still has `enabled=true` so it sits in
the active list and the matching `notification` rows still surface in
the user inbox.

Decision (chốt 2026-04-27, "disable+clean inbox" option)
--------------------------------------------------------
- Do NOT hard-delete the rule. A future PR may rename or reuse the
  `payment_overdue` event with a clean title; deleting the row would
  remove that history.
- Set `enabled=false` so the dispatcher stops loading it and admin UI
  hides it from the active filter.
- Delete `notification` (inbox) rows that match BOTH the title prefix
  AND are linked via `notification_delivery.event='payment_overdue'`.
  The `notification_delivery → notification` FK is `ON DELETE SET NULL`,
  so delivery rows are preserved for audit (their `notification_id`
  becomes NULL).

Strict predicate
----------------
- Rule: `event = 'payment_overdue' AND title_template LIKE '[LEGACY DISABLED]%'`
- Inbox: `title LIKE '[LEGACY DISABLED] payment_overdue%'`
  AND `id IN (SELECT notification_id FROM notification_delivery
              WHERE event = 'payment_overdue' AND notification_id IS NOT NULL)`

Future legitimate `payment_overdue` rules — i.e. those without the
`[LEGACY DISABLED]` title prefix — are not touched. Future
`[LEGACY DISABLED]` titles for *other* events are also not touched
because the inbox predicate scopes to `payment_overdue%` and the
delivery join restricts to `event='payment_overdue'`.

Audit on dev DB 2026-04-27 (worktree QLTS):
- 1 rule row matched (id=18, enabled=true)
- 6 notification rows matched both predicates
- 6 notification_delivery rows linked to those notifications

Idempotency
-----------
Re-running upgrade is a no-op:
- Rule already at `enabled=false` after first run; UPDATE matches but
  sets the same value.
- Notifications deleted on first run; predicate matches zero rows on
  second.

Downgrade
---------
Downgrade is intentionally a no-op with a comment. Re-enabling the
legacy rule is unsafe (admin may have intentionally kept it disabled
since), and the deleted inbox rows cannot be reconstructed — the
intent of this migration is one-way data hygiene.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "legacy001"
down_revision: Union[str, None] = "nullsql001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Disable the legacy rule (predicate scoped to payment_overdue +
    #    [LEGACY DISABLED] title prefix only).
    op.execute(
        """
        UPDATE notification_rule
        SET enabled = false
        WHERE event = 'payment_overdue'
          AND title_template LIKE '[LEGACY DISABLED]%'
        """
    )

    # 2. Clean inbox notifications matching BOTH the title prefix AND the
    #    delivery join. Delivery rows preserved (FK ON DELETE SET NULL).
    op.execute(
        """
        DELETE FROM notification
        WHERE title LIKE '[LEGACY DISABLED] payment_overdue%'
          AND id IN (
            SELECT notification_id FROM notification_delivery
            WHERE event = 'payment_overdue'
              AND notification_id IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    # Intentional no-op. See docstring for rationale (deleted inbox rows
    # cannot be reconstructed; rule re-enable would risk overriding a
    # later admin decision).
    pass
