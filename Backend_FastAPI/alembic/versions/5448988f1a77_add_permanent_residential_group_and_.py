"""add permanent residential_group and street_address to admission_profile

Revision ID: 5448988f1a77
Revises: 0e58c2f554f7
Create Date: 2026-04-06 14:33:40.964088

Adds two free-text fields below the existing province/district/ward
columns so the admission profile can capture the full Vietnamese
permanent address per the CCCD form (mẫu CC01):

- ``permanent_residential_group`` (VARCHAR 150) — community sub-unit
  (Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố). Free-text because
  there is no national database of sub-ward units and naming varies
  across regions.
- ``permanent_street_address`` (VARCHAR 255) — street address line
  (số nhà, tên đường). Free-text.

Pure additive migration: no data backfill, both columns nullable, no
existing column touched. Downgrade simply drops the two columns.

NOTE: ``alembic revision --autogenerate`` produced a much larger diff
including unrelated column-comment drift on many tables and a
``DROP TABLE casbin_rule`` operation. That noise has been stripped —
only the two real ``add_column`` / ``drop_column`` ops remain. If you
need to clean up the unrelated drift, do it in a separate, focused
migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5448988f1a77'
down_revision: Union[str, Sequence[str], None] = '0e58c2f554f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the two new permanent address columns."""
    op.add_column(
        'admission_profile',
        sa.Column(
            'permanent_residential_group',
            sa.String(length=150),
            nullable=True,
            comment='Tổ dân phố / Thôn / Buôn / Ấp / Khóm / Khu phố — community sub-unit, free-text',
        ),
    )
    op.add_column(
        'admission_profile',
        sa.Column(
            'permanent_street_address',
            sa.String(length=255),
            nullable=True,
            comment='Số nhà, tên đường — street address line, free-text',
        ),
    )


def downgrade() -> None:
    """Drop the two new permanent address columns."""
    op.drop_column('admission_profile', 'permanent_street_address')
    op.drop_column('admission_profile', 'permanent_residential_group')
