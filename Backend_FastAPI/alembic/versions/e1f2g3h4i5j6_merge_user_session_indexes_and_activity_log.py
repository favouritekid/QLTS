"""merge user_session indexes and activity_log

Revision ID: e1f2g3h4i5j6
Revises: bf0ce03e4900, d1e2f3g4h5i6
Create Date: 2025-01-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2g3h4i5j6'
down_revision: Union[str, Sequence[str], None] = ('bf0ce03e4900', 'd1e2f3g4h5i6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This is a merge migration - no operations needed
    # Both branches have already created their tables/indexes
    pass


def downgrade() -> None:
    # This is a merge migration - no operations needed
    pass
