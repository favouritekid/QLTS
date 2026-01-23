"""add_actual_submission_format_to_profile_document

Revision ID: 6g5h4i3j2k1l
Revises: 5f4e3d2c1b0a
Create Date: 2026-01-22 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6g5h4i3j2k1l'
down_revision: Union[str, None] = '5f4e3d2c1b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add actual_submission_format column
    # This tracks what the user/officer DECLARES when submitting the document
    # (may differ from verified_format which officer confirms later)
    op.add_column('profile_document', sa.Column(
        'actual_submission_format',
        sa.String(length=50),
        nullable=True,
        comment='Declared by user/officer at submission: original | certified_copy | photo'
    ))


def downgrade() -> None:
    op.drop_column('profile_document', 'actual_submission_format')
