"""resetcasbin01: seed Casbin policy cho officer RESET tài liệu

Revision ID: resetcasbin01
Revises: ampfix01_20260609
Create Date: 2026-06-09

BR3 (2026-06-09) — officer được tự RESET tài liệu của hồ sơ mình phụ trách khi
hồ sơ ở draft/rejected/revision_requested (gỡ submission để sửa). Route
``POST /api/admissions/{id}/documents/{doc_code}/reset`` được ``CasbinAuth`` bảo
vệ và TRƯỚC ĐÂY chỉ nằm trong MANAGER_TEMPLATE → officer bị 403 ở tầng route.

``policy_templates.py`` đã thêm 1 ALLOW row vào OFFICER_TEMPLATE trong CÙNG
commit. Nhưng auto-sync template chỉ chạy ở dev/test; prod KHÔNG sync → cần
migration seed row ``role:officer`` cho prod (nếu thiếu: dev PASS nhưng prod
officer-reset 403, bug ẩn dev-prod). Service ``DocumentActionPolicy`` mới
narrows tiếp owner + OWNER_DOC_MUTATION_STATES + doc non-missing; reset KHÔNG
mở verify/reject.

Manager + admin đã có reset (MANAGER_TEMPLATE + admin ``/*`` wildcard) → chỉ
seed lone ``role:officer`` row để "fresh seed + migration = same end state".
Accountant: no deny (mirror paper-submitted/graduation-proof family — finance
không qua owning-officer IDOR scope nên allow kế thừa là moot).

Per memory ``casbin-insert-must-include-eft``: v3 (eft) BẮT BUỘC trong INSERT —
NULL eft làm ``load_policy()`` crash → 500. Idempotent ``INSERT ... WHERE NOT
EXISTS`` để rerun + boot ``sync_casbin_policy`` an toàn.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "resetcasbin01"
down_revision: Union[str, None] = "ampfix01_20260609"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Single row: (v0=subject, v1=object, v2=action, v3=eft). Mirror lone row thêm
# vào OFFICER_TEMPLATE — manager/admin kế thừa, accountant moot.
_OFFICER_RESET_POLICIES = [
    (
        "role:officer",
        "/api/admissions/{id}/documents/{doc_code}/reset",
        "POST",
        "allow",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM casbin_rule "
            "WHERE v1 LIKE '/api/admissions/%documents%reset' AND v0='role:officer'"
        )
    ).scalar()
    print(f"[resetcasbin01] Pre-flight: existing officer-reset rows={pre_count}")

    inserted = 0
    for v0, v1, v2, v3 in _OFFICER_RESET_POLICIES:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO casbin_rule
                    (ptype, v0, v1, v2, v3, template_id, applied_at)
                SELECT 'p',
                       CAST(:v0 AS VARCHAR),
                       CAST(:v1 AS VARCHAR),
                       CAST(:v2 AS VARCHAR),
                       CAST(:v3 AS VARCHAR),
                       '_resetcasbin01_officer_reset_seed',
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
        inserted += result.rowcount

    print(f"[resetcasbin01] Seeded {inserted} new policy row(s).")


def downgrade() -> None:
    conn = op.get_bind()
    deleted = 0
    for v0, v1, v2, v3 in _OFFICER_RESET_POLICIES:
        result = conn.execute(
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
        deleted += result.rowcount
    print(f"[resetcasbin01] Removed {deleted} policy row(s).")
