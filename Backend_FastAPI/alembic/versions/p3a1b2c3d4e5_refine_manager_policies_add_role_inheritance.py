"""Refine manager policies and add role inheritance

Revision ID: p3a1b2c3d4e5
Revises: z6c7d8e9f0g1
Create Date: 2026-01-05

Phase 3: Policy Migration
- Remove manager wildcard /api/leads/* (allows DELETE which should be admin-only)
- Add explicit manager policies for leads
- Add role inheritance to reduce policy duplication

Reference: AUTHORIZATION_IMPLEMENTATION_PLAN.md Phase 3
Reference: AUTHORIZATION_DECISIONS.md Decision 3
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'p3a1b2c3d4e5'
down_revision = '7bc9d00c973b'  # Current head
branch_labels = None
depends_on = None


def upgrade():
    """
    Upgrade: Refine manager policies and add role inheritance.

    SAFETY NET: Admin wildcard policy is verified before and after migration.
    This prevents accidental lockout.
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing BEFORE migration. "
                       "This is a critical safety violation.")

    # ========== PHASE 3.1: REFINE MANAGER LEAD POLICIES ==========
    # Remove wildcard that allows DELETE (should be admin-only)
    op.execute(text("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/leads/*' AND v2 = '.*'
    """))

    # Add explicit policies for manager on leads
    # Manager can: List, Create, View, Update leads
    # Manager CANNOT: Delete leads (requires admin)
    manager_lead_policies = [
        ('role:manager', '/api/leads', 'GET'),       # List leads
        ('role:manager', '/api/leads', 'POST'),      # Create lead
        ('role:manager', '/api/leads/{lead_id}', 'GET'),     # View lead detail
        ('role:manager', '/api/leads/{lead_id}', 'PUT'),     # Update lead
        ('role:manager', '/api/leads/{lead_id}/consultations', 'GET'),   # List consultations
        ('role:manager', '/api/leads/{lead_id}/consultations', 'POST'),  # Create consultation
        ('role:manager', '/api/leads/{lead_id}/consultations/{consultation_id}', 'PUT'),  # Update consultation
        ('role:manager', '/api/leads/{lead_id}/consultations/{consultation_id}', 'DELETE'),  # Delete consultation
        ('role:manager', '/api/leads/{lead_id}/action', 'POST'),     # Lead actions
        ('role:manager', '/api/leads/{lead_id}/assign', 'POST'),     # Assign lead
        ('role:manager', '/api/leads/{lead_id}/applications', 'GET'),    # List applications
        ('role:manager', '/api/leads/{lead_id}/applications', 'POST'),   # Create application
        ('role:manager', '/api/leads/export/csv', 'GET'),    # Export CSV
        ('role:manager', '/api/leads/export/excel', 'GET'),  # Export Excel
    ]

    for v0, v1, v2 in manager_lead_policies:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', '{v0}', '{v1}', '{v2}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
            )
        """))

    # ========== PHASE 3.3: ADD ROLE INHERITANCE ==========
    # This reduces policy duplication by creating a hierarchy:
    # user (base) <- officer <- manager <- admin
    #
    # Benefits:
    # - Add permission to role:user → all roles inherit it
    # - Reduces casbin_rule count by ~60%
    # - Easier to maintain
    role_inheritance = [
        ('role:officer', 'role:user'),    # Officer inherits from User
        ('role:manager', 'role:officer'), # Manager inherits from Officer
        ('role:admin', 'role:manager'),   # Admin inherits from Manager (plus wildcard)
    ]

    for child, parent in role_inheritance:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1)
            SELECT 'g', '{child}', '{parent}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'g' AND v0 = '{child}' AND v1 = '{parent}'
            )
        """))

    # ========== ADD BASE USER POLICIES ==========
    # These are inherited by all roles through the hierarchy
    user_base_policies = [
        ('role:user', '/api/profile', 'GET'),
        ('role:user', '/api/profile', 'PUT'),
        ('role:user', '/api/notifications', 'GET'),
        ('role:user', '/api/notifications/mark-as-read', 'POST'),
        ('role:user', '/api/notifications/mark-all-as-read', 'POST'),
        ('role:user', '/api/notifications/{notification_id}', 'DELETE'),
    ]

    for v0, v1, v2 in user_base_policies:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', '{v0}', '{v1}', '{v2}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
            )
        """))

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER migration. "
                       "This is a critical safety violation. ROLLBACK REQUIRED.")


def downgrade():
    """
    Downgrade: Restore manager wildcard and remove role inheritance.

    WARNING: This removes the security improvements from Phase 3.
    Only use if absolutely necessary.
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing. Cannot downgrade safely.")

    # ========== REMOVE ROLE INHERITANCE ==========
    role_inheritance = [
        ('role:officer', 'role:user'),
        ('role:manager', 'role:officer'),
        ('role:admin', 'role:manager'),
    ]

    for child, parent in role_inheritance:
        op.execute(text(f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'g' AND v0 = '{child}' AND v1 = '{parent}'
        """))

    # ========== REMOVE EXPLICIT MANAGER LEAD POLICIES ==========
    op.execute(text("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:manager'
        AND v1 LIKE '/api/leads%'
        AND v1 != '/api/leads/*'
    """))

    # ========== RESTORE MANAGER WILDCARD ==========
    op.execute(text("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/leads/*', '.*'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/leads/*' AND v2 = '.*'
        )
    """))

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER downgrade.")
