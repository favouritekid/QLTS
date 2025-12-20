"""add officer dashboard policies for unified access

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2024-12-18 11:20:00.000000

This migration adds officer dashboard API permissions to all roles,
enabling the unified dashboard to work for officers, managers, and admins.

Phase 4: Unified Dashboard Page
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'r2s3t4u5v6w7'
down_revision: Union[str, None] = 'q1r2s3t4u5v6'  # After KPI config tables
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Officer dashboard endpoints to add permissions for
OFFICER_DASHBOARD_POLICIES = [
    ("/api/officer/stats", "GET"),
    ("/api/officer/dashboard", "GET"),
    ("/api/officer/leaderboard", "GET"),
    ("/api/officer/team-stats", "GET"),
    ("/api/officer/upcoming-activities", "GET"),
    ("/api/officer/availability", "POST"),
    ("/api/officer/recommendations", "GET"),  # Phase 7
]

# Roles that should have dashboard access
ROLES = ["role:officer", "role:manager"]


def upgrade() -> None:
    """
    Add officer dashboard API permissions to officer and manager roles.
    Admin already has wildcard access so no need to add specific policies.
    """
    conn = op.get_bind()
    
    for role in ROLES:
        for obj, action in OFFICER_DASHBOARD_POLICIES:
            # Check if policy already exists
            result = conn.execute(text("""
                SELECT id FROM casbin_rule 
                WHERE ptype = 'p' 
                AND v0 = :role 
                AND v1 = :obj 
                AND v2 = :action
            """), {"role": role, "obj": obj, "action": action})
            
            if result.fetchone() is None:
                # Insert new policy
                conn.execute(text("""
                    INSERT INTO casbin_rule (ptype, v0, v1, v2)
                    VALUES ('p', :role, :obj, :action)
                """), {"role": role, "obj": obj, "action": action})
    
    conn.commit()


def downgrade() -> None:
    """
    Remove officer dashboard API permissions.
    """
    conn = op.get_bind()
    
    for role in ROLES:
        for obj, action in OFFICER_DASHBOARD_POLICIES:
            conn.execute(text("""
                DELETE FROM casbin_rule 
                WHERE ptype = 'p' 
                AND v0 = :role 
                AND v1 = :obj 
                AND v2 = :action
            """), {"role": role, "obj": obj, "action": action})
    
    conn.commit()
