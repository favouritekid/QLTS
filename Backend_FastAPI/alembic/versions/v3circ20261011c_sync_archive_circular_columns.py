"""Đồng bộ `_archived_admission_profile` với 6 cột V3 (lần nộp đầu + thông tư áp dụng).

Revision ID: v3circ20261011c
Revises: v3circ20261011b
Create Date: 2026-10-11

Bảng archive phải soi gương ``AdmissionProfile`` THEO TÊN, cùng kiểu và cùng nullability (giao ước sửa lại ở
``arch20260829``; ``tests/unit/test_phase1_16_archived_admission_profile.py`` khoá bằng cách dựng lại từng
``sa.Column`` trong các lời gọi ``op.add_column(TABLE, …)``). ``v3circ20261011`` thêm 6 cột vào bảng nguồn bằng một
câu ``DO`` — phép kiểm AST không thấy SQL thô, và quan trọng hơn: bảng archive chưa có 6 cột ấy.

Khuôn giữ nguyên theo ``arch20260829``:
* cột khai NỘI TUYẾN trong từng ``op.add_column`` (phép kiểm khoanh vùng theo lời gọi);
* idempotent theo cột (chạy lại bỏ qua cột đã có);
* bảng archive THIẾU ⇒ NÉM, không ``return`` (không để Alembic đánh dấu revision là đã áp khi không thêm gì);
* KHÔNG khoá ngoại / CHECK — archive phải nhận hàng lịch sử vi phạm giao ước hiện tại.

Cả 6 cột đều nullable, không server_default ⇒ ``ADD COLUMN`` an toàn khi bảng đã có hàng. Mỗi ``add_column`` một lệnh
(AUTOCOMMIT): đổ giữa chừng thì chạy lại — các cột đã thêm được bỏ qua.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "v3circ20261011c"
down_revision: Union[str, None] = "v3circ20261011b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "_archived_admission_profile"
_TEN_COT = (
    "first_submitted_at",
    "first_submitted_source",
    "applicable_circular",
    "applicable_circular_source",
    "applicable_circular_set_at",
    "applicable_circular_set_by_id",
)


class BangArchiveThieu(RuntimeError):
    """Bảng archive không tồn tại lúc migration này chạy — schema đích bị can thiệp ngoài luồng; KHÔNG nuốt."""


def _cot_hien_co() -> set:
    inspector = inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        raise BangArchiveThieu(
            f"Bảng {TABLE!r} không tồn tại (phải do `phase1_16` tạo). Không thêm cột nào, KHÔNG đánh dấu revision."
        )
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    hien_co = _cot_hien_co()
    if "first_submitted_at" not in hien_co:
        op.add_column(TABLE, sa.Column("first_submitted_at", sa.DateTime(timezone=True), nullable=True))
    if "first_submitted_source" not in hien_co:
        op.add_column(TABLE, sa.Column("first_submitted_source", sa.String(length=24), nullable=True))
    if "applicable_circular" not in hien_co:
        op.add_column(TABLE, sa.Column("applicable_circular", sa.String(length=16), nullable=True))
    if "applicable_circular_source" not in hien_co:
        op.add_column(TABLE, sa.Column("applicable_circular_source", sa.String(length=32), nullable=True))
    if "applicable_circular_set_at" not in hien_co:
        op.add_column(TABLE, sa.Column("applicable_circular_set_at", sa.DateTime(timezone=True), nullable=True))
    if "applicable_circular_set_by_id" not in hien_co:
        op.add_column(TABLE, sa.Column("applicable_circular_set_by_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    hien_co = _cot_hien_co()
    for cot in reversed(_TEN_COT):
        if cot in hien_co:
            op.drop_column(TABLE, cot)
