"""dorm_sync_operations — sổ cái idempotency cho lượt đồng bộ ký túc xá

Revision ID: dsync20260807001
Revises: dbte20260803002
Create Date: 2026-08-07

🔴 Bảng này là hàng rào chống replay. ``sync_runs.note`` bên KTX KHÔNG đủ:
``find_run_by_token`` lọc ``status='running'`` nên lượt đã ``completed`` không
tìm thấy, và ``note`` là ``text`` thường không ràng buộc gì.

⚠️ CHECK constraint phải liệt kê ĐỦ BỐN trạng thái. ``outcome_unknown`` là trạng
thái non-terminal — gộp nó vào ``failed`` sẽ mời người vận hành chạy lại một
lượt có thể đã ghi xong, mà lượt hạ cờ thì không có đường lùi.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "dsync20260807001"
down_revision: Union[str, Sequence[str], None] = "dbte20260803002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dorm_sync_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "operation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Do server sinh lúc preview và ký trong token; client không đặt được.",
        ),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "snapshot_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'running'"),
            nullable=False,
        ),
        sa.Column("ktx_run_id", sa.Integer(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # RESTRICT chứ không CASCADE: đây là sổ đối soát giữa hai hệ, xoá người
        # bấm là mất dấu vết của một thao tác đã đổi dữ liệu bên KTX.
        sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation_id", name="uq_dorm_sync_operations_operation_id"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'outcome_unknown')",
            name="ck_dorm_sync_operations_status",
        ),
    )
    op.create_index(
        "ix_dorm_sync_operations_operation_id",
        "dorm_sync_operations",
        ["operation_id"],
    )
    op.create_index(
        "ix_dorm_sync_operations_actor_id", "dorm_sync_operations", ["actor_id"]
    )
    op.create_index(
        "ix_dorm_sync_operations_academic_year",
        "dorm_sync_operations",
        ["academic_year"],
    )
    op.create_index(
        "ix_dorm_sync_operations_status", "dorm_sync_operations", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_dorm_sync_operations_status", table_name="dorm_sync_operations")
    op.drop_index(
        "ix_dorm_sync_operations_academic_year", table_name="dorm_sync_operations"
    )
    op.drop_index("ix_dorm_sync_operations_actor_id", table_name="dorm_sync_operations")
    op.drop_index(
        "ix_dorm_sync_operations_operation_id", table_name="dorm_sync_operations"
    )
    op.drop_table("dorm_sync_operations")
