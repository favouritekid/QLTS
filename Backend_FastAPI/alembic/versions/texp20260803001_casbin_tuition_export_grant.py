"""PR-A: Casbin grant cho route xuất danh sách học phí

Cấp quyền route MỚI cho **accountant + manager**:
  GET /api/invoices/export

- admin có wildcard ('/*', '.*') → không cần grant riêng.
- officer/user KHÔNG được cấp → CasbinAuth từ chối (403); route còn dual-gate
  ``require_finance_staff`` nên bị chặn hai lớp.
- Khớp ACCOUNTANT_TEMPLATE + MANAGER_TEMPLATE (policy_templates.py); migration
  này seed cho DB prod đã có sẵn policy.
- ⚠️ ``keyMatch4`` khiến '/api/invoices/export' đã khớp NGẦM policy
  '/api/invoices/{id}' GET, nên thiếu grant này cũng chưa chắc 403. Vẫn khai
  tường minh theo convention của policy_templates.py (đừng dựa vào va chạm
  keyMatch4 — đổi shape route là mất quyền mà không ai biết vì sao).
- v3='allow' (eft) BẮT BUỘC — auth_model.conf p=sub,obj,act,eft; thiếu v3 →
  grant bị BỎ khi load_policy (xem qae2e02). Casbin nạp lúc startup →
  **RESTART backend sau migration**.

Idempotent: WHERE NOT EXISTS + sweep NULL v3 (self-heal). Khớp style bvg/bvh/bvj.

Revision ID: texp20260803001
Revises: majchg1g_pay_recmajor_20260724
Create Date: 2026-08-03
"""

from alembic import op
from sqlalchemy import text


revision = "texp20260803001"
down_revision = "majchg1g_pay_recmajor_20260724"
branch_labels = None
depends_on = None


# (v0 subject, v1 object, v2 action, template_id)
_GRANTS = [
    ("role:accountant", "/api/invoices/export", "GET", "accountant"),
    ("role:manager", "/api/invoices/export", "GET", "manager"),
]

_EXPORT_OBJECTS = "'/api/invoices/export'"


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
            WHERE ptype = 'p' AND v3 IS NULL AND v1 IN ({_EXPORT_OBJECTS})
            """
        )
    )
    print(f"[texp20260803001] Seeded {len(_GRANTS)} casbin grant (export, eft=allow)")


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
