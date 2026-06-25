"""BV-3.5: Casbin grant cho route void (đảo lô) import thu học phí hàng loạt

Cấp quyền route MỚI (đảo lô đã ghi tiền) cho **manager** (KHÔNG accountant):
  POST /api/payments/import/{batch_id}/void

- admin có wildcard ('/*', '.*') → không cần grant riêng.
- accountant CỐ Ý KHÔNG được cấp: void cao hơn finance staff (manager/admin). Route
  có dual-gate require_admin_or_manager nên accountant bị chặn cả 2 lớp.
- officer/user KHÔNG được cấp → CasbinAuth từ chối (403).
- Khớp MANAGER_TEMPLATE (policy_templates.py); migration này seed cho DB prod đã có policy.
- v3='allow' (eft) BẮT BUỘC — auth_model.conf p=sub,obj,act,eft; thiếu v3 → grant bị
  bỏ khi load_policy (xem qae2e02). Casbin nạp lúc startup → RESTART backend sau migration.

Idempotent: WHERE NOT EXISTS + sweep NULL v3 (self-heal). Khớp style bvg/bvh.

Revision ID: bvj20260625001
Revises: bvh20260624001
Create Date: 2026-06-25
"""

from alembic import op
from sqlalchemy import text


revision = "bvj20260625001"
down_revision = "bvh20260624001"
branch_labels = None
depends_on = None


# (v0 subject, v1 object, v2 action, template_id) — CHỈ manager.
_GRANTS = [
    ("role:manager", "/api/payments/import/{batch_id}/void", "POST", "manager"),
]

_IMPORT_OBJECTS = "'/api/payments/import/{batch_id}/void'"


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
    print(f"[bvj20260625001] Seeded {len(_GRANTS)} casbin grant (void, eft=allow)")


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
