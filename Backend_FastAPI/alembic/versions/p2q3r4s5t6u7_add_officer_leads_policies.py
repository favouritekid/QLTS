"""Add missing officer leads and organization-units policies

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2024-11-19

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'p2q3r4s5t6u7'
down_revision: Union[str, None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing Casbin policies for officer to access leads and organization-units."""

    # Add policy for officer to list leads (GET /api/leads)
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads' AND v2 = 'GET'
        );
    """)

    # Add policy for officer to view lead details (GET /api/leads/{lead_id})
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads/{lead_id}', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads/{lead_id}' AND v2 = 'GET'
        );
    """)

    # Add policy for officer to access organization-units (for dropdowns)
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/organization-units', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/organization-units' AND v2 = 'GET'
        );
    """)

    # Add policy for officer to access organization-units tree
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/organization-units/tree-with-aggregation', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/organization-units/tree-with-aggregation' AND v2 = 'GET'
        );
    """)


def downgrade() -> None:
    """Remove the added Casbin policies."""

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 = '/api/leads'
        AND v2 = 'GET';
    """)

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 = '/api/leads/{lead_id}'
        AND v2 = 'GET';
    """)

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 = '/api/organization-units'
        AND v2 = 'GET';
    """)

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 = '/api/organization-units/tree-with-aggregation'
        AND v2 = 'GET';
    """)
