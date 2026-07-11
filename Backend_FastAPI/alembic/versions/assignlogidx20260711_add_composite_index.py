"""add composite index assignment_log(lead_id, officer_id, timestamp DESC)

Hỗ trợ ``_self_sourced_subquery`` (khi ENABLE_DISTRIBUTION_EXCLUDE_SELF_SOURCED +
member/fairness): ``ORDER BY timestamp DESC LIMIT 1`` lọc theo (lead_id,
officer_id) — chạy 1 lần / lead-row của đơn vị. Index rời sẵn có (lead_id /
officer_id) KHÔNG phục vụ được ORDER BY timestamp → Postgres phải sort. Composite
(lead_id, officer_id, timestamp DESC) cho index-scan lấy bản ghi mới nhất của cặp.
Additive + reversible, KHÔNG đổi dữ liệu.

``assignment_log`` là bảng log nhỏ (1 dòng / sự kiện phân công, ~vài nghìn dòng)
nên ``CREATE INDEX`` thường (trong transaction) build mili-giây — KHÔNG cần
CONCURRENTLY (đơn giản + rollback an toàn). Nếu về sau bảng phình rất lớn, cân
nhắc rebuild CONCURRENTLY thủ công. Đồng bộ với model AssignmentLog.__table_args__.

Revision ID: assignlogidx20260711
Revises: zbmonthlyseed20260706
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "assignlogidx20260711"
down_revision = "zbmonthlyseed20260706"
branch_labels = None
depends_on = None

_INDEX = "ix_assignment_log_lead_officer_ts"
_TABLE = "assignment_log"


def upgrade():
    op.create_index(
        _INDEX,
        _TABLE,
        ["lead_id", "officer_id", sa.text("timestamp DESC")],
        unique=False,
    )


def downgrade():
    op.drop_index(_INDEX, table_name=_TABLE)
