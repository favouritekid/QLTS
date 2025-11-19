"""Add officer program-offerings and leads import policies

Revision ID: o1p2q3r4s5t6
Revises: 017b25021a96
Create Date: 2024-11-19

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, None] = '017b25021a96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add missing Casbin policies for officer and manager roles."""

    # Add policy for officer to access program-offerings (flat list for dropdown)
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/program-offerings', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/program-offerings' AND v2 = 'GET'
        );
    """)

    # Add policy for manager to access program-offerings
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/program-offerings', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/program-offerings' AND v2 = 'GET'
        );
    """)

    # Add policy for officer to import leads
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads/import', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads/import' AND v2 = 'POST'
        );
    """)


def downgrade() -> None:
    """Remove the added Casbin policies."""

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 = '/api/program-offerings'
        AND v2 = 'GET';
    """)

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:manager'
        AND v1 = '/api/program-offerings'
        AND v2 = 'GET';
    """)

    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 = '/api/leads/import'
        AND v2 = 'POST';
    """)
