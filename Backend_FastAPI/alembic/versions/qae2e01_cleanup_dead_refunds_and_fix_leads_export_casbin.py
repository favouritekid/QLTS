"""Cleanup dead /api/refunds/* + fix /api/leads/export Casbin policies.

Revision ID: qae2e01
Revises: phase3_06
Create Date: 2026-05-16

Post-QA-E2E findings 2026-05-16 cleanup:

**W2-2** (refunds dead policy): ACCOUNTANT_TEMPLATE seeded 4 entries cho
`/api/refunds/*` nhưng router không tồn tại (live probe → 404). Refunds
module deferred per memory `finance-event-decisions` (REFUND_PROCESSED
tagged internal_future, 0 prod traffic). Promote khi router ships.

**W2-3** (leads export path mismatch): MANAGER_TEMPLATE seeded 2 entries
cho `/api/leads/export/csv` + `/api/leads/export/excel` nhưng router
actual là `/api/leads/export` single endpoint với `?format=csv|excel`
query param (router: leads.py:315). FE Axios call `/api/leads/export`
đúng nhưng Casbin 404 path → manager bị block "Xuất CSV/Excel". Fix:
DELETE 2 wrong entries, INSERT 1 correct `/api/leads/export` GET.

Idempotent. Re-run safe.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "qae2e01"
down_revision: Union[str, None] = "phase3_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Dead refunds policies (ACCOUNTANT_TEMPLATE) — REMOVE
DEAD_REFUNDS = [
    ("/api/refunds",              "GET"),
    ("/api/refunds/{id}",         "GET"),
    ("/api/refunds/request",      "POST"),
    ("/api/refunds/{id}/process", "PUT"),
]

# Wrong leads export paths (MANAGER_TEMPLATE) — REMOVE
WRONG_LEADS_EXPORT = [
    ("/api/leads/export/csv",   "GET"),
    ("/api/leads/export/excel", "GET"),
]


def upgrade() -> None:
    # ---- W2-2: Remove 4 dead /api/refunds/* entries from accountant ----
    for obj, act in DEAD_REFUNDS:
        op.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype = CAST(:ptype AS VARCHAR)
                  AND v0 = CAST(:v0 AS VARCHAR)
                  AND v1 = CAST(:v1 AS VARCHAR)
                  AND v2 = CAST(:v2 AS VARCHAR)
                """
            ).bindparams(
                ptype="p",
                v0="role:accountant",
                v1=obj,
                v2=act,
            )
        )

    # ---- W2-3: Fix /api/leads/export Casbin path mismatch ----
    # Delete 2 wrong entries from manager
    for obj, act in WRONG_LEADS_EXPORT:
        op.execute(
            sa.text(
                """
                DELETE FROM casbin_rule
                WHERE ptype = CAST(:ptype AS VARCHAR)
                  AND v0 = CAST(:v0 AS VARCHAR)
                  AND v1 = CAST(:v1 AS VARCHAR)
                  AND v2 = CAST(:v2 AS VARCHAR)
                """
            ).bindparams(
                ptype="p",
                v0="role:manager",
                v1=obj,
                v2=act,
            )
        )

    # Insert correct entry (idempotent — skip if already exists)
    op.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2)
            SELECT CAST('p' AS VARCHAR), CAST('role:manager' AS VARCHAR),
                   CAST('/api/leads/export' AS VARCHAR), CAST('GET' AS VARCHAR)
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = 'role:manager'
                  AND v1 = '/api/leads/export'
                  AND v2 = 'GET'
            )
            """
        )
    )


def downgrade() -> None:
    # Re-insert dead refunds policies (idempotent)
    for obj, act in DEAD_REFUNDS:
        op.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2)
                SELECT CAST('p' AS VARCHAR), CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR), CAST(:v2 AS VARCHAR)
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p' AND v0 = :v0 AND v1 = :v1 AND v2 = :v2
                )
                """
            ).bindparams(
                v0="role:accountant",
                v1=obj,
                v2=act,
            )
        )

    # Restore wrong leads export paths + remove correct one
    for obj, act in WRONG_LEADS_EXPORT:
        op.execute(
            sa.text(
                """
                INSERT INTO casbin_rule (ptype, v0, v1, v2)
                SELECT CAST('p' AS VARCHAR), CAST('role:manager' AS VARCHAR),
                       CAST(:v1 AS VARCHAR), CAST(:v2 AS VARCHAR)
                WHERE NOT EXISTS (
                    SELECT 1 FROM casbin_rule
                    WHERE ptype = 'p' AND v0 = 'role:manager'
                      AND v1 = :v1 AND v2 = :v2
                )
                """
            ).bindparams(
                v1=obj,
                v2=act,
            )
        )

    op.execute(
        sa.text(
            """
            DELETE FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:manager'
              AND v1 = '/api/leads/export'
              AND v2 = 'GET'
            """
        )
    )
