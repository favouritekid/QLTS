"""BV-3: Casbin grants cho route commit + lịch sử lô import thu học phí

Cấp quyền 2 route MỚI (ghi tiền) cho accountant + manager:
  POST /api/payments/import/{batch_id}/commit
  GET  /api/payments/import/batches

- admin có wildcard ('/*', '.*') → không cần grant riêng.
- officer/user KHÔNG được cấp → CasbinAuth từ chối (403) + require_finance_staff (dual-gate).
- Khớp ACCOUNTANT_TEMPLATE + MANAGER_TEMPLATE (policy_templates.py).
- v3='allow' (eft) BẮT BUỘC — auth_model.conf p=sub,obj,act,eft; thiếu v3 → grant bị
  bỏ khi load_policy (xem qae2e02). Casbin nạp lúc startup → RESTART backend sau migration.

Idempotent: WHERE NOT EXISTS + sweep NULL v3 (self-heal). Khớp style bvg20260624001.

Revision ID: bvh20260624001
Revises: bvg20260624001
Create Date: 2026-06-24
"""

from alembic import op
from sqlalchemy import text


revision = "bvh20260624001"
down_revision = "bvg20260624001"
branch_labels = None
depends_on = None


# (v0 subject, v1 object, v2 action, template_id)
_GRANTS = [
    ("role:accountant", "/api/payments/import/{batch_id}/commit", "POST", "accountant"),
    ("role:accountant", "/api/payments/import/batches", "GET", "accountant"),
    ("role:manager", "/api/payments/import/{batch_id}/commit", "POST", "manager"),
    ("role:manager", "/api/payments/import/batches", "GET", "manager"),
]

_IMPORT_OBJECTS = (
    "'/api/payments/import/{batch_id}/commit', '/api/payments/import/batches'"
)


def upgrade() -> None:
    for v0, v1, v2, tmpl in _GRANTS:
        op.execute(
            text(
                f"""
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
            SELECT 'p', '{v0}', '{v1}', '{v2}', 'allow', '{tmpl}', NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
            )
            """
            )
        )
    op.execute(
        text(
            f"""
            UPDATE casbin_rule SET v3 = CAST('allow' AS VARCHAR)
            WHERE ptype = 'p' AND v3 IS NULL AND v1 IN ({_IMPORT_OBJECTS})
            """
        )
    )
    print(f"[bvh20260624001] Seeded {len(_GRANTS)} casbin grants (eft=allow)")


def downgrade() -> None:
    for v0, v1, v2, _tmpl in _GRANTS:
        op.execute(
            text(
                f"""
            DELETE FROM casbin_rule
            WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' AND v2 = '{v2}'
            """
            )
        )
