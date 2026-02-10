"""add notification casbin policies

Revision ID: g2h3i4j5k6l7
Revises: f1g2h3i4j5k6
Create Date: 2025-11-07 13:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g2h3i4j5k6l7'
down_revision: Union[str, None] = 'f1g2h3i4j5k6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Casbin policies for notification endpoints."""
    # Ensure casbin_rule table exists (normally created by Casbin adapter at runtime)
    op.execute("""
        CREATE TABLE IF NOT EXISTS casbin_rule (
            id SERIAL PRIMARY KEY,
            ptype VARCHAR(255),
            v0 VARCHAR(255),
            v1 VARCHAR(255),
            v2 VARCHAR(255),
            v3 VARCHAR(255),
            v4 VARCHAR(255),
            v5 VARCHAR(255)
        )
    """)
    # Insert policies for user role
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/notifications', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:user' AND v1 = '/api/notifications' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/notifications/mark-as-read', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:user' AND v1 = '/api/notifications/mark-as-read' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/notifications/mark-all-as-read', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:user' AND v1 = '/api/notifications/mark-all-as-read' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/notifications/{notification_id}', 'DELETE'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:user' AND v1 = '/api/notifications/{notification_id}' AND v2 = 'DELETE'
        );
    """)

    # Insert policies for officer role
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/notifications', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/notifications' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/notifications/mark-as-read', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/notifications/mark-as-read' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/notifications/mark-all-as-read', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/notifications/mark-all-as-read' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/notifications/{notification_id}', 'DELETE'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/notifications/{notification_id}' AND v2 = 'DELETE'
        );
    """)

    # Insert policies for manager role
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/notifications', 'GET'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/notifications' AND v2 = 'GET'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/notifications/mark-as-read', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/notifications/mark-as-read' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/notifications/mark-all-as-read', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/notifications/mark-all-as-read' AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/notifications/{notification_id}', 'DELETE'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/notifications/{notification_id}' AND v2 = 'DELETE'
        );
    """)


def downgrade() -> None:
    """Remove Casbin policies for notification endpoints."""
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v1 LIKE '/api/notifications%'
        AND v0 IN ('role:user', 'role:officer', 'role:manager');
    """)
