"""Remove manager enroll permission

Revision ID: p5a1b2c3d4e5
Revises: p4a1b2c3d4e5
Create Date: 2026-01-06

Phase 5 Fix: Remove manager enroll permission from casbin_rule

Per AUTHORIZATION_DECISIONS.md Decision 10:
- Enroll is ADMIN-ONLY with break-glass audit
- State Diagram confirms: enroll() = System / Admin only

This migration:
- REMOVES: role:manager /api/admissions/{profile_id}/enroll POST
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'p5a1b2c3d4e5'
down_revision = 'p4a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    """
    Remove manager enroll permission from casbin_rule.
    
    Per Decision 10: Enroll is ADMIN-ONLY.
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing BEFORE migration.")

    # ========== REMOVE MANAGER ENROLL ==========
    # Per Decision 10: Enroll is ADMIN-ONLY
    result = conn.execute(text("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:manager'
        AND v1 LIKE '%/enroll'
    """))
    
    print(f"✅ Removed {result.rowcount} manager enroll policies")

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER migration.")


def downgrade():
    """
    Restore manager enroll permission.
    
    WARNING: This restores a permission that violates Decision 10.
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

    # Restore manager enroll (SECURITY WARNING)
    conn.execute(text("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/admissions/{profile_id}/enroll', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:manager'
            AND v1 = '/api/admissions/{profile_id}/enroll'
            AND v2 = 'POST'
        )
    """))

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER downgrade.")
