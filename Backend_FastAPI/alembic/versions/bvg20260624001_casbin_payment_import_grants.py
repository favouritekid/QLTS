"""BV-2: Casbin grants cho route import thu học phí hàng loạt (template + preview)

Cấp quyền 2 route MỚI cho accountant + manager:
  GET  /api/payments/import/template
  POST /api/payments/import/preview

- admin đã có wildcard ('/*', '.*') → không cần grant riêng.
- officer/user KHÔNG được cấp → CasbinAuth từ chối (403). require_finance_staff là
  lớp gate thứ 2 (defense-in-depth) trên cùng route.
- Khớp ACCOUNTANT_TEMPLATE + MANAGER_TEMPLATE trong policy_templates.py (nguồn cho
  fresh-install / dev-test auto-seed); migration này seed cho DB prod đã có policy.
- commit/void/batches (ghi tiền/đảo lô) sẽ thêm grant ở BV-3 (CÙNG dual-gate pattern).

⚠️ PHẢI ghi v3='allow' (eft): auth_model.conf `p = sub, obj, act, eft` → row p thiếu
v3 sẽ bị bỏ khi load_policy (hoặc RuntimeError "invalid policy size") → grant vô
hiệu/sập auth. Đây đúng lỗi đã hotfix ở qae2e02_hotfix_null_eft_casbin_rules.py.
Casbin nạp policy lúc app startup → cần RESTART backend sau migration thì grant mới
hiệu lực (deploy.sh có restart).

Idempotent: WHERE NOT EXISTS (re-run an toàn) + sweep NULL v3 (self-heal).

Revision ID: bvg20260624001
Revises: bvi20260624001
Create Date: 2026-06-24
"""

from alembic import op
from sqlalchemy import text


revision = "bvg20260624001"
down_revision = "bvi20260624001"
branch_labels = None
depends_on = None


# (v0 subject, v1 object, v2 action, template_id)
_GRANTS = [
    ("role:accountant", "/api/payments/import/template", "GET", "accountant"),
    ("role:accountant", "/api/payments/import/preview", "POST", "accountant"),
    ("role:manager", "/api/payments/import/template", "GET", "manager"),
    ("role:manager", "/api/payments/import/preview", "POST", "manager"),
]

_IMPORT_OBJECTS = (
    "'/api/payments/import/template', '/api/payments/import/preview'"
)


def upgrade() -> None:
    for v0, v1, v2, tmpl in _GRANTS:
        # v3='allow' BẮT BUỘC (eft) — xem docstring + qae2e02.
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
    # Self-heal: grant đã tồn tại với v3 NULL (re-run sau bản thiếu eft) → set 'allow'.
    op.execute(
        text(
            f"""
            UPDATE casbin_rule SET v3 = CAST('allow' AS VARCHAR)
            WHERE ptype = 'p' AND v3 IS NULL AND v1 IN ({_IMPORT_OBJECTS})
            """
        )
    )
    print(f"[bvg20260624001] Seeded {len(_GRANTS)} casbin grants (eft=allow)")


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
