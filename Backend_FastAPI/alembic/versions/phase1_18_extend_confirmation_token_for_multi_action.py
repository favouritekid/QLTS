"""Wave 3-D / M-1-18 — extend ``admission_confirmation_token`` for multi-action ⚠ ONE-WAY.

Promotes the magic-link token from single-purpose (only ``confirm``) to
multi-action (``submit`` / ``resubmit`` / ``confirm`` / ``withdraw``) per
PLAN §3.3.g + §4 P1 #18 + line 1880-1901. Each profile can now have ONE
active token per action concurrently — e.g. a profile can hold an active
``submit`` token AND an active ``confirm`` token simultaneously.

5-step DDL
----------

1. ``ADD COLUMN action_type VARCHAR(20) NOT NULL DEFAULT 'confirm'``.
   Backfills every existing row to ``'confirm'`` at ALTER time (PG fast
   path), preserving the legacy single-action behavior.
2. ``ADD CONSTRAINT ck_token_action_type`` CHECK action_type IN
   ('submit', 'resubmit', 'confirm', 'withdraw'). Locks the enum at the
   DB layer.
3. Drop the existing single-token-per-profile UNIQUE INDEX
   (``ix_admission_confirmation_token_profile_id``) — that index was
   created from ``unique=True + index=True`` on the column; SQLAlchemy
   names it with the ``ix_*`` prefix, NOT the ``_profile_id_key``
   convention used in some PLAN draft examples (verified live via
   ``\\d admission_confirmation_token`` on dev DB).
4. ``CREATE UNIQUE INDEX uq_active_token_per_profile_action`` ON
   ``(profile_id, action_type) WHERE confirmed_at IS NULL``. Partial
   uniqueness keeps audit trail rows (already-confirmed tokens) free
   from contention with newly-issued live tokens for the same
   ``(profile, action)`` pair.
5. ``CREATE INDEX ix_token_action_type`` ON ``(token, action_type)`` —
   covers the ``get_profile_by_magic_link_token()`` lookup which
   filters by both columns.

ONE-WAY downgrade
-----------------

After this migration ships, the application will start writing rows
with ``action_type ∈ {'submit','resubmit','withdraw'}``. Reverting the
schema to the legacy single-action contract:
* would break any caller that issued non-``confirm`` tokens, and
* the pre-existing UNIQUE on ``profile_id`` cannot be re-added because
  it would reject any profile that holds 2+ tokens with different
  action types.

Defensive guard: ``SELECT COUNT(*)`` for non-``confirm`` rows. If any
exist, ``RuntimeError`` with snapshot-restore hint. If zero (only
legacy ``confirm`` tokens), downgrade can rebuild the legacy shape.

Idempotent guards
-----------------

* Column add via ``op.add_column`` is intrinsically idempotent on a
  fresh DB; in a half-applied state, re-running raises a clean
  ``DuplicateColumn`` (alembic surfaces it).
* Index create/drop wrapped with ``IF NOT EXISTS`` / ``IF EXISTS`` via
  inspector pattern — same shape as Wave 5-D phase1_16.
* CHECK constraint ADD reuses the canonical name; PG raises if
  duplicate.

Live cold cutover rehearsal (dev DB w/ prod data 2026-05-05)
------------------------------------------------------------

Pre-flight verified live: 0 rows in ``admission_confirmation_token``
on dev DB (post prod-data import). Zero break risk for any migration
step — column add, CHECK, partial UNIQUE, and new index all operate
on an empty table.

Revision ID: phase1_18
Revises: phase1_12
Create Date: 2026-05-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "phase1_18"
down_revision: Union[str, None] = "phase1_12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "admission_confirmation_token"

# Existing single-token-per-profile UNIQUE — created from
# ``unique=True + index=True`` on the model column. Verified live via
# ``\d admission_confirmation_token`` on dev DB 2026-05-05.
LEGACY_UNIQUE_INDEX = "ix_admission_confirmation_token_profile_id"

# 4-action enum lockdown — PLAN §3.3.g + §4 P1 #18 + line 1887.
ACTION_TYPES: tuple[str, ...] = ("submit", "resubmit", "confirm", "withdraw")
CHECK_NAME = "ck_token_action_type"

# Partial UNIQUE — 1 active (un-confirmed) token per (profile, action).
PARTIAL_UNIQUE_NAME = "uq_active_token_per_profile_action"

# Lookup index for ``get_profile_by_magic_link_token(token, action)``.
LOOKUP_INDEX_NAME = "ix_token_action_type"


def _index_exists(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return column_name in {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    # Step 1: ADD COLUMN action_type with default 'confirm' — backfills
    # legacy rows at ALTER time (PG fast path).
    if not _column_exists(TABLE, "action_type"):
        op.add_column(
            TABLE,
            sa.Column(
                "action_type",
                sa.String(20),
                nullable=False,
                server_default=sa.text("'confirm'"),
            ),
        )

    # Step 2: ADD CHECK constraint to lock the enum at DB layer.
    op.execute(
        sa.text(
            f"""
            ALTER TABLE {TABLE}
                DROP CONSTRAINT IF EXISTS {CHECK_NAME};
            """
        )
    )
    quoted_actions = ", ".join(repr(a) for a in ACTION_TYPES)
    op.create_check_constraint(
        CHECK_NAME,
        TABLE,
        f"action_type IN ({quoted_actions})",
    )

    # Step 3: DROP legacy single-token-per-profile UNIQUE index.
    if _index_exists(TABLE, LEGACY_UNIQUE_INDEX):
        op.drop_index(LEGACY_UNIQUE_INDEX, table_name=TABLE)

    # Step 4: CREATE partial UNIQUE — 1 active token per (profile,
    # action). Audit-trail rows (already-confirmed) excluded by
    # ``WHERE confirmed_at IS NULL``.
    if not _index_exists(TABLE, PARTIAL_UNIQUE_NAME):
        op.create_index(
            PARTIAL_UNIQUE_NAME,
            TABLE,
            ["profile_id", "action_type"],
            unique=True,
            postgresql_where=sa.text("confirmed_at IS NULL"),
        )

    # Step 5: Lookup index for ``get_profile_by_magic_link_token()``.
    if not _index_exists(TABLE, LOOKUP_INDEX_NAME):
        op.create_index(
            LOOKUP_INDEX_NAME,
            TABLE,
            ["token", "action_type"],
        )


def downgrade() -> None:
    """⚠ ONE-WAY — defensive guard against multi-action token rows.

    If any row has ``action_type != 'confirm'``, the application has
    started using multi-action semantics. Reverting the schema would
    break those callers AND fail to re-add the legacy single-
    profile_id UNIQUE because of multi-token-per-profile rows.
    """
    bind = op.get_bind()
    multi_action_count = bind.execute(
        sa.text(
            f"SELECT COUNT(*) FROM {TABLE} WHERE action_type != 'confirm'"
        )
    ).scalar()
    if multi_action_count and multi_action_count > 0:
        raise RuntimeError(
            f"Cannot downgrade phase1_18: {multi_action_count} row(s) in "
            f"{TABLE} hold non-'confirm' action_type values "
            f"({', '.join(a for a in ACTION_TYPES if a != 'confirm')}). "
            f"This is a ONE-WAY migration — restore from a pre-Wave-3 "
            f"snapshot instead of running `alembic downgrade`."
        )

    # Reverse order: drop new indexes + CHECK, then re-add legacy
    # UNIQUE + drop column.
    if _index_exists(TABLE, LOOKUP_INDEX_NAME):
        op.drop_index(LOOKUP_INDEX_NAME, table_name=TABLE)
    if _index_exists(TABLE, PARTIAL_UNIQUE_NAME):
        op.drop_index(PARTIAL_UNIQUE_NAME, table_name=TABLE)
    op.execute(
        sa.text(
            f"""
            ALTER TABLE {TABLE}
                DROP CONSTRAINT IF EXISTS {CHECK_NAME};
            """
        )
    )

    # Recreate legacy UNIQUE on profile_id (only safe because the guard
    # above ensured no profile holds >1 token after column drop).
    if not _index_exists(TABLE, LEGACY_UNIQUE_INDEX):
        op.create_index(
            LEGACY_UNIQUE_INDEX,
            TABLE,
            ["profile_id"],
            unique=True,
        )

    if _column_exists(TABLE, "action_type"):
        op.drop_column(TABLE, "action_type")
