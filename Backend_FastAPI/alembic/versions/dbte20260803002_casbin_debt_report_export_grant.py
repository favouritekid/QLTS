"""PR-A: Casbin grant cho route xuất báo cáo công nợ

Cấp quyền route MỚI cho **accountant + manager**:
  GET /api/finance/debt-report/export

🔴 KHÁC với /api/invoices/export: policy hiện có cho báo cáo công nợ là literal
'/api/finance/debt-report', thêm một segment là **hết khớp keyMatch4** ⇒ thiếu
migration này thì accountant/manager nhận 403 THẬT (không có va chạm nào cứu).

- admin có wildcard ('/*', '.*') → không cần grant riêng.
- v3='allow' (eft) BẮT BUỘC — thiếu v3 → grant bị BỎ khi load_policy (qae2e02).
  Casbin nạp lúc startup → **RESTART backend sau migration**.

Idempotent: WHERE NOT EXISTS + sweep NULL v3. Khớp style bvg/bvh/bvj/texp.

Revision ID: dbte20260803002
Revises: texp20260803001
Create Date: 2026-08-03
"""

from alembic import op
from sqlalchemy import text


revision = "dbte20260803002"
down_revision = "texp20260803001"
branch_labels = None
depends_on = None


_GRANTS = [
    ("role:accountant", "/api/finance/debt-report/export", "GET", "accountant"),
    ("role:manager", "/api/finance/debt-report/export", "GET", "manager"),
]

_EXPORT_OBJECTS = "'/api/finance/debt-report/export'"


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
    print(
        f"[dbte20260803002] Seeded {len(_GRANTS)} casbin grant "
        "(debt-report export, eft=allow)"
    )


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
