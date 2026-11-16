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
(:func:`_downgrade_sql`; cùng khuôn với ``hdts20261104``): ``LOCK TABLE … ACCESS EXCLUSIVE`` theo thứ
tự mẫu → bộ → tệp (thứ tự ghi của luồng tạo bộ) TRƯỚC khi kiểm, kiểm bằng ảnh chụp mới sau khoá
(READ COMMITTED), rồi DROP tệp → bộ → mẫu — vẫn giữ khoá. Mức cô lập khác READ COMMITTED ⇒ từ
chối, không xoá gì (:class:`DowngradeNeedsReadCommitted`).

Trần chờ khoá (F227, lượt G — Codex lần 7; cùng khuôn ``hdts20261104``): câu ``DO`` tự đặt
``lock_timeout`` = :data:`LOCK_TIMEOUT` trong CÙNG câu; quá trần ⇒ :class:`DowngradeLockTimeout`,
không xoá gì, ``alembic`` thoát khác 0 (trước đây chờ vô hạn và chặn mọi lượt đọc đến sau).
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

TEMPLATE_TABLE = "council_document_template"
SET_TABLE = "council_document_set"
SET_FILE_TABLE = "council_document_set_file"

CHECK_TEMPLATE_KIND = "loai IN ('bien_ban', 'quyet_dinh', 'danh_sach')"
CHECK_SHA_CONTENT = "sha256 = encode(sha256(noi_dung), 'hex')"
CHECK_SIZE = "kich_thuoc > 0 AND kich_thuoc = octet_length(noi_dung)"
CHECK_CODE_ARRAY = (
    "jsonb_typeof(ma_ho_so_dau_vao) = 'array' "
    "AND jsonb_array_length(ma_ho_so_dau_vao) = so_ho_so"
)
CHECK_DTO_ARRAY = (
    "jsonb_typeof(snapshot_dto) = 'array' "
    "AND jsonb_array_length(snapshot_dto) = so_ho_so"
)

DROP_DATA_ENABLED_ENV = "COUNCIL_DOCS_DOWNGRADE_DROP_DATA_ENABLED"


class CouncilDocumentDataPresent(RuntimeError):
    """downgrade gặp bảng còn hàng mà cờ cho phép xoá chưa bật — không xoá gì."""


class DowngradeNeedsReadCommitted(RuntimeError):
    """downgrade chạy ở mức cô lập khác READ COMMITTED — không xoá gì (kiểm sau khoá cần ảnh
    chụp mới)."""


class DowngradeLockTimeout(RuntimeError):
    """downgrade chờ khoá bảng quá ``LOCK_TIMEOUT`` (có giao dịch khác đang dùng bảng) — câu
    ``DO`` bị huỷ, giao dịch của nó lùi: không xoá gì, phiên bản không đổi."""


_MARK_NEEDS_READ_COMMITTED = "HDTS20261103_CAN_READ_COMMITTED"
_MARK_LOCK_TIMEOUT = "HDTS20261103_CHO_KHOA_QUA_TRAN"

#: Trần kỹ thuật chờ khoá của câu hạ cấp (F227 — người điều phối chọn 10 giây, owner có thể
#: đổi). CÙNG giá trị với ``hdts20261104.LOCK_TIMEOUT`` (test khoá hai bản bằng nhau).
LOCK_TIMEOUT = "10s"


def _downgrade_sql(allowed: bool) -> str:
    """MỘT câu ``DO`` (cùng khuôn ``hdts20261104``): chặn khi không phải READ COMMITTED; đặt trần
    chờ khoá ``LOCK_TIMEOUT`` bằng ``set_config('lock_timeout', …, true)`` NGAY TRONG câu này
    (AUTOCOMMIT của ``env.py``: câu riêng trước đó là giao dịch khác — hết hiệu lực); khoá ACCESS
    EXCLUSIVE mẫu → bộ → tệp (bảng đang có); kiểm còn hàng sau khoá; còn hàng mà cờ chưa bật ⇒
    ``RETURN`` (KHÔNG xoá gì, Python báo lỗi miền); không thì DROP tệp → bộ → mẫu. Chờ khoá quá
    trần (ở bước khoá HAY bước xoá) ⇒ ``RAISE`` mang dấu ``_MARK_LOCK_TIMEOUT`` ⇒ cả câu lùi.
    """
    if not isinstance(allowed, bool):
        raise TypeError("cho_phep phải là bool")
    lock_sql = "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n'
        "        END IF;\n" % (b, b)
        for b in (TEMPLATE_TABLE, SET_TABLE, SET_FILE_TABLE)
    )
    check_sql = "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            co_hang := co_hang OR EXISTS (SELECT 1 FROM "%s");\n'
        "        END IF;\n" % (b, b)
        for b in (TEMPLATE_TABLE, SET_TABLE, SET_FILE_TABLE)
    )
    return (
        "DO $hdts20261103_ha_cap$\n"
        "DECLARE\n"
        "    co_hang boolean := false;\n"
        "BEGIN\n"
        "    IF current_setting('transaction_isolation') <> 'read committed' THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END IF;\n"
        "    PERFORM set_config('lock_timeout', '%s', true);\n"
        "    BEGIN\n"
        "%s%s"
        "        IF co_hang AND NOT %s THEN\n"
        "            RETURN;\n"
        "        END IF;\n"
        '        DROP TABLE IF EXISTS "%s";\n'
        '        DROP TABLE IF EXISTS "%s";\n'
        '        DROP TABLE IF EXISTS "%s";\n'
        "    EXCEPTION WHEN lock_not_available THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END;\n"
        "END\n"
        "$hdts20261103_ha_cap$"
        % (
            _MARK_NEEDS_READ_COMMITTED,
            LOCK_TIMEOUT,
            lock_sql,
            check_sql,
            "true" if allowed else "false",
            SET_FILE_TABLE,
            SET_TABLE,
            TEMPLATE_TABLE,
            _MARK_LOCK_TIMEOUT,
        )
    )


def upgrade() -> None:
    op.create_table(
        TEMPLATE_TABLE,
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
        sa.CheckConstraint(CHECK_TEMPLATE_KIND, name="ck_council_document_template_loai"),
        sa.CheckConstraint(
            CHECK_SHA_CONTENT, name="ck_council_document_template_sha256_noi_dung"
        ),
        sa.CheckConstraint(
            CHECK_SIZE, name="ck_council_document_template_kich_thuoc"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_council_document_template_nguoi_tai_id",
        TEMPLATE_TABLE,
        ["nguoi_tai_id"],
        if_not_exists=True,
    )

    op.create_table(
        SET_TABLE,
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
        sa.CheckConstraint(CHECK_CODE_ARRAY, name="ck_council_document_set_ma_dau_vao"),
        sa.CheckConstraint(CHECK_DTO_ARRAY, name="ck_council_document_set_snapshot_dto"),
        if_not_exists=True,
    )
    for column in ("nguoi_tao_id", "tao_luc", "unit_id"):
        op.create_index(
            "ix_council_document_set_%s" % column, SET_TABLE, [column], if_not_exists=True
        )

    op.create_table(
        SET_FILE_TABLE,
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
            CHECK_SHA_CONTENT, name="ck_council_document_set_file_sha256_noi_dung"
        ),
        sa.CheckConstraint(
            CHECK_SIZE, name="ck_council_document_set_file_kich_thuoc"
        ),
        if_not_exists=True,
    )
    op.create_index(
        "ix_council_document_set_file_set_id", SET_FILE_TABLE, ["set_id"], if_not_exists=True
    )


def downgrade() -> None:
    bind = op.get_bind()
    try:
        bind.execute(text(_downgrade_sql(os.environ.get(DROP_DATA_ENABLED_ENV) == "1")))
    except DBAPIError as e:
        # So dấu trên THÔNG BÁO của CSDL (``e.orig``), KHÔNG trên ``str(e)``: ``str(e)`` của
        # SQLAlchemy chép cả câu lệnh — mà câu ``DO`` chứa CẢ HAI dấu ⇒ mọi lỗi (vd chờ khoá quá
        # trần) từng bị báo nhầm là "cần READ COMMITTED" (lượt G phát hiện bằng ca chờ khoá).
        error_text = str(e.orig) if getattr(e, "orig", None) is not None else ""
        if _MARK_NEEDS_READ_COMMITTED in error_text:
            raise DowngradeNeedsReadCommitted(
                "Hạ cấp hdts20261103 cần mức cô lập READ COMMITTED. Không xoá gì."
            ) from None
        if _MARK_LOCK_TIMEOUT in error_text:
            raise DowngradeLockTimeout(
                "Hạ cấp hdts20261103 dừng: chờ khoá bảng mẫu / bộ / tệp văn bản Hội đồng quá %s "
                "(có giao dịch khác đang dùng bảng). Không xoá gì, phiên bản không đổi — chạy "
                "lại khi bảng rảnh." % LOCK_TIMEOUT
            ) from None
        raise
    # Câu DO KHÔNG xoá ⇔ còn hàng mà cờ chưa bật ⇒ báo lỗi miền (danh sách bảng chỉ để báo).
    remaining = [
        b
        for b in (SET_FILE_TABLE, SET_TABLE, TEMPLATE_TABLE)
        if bind.execute(text("SELECT to_regclass(:b)"), {"b": b}).scalar() is not None
    ]
    if remaining:
        con_hang = [
            b
            for b in remaining
            if bind.execute(text('SELECT EXISTS (SELECT 1 FROM "%s")' % b)).scalar()
        ]
        raise CouncilDocumentDataPresent(
            "Bảng %s còn dữ liệu (mẫu / bộ văn bản có dữ liệu cá nhân). Không xoá gì. "
            "Sao lưu rồi đặt %s=1 nếu thật sự muốn xoá."
            % (", ".join(con_hang or remaining), DROP_DATA_ENABLED_ENV)
        )
