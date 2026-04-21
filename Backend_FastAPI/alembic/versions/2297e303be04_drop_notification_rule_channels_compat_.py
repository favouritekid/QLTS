"""drop_notification_rule_channels_compat_column

Revision ID: 2297e303be04
Revises: nn20260420001
Create Date: 2026-04-21 08:38:31.910038

Wave 4b (2026-04-21): `notification_rule.channels` was DEPRECATED in
Phase C1 (superseded by per-action rows in `notification_action`). The
column has been a pure write-through copy since then — runtime
delivery reads from actions. Wave 4a (FE) already rewired the admin
UI to derive channels from `actions[].channel`, so dropping the
column is deploy-safe.

Downgrade adds the column back with the legacy default (`["browser"]`)
but cannot restore historical values (they are no longer written by
the ORM). Use with caution — intended for rollback, not data
recovery.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '2297e303be04'
down_revision: Union[str, Sequence[str], None] = 'nn20260420001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — drop the Phase C1 compat column."""
    op.drop_column("notification_rule", "channels")


def downgrade() -> None:
    """Downgrade schema — re-add the column with legacy default.

    NOTE: historical per-row values cannot be restored; existing rows
    will all default to `["browser"]` until the old write-through is
    reinstated in code.
    """
    op.add_column(
        "notification_rule",
        sa.Column(
            "channels",
            postgresql.JSON(astext_type=sa.Text()),
            server_default=sa.text("'[\"browser\"]'::json"),
            nullable=False,
        ),
    )
