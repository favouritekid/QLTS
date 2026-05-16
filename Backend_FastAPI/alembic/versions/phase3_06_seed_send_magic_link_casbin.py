"""Phase 3 Wave 7 — seed /send-magic-link Casbin policies (W2-1 fix)

2026-05-16 ship: New endpoint POST /api/admissions/{id}/send-magic-link
(generate magic-link cho 3 actions submit/resubmit/withdraw) requires
Casbin policy entries. Per ROLE inheritance:
- officer ALLOW (chính chủ profile)
- manager ALLOW (unit scope)
- admin: via wildcard `/*`
- accountant DENY (separation-of-duties — finance staff không tạo
  magic-link cho candidate self-service)

Mirror /send-confirmation policy shape (officer line 165, manager line 432,
accountant deny line 377).

Idempotent INSERT WHERE NOT EXISTS — safe re-run.

Revision ID: phase3_06
Revises: phase3_05
Create Date: 2026-05-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase3_06"
down_revision: Union[str, None] = "phase3_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEND_MAGIC_LINK_POLICIES = [
    ("role:officer", "/api/admissions/{id}/send-magic-link", "POST", "allow"),
    ("role:manager", "/api/admissions/{id}/send-magic-link", "POST", "allow"),
    ("role:accountant", "/api/admissions/{id}/send-magic-link", "POST", "deny"),
]


def upgrade() -> None:
    conn = op.get_bind()
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule WHERE v1='/api/admissions/{id}/send-magic-link'"
        )
    ).scalar()
    print(f"[phase3_06] Pre-flight: existing send-magic-link policy rows={pre_count}")

    inserted = 0
    for v0, v1, v2, v3 in _SEND_MAGIC_LINK_POLICIES:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_phase3_06_send_magic_link',
                       NOW()
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype='p'
                      AND v0=CAST(:v0 AS VARCHAR)
                      AND v1=CAST(:v1 AS VARCHAR)
                      AND v2=CAST(:v2 AS VARCHAR)
                      AND v3=CAST(:v3 AS VARCHAR)
                )
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
        inserted += result.rowcount

    print(f"[phase3_06] Seeded {inserted} new policy row(s).")


def downgrade() -> None:
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _SEND_MAGIC_LINK_POLICIES:
        result = conn.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
                """
            ),
            {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
        )
        deleted += result.rowcount
    print(f"[phase3_06] Removed {deleted} policy row(s).")
