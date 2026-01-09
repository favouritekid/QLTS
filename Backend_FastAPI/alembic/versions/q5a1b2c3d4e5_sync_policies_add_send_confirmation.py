"""Sync policies: Add Admission Base CRUD and Send-Confirmation

Revision ID: q5a1b2c3d4e5
Revises: q4a1b2c3d4e5
Create Date: 2026-01-08

Changes:
1. Add missing Base CRUD policies for Admissions (GET, POST, PUT, UPLOAD) for Officer.
   - These existed as '_legacy' in some environments but were missing from migration history.
2. Add missing 'send-confirmation' policy for Officer and Manager.
3. This syncs the database with policy_templates.py and fixes Test environment 403 errors.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'q5a1b2c3d4e5'
down_revision: Union[str, None] = 'q4a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add missing policies found during Casbin Audit.
    """
    
    # List of missing policies for OFFICER (Manager inherits these)
    # These match OFFICER_TEMPLATE in policy_templates.py
    officer_policies = [
        # Base CRUD
        ('/api/admissions', 'GET'),
        ('/api/admissions', 'POST'),
        ('/api/admissions/{profile_id}', 'GET'),
        ('/api/admissions/{profile_id}', 'PUT'),
        ('/api/admissions/{profile_id}/submit', 'POST'),
        ('/api/admissions/{profile_id}/documents/{doc_code}/upload', 'POST'),
        
        # New Action
        ('/api/admissions/{profile_id}/send-confirmation', 'POST'),
    ]

    for path, method in officer_policies:
        op.execute(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', 'role:officer', '{path}', '{method}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                AND v0 = 'role:officer'
                AND v1 = '{path}'
                AND v2 = '{method}'
            );
        """)

    # ============================================
    # MANAGER ROLE - Send Confirmation (Explicit)
    # ============================================
    # Explicitly listed in MANAGER_TEMPLATE, so we add it explicitly.
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/admissions/{profile_id}/send-confirmation', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:manager'
            AND v1 = '/api/admissions/{profile_id}/send-confirmation'
            AND v2 = 'POST'
        );
    """)

    print(f"✅ Synced {len(officer_policies)} missing Officer policies and 1 Manager policy")


def downgrade() -> None:
    """
    Remove the added policies.
    """
    # Remove Manager explicit policy
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:manager'
        AND v1 = '/api/admissions/{profile_id}/send-confirmation'
        AND v2 = 'POST';
    """)

    # Remove Officer policies added by this migration
    # Note: We use specific paths to avoid removing other valid policies
    paths = [
        '/api/admissions',
        '/api/admissions/{profile_id}',
        '/api/admissions/{profile_id}/submit',
        '/api/admissions/{profile_id}/documents/{doc_code}/upload',
        '/api/admissions/{profile_id}/send-confirmation'
    ]
    
    paths_sql = ", ".join(f"'{p}'" for p in paths)
    
    op.execute(f"""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 IN ({paths_sql});
    """)

    print("✅ Reverted policies")
