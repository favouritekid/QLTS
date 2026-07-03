"""SMS P2-3 consult officer Casbin grants (role:officer 2 route).

Seeds POST /api/sms/leads/{id}/consult-link + GET /api/sms/leads/{id}/interests
cho role:officer (manager kế thừa qua g, role:manager, role:officer; accountant
kế thừa nhưng get_lead_for_user chặn 404; admin dùng wildcard /*.*). Không có
migration này → entrypoint không sync template grant → CasbinAuth 403 officer.
Idempotent (mẫu feepicker_casbin_20260621).

Revision ID: smsp2consultcasbin20260702003
Revises: smsp2consult20260702002
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "smsp2consultcasbin20260702003"
down_revision: Union[str, None] = "smsp2consult20260702002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (v0=sub, v1=obj, v2=act, v3=eft) — eft MUST be present (NULL v3 crashes load).
# {id} = keyMatch4 named wildcard (giữ literal trong casbin_rule).
_POLICIES = [
    ("role:officer", "/api/sms/leads/{id}/consult-link", "POST", "allow"),
    ("role:officer", "/api/sms/leads/{id}/interests", "GET", "allow"),
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
                       '_smsp2consultcasbin20260702003',
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
