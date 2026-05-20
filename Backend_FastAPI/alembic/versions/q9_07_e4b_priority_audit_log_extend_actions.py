"""q9_07_e4b: extend priority_audit_log action_type CHECK with E.4 actions

Revision ID: q9_07_e4b
Revises: q9_07_e4a
Create Date: 2026-05-20

Q9 #07 Phase E.4 — Priority Workbench foundation. priority_audit_log
CHECK ck_priority_audit_log_action_type hiện chỉ allow 4 actions từ
Phase E.0a:
  - kv_manual_override
  - ut_evidence_verified
  - ut_evidence_rejected
  - admin_bulk_fill

Phase E.4 thêm 2 actions:
  - ut_evidence_untick — G1 atomic delete khi officer untick UT code
    có file đính kèm (cascade hard delete + JSONB cleanup).
  - ut_evidence_warning_dismissed — Decision #2 audit khi officer submit
    hồ sơ với missing_priority_evidence_codes non-empty (track only,
    KHÔNG block submit).

Migration is metadata-only — drop + recreate CHECK constraint là
instant DDL trên PostgreSQL, zero downtime. Existing rows không bị
ảnh hưởng (4 action types cũ vẫn pass new CHECK).

Downgrade: revert CHECK to 4 actions only. Nếu có audit rows với 2
action mới tại thời điểm downgrade, CHECK validation sẽ fail —
manually delete những rows đó trước, hoặc skip downgrade migration.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers
revision: str = "q9_07_e4b"
down_revision: Union[str, None] = "q9_07_e4a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_CHECK = (
    "action_type IN ("
    "'kv_manual_override',"
    "'ut_evidence_verified',"
    "'ut_evidence_rejected',"
    "'admin_bulk_fill',"
    "'ut_evidence_untick',"
    "'ut_evidence_warning_dismissed'"
    ")"
)

_OLD_CHECK = (
    "action_type IN ("
    "'kv_manual_override',"
    "'ut_evidence_verified',"
    "'ut_evidence_rejected',"
    "'admin_bulk_fill'"
    ")"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_priority_audit_log_action_type",
        "priority_audit_log",
        type_="check",
    )
    op.create_check_constraint(
        "ck_priority_audit_log_action_type",
        "priority_audit_log",
        _NEW_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_priority_audit_log_action_type",
        "priority_audit_log",
        type_="check",
    )
    op.create_check_constraint(
        "ck_priority_audit_log_action_type",
        "priority_audit_log",
        _OLD_CHECK,
    )
