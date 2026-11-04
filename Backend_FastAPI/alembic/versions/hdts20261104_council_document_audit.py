"""Vết xoá + nhật ký tải bộ văn bản Hội đồng (Lần xét tuyển GĐ1, lượt E3 — owner 04-11).

Revision ID: hdts20261104
Revises: hdts20261103b
Create Date: 2026-11-04

Hai bảng MỚI (không chạm bảng nào đang có), sống ĐỘC LẬP với bộ văn bản — KHÔNG khoá ngoại tới
``council_document_set`` (xoá bộ không cascade mất vết) hay ``user`` (giữ nguyên id người làm):

* ``council_document_set_deletion`` — Admin xoá một bộ (``Y-TUONG-…`` J1 dòng 29): id bộ, số
  hồ sơ, danh sách tệp (thứ tự, path, sha256, kích thước), người xoá, lúc xoá, lý do bắt buộc.
  UNIQUE (set_id). KHÔNG danh sách CCCD, KHÔNG DTO.
* ``council_document_download_log`` — mỗi lần máy chủ CẤP một tệp (J1 dòng 31): người, bộ,
  thứ tự tệp, path, sha256, lúc.

CHECK khai ĐÚNG chuỗi của model (``app/models/council_document.py``) — CSDL test dựng bằng
``create_all()``; ``tests/unit/test_council_document_models.py`` so hai bên. Migration chạy
ở AUTOCOMMIT (``alembic/env.py``) ⇒ mọi lệnh tạo đều ``IF NOT EXISTS`` (chạy lại được).

``downgrade`` XOÁ hai bảng — tức xoá mọi vết xoá và nhật ký tải (bằng chứng truy vết, không
dựng lại được) ⇒ FAIL-CLOSED như ``hdts20261103``: bảng nào còn hàng thì DỪNG, không xoá gì,
trừ khi đặt ``COUNCIL_DOCS_AUDIT_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ mang nghĩa CHO PHÉP, mặc
định tắt; đúng chuỗi ``1`` — CLAUDE.md §8). Cờ RIÊNG với cờ của ``hdts20261103``: bỏ bằng
chứng truy vết là một quyết định khác bỏ bộ văn bản. Sao lưu trước khi bật cờ.
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "hdts20261104"
down_revision: Union[str, None] = "hdts20261103b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

XOA = "council_document_set_deletion"
TAI = "council_document_download_log"

LY_DO_XOA_TOI_DA = 1000
CHECK_DANH_SACH_TEP = (
    "jsonb_typeof(danh_sach_tep) = 'array' "
    "AND jsonb_array_length(danh_sach_tep) = so_tep"
)
CHECK_LY_DO = "char_length(btrim(ly_do)) > 0"
CHECK_SHA_HEX = "sha256 ~ '^[0-9a-f]{64}$'"

CO_CHO_PHEP_XOA = "COUNCIL_DOCS_AUDIT_DOWNGRADE_DROP_DATA_ENABLED"


class ConVetVanBanHoiDong(RuntimeError):
    """downgrade gặp bảng vết còn hàng mà cờ cho phép xoá chưa bật — không xoá gì."""


def upgrade() -> None:
    op.create_table(
        XOA,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("so_ho_so", sa.Integer(), nullable=False),
        sa.Column("so_tep", sa.Integer(), nullable=False),
        sa.Column(
            "danh_sach_tep", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("nguoi_xoa_id", sa.Integer(), nullable=False),
        sa.Column(
            "xoa_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ly_do", sa.String(length=LY_DO_XOA_TOI_DA), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_id", name="uq_council_document_set_deletion_set_id"),
        sa.CheckConstraint(
            "so_ho_so > 0", name="ck_council_document_set_deletion_so_ho_so"
        ),
        sa.CheckConstraint(
            "so_tep > 0", name="ck_council_document_set_deletion_so_tep"
        ),
        sa.CheckConstraint(
            CHECK_DANH_SACH_TEP, name="ck_council_document_set_deletion_danh_sach_tep"
        ),
        sa.CheckConstraint(CHECK_LY_DO, name="ck_council_document_set_deletion_ly_do"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_council_document_set_deletion_xoa_luc", XOA, ["xoa_luc"], if_not_exists=True
    )

    op.create_table(
        TAI,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("thu_tu", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("nguoi_tai_id", sa.Integer(), nullable=False),
        sa.Column(
            "tai_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "thu_tu >= 1", name="ck_council_document_download_log_thu_tu"
        ),
        sa.CheckConstraint("path <> ''", name="ck_council_document_download_log_path"),
        sa.CheckConstraint(
            CHECK_SHA_HEX, name="ck_council_document_download_log_sha256"
        ),
        if_not_exists=True,
    )
    for cot in ("set_id", "tai_luc"):
        op.create_index(
            "ix_council_document_download_log_%s" % cot, TAI, [cot], if_not_exists=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    co = set(inspect(bind).get_table_names())
    con_hang = [
        b
        for b in (XOA, TAI)
        if b in co
        and bind.execute(text('SELECT EXISTS (SELECT 1 FROM "%s")' % b)).scalar()
    ]
    if con_hang and os.environ.get(CO_CHO_PHEP_XOA) != "1":
        raise ConVetVanBanHoiDong(
            "Bảng %s còn dữ liệu (vết xoá / nhật ký tải bộ văn bản Hội đồng). Không xoá gì. "
            "Sao lưu rồi đặt %s=1 nếu thật sự muốn xoá."
            % (", ".join(con_hang), CO_CHO_PHEP_XOA)
        )
    op.drop_table(TAI, if_exists=True)
    op.drop_table(XOA, if_exists=True)
