"""add applied_rules immutability trigger

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2025-12-03 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create PostgreSQL trigger to prevent mutation of applied_rules after creation.

    Security Rationale:
    - applied_rules is a snapshot of admission rules at profile creation time
    - Must remain immutable to prevent rule-change exploits
    - Example: Admin cannot retroactively change min_gpa after student applied

    This prevents direct database manipulation by administrators.
    """

    # Create the trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Allow insertion (NEW.applied_rules can be set)
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;

            -- On UPDATE: prevent applied_rules modification
            IF TG_OP = 'UPDATE' THEN
                -- Check if applied_rules changed
                IF OLD.applied_rules IS NOT NULL AND NEW.applied_rules IS DISTINCT FROM OLD.applied_rules THEN
                    RAISE EXCEPTION 'applied_rules is immutable after creation and cannot be modified';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create the trigger
    op.execute("""
        CREATE TRIGGER enforce_applied_rules_immutability
        BEFORE UPDATE ON admission_profile
        FOR EACH ROW
        EXECUTE FUNCTION prevent_applied_rules_update();
    """)


def downgrade() -> None:
    """
    Remove the immutability trigger and function.
    """

    # Drop the trigger first
    op.execute("""
        DROP TRIGGER IF EXISTS enforce_applied_rules_immutability ON admission_profile;
    """)

    # Drop the function
    op.execute("""
        DROP FUNCTION IF EXISTS prevent_applied_rules_update();
    """)
