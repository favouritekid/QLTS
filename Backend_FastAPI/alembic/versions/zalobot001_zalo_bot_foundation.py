"""Zalo Bot Platform foundation: link table + preference column.

Revision ID: zalobot001
Revises: dd5m6n7o8p9q
Create Date: 2026-04-26

Adds three pieces in a single revision so deploy stays atomic:

1. Table ``staff_zalo_bot_link`` — one row per linked staff user.
   ``user_id`` is unique (one binding per user, reused on relink).
   ``chat_id`` is **not** column-unique — instead a partial unique
   index enforces "one active binding per chat_id at a time", letting
   inactive history rows accumulate for audit.
2. Column ``notification_preference.zalo_bot_enabled`` — boolean, NOT
   NULL, server default false. Existing rows back-fill to ``false``
   automatically. Managed exclusively by ``zalo_bot_link_service``;
   the generic preference update endpoint deliberately omits it.
3. Partial unique index ``ux_staff_zalo_bot_link_active_chat`` on
   ``staff_zalo_bot_link(chat_id) WHERE is_active = true``. PostgreSQL
   only — relies on the partial-index feature. Test DB uses
   ``Base.metadata.create_all`` and skips this index, which is fine
   because tests don't exercise the chat_id collision path.

Downgrade is symmetric: drop index → drop column → drop table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "zalobot001"
down_revision: Union[str, None] = "dd5m6n7o8p9q"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "staff_zalo_bot_link"
_PARTIAL_INDEX = "ux_staff_zalo_bot_link_active_chat"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("chat_id", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Partial unique index: only one active binding per chat_id.
    # Inactive rows (is_active = false) are unconstrained so audit
    # history can accumulate.
    op.create_index(
        _PARTIAL_INDEX,
        _TABLE,
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    op.add_column(
        "notification_preference",
        sa.Column(
            "zalo_bot_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment=(
                "Zalo Bot Platform channel — managed by "
                "zalo_bot_link_service only, NOT writable through the "
                "generic preference update endpoint."
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("notification_preference", "zalo_bot_enabled")
    op.drop_index(_PARTIAL_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
