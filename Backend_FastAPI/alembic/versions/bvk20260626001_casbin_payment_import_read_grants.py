"""BV-5 R2/R1: Casbin grant cho 2 route ĐỌC import (chi tiết lô + tải file kết quả)

Cấp quyền 2 route GET MỚI cho **accountant + manager** (đọc — như /import/batches):
  GET /api/payments/import/batches/{batch_id}          (R2: xem lại per-row)
  GET /api/payments/import/batches/{batch_id}/result   (R1: tải file kết quả)

- admin có wildcard ('/*', '.*') → không cần grant riêng.
- accountant + manager: cùng audience đọc với /import/batches (bvh) + /import/preview (bvg).
- officer/user KHÔNG cấp → CasbinAuth từ chối (403).
- v3='allow' (eft) BẮT BUỘC — auth_model.conf p=sub,obj,act,eft; thiếu v3 → grant bị bỏ
  khi load_policy. Casbin nạp lúc startup → RESTART backend sau migration.

Idempotent: WHERE NOT EXISTS + sweep NULL v3 (self-heal). Khớp style bvg/bvh/bvj.

Revision ID: bvk20260626001
Revises: bvj20260625001
Create Date: 2026-06-26
"""

from alembic import op
from sqlalchemy import text


revision = "bvk20260626001"
down_revision = "bvj20260625001"
branch_labels = None
depends_on = None


_DETAIL = "/api/payments/import/batches/{batch_id}"
_RESULT = "/api/payments/import/batches/{batch_id}/result"

# (v0 subject, v1 object, v2 action, template_id)
_GRANTS = [
    ("role:accountant", _DETAIL, "GET", "accountant"),
    ("role:accountant", _RESULT, "GET", "accountant"),
    ("role:manager", _DETAIL, "GET", "manager"),
    ("role:manager", _RESULT, "GET", "manager"),
]

_IMPORT_OBJECTS = f"'{_DETAIL}', '{_RESULT}'"


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
    print(f"[bvk20260626001] Seeded {len(_GRANTS)} casbin grant (read detail/result, eft=allow)")


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
