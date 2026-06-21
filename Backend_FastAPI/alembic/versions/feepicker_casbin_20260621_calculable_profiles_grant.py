"""Finance "Tính phí" picker route Casbin grant (accountant + manager).

Seeds GET /api/fees/calculable-profiles for accountant + manager — the finance
picker endpoint that lets them search admission profiles to calculate a fee for
WITHOUT /api/admissions (accountant is DENIED that route by design, separation
of duties). Admin uses its wildcard. Without this the deploy entrypoint never
syncs the new template grant → enforcer 403s accountant/manager on the picker.
Same idempotent pattern as fincollect_casbin_20260621.

Revision ID: feepicker_casbin_20260621
Revises: accdead_casbin_20260621
Create Date: 2026-06-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "feepicker_casbin_20260621"
down_revision: Union[str, None] = "accdead_casbin_20260621"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (v0=sub, v1=obj, v2=act, v3=eft) — eft MUST be present (NULL v3 crashes load).
_POLICIES = [
    ("role:accountant", "/api/fees/calculable-profiles", "GET", "allow"),
    ("role:manager", "/api/fees/calculable-profiles", "GET", "allow"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _POLICIES:
        conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule
                    (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_feepicker_casbin_20260621',
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


def downgrade() -> None:
    conn = op.get_bind()
    for v0, v1, v2, v3 in _POLICIES:
        conn.execute(
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
