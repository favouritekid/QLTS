"""Add template tracking columns to casbin_rule

Revision ID: p6a1b2c3d4e5
Revises: p5a1b2c3d4e5
Create Date: 2026-01-06

Phase 6: Template Tracking for Audit & Drift Detection

Per AUTHORIZATION_DECISIONS.md Decision 14:
- policy_templates.py is SINGLE SOURCE OF TRUTH
- Need to track which template each policy came from
- Enable drift detection and audit trail

New columns:
- template_id: Which template this policy came from (NULL = manual/legacy)
- applied_at: When this policy was applied
- applied_by: User ID who applied this policy (NULL = migration/system)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'p6a1b2c3d4e5'
down_revision = 'p5a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add template tracking columns to casbin_rule table.

    These columns enable:
    1. Tracking policy origin (which template)
    2. Audit trail (when/who applied)
    3. Better drift detection (template vs manual policies)
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing BEFORE migration.")

    # ========== ADD NEW COLUMNS ==========
    # Check if columns already exist (idempotent)
    result = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'casbin_rule' AND column_name = 'template_id'
    """))
    if result.fetchone() is None:
        op.add_column('casbin_rule', sa.Column('template_id', sa.String(50), nullable=True))
        op.add_column('casbin_rule', sa.Column('applied_at', sa.DateTime(), nullable=True))
        op.add_column('casbin_rule', sa.Column('applied_by', sa.Integer(), nullable=True))

        # Add index for efficient template queries
        op.create_index('ix_casbin_rule_template_id', 'casbin_rule', ['template_id'])

        print("✅ Added template tracking columns: template_id, applied_at, applied_by")
    else:
        print("⏭️ Template tracking columns already exist, skipping")

    # ========== BACKFILL EXISTING POLICIES ==========
    # Mark existing policies as 'legacy' (applied before tracking)
    conn.execute(text("""
        UPDATE casbin_rule
        SET template_id = '_legacy',
            applied_at = NOW()
        WHERE template_id IS NULL
    """))

    print("✅ Backfilled existing policies with template_id='_legacy'")

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER migration.")


def downgrade():
    """
    Remove template tracking columns.

    WARNING: This will lose all template tracking data.
    """
    conn = op.get_bind()

    # ========== SAFETY CHECK BEFORE ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing. Cannot downgrade safely.")

    # ========== REMOVE COLUMNS ==========
    # Check if columns exist before dropping
    result = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'casbin_rule' AND column_name = 'template_id'
    """))
    if result.fetchone() is not None:
        # Drop index first
        op.drop_index('ix_casbin_rule_template_id', table_name='casbin_rule')

        # Drop columns
        op.drop_column('casbin_rule', 'applied_by')
        op.drop_column('casbin_rule', 'applied_at')
        op.drop_column('casbin_rule', 'template_id')

        print("✅ Removed template tracking columns")
    else:
        print("⏭️ Template tracking columns don't exist, skipping")

    # ========== SAFETY CHECK AFTER ==========
    result = conn.execute(text("""
        SELECT COUNT(*) FROM casbin_rule
        WHERE ptype = 'p' AND v0 = 'role:admin' AND v1 = '/*' AND v2 = '.*'
    """))
    if result.scalar() == 0:
        raise Exception("🚨 ABORT: Admin wildcard policy missing AFTER downgrade.")
