"""Manual-tuition-amount: Casbin grant cho GET /api/fees/tuition-preview.

Seeds GET /api/fees/tuition-preview cho officer + accountant — endpoint preview
giá chuẩn học phí (read-only) của add-on "Nhập học phí thủ công" trong dialog
Tính phí. Mirror đúng pattern grant /api/fees/calculate (officer + accountant
trong template; manager kế thừa officer qua edge g; admin qua wildcard).

Không có migration này, entrypoint deploy không sync grant template mới →
enforcer 403 officer/accountant trên endpoint preview (toggle nhập tay sẽ không
thấy được giá chuẩn / giảm giá / dự kiến phải thu).

Idempotent (INSERT WHERE NOT EXISTS) — cùng kiểu feepicker_casbin_20260621.

Revision ID: mta20260628001
Revises: feecancel20260628001
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "mta20260628001"
down_revision: Union[str, None] = "feecancel20260628001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (v0=sub, v1=obj, v2=act, v3=eft) — eft MUST be present (NULL v3 crashes load).
# officer + accountant chỉ — manager kế thừa officer (edge g, role:manager,
# role:officer), admin qua wildcard /*.*. Cùng tập với /api/fees/calculate.
_POLICIES = [
    ("role:officer", "/api/fees/tuition-preview", "GET", "allow"),
    ("role:accountant", "/api/fees/tuition-preview", "GET", "allow"),
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
                       '_mta20260628001',
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
