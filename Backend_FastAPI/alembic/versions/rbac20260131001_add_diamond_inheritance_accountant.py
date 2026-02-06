"""Add Diamond Inheritance and Accountant Role

Revision ID: rbac20260131001
Revises: fin20260131003
Create Date: 2026-01-31

Diamond Inheritance Pattern:
                    ┌─────────┐
                    │  Admin  │
                    └────┬────┘
                      ▲   ▲
           ┌──────────┘   └──────────┐
           │                         │
     ┌─────┴──────┐           ┌──────┴─────┐
     │  Manager   │           │ Accountant │
     └─────┬──────┘           └─────┬──────┘
           │                        │
           └──────────┐  ┌──────────┘
                      ▼  ▼
                   ┌───────────┐
                   │  Officer  │
                   └─────┬─────┘
                         │
                   ┌─────┴─────┐
                   │   User    │
                   └───────────┘

Benefits:
- Separation of Duties: Manager (users/leads) vs Accountant (finance)
- Manager does NOT inherit Accountant permissions
- Accountant does NOT inherit Manager permissions
- Admin inherits BOTH branches (full access)

Reference: AUTHORIZATION_GUIDELINES.md - Diamond Inheritance
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'rbac20260131001'
down_revision = 'fin20260131003'
branch_labels = None
depends_on = None


def upgrade():
    """
    Upgrade: Add Diamond Inheritance structure and Accountant role policies.

    SAFETY NET: Admin wildcard policy is verified before and after migration.
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("ABORT: Admin wildcard policy missing BEFORE migration. "
                       "This is a critical safety violation.")

    # ========== PHASE 1: UPDATE ROLE INHERITANCE TO DIAMOND ==========
    # Old linear: user <- officer <- manager <- admin
    # New diamond: user <- officer <- [manager, accountant] <- admin (inherits both)

    # First, add the NEW diamond inheritance rules
    diamond_inheritance = [
        ('role:officer', 'role:user'),       # Officer inherits from User
        ('role:accountant', 'role:officer'), # Accountant inherits from Officer
        ('role:manager', 'role:officer'),    # Manager inherits from Officer (NOT from Accountant!)
        ('role:admin', 'role:manager'),      # Admin inherits from Manager
        ('role:admin', 'role:accountant'),   # Admin ALSO inherits from Accountant (Diamond!)
    ]

    for child, parent in diamond_inheritance:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, template_id, applied_at)
            SELECT 'g', '{child}', '{parent}', '_system_inheritance', NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'g' AND v0 = '{child}' AND v1 = '{parent}'
            )
        """))

    # ========== PHASE 2: ADD ACCOUNTANT POLICIES ==========
    # These are from ACCOUNTANT_TEMPLATE in policy_templates.py
    # NOTE: Some overlap with inherited officer policies, but explicit for clarity
    accountant_policies = [
        # Profile & Notifications (inherited from Officer, but explicit for safety)
        ('role:accountant', '/api/profile', 'GET'),
        ('role:accountant', '/api/profile', 'PUT'),
        ('role:accountant', '/api/notifications', 'GET'),
        ('role:accountant', '/api/notifications/mark-as-read', 'POST'),
        ('role:accountant', '/api/notifications/mark-all-as-read', 'POST'),
        ('role:accountant', '/api/notifications/{notification_id}', 'DELETE'),

        # Sessions & Security
        ('role:accountant', '/api/sessions', 'GET'),
        ('role:accountant', '/api/sessions/{id}', 'DELETE'),
        ('role:accountant', '/api/sessions/revoke-all', 'POST'),
        ('role:accountant', '/api/security/login-history', 'GET'),
        ('role:accountant', '/api/security/active-sessions', 'GET'),
        ('role:accountant', '/api/security/not-me', 'POST'),

        # =====================================================================
        # FINANCE MODULE - Accountant-specific operations
        # =====================================================================

        # FEES - Read + Calculate + Waive + Recalculate (not Cancel - admin only)
        ('role:accountant', '/api/fees', 'GET'),
        ('role:accountant', '/api/fees/{id}', 'GET'),
        ('role:accountant', '/api/fees/by-profile/{profile_id}', 'GET'),
        ('role:accountant', '/api/fees/summary/{profile_id}', 'GET'),
        ('role:accountant', '/api/fees/calculate', 'POST'),
        ('role:accountant', '/api/fees/{id}/waive', 'POST'),
        ('role:accountant', '/api/fees/{id}/recalculate', 'POST'),

        # INVOICES - Full CRUD (except delete)
        ('role:accountant', '/api/invoices', 'GET'),
        ('role:accountant', '/api/invoices/{id}', 'GET'),
        ('role:accountant', '/api/invoices/by-fee/{fee_id}', 'GET'),
        ('role:accountant', '/api/invoices/{id}/issue', 'PUT'),
        ('role:accountant', '/api/invoices/{id}/cancel', 'PUT'),
        ('role:accountant', '/api/invoices/{id}/apply-penalty', 'POST'),

        # PAYMENTS - Record + Verify + Reject
        ('role:accountant', '/api/payments', 'GET'),
        ('role:accountant', '/api/payments', 'POST'),  # Record payment
        ('role:accountant', '/api/payments/{id}', 'GET'),
        ('role:accountant', '/api/payments/by-invoice/{invoice_id}', 'GET'),
        ('role:accountant', '/api/payments/{id}/verify', 'PUT'),  # Verify payment
        ('role:accountant', '/api/payments/{id}/reject', 'PUT'),  # Reject payment
        ('role:accountant', '/api/payments/intents', 'POST'),
        ('role:accountant', '/api/payments/intents/{id}', 'GET'),
        ('role:accountant', '/api/payments/methods', 'GET'),

        # ACCOUNTING PERIODS - View only (create/close is admin only)
        ('role:accountant', '/api/accounting/periods', 'GET'),
        ('role:accountant', '/api/accounting/periods/current', 'GET'),
        ('role:accountant', '/api/accounting/periods/{id}', 'GET'),
        ('role:accountant', '/api/accounting/periods/{id}/summary', 'GET'),

        # REFUNDS - Request + Process (approve is manager only)
        ('role:accountant', '/api/refunds', 'GET'),
        ('role:accountant', '/api/refunds/{id}', 'GET'),
        ('role:accountant', '/api/refunds/request', 'POST'),
        ('role:accountant', '/api/refunds/{id}/process', 'PUT'),

        # Admission config (read-only lookup data)
        ('role:accountant', '/api/admission-config/subjects', 'GET'),
        ('role:accountant', '/api/admission-config/methods', 'GET'),
    ]

    for v0, v1, v2 in accountant_policies:
        op.execute(text(f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2, template_id, applied_at)
            SELECT 'p', '{v0}', '{v1}', '{v2}', 'accountant', NOW()
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
        raise Exception("ABORT: Admin wildcard policy missing AFTER migration. "
                       "This is a critical safety violation. ROLLBACK REQUIRED.")

    # Log migration success
    print(f"[rbac20260131001] Diamond inheritance and accountant role added successfully")
    print(f"  - Added {len(diamond_inheritance)} g-rules for diamond inheritance")
    print(f"  - Added {len(accountant_policies)} policies for role:accountant")


def downgrade():
    """
    Downgrade: Remove accountant role and revert to linear inheritance.

    WARNING: This removes separation of duties. Only use if absolutely necessary.
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("ABORT: Admin wildcard policy missing. Cannot downgrade safely.")

    # ========== REMOVE ACCOUNTANT POLICIES ==========
    op.execute(text("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:accountant'
    """))

    # ========== REMOVE DIAMOND INHERITANCE G-RULES ==========
    # Remove the new g-rules specific to diamond inheritance
    diamond_rules_to_remove = [
        ('role:accountant', 'role:officer'),  # Accountant branch
        ('role:admin', 'role:accountant'),    # Admin inheriting from Accountant
    ]

    for child, parent in diamond_rules_to_remove:
        op.execute(text(f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'g' AND v0 = '{child}' AND v1 = '{parent}'
        """))

    print("[rbac20260131001] Downgrade complete - reverted to linear inheritance")
