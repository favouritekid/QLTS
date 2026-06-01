"""Cleanup system_alert rule: drop zalo_bot action + restore all_users recipient.

Revision ID: naflood001
Revises: docgrp_audience_bf_20260530
Create Date: 2026-06-01

Part of the ``fix/notification-alert-flood`` hotfix. The notification
health-check beat task now dispatches the dedicated admin-only
``notification_health_alert`` event (shipped in the same PR), so the
``system_alert`` rule no longer needs the zalo_bot fan-out — and is
restored to its seed contract (``all_users``) for the manual admin
broadcast endpoint ``POST /system/alert``.

upgrade()
---------
1. DELETE the ``zalo_bot`` action that ``zalobot002`` seeded onto the
   ``system_alert`` rule (marker ``config->>'seeded_by' = 'zalobot002'``).
   Scoped to ``system_alert`` ONLY — the other 9 zalobot002 pilot events
   keep their zalo_bot actions untouched. Idempotent: if already deleted
   (e.g. by Phase 0 prod mitigation), the DELETE matches zero rows.
2. UPDATE recipient_config from ``all_admins`` back to ``all_users`` for
   ``system_alert``. Narrow predicate ``resolver_type = 'all_admins'`` so
   this ONLY undoes the Phase 0 mitigation — it never overwrites a custom
   resolver an operator may have set, and is a no-op if Phase 0 never ran
   (recipient still ``all_users``). Idempotent.

   ``recipient_config`` is a JSON (not JSONB) column
   (``models/notification.py``), so the cast is ``::json`` and the
   ``->>'resolver_type'`` text-extraction operator applies normally.

Removing zalo_bot from ``system_alert`` is INTENTIONAL, not a side
effect: an admin broadcast to ``all_users`` (most of whom have no Zalo
Bot link) would only dead-letter on the zalo_bot channel. browser + email
is the correct delivery surface for a system-wide broadcast.

downgrade()
-----------
Re-insert the zalo_bot action for ``system_alert`` ONLY, gated by
``WHERE NOT EXISTS`` so it never duplicates, carrying the zalobot002
marker. recipient_config is NOT touched on downgrade — ``all_users`` is
the seed default, not a state that needs reverting.

⚠️ Do NOT run ``downgrade`` on production as a flood remediation: it
re-creates exactly the zalo_bot fan-out this hotfix removed. See the
plan's rollback runbook (stop the beat source FIRST).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "naflood001"
down_revision: Union[str, None] = "docgrp_audience_bf_20260530"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop the zalobot002-seeded zalo_bot action — scoped to system_alert.
    op.execute(
        sa.text(
            """
            DELETE FROM notification_action
            WHERE channel = 'zalo_bot'
              AND config IS NOT NULL
              AND config->>'seeded_by' = 'zalobot002'
              AND rule_id = (
                  SELECT id FROM notification_rule WHERE event = 'system_alert'
              );
            """
        )
    )

    # 2. Restore recipient all_users — undoes Phase 0 mitigation only.
    op.execute(
        sa.text(
            """
            UPDATE notification_rule
            SET recipient_config = '{"resolver_type": "all_users", "params": {}}'::json,
                updated_at = now()
            WHERE event = 'system_alert'
              AND recipient_config->>'resolver_type' = 'all_admins';
            """
        )
    )


def downgrade() -> None:
    # Re-insert the zalo_bot action for system_alert ONLY, idempotently.
    # Mirrors zalobot002's INSERT shape; recipient_config left as-is.
    op.execute(
        sa.text(
            """
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
                '{"seeded_by": "zalobot002"}'::json,
                now(),
                now()
            FROM notification_rule nr
            LEFT JOIN notification_action na ON na.rule_id = nr.id
            WHERE nr.event = 'system_alert'
              AND NOT EXISTS (
                  SELECT 1 FROM notification_action
                  WHERE rule_id = nr.id AND channel = 'zalo_bot'
              )
            GROUP BY nr.id;
            """
        )
    )
