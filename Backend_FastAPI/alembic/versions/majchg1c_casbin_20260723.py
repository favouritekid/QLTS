"""major-change reprice 1C — casbin grant accountant for confirm-major-change.

Route ``PUT /api/fees/{fee_id}/confirm-major-change`` (endpoint kế toán xác nhận
đổi ngành) gate bằng ``CasbinAuth``. Prod KHÔNG auto-sync template
(AUTO_SYNC_TEMPLATES False; docker-entrypoint.sh không có bước sync) → migration
này là đường ghi tự động DUY NHẤT vào casbin_rule cho DB live.

Grant ``role:accountant`` ALLOW (maker-checker: chỉ kế toán chốt tiền đổi ngành).
Admin giữ wildcard ``/*`` → tự khớp. Manager/officer KHÔNG được grant route này
(officer fee-grants chỉ GET; accountant inherit officer nhưng officer cũng không
có) → deny-by-default tự chặn, KHÔNG cần deny row.

Object dùng ``{id}`` (keyMatch4 pattern khớp path thật ``request.url.path`` —
xem deps.py:450). Segment cuối ``confirm-major-change`` là literal riêng nên
KHÔNG đụng keyMatch4 với ``/api/fees/{id}/waive|recalculate`` của manager.

Insert WITH v3='allow' (NULL eft làm ``load_policy`` crash — memory
casbin-insert-must-include-eft). ``template_id='_legacy'`` để drift/sync không
coi là orphan. Idempotent (WHERE NOT EXISTS kèm v3). Grant cũng thêm vào
ACCOUNTANT_TEMPLATE (policy_templates.py) để sync tương lai regenerate.

NOTE: RESTART backend sau upgrade — enforcer load policy 1 lần/process ở lifespan.

Revision ID: majchg1c_casbin_20260723
Revises: majchg1f_applied_rules_20260723
Create Date: 2026-07-23
"""
from alembic import op

revision = "majchg1c_casbin_20260723"
down_revision = "majchg1f_applied_rules_20260723"
branch_labels = None
depends_on = None


_OBJECT = "/api/fees/{id}/confirm-major-change"
_ACTION = "PUT"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
        SELECT 'p', 'role:accountant', '{_OBJECT}', '{_ACTION}', 'allow', '_legacy'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = 'role:accountant'
              AND v1 = '{_OBJECT}'
              AND v2 = '{_ACTION}'
              AND v3 IS NOT DISTINCT FROM 'allow'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM casbin_rule
        WHERE ptype = 'p'
          AND v0 = 'role:accountant'
          AND v1 = '{_OBJECT}'
          AND v2 = '{_ACTION}'
          AND v3 = 'allow'
        """
    )
