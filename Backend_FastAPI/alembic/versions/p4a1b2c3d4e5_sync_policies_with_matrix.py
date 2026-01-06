"""Sync policies with authorization matrix

Revision ID: p4fix_sync_policies_with_matrix
Revises: p3a1b2c3d4e5
Create Date: 2026-01-06

Phase 4 Fix: Synchronize casbin_rule with AUTHORIZATION_MATRIX.md

Changes:
- REMOVE: Officer enroll permission (violates Decision 10)
- ADD: User base policies (sessions, security, notification-preferences)
- ADD: Officer policies (consultation CRUD, timeline, insights, import)
- ADD: Manager policies (bulk-assign, distribution-preview, import, override)

Reference: AUTHORIZATION_MATRIX.md (FINAL FORM)
Reference: AUTHORIZATION_DECISIONS.md Decision 10
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'p4a1b2c3d4e5'  # Phase 4 fix
down_revision = 'p3a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    """
    Sync policies with AUTHORIZATION_MATRIX.md
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing BEFORE migration.")

    # ========== CRITICAL FIX: REMOVE Officer Enroll ==========
    # Per Decision 10: Admission State ≠ Authorization
    # Enroll is ADMIN-ONLY (requires break-glass audit)
    op.execute(text("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
        AND v0 = 'role:officer'
        AND v1 LIKE '%/enroll'
    """))

    # ========== ADD USER BASE POLICIES ==========
    # These are inherited by all roles through role inheritance
    user_policies = [
        # Sessions (SELF check)
        ('role:user', '/api/sessions', 'GET'),
        ('role:user', '/api/sessions/{session_id}', 'DELETE'),
        ('role:user', '/api/sessions/revoke-all', 'POST'),
        # Security (SELF check)
        ('role:user', '/api/security/login-history', 'GET'),
        ('role:user', '/api/security/active-sessions', 'GET'),
        ('role:user', '/api/security/not-me', 'POST'),
        # Notification preferences (SELF check)
        ('role:user', '/api/notification-preferences', 'GET'),
        ('role:user', '/api/notification-preferences', 'PUT'),
        ('role:user', '/api/notification-preferences/{channel}', 'PUT'),
        # Admission config (read-only lookup)
        ('role:user', '/api/admission-config/subjects', 'GET'),
        ('role:user', '/api/admission-config/methods', 'GET'),
    ]

    for v0, v1, v2 in user_policies:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', :v0, :v1, :v2
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
            )
        """), {"v0": v0, "v1": v1, "v2": v2})

    # ========== ADD OFFICER POLICIES ==========
    officer_policies = [
        # Consultation CRUD
        ('role:officer', '/api/leads/{lead_id}/consultations', 'GET'),
        ('role:officer', '/api/leads/{lead_id}/consultations/{consultation_id}', 'PUT'),
        ('role:officer', '/api/leads/{lead_id}/consultations/{consultation_id}', 'DELETE'),
        # Timeline & Insights
        ('role:officer', '/api/leads/{lead_id}/timeline', 'GET'),
        ('role:officer', '/api/leads/{lead_id}/insights', 'GET'),
        # Import & Quota
        ('role:officer', '/api/leads/my/reassign-quota', 'GET'),
        ('role:officer', '/api/leads/import/template', 'GET'),
        ('role:officer', '/api/leads/import', 'POST'),
        # Admission config (lookup)
        ('role:officer', '/api/admission-config/subjects', 'GET'),
        ('role:officer', '/api/admission-config/methods', 'GET'),
        ('role:officer', '/api/admission-config/criteria', 'GET'),
        ('role:officer', '/api/admission-config/criteria/{criteria_code}', 'GET'),
    ]

    for v0, v1, v2 in officer_policies:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', :v0, :v1, :v2
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
            )
        """), {"v0": v0, "v1": v1, "v2": v2})

    # ========== ADD MANAGER POLICIES ==========
    manager_policies = [
        # Bulk operations
        ('role:manager', '/api/leads/bulk-assign', 'POST'),
        ('role:manager', '/api/leads/distribution-preview', 'GET'),
        ('role:manager', '/api/leads/import/template', 'GET'),
        ('role:manager', '/api/leads/import', 'POST'),
        # Admission override (with audit)
        ('role:manager', '/api/admissions/{profile_id}/override', 'POST'),
    ]

    for v0, v1, v2 in manager_policies:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', :v0, :v1, :v2
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
            )
        """), {"v0": v0, "v1": v1, "v2": v2})

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER migration.")


def downgrade():
    """
    Rollback: Remove added policies, restore officer enroll.

    WARNING: This restores a security vulnerability (officer enroll).
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

    # Remove added policies
    policies_to_remove = [
        # User policies
        ('role:user', '/api/sessions', 'GET'),
        ('role:user', '/api/sessions/{session_id}', 'DELETE'),
        ('role:user', '/api/sessions/revoke-all', 'POST'),
        ('role:user', '/api/security/login-history', 'GET'),
        ('role:user', '/api/security/active-sessions', 'GET'),
        ('role:user', '/api/security/not-me', 'POST'),
        ('role:user', '/api/notification-preferences', 'GET'),
        ('role:user', '/api/notification-preferences', 'PUT'),
        ('role:user', '/api/notification-preferences/{channel}', 'PUT'),
        ('role:user', '/api/admission-config/subjects', 'GET'),
        ('role:user', '/api/admission-config/methods', 'GET'),
        # Officer policies
        ('role:officer', '/api/leads/{lead_id}/consultations', 'GET'),
        ('role:officer', '/api/leads/{lead_id}/consultations/{consultation_id}', 'PUT'),
        ('role:officer', '/api/leads/{lead_id}/consultations/{consultation_id}', 'DELETE'),
        ('role:officer', '/api/leads/{lead_id}/timeline', 'GET'),
        ('role:officer', '/api/leads/{lead_id}/insights', 'GET'),
        ('role:officer', '/api/leads/my/reassign-quota', 'GET'),
        ('role:officer', '/api/leads/import/template', 'GET'),
        ('role:officer', '/api/leads/import', 'POST'),
        ('role:officer', '/api/admission-config/subjects', 'GET'),
        ('role:officer', '/api/admission-config/methods', 'GET'),
        ('role:officer', '/api/admission-config/criteria', 'GET'),
        ('role:officer', '/api/admission-config/criteria/{criteria_code}', 'GET'),
        # Manager policies
        ('role:manager', '/api/leads/bulk-assign', 'POST'),
        ('role:manager', '/api/leads/distribution-preview', 'GET'),
        ('role:manager', '/api/leads/import/template', 'GET'),
        ('role:manager', '/api/leads/import', 'POST'),
        ('role:manager', '/api/admissions/{profile_id}/override', 'POST'),
    ]

    for v0, v1, v2 in policies_to_remove:
        op.execute(text(f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
        """), {"v0": v0, "v1": v1, "v2": v2})

    # Restore officer enroll (SECURITY WARNING)
    op.execute(text("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/admissions/{profile_id}/enroll', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
            AND v0 = 'role:officer'
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
