"""PR #5: seed Casbin policies for document reviewer + paper-submit actions.

Revision ID: zz7h8i9j0k1l2
Revises: zz6g7h8i9j0k1
Create Date: 2026-04-24

Before PR #5 the document mutation routes (paper-submitted / verify-format /
reject / reset) were defended only by ``CasbinAuth`` but had no Casbin
policy rows, so officer / manager requests always returned 403. PR #5
adds per-doc permission flags to ``documents_checklist`` and wires the
FE buttons to them — those flags promise the user can actually invoke
the route. This migration brings prod DB policies in line with the
updated ``policy_templates.py``:

- officer role gets ``POST /documents/{doc_code}/paper-submitted``.
- manager role gets ``PATCH /documents/{doc_code}/verify-format``,
  ``POST /documents/{doc_code}/reject``, ``POST /documents/{doc_code}/reset``.

Admin already carries a wildcard ``/*`` `.*` row and needs no change.
The service layer enforces unit scope + allowed doc_status per
``_compute_document_permissions``.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "zz7h8i9j0k1l2"
down_revision: Union[str, None] = "nn20260422001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (subject, object, action) — matches the rows in policy_templates.py so
# a fresh seed + this migration produce the same end state.
NEW_POLICIES = [
    ("role:officer", "/api/admissions/{id}/documents/{doc_code}/paper-submitted", "POST"),
    ("role:manager", "/api/admissions/{id}/documents/{doc_code}/verify-format", "PATCH"),
    ("role:manager", "/api/admissions/{id}/documents/{doc_code}/reject", "POST"),
    ("role:manager", "/api/admissions/{id}/documents/{doc_code}/reset", "POST"),
]


def upgrade() -> None:
    """Insert missing Casbin rows; idempotent so reruns are safe."""
    for subject, obj, action in NEW_POLICIES:
        op.execute(
            f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT 'p', '{subject}', '{obj}', '{action}'
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = '{subject}'
                  AND v1 = '{obj}'
                  AND v2 = '{action}'
            )
            """
        )


def downgrade() -> None:
    """Remove the 4 rows if rolling back PR #5."""
    for subject, obj, action in NEW_POLICIES:
        op.execute(
            f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{subject}'
              AND v1 = '{obj}'
              AND v2 = '{action}'
            """
        )
