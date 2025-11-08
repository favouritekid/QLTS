"""add default casbin policies

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2025-11-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i4j5k6l7m8n9'
down_revision: Union[str, None] = 'h3i4j5k6l7m8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add default Casbin policies to ensure system always has base permissions.

    This migration fixes a critical issue where if casbin_rule table is truncated
    or database is restored without this table, the system would be completely locked.

    All policies use INSERT ... WHERE NOT EXISTS pattern to be idempotent.
    """

    # ============================================
    # ADMIN ROLE - Full system access
    # ============================================
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:admin', '/*', '.*'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
        );
    """)

    # ============================================
    # MANAGER ROLE - Admin users and leads management
    # ============================================
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/admin/users', '.*'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/admin/users' AND v2 = '.*'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/leads/*', '.*'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/leads/*' AND v2 = '.*'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/leads', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/leads' AND v2 = 'GET'
        );
    """)

    # ============================================
    # OFFICER ROLE - View and manage leads
    # ============================================
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads/{lead_id}', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads/{lead_id}' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads/{lead_id}/consultations', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads/{lead_id}/consultations' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads/{lead_id}/action', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads/{lead_id}/action' AND v2 = 'POST'
        );
    """)

    # ============================================
    # PROFILE ACCESS - All roles can manage their profile
    # ============================================
    # USER role
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/profile', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:user' AND v1 = '/api/profile' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/profile', 'PUT'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:user' AND v1 = '/api/profile' AND v2 = 'PUT'
        );
    """)

    # OFFICER role
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/profile', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/profile' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/profile', 'PUT'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/profile' AND v2 = 'PUT'
        );
    """)

    # MANAGER role
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/profile', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/profile' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/profile', 'PUT'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/profile' AND v2 = 'PUT'
        );
    """)


def downgrade() -> None:
    """
    Remove default Casbin policies.

    WARNING: Running this downgrade will remove critical system permissions
    and may lock all users out of the system.
    """
    # Remove admin wildcard policy
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:admin'
        AND v1 = '/*'
        AND v2 = '.*';
    """)

    # Remove manager policies
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:manager'
        AND v1 IN ('/api/admin/users', '/api/leads/*', '/api/leads', '/api/profile');
    """)

    # Remove officer policies
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 IN (
            '/api/leads',
            '/api/leads/{lead_id}',
            '/api/leads/{lead_id}/consultations',
            '/api/leads/{lead_id}/action',
            '/api/profile'
        );
    """)

    # Remove user profile policies
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:user'
        AND v1 = '/api/profile';
    """)
