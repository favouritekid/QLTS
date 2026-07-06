"""index sms_landing_session.started_at cho retention DELETE (§16.9)

Hỗ trợ cron `cleanup_sms_interest_events_task` (`DELETE FROM sms_landing_session
WHERE started_at < cutoff`) — tránh seq-scan khi bảng phình theo traffic landing
công khai. Tạo rẻ (bảng gần rỗng lúc deploy — deep-tracking còn dormant §16.9).

Revision ID: smsp2retidx20260705001
Revises: memwt20260703001
Create Date: 2026-07-05
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "smsp2retidx20260705001"
down_revision = "memwt20260703001"
branch_labels = None
depends_on = None

_INDEX = "ix_sms_landing_session_started_at"
_TABLE = "sms_landing_session"


def upgrade() -> None:
    op.create_index(_INDEX, _TABLE, ["started_at"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
