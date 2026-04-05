"""merge cleanup_drop_app and notification branches

Revision ID: 0e58c2f554f7
Revises: 4d56a08f089a, cleanup_drop_app_001
Create Date: 2026-04-03 08:23:26.484968

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e58c2f554f7'
down_revision: Union[str, Sequence[str], None] = ('4d56a08f089a', 'cleanup_drop_app_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
