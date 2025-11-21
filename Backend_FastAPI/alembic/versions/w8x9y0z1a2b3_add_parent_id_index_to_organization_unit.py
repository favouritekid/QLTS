"""Add parent_id index to organization_unit for tree traversal performance

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2025-01-21

This migration adds an index on the parent_id column of the organization_unit table.
This significantly improves performance for:
1. Recursive CTE queries (ancestor/descendant traversal)
2. Child lookups when building organization tree
3. Circular dependency checks
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'w8x9y0z1a2b3'
down_revision = 'v7w8x9y0z1a2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add index on parent_id for faster tree traversal queries
    # This is critical for recursive CTEs and child lookups
    op.create_index(
        'ix_organization_unit_parent_id',
        'organization_unit',
        ['parent_id'],
        unique=False
    )
    print("✅ Created index ix_organization_unit_parent_id on organization_unit.parent_id")


def downgrade() -> None:
    op.drop_index('ix_organization_unit_parent_id', table_name='organization_unit')
    print("⬇️ Dropped index ix_organization_unit_parent_id")
