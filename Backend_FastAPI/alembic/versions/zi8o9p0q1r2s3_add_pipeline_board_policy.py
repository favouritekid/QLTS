"""add pipeline board casbin policy for officer/manager roles

Revision ID: zi8o9p0q1r2s3
Revises: zh7n8o9p0q1r2
Create Date: 2026-03-13 14:30:00.000000

Adds GET /api/pipeline/board to officer and manager Casbin policies.
The endpoint existed but was missing from both the policy template and migrations,
causing 403 for officers accessing the pipeline Kanban board.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = 'zi8o9p0q1r2s3'
down_revision: Union[str, None] = 'zh7n8o9p0q1r2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_POLICIES = [
    ("/api/pipeline/board", "GET"),
]

ROLES = ["role:officer", "role:manager"]


def upgrade() -> None:
    conn = op.get_bind()

    for role in ROLES:
        for obj, action in NEW_POLICIES:
            result = conn.execute(text("""
                SELECT id FROM casbin_rule
                WHERE ptype = 'p'
                AND v0 = :role
                AND v1 = :obj
                AND v2 = :action
            """), {"role": role, "obj": obj, "action": action})

            if result.fetchone() is None:
                conn.execute(text("""
                    INSERT INTO casbin_rule (ptype, v0, v1, v2)
                    VALUES ('p', :role, :obj, :action)
                """), {"role": role, "obj": obj, "action": action})

    conn.commit()


def downgrade() -> None:
    conn = op.get_bind()

    for role in ROLES:
        for obj, action in NEW_POLICIES:
            conn.execute(text("""
                DELETE FROM casbin_rule
                WHERE ptype = 'p'
                AND v0 = :role
                AND v1 = :obj
                AND v2 = :action
            """), {"role": role, "obj": obj, "action": action})

    conn.commit()
