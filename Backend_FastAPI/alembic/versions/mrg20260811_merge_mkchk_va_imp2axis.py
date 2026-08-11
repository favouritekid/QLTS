"""Hợp nhất hai nhánh migration: mkchk20260811 (PR #550) và imp2axis20260807.

Hai nhánh mọc song song từ ``dbte20260803002``:

    dbte20260803002
    ├── mkchk20260811                          # PR #550 — maker-checker
    └── dupguard20260807 → imp2axis20260807    # nhánh Duplicate Review Protocol

Sau khi #550 vào ``main``, cây có HAI head và ``alembic upgrade head`` từ chối
chạy. Revision này chỉ nối chúng lại; nó KHÔNG đụng gì tới lược đồ — mọi thay
đổi thật đã nằm ở hai nhánh cha.

Vì sao hợp nhất thay vì đổi cha của ``dupguard20260807``: các cơ sở dữ liệu
(dev, và mọi worktree đang chạy nhánh này) ĐÃ áp chuỗi ``dupguard →
imp2axis``. Đổi cha là viết lại lịch sử mà những DB ấy đã ghi vào
``alembic_version``; chúng sẽ không còn định vị được revision của mình. Merge
revision thì cộng thêm, không viết lại.

Revision ID: mrg20260811
Revises: mkchk20260811, imp2axis20260807
Create Date: 2026-08-11
"""
from typing import Sequence, Union


revision: str = "mrg20260811"
down_revision: Union[str, Sequence[str], None] = (
    "mkchk20260811",
    "imp2axis20260807",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Không có gì để làm — đây là điểm hợp lưu, không phải thay đổi lược đồ."""


def downgrade() -> None:
    """Tách lại thành hai head. Alembic tự lo phần bookkeeping."""
