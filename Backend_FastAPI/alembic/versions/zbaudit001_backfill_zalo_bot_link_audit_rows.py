"""Backfill entity_audit_log rows for existing staff_zalo_bot_link.

Revision ID: zbaudit001
Revises: adm003path001
Create Date: 2026-04-28

Why
---
``zalo_bot_link_service`` started writing ``entity_audit_log`` rows for
link/unlink/displacement/preference-flip ops in this PR. Prior to this
change, no audit rows existed for the 6 active staff bot links already
on prod (1 admin + 5 officer, all linked 2026-04-27/28). Without
backfill, the audit timeline begins arbitrarily at "first action after
this migration" — compliance/forensic queries would show those 6 links
as having no creation provenance.

This migration writes 1 ``entity_audit_log`` row per active link with
``action="created"`` and ``source="backfill"``. The original link
timestamp is in ``staff_zalo_bot_link.linked_at``; we retain it via
``new_value`` JSONB so downstream tooling can reconcile.

Prod state audit (verified 2026-04-28 via DB query):
- ``staff_zalo_bot_link``: 6 rows, all ``is_active=true``
- ``entity_audit_log`` filtered by ``entity_type='StaffZaloBotLink'``: 0 rows
- After upgrade: should show exactly 6 rows with ``source='backfill'``.

Idempotency
-----------
``INSERT ... SELECT ... WHERE NOT EXISTS`` over the same
(entity_type, entity_id, source='backfill') triple, so re-running the
migration (or running on a DB where some rows were already backfilled)
inserts nothing for already-handled rows. Safe to re-apply.

Downgrade deletes only the rows tagged ``source='backfill'`` for entity
type ``StaffZaloBotLink``. Audit rows written by the live service
(``source='zalo_bot_webhook'`` or ``source='api'``) are NOT touched —
those represent real operator actions and must persist across
migration roll-back.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "zbaudit001"
down_revision: Union[str, None] = "adm003path001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_BACKFILL_SQL = """
    INSERT INTO entity_audit_log (
        entity_type, entity_id, action,
        actor_user_id, field_name,
        old_value, new_value, changes,
        reason, source, ip_address, user_agent,
        created_at
    )
    SELECT
        'StaffZaloBotLink',
        l.id,
        'created',
        l.user_id,
        NULL,
        NULL,
        json_build_object(
            'user_id', l.user_id,
            'is_active', l.is_active,
            'linked_at', l.linked_at,
            'note', 'backfilled — actual link predates audit instrumentation'
        )::jsonb,
        NULL,
        'backfilled 2026-04-28; original linked_at preserved in new_value',
        'backfill',
        NULL,
        NULL,
        l.linked_at
    FROM staff_zalo_bot_link l
    WHERE l.is_active = true
      AND NOT EXISTS (
          SELECT 1 FROM entity_audit_log a
          WHERE a.entity_type = 'StaffZaloBotLink'
            AND a.entity_id = l.id
            AND a.source = 'backfill'
      );
"""


_DOWNGRADE_SQL = """
    DELETE FROM entity_audit_log
    WHERE entity_type = 'StaffZaloBotLink'
      AND source = 'backfill';
"""


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
