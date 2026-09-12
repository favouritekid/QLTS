"""Point the live lead_assignment_failed rule at the manager -> admin fallback.

Revision ID: e1safety20260912
Revises: arch20260829
Create Date: 2026-09-12

WHY A MIGRATION IS REQUIRED
---------------------------
Editing ``NOTIFICATION_SEED_DEFAULTS`` alone changes NOTHING on an environment
that has already been seeded, and that was verified rather than assumed:

* ``app/scripts/sync_notification_rules.py`` (the only thing that runs
  automatically, via docker-entrypoint) never reads NOTIFICATION_SEED_DEFAULTS
  at all — it builds a minimal config from ``EVENT_CATALOG[...].default_resolver``,
  which is a single resolver name and cannot express a fallback chain. It also
  skips any event that already has a row (``if event_key in existing_events``).
* ``app/scripts/seed_notification_rules.py`` is insert-only and manual.

``lead_assignment_failed`` is an old event, so production already holds a row
with the old config. Without this migration the code change would ship and the
alerts would keep going to the same empty recipient list — the exact
"command returned 0 but nothing happened" shape this repo keeps getting bitten by.

IDEMPOTENT AND NON-DESTRUCTIVE
------------------------------
The UPDATE only fires when the stored config is still byte-for-byte the old
default. If an operator has customised the rule through the admin UI, this
migration leaves it alone rather than silently reverting their work.
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "e1safety20260912"
down_revision = "arch20260829"
branch_labels = None
depends_on = None


EVENT_KEY = "lead_assignment_failed"

# Every shape a pre-existing environment can legitimately be holding.
#
# Two producers wrote this rule over time and they did NOT agree:
#   * NOTIFICATION_SEED_DEFAULTS / reset_notification_rules_dev wrote the
#     actor_excluded wrapper;
#   * sync_notification_rules built a BARE single resolver from
#     EVENT_CATALOG.default_resolver.
# Matching only the first would leave every environment bootstrapped by the
# second still resolving to unit_managers - the migration would report success
# and change nothing, which is the failure mode this revision exists to fix.
OLD_CONFIGS = [
    {
        "resolver_type": "actor_excluded",
        "params": {"inner_resolver": {"resolver_type": "unit_managers", "params": {}}},
    },
    {"resolver_type": "unit_managers", "params": {}},
]
# Kept as the canonical "what upgrade came from" for downgrade.
OLD_CONFIG = OLD_CONFIGS[0]

NEW_CONFIG = {
    "resolver_type": "first_nonempty",
    "params": {
        "resolvers": [
            {
                "resolver_type": "actor_excluded",
                "params": {
                    "inner_resolver": {"resolver_type": "unit_managers", "params": {}}
                },
            },
            {
                "resolver_type": "actor_excluded",
                "params": {
                    "inner_resolver": {"resolver_type": "all_admins", "params": {}}
                },
            },
        ]
    },
}


def _swap(from_config: dict, to_config: dict) -> None:
    """Replace recipient_config wherever it still equals ``from_config``.

    Covers BOTH levels, because the dispatcher prefers the action row:

        elif action.recipient_config:  -> action wins
        else:                          -> rule is used

    Updating only ``notification_rule`` would therefore leave any action that
    carries its own copy of the old default still resolving to unit_managers,
    and the fallback would never run on that channel. Actions with a NULL
    recipient_config are left alone on purpose — NULL means "inherit the rule",
    which is exactly what we want.

    Comparison is done in Python on parsed JSON, not as a SQL string compare:
    key order and whitespace inside a JSON column are not stable, so a text
    comparison would match nothing while still reporting success.
    """
    conn = op.get_bind()

    rule_rows = conn.execute(
        sa.text(
            "SELECT id, recipient_config FROM notification_rule WHERE event = :evt"
        ),
        {"evt": EVENT_KEY},
    ).fetchall()
    rule_ids = [r[0] for r in rule_rows]

    for rid in rows_needing_update(rule_rows, from_config):
        conn.execute(
            sa.text(
                "UPDATE notification_rule SET recipient_config = CAST(:cfg AS JSON) "
                "WHERE id = :rid"
            ),
            {"cfg": json.dumps(to_config), "rid": rid},
        )

    if not rule_ids:
        return

    action_rows = conn.execute(
        sa.text(
            "SELECT id, recipient_config FROM notification_action "
            "WHERE rule_id = ANY(:rids) AND recipient_config IS NOT NULL"
        ),
        {"rids": rule_ids},
    ).fetchall()

    for aid in rows_needing_update(action_rows, from_config):
        conn.execute(
            sa.text(
                "UPDATE notification_action SET recipient_config = CAST(:cfg AS JSON) "
                "WHERE id = :aid"
            ),
            {"cfg": json.dumps(to_config), "aid": aid},
        )


def rows_needing_update(rows, from_config) -> list:
    """Ids from ``rows`` whose stored config still equals ``from_config``.

    The DECISION lives here, separate from the SQL, so tests can exercise the
    real rule instead of restating it. A test that re-implements this comparison
    keeps passing when the migration drifts — which is exactly the failure mode
    a migration test exists to prevent.
    """
    wanted = from_config if isinstance(from_config, list) else [from_config]
    out = []
    for row in rows:
        if _parsed(row[1]) in wanted:
            out.append(row[0])
    return out


def _parsed(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None
    return value


def upgrade() -> None:
    _swap(OLD_CONFIGS, NEW_CONFIG)


def downgrade() -> None:
    _swap(NEW_CONFIG, OLD_CONFIG)
