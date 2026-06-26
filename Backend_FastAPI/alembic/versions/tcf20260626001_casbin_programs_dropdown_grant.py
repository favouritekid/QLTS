"""Casbin grant GET /api/programs (dropdown ngành cho filter "Thu học phí")

Cấp quyền GET /api/programs (MajorProgram list) cho **officer + manager** — y hệt
/api/program-offerings (cùng mục đích "Dropdown data"). Accountant kế thừa officer
(g, role:accountant, role:officer) → cũng có quyền; admin có wildcard.

Service ``get_programs_by_unit_tree`` tự unit-scope manager/officer; accountant
(finance global read) thấy full list — chủ ý cho filter công nợ toàn đơn vị.

Trước fix này filter Ngành trống cho accountant/manager (403) vì chỉ
/api/program-offerings được cấp, KHÔNG có /api/programs.

- v3='allow' (eft) BẮT BUỘC — auth_model.conf p=sub,obj,act,eft; thiếu v3 → grant
  bị bỏ khi load_policy. Casbin nạp lúc startup → RESTART backend sau migration.
- Idempotent: WHERE NOT EXISTS + sweep NULL v3 (self-heal). Khớp style bvk.

Revision ID: tcf20260626001
Revises: 3a3edf2b968b
Create Date: 2026-06-26
"""

from alembic import op
from sqlalchemy import text


revision = "tcf20260626001"
down_revision = "3a3edf2b968b"
branch_labels = None
depends_on = None


_PROGRAMS = "/api/programs"

# (v0 subject, v1 object, v2 action, template_id) — mirror /api/program-offerings.
_GRANTS = [
    ("role:officer", _PROGRAMS, "GET", "officer"),
    ("role:manager", _PROGRAMS, "GET", "manager"),
]


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
            WHERE ptype = 'p' AND v3 IS NULL AND v1 = '{_PROGRAMS}'
            """
        )
    )
    print(f"[tcf20260626001] Seeded {len(_GRANTS)} casbin grant GET {_PROGRAMS} (eft=allow)")


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
