"""major-change reprice 1B — admission_profile.major_change_requested.

Cờ do admin đặt khi "trả hồ sơ cho phép đổi ngành" (``admin_rollback_profile`` /
``request_revision`` với ``allow_major_change=True``). Nó NỚI ``_assert_no_finance_lock``
CHỈ cho hồ sơ này (không nới theo status chung) và bypass ``assert_round_open``
cho ``add_choice``, để officer sửa nguyện vọng dù đã đóng học phí. Clear ở hook
submit/resubmit (mọi nhánh, kể cả no-op). Là VẾ CÒN LẠI của ``_major_change_cycle_open``.

Cột thuần cộng thêm (default false). Flag OFF → không code nào set/đọc → no-op.

Revision ID: majchg1b_profile_col_20260723
Revises: majchg1a_fee_cols_20260723
Create Date: 2026-07-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "majchg1b_profile_col_20260723"
down_revision: Union[str, None] = "majchg1a_fee_cols_20260723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "admission_profile"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "major_change_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Admin đã cho phép đổi ngành (nới finance lock + bypass round-open). Clear ở submit/resubmit.",
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE, "major_change_requested")
