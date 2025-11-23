"""Lead creation enhancements: Email nullable + Manager/Officer create lead policies

Revision ID: x1y2z3a4b5c6
Revises: c3d4e5f6g7h8
Create Date: 2025-11-23

Changes:
1. Make email column nullable in lead table (email is optional)
2. Add Casbin policy for Manager to create leads (POST /api/leads)
3. Add Casbin policy for Officer to create leads (POST /api/leads)
4. Remove Casbin policy for Officer to import leads (POST /api/leads/import)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "x1y2z3a4b5c6"
down_revision: Union[str, None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade:
    1. Alter lead.email to nullable=True
    2. Add Manager POST /api/leads policy
    3. Add Officer POST /api/leads policy
    4. Remove Officer POST /api/leads/import policy
    """
    # === 1. Make email column nullable ===
    op.alter_column(
        'lead',
        'email',
        existing_type=sa.String(255),
        nullable=True,
        comment='Email is optional - not all leads have email'
    )

    # === 2. Add Casbin policy for Manager to create leads ===
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:manager', '/api/leads', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:manager' AND v1 = '/api/leads' AND v2 = 'POST'
        )
    """)

    # === 3. Add Casbin policy for Officer to create leads ===
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads' AND v2 = 'POST'
        )
    """)

    # === 4. Remove Officer import leads policy ===
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v0 = 'role:officer'
          AND v1 = '/api/leads/import'
          AND v2 = 'POST'
    """)


def downgrade() -> None:
    """
    Downgrade:
    1. Revert email to nullable=False (may fail if NULL values exist)
    2. Remove Manager POST /api/leads policy
    3. Remove Officer POST /api/leads policy
    4. Re-add Officer POST /api/leads/import policy
    """
    # === 1. Revert email to NOT NULL (WARNING: may fail if NULL values exist) ===
    # First update any NULL emails to empty string to avoid constraint violation
    op.execute("UPDATE lead SET email = '' WHERE email IS NULL")
    op.alter_column(
        'lead',
        'email',
        existing_type=sa.String(255),
        nullable=False
    )

    # === 2. Remove Manager POST /api/leads policy ===
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v0 = 'role:manager'
          AND v1 = '/api/leads'
          AND v2 = 'POST'
    """)

    # === 3. Remove Officer POST /api/leads policy ===
    op.execute("""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v0 = 'role:officer'
          AND v1 = '/api/leads'
          AND v2 = 'POST'
    """)

    # === 4. Re-add Officer import leads policy ===
    op.execute("""
        INSERT INTO casbin_rule (ptype, v0, v1, v2)
        SELECT 'p', 'role:officer', '/api/leads/import', 'POST'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p' AND v0 = 'role:officer' AND v1 = '/api/leads/import' AND v2 = 'POST'
        )
    """)
