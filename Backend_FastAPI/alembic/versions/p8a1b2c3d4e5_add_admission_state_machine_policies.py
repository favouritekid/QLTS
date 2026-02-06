"""Add admission state machine Casbin policies

Revision ID: p8a1b2c3d4e5
Revises: p7a1b2c3d4e5
Create Date: 2026-01-06

Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 4:
- Manager: approve, reject
- Officer: resubmit
- User: confirm
- Admin: override, finalize (plus inherits all via wildcard)

All policies use INSERT ... WHERE NOT EXISTS pattern to be idempotent.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'p8a1b2c3d4e5'
down_revision: Union[str, None] = 'p7a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add Casbin policies for admission state machine endpoints.

    Architecture Compliance:
    - All state transition endpoints protected by RBAC
    - IDOR protection handled by dependencies (not Casbin)
    - Admin wildcard (/*) already covers override/finalize, but explicit for clarity
    """

    # ============================================
    # MANAGER ROLE - Approve and Reject
    # ============================================
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/admissions/{profile_id}/approve', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:manager'
            AND v1 = '/api/admissions/{profile_id}/approve'
            AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/admissions/{profile_id}/reject', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:manager'
            AND v1 = '/api/admissions/{profile_id}/reject'
            AND v2 = 'POST'
        );
    """)

    # ============================================
    # OFFICER ROLE - Resubmit after rejection
    # ============================================
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/admissions/{profile_id}/resubmit', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:officer'
            AND v1 = '/api/admissions/{profile_id}/resubmit'
            AND v2 = 'POST'
        );
    """)

    # ============================================
    # USER ROLE - Confirm enrollment (SELF only)
    # ============================================
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:user', '/api/admissions/{profile_id}/confirm', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:user'
            AND v1 = '/api/admissions/{profile_id}/confirm'
            AND v2 = 'POST'
        );
    """)

    # ============================================
    # ADMIN ROLE - Override and Finalize (explicit)
    # ============================================
    # Note: Admin already has /* wildcard, but we add explicit policies for:
    # 1. Documentation clarity
    # 2. Audit trail visibility
    # 3. Future role hierarchy changes

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:admin', '/api/admissions/{profile_id}/override', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:admin'
            AND v1 = '/api/admissions/{profile_id}/override'
            AND v2 = 'POST'
        );
    """)

    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:admin', '/api/admissions/{profile_id}/finalize', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:admin'
            AND v1 = '/api/admissions/{profile_id}/finalize'
            AND v2 = 'POST'
        );
    """)

    print("✅ Added admission state machine Casbin policies")


def downgrade() -> None:
    """
    Remove admission state machine Casbin policies.

    WARNING: This will disable RBAC for state transition endpoints.
    Only admin wildcard will remain effective.
    """
    # Remove all state machine policies
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v1 IN (
            '/api/admissions/{profile_id}/approve',
            '/api/admissions/{profile_id}/reject',
            '/api/admissions/{profile_id}/resubmit',
            '/api/admissions/{profile_id}/confirm',
            '/api/admissions/{profile_id}/override',
            '/api/admissions/{profile_id}/finalize'
        );
    """)

    print("✅ Removed admission state machine Casbin policies")
