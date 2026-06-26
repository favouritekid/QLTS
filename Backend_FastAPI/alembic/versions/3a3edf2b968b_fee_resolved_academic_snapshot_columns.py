"""fee resolved academic snapshot columns

Denormalize the resolved admission major onto Fee so the "Thu học phí"
workspace (filter + list row + drawer + status-counts) shares ONE source of
truth. For multi-NV profiles the value reflects the ADMITTED choice (via
``resolve_fee_academic_info``), never the lead's intent offering. All columns
are nullable + fail-soft: when the resolver can't decide they stay NULL and the
UI shows "(chưa chốt ngành)".

Hand-written (autogenerate was polluted by unrelated model/DB comment drift) —
only the three Fee columns + index + FKs.

Revision ID: 3a3edf2b968b
Revises: bvk20260626001
Create Date: 2026-06-26 12:09:18.244367

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3a3edf2b968b'
down_revision: Union[str, Sequence[str], None] = 'bvk20260626001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'fee',
        sa.Column(
            'resolved_academic_info_id',
            sa.Integer(),
            nullable=True,
            comment='Snapshot: resolved OfferingAcademicInfo (trace source of major)',
        ),
    )
    op.add_column(
        'fee',
        sa.Column(
            'resolved_major_id',
            sa.Integer(),
            nullable=True,
            comment='Snapshot: resolved MajorProgram (filter/display source — NULL = chưa chốt)',
        ),
    )
    op.add_column(
        'fee',
        sa.Column(
            'resolved_degree_level',
            sa.String(length=50),
            nullable=True,
            comment=(
                "Snapshot: degree level TEXT NAME ('Cao đẳng'…) matching "
                "MajorProgram.degree_level legacy text + admissions FE filter value"
            ),
        ),
    )
    op.create_index(
        op.f('ix_fee_resolved_major_id'),
        'fee',
        ['resolved_major_id'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_fee_resolved_academic_info',
        'fee',
        'offering_academic_info',
        ['resolved_academic_info_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_fee_resolved_major',
        'fee',
        'major_program',
        ['resolved_major_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_fee_resolved_major', 'fee', type_='foreignkey')
    op.drop_constraint('fk_fee_resolved_academic_info', 'fee', type_='foreignkey')
    op.drop_index(op.f('ix_fee_resolved_major_id'), table_name='fee')
    op.drop_column('fee', 'resolved_degree_level')
    op.drop_column('fee', 'resolved_major_id')
    op.drop_column('fee', 'resolved_academic_info_id')
