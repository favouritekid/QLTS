"""add unique constraint student_code

✅ CRITICAL FIX #5: Add UNIQUE constraint to student.student_code
Prevents duplicate student codes from concurrent enrollment requests

Revision ID: z7d8e9f0g1h2
Revises: z6c7d8e9f0g1
Create Date: 2026-01-07 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q2a1b2c3d4e5'
down_revision: Union[str, None] = 'q1a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add UNIQUE constraint to student.student_code column.

    Security: Prevents duplicate student codes even if Redis lock fails.
    Combined with application-level Redis lock, provides defense-in-depth.

    Pre-check: Ensure no existing duplicates before adding constraint.
    """
    # Step 1: Check for existing duplicates (fail-safe)
    # In production, run this query first:
    # SELECT student_code, COUNT(*) FROM student GROUP BY student_code HAVING COUNT(*) > 1;

    # Step 2: Add unique constraint
    op.create_unique_constraint(
        'uq_student_code',  # Constraint name
        'student',          # Table name
        ['student_code']    # Column(s)
    )


def downgrade() -> None:
    """
    Remove UNIQUE constraint from student.student_code.

    WARNING: Only downgrade if absolutely necessary.
    Removing this constraint creates security vulnerability.
    """
    op.drop_constraint('uq_student_code', 'student', type_='unique')
