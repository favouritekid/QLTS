"""Backfill: gỡ double HTML-escape ("amp") trong school_name + family_info.

Revision ID: ampfix01_20260609
Revises: leadreopen_b_20260609
Create Date: 2026-06-09

Bug "amp": ``AcademicRecordSchema``/``FamilyMemberSchema`` html.escape() KHÔNG
idempotent (``&`` → ``&amp;``) + schema dùng chung request/response → mỗi vòng
đọc→sửa→lưu cộng thêm một lớp ``&amp;`` vào ``school_name`` (và text family).
Schema đã NGỪNG escape (commit trước); migration này gỡ các giá trị lịch sử đã
hỏng bằng ``html.unescape`` lặp tới khi ổn định.

- Predicate CHẶT: chỉ profiles có HTML entity trong academic_history/family_info.
- Idempotent: giá trị sạch unescape ra chính nó (chạy lại = no-op).
- Downgrade: no-op — double-escape là dữ liệu HỎNG, không tái tạo (forward-only).
- Scope đã verify (prod + dev 2026-06-09): 1 hồ sơ #31 (academic), 0 family.
"""
import html
import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ampfix01_20260609"
down_revision = "leadreopen_b_20260609"
branch_labels = None
depends_on = None

# HTML entity (độ dài thay đổi) còn sót trong giá trị đã lưu — POSIX regex.
_ENTITY_RE = r"&(amp;|#x[0-9a-fA-F]+;|#[0-9]+;|lt;|gt;|quot;)"

_FAMILY_TEXT_FIELDS = ("full_name", "occupation", "relationship")


def _unescape_stable(value):
    """html.unescape lặp tới khi ổn định — gỡ N lớp ``&amp;...``."""
    if not isinstance(value, str):
        return value
    prev = value
    for _ in range(20):  # guard; thực tế chỉ 8-9 lớp
        cur = html.unescape(prev)
        if cur == prev:
            return cur
        prev = cur
    return prev


def _clean_list(items, fields):
    """Unescape các field text trong list dict; trả True nếu có thay đổi."""
    changed = False
    for entry in items or []:
        if not isinstance(entry, dict):
            continue
        for field in fields:
            if isinstance(entry.get(field), str):
                new = _unescape_stable(entry[field])
                if new != entry[field]:
                    entry[field] = new
                    changed = True
    return changed


def _coerce_json(value):
    """JSONB qua sa.text() có thể về str (asyncpg) hoặc list/dict — chuẩn hóa."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, academic_history, family_info FROM admission_profile "
            "WHERE academic_history::text ~ :pat OR family_info::text ~ :pat"
        ),
        {"pat": _ENTITY_RE},
    ).fetchall()

    for row in rows:
        m = row._mapping
        academic = _coerce_json(m["academic_history"]) or []
        family = _coerce_json(m["family_info"]) or []

        a_changed = _clean_list(academic, ("school_name",))
        f_changed = _clean_list(family, _FAMILY_TEXT_FIELDS)

        if a_changed or f_changed:
            bind.execute(
                sa.text(
                    "UPDATE admission_profile "
                    "SET academic_history = CAST(:a AS jsonb), "
                    "    family_info = CAST(:f AS jsonb) "
                    "WHERE id = :id"
                ),
                {
                    "a": json.dumps(academic, ensure_ascii=False),
                    "f": json.dumps(family, ensure_ascii=False),
                    "id": m["id"],
                },
            )


def downgrade() -> None:
    # No-op: double-escape là dữ liệu hỏng — không tái tạo. Forward-only.
    pass
