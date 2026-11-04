"""Kho mẫu + bộ văn bản Hội đồng tuyển sinh (giai đoạn 1 "Lần xét tuyển" — PR 1.2 / 1.4).

Revision ID: hdts20261103
Revises: v3circ20261011c
Create Date: 2026-11-03

Ba bảng MỚI (không chạm bảng nào đang có):

* ``council_document_template`` — mẫu Word (bytea) + sha256 + ngày hiệu lực theo ngày ký;
  UNIQUE (loai, hieu_luc_tu).
* ``council_document_set`` — metadata của một lần dựng: người tạo, lúc tạo, mốc chụp của
  giao dịch đọc, đơn vị (NULL = chỉ admin xem), trình độ, số hồ sơ, tham số QĐ, danh sách mã
  đầu vào + ảnh chụp DTO (DỮ LIỆU CÁ NHÂN), thông tin bộ dựng.
* ``council_document_set_file`` — bytes nguyên từng tệp; FK ON DELETE CASCADE; UNIQUE
  (set_id, path) và (set_id, thu_tu).

CHECK khai ĐÚNG chuỗi của model (``app/models/council_document.py``) — CSDL test dựng bằng
``create_all()``; ``tests/unit/test_council_document_models.py`` so hai bên. CSDL tự canh:
``kich_thuoc = octet_length(noi_dung)``, ``sha256 = encode(sha256(noi_dung), 'hex')`` (hàm
``sha256(bytea)`` có từ PostgreSQL 11, IMMUTABLE), độ dài hai mảng JSON = ``so_ho_so``.

Migration chạy ở AUTOCOMMIT (``alembic/env.py``) ⇒ mỗi lệnh tự commit: mọi lệnh tạo đều
``IF NOT EXISTS`` để đổ giữa chừng thì chạy lại được.

``downgrade`` XOÁ ba bảng — tức xoá mọi mẫu đã tải và mọi bộ văn bản đã lưu (có dữ liệu cá
nhân, không dựng lại được). Vì vậy nó FAIL-CLOSED: bảng nào còn hàng thì DỪNG, không xoá gì,
trừ khi đặt ``COUNCIL_DOCS_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ mang nghĩa CHO PHÉP, mặc định
tắt — CLAUDE.md §8). Sao lưu trước khi bật cờ.

Kiểm–xoá NGUYÊN TỬ (E4 — nhánh anh em của F222 do người điều phối nêu): dưới AUTOCOMMIT của
``env.py``, khuôn cũ (``SELECT EXISTS`` rồi ``DROP`` — nhiều câu) để một lần tạo bộ / tải mẫu
chen giữa ⇒ mất bộ văn bản dù cờ chưa bật. Nay khoá + kiểm + xoá là MỘT câu ``DO``
(:func:`_sql_ha_cap`; cùng khuôn với ``hdts20261104``): ``LOCK TABLE … ACCESS EXCLUSIVE`` theo thứ
tự mẫu → bộ → tệp (thứ tự ghi của luồng tạo bộ) TRƯỚC khi kiểm, kiểm bằng ảnh chụp mới sau khoá
(READ COMMITTED), rồi DROP tệp → bộ → mẫu — vẫn giữ khoá. Mức cô lập khác READ COMMITTED ⇒ từ
chối, không xoá gì (:class:`HaCapCanReadCommitted`).
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "hdts20261103"
down_revision: Union[str, None] = "v3circ20261011c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MAU = "council_document_template"
BO = "council_document_set"
TEP = "council_document_set_file"

CHECK_LOAI_MAU = "loai IN ('bien_ban', 'quyet_dinh', 'danh_sach')"
CHECK_SHA_NOI_DUNG = "sha256 = encode(sha256(noi_dung), 'hex')"
CHECK_KICH_THUOC = "kich_thuoc > 0 AND kich_thuoc = octet_length(noi_dung)"
CHECK_MANG_MA = (
    "jsonb_typeof(ma_ho_so_dau_vao) = 'array' "
    "AND jsonb_array_length(ma_ho_so_dau_vao) = so_ho_so"
)
CHECK_MANG_DTO = (
    "jsonb_typeof(snapshot_dto) = 'array' "
    "AND jsonb_array_length(snapshot_dto) = so_ho_so"
)

CO_CHO_PHEP_XOA = "COUNCIL_DOCS_DOWNGRADE_DROP_DATA_ENABLED"


class ConDuLieuVanBanHoiDong(RuntimeError):
    """downgrade gặp bảng còn hàng mà cờ cho phép xoá chưa bật — không xoá gì."""


class HaCapCanReadCommitted(RuntimeError):
    """downgrade chạy ở mức cô lập khác READ COMMITTED — không xoá gì (kiểm sau khoá cần ảnh
    chụp mới)."""


_DAU_CAN_RC = "HDTS20261103_CAN_READ_COMMITTED"


def _sql_ha_cap(cho_phep: bool) -> str:
    """MỘT câu ``DO`` (cùng khuôn ``hdts20261104``): chặn khi không phải READ COMMITTED; khoá
    ACCESS EXCLUSIVE mẫu → bộ → tệp (bảng đang có); kiểm còn hàng sau khoá; còn hàng mà cờ chưa
    bật ⇒ ``RETURN`` (KHÔNG xoá gì, Python báo lỗi miền); không thì DROP tệp → bộ → mẫu.
    """
    if not isinstance(cho_phep, bool):
        raise TypeError("cho_phep phải là bool")
    khoa = "".join(
        "    IF to_regclass('%s') IS NOT NULL THEN\n"
        '        LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n'
        "    END IF;\n" % (b, b)
        for b in (MAU, BO, TEP)
    )
    kiem = "".join(
        "    IF to_regclass('%s') IS NOT NULL THEN\n"
        '        co_hang := co_hang OR EXISTS (SELECT 1 FROM "%s");\n'
        "    END IF;\n" % (b, b)
        for b in (MAU, BO, TEP)
    )
    return (
        "DO $hdts20261103_ha_cap$\n"
        "DECLARE\n"
        "    co_hang boolean := false;\n"
        "BEGIN\n"
        "    IF current_setting('transaction_isolation') <> 'read committed' THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END IF;\n"
        "%s%s"
        "    IF co_hang AND NOT %s THEN\n"
        "        RETURN;\n"
        "    END IF;\n"
        '    DROP TABLE IF EXISTS "%s";\n'
        '    DROP TABLE IF EXISTS "%s";\n'
        '    DROP TABLE IF EXISTS "%s";\n'
        "END\n"
        "$hdts20261103_ha_cap$"
        % (_DAU_CAN_RC, khoa, kiem, "true" if cho_phep else "false", TEP, BO, MAU)
    )


def upgrade() -> None:
    op.create_table(
        MAU,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loai", sa.String(length=16), nullable=False),
        sa.Column("hieu_luc_tu", sa.Date(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kich_thuoc", sa.BigInteger(), nullable=False),
        sa.Column("noi_dung", sa.LargeBinary(), nullable=False),
        sa.Column("nguoi_tai_id", sa.Integer(), nullable=True),
        sa.Column(
            "tai_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ghi_chu", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["nguoi_tai_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "loai", "hieu_luc_tu", name="uq_council_document_template_loai_hieu_luc"
        ),
        sa.CheckConstraint(CHECK_LOAI_MAU, name="ck_council_document_template_loai"),
        sa.CheckConstraint(
            CHECK_SHA_NOI_DUNG, name="ck_council_document_template_sha256_noi_dung"
        ),
        sa.CheckConstraint(
            CHECK_KICH_THUOC, name="ck_council_document_template_kich_thuoc"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_council_document_template_nguoi_tai_id",
        MAU,
        ["nguoi_tai_id"],
        if_not_exists=True,
    )

    op.create_table(
        BO,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nguoi_tao_id", sa.Integer(), nullable=True),
        sa.Column(
            "tao_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("moc_chup", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("trinh_do", sa.String(length=64), nullable=False),
        sa.Column("so_ho_so", sa.Integer(), nullable=False),
        sa.Column("so_tep", sa.Integer(), nullable=False),
        sa.Column("kich_thuoc_tong", sa.BigInteger(), nullable=False),
        sa.Column(
            "tham_so_quyet_dinh",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "ma_ho_so_dau_vao", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "snapshot_dto", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "thong_tin_dung", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(["nguoi_tao_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["unit_id"], ["organization_unit.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("so_ho_so > 0", name="ck_council_document_set_so_ho_so"),
        sa.CheckConstraint("so_tep > 0", name="ck_council_document_set_so_tep"),
        sa.CheckConstraint(
            "kich_thuoc_tong > 0", name="ck_council_document_set_kich_thuoc_tong"
        ),
        sa.CheckConstraint(CHECK_MANG_MA, name="ck_council_document_set_ma_dau_vao"),
        sa.CheckConstraint(CHECK_MANG_DTO, name="ck_council_document_set_snapshot_dto"),
        if_not_exists=True,
    )
    for cot in ("nguoi_tao_id", "tao_luc", "unit_id"):
        op.create_index(
            "ix_council_document_set_%s" % cot, BO, [cot], if_not_exists=True
        )

    op.create_table(
        TEP,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("thu_tu", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kich_thuoc", sa.BigInteger(), nullable=False),
        sa.Column("noi_dung", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["set_id"], ["council_document_set.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("set_id", "path", name="uq_council_document_set_file_path"),
        sa.UniqueConstraint(
            "set_id", "thu_tu", name="uq_council_document_set_file_thu_tu"
        ),
        sa.CheckConstraint("thu_tu >= 1", name="ck_council_document_set_file_thu_tu"),
        sa.CheckConstraint("path <> ''", name="ck_council_document_set_file_path"),
        sa.CheckConstraint(
            CHECK_SHA_NOI_DUNG, name="ck_council_document_set_file_sha256_noi_dung"
        ),
        sa.CheckConstraint(
            CHECK_KICH_THUOC, name="ck_council_document_set_file_kich_thuoc"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_council_document_set_file_set_id", TEP, ["set_id"], if_not_exists=True
    )


def downgrade() -> None:
    bind = op.get_bind()
    try:
        bind.execute(text(_sql_ha_cap(os.environ.get(CO_CHO_PHEP_XOA) == "1")))
    except DBAPIError as e:
        if _DAU_CAN_RC in str(e):
            raise HaCapCanReadCommitted(
                "Hạ cấp hdts20261103 cần mức cô lập READ COMMITTED. Không xoá gì."
            ) from None
        raise
    # Câu DO KHÔNG xoá ⇔ còn hàng mà cờ chưa bật ⇒ báo lỗi miền (danh sách bảng chỉ để báo).
    con = [
        b
        for b in (TEP, BO, MAU)
        if bind.execute(text("SELECT to_regclass(:b)"), {"b": b}).scalar() is not None
    ]
    if con:
        con_hang = [
            b
            for b in con
            if bind.execute(text('SELECT EXISTS (SELECT 1 FROM "%s")' % b)).scalar()
        ]
        raise ConDuLieuVanBanHoiDong(
            "Bảng %s còn dữ liệu (mẫu / bộ văn bản có dữ liệu cá nhân). Không xoá gì. "
            "Sao lưu rồi đặt %s=1 nếu thật sự muốn xoá."
            % (", ".join(con_hang or con), CO_CHO_PHEP_XOA)
        )
