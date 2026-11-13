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

Kiểm–xoá NGUYÊN TỬ (F222, Codex lần 6): ``env.py`` chạy migration ở AUTOCOMMIT ⇒ mỗi câu lệnh là
MỘT giao dịch ngầm; khuôn cũ (``SELECT EXISTS`` rồi ``DROP`` — hai câu) để một GET tải tệp
INSERT … COMMIT chen giữa ⇒ mất dòng nhật ký dù cờ chưa bật (đo: ``do_khoa_e4.py`` biến thể A).
Nay khoá + kiểm + xoá là MỘT câu ``DO`` (:func:`_sql_ha_cap`) — một câu = một giao dịch dưới
AUTOCOMMIT (và nằm trong giao dịch bao ngoài nếu có): ``LOCK TABLE … ACCESS EXCLUSIVE`` TRƯỚC khi
kiểm (đợi phiên đang ghi kết thúc; chặn phiên ghi mới tới hết câu lệnh), kiểm bằng ảnh chụp MỚI
sau khoá (READ COMMITTED: mỗi câu trong PL/pgSQL một ảnh chụp), rồi DROP — vẫn giữ khoá. Ở
REPEATABLE READ / SERIALIZABLE ảnh chụp chốt TRƯỚC khoá (đo: biến thể C mất dòng) ⇒ câu ``DO``
từ chối chạy (:class:`HaCapCanReadCommitted`), không xoá gì.

Trần chờ khoá (F227, lượt G — Codex lần 7): trước đây câu ``DO`` chờ khoá VÔ HẠN — một giao dịch
dài đang dùng bảng làm hạ cấp đợi mãi, và trong lúc đợi CHẶN luôn các lượt đọc mới vào bảng ấy.
Nay câu ``DO`` tự đặt ``lock_timeout`` = :data:`TRAN_CHO_KHOA` (``set_config(…, true)``, trong
CÙNG câu); quá trần ⇒ :class:`HaCapChoKhoaQuaTran`, không xoá gì, ``alembic`` thoát khác 0.
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

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


class HaCapCanReadCommitted(RuntimeError):
    """downgrade chạy ở mức cô lập khác READ COMMITTED — không xoá gì (kiểm sau khoá cần ảnh
    chụp mới)."""


class HaCapChoKhoaQuaTran(RuntimeError):
    """downgrade chờ khoá bảng quá ``TRAN_CHO_KHOA`` (có giao dịch khác đang dùng bảng) — câu
    ``DO`` bị huỷ, giao dịch của nó lùi: không xoá gì, phiên bản không đổi."""


_DAU_CAN_RC = "HDTS20261104_CAN_READ_COMMITTED"
_DAU_CHO_KHOA = "HDTS20261104_CHO_KHOA_QUA_TRAN"

#: Trần kỹ thuật chờ khoá của câu hạ cấp (F227 — người điều phối chọn 10 giây, owner có thể
#: đổi). CÙNG giá trị với ``hdts20261103.TRAN_CHO_KHOA`` (test khoá hai bản bằng nhau).
TRAN_CHO_KHOA = "10s"


def _sql_ha_cap(cho_phep: bool) -> str:
    """MỘT câu ``DO``: (1) chặn khi không phải READ COMMITTED; (2) đặt trần chờ khoá
    ``TRAN_CHO_KHOA`` bằng ``set_config('lock_timeout', …, true)`` NGAY TRONG câu này — dưới
    AUTOCOMMIT của ``env.py`` mỗi câu là một giao dịch, nên đặt ở câu RIÊNG trước đó thì hết hiệu
    lực trước khi câu ``DO`` chạy; ``true`` = chỉ trong giao dịch này; (3) khoá ACCESS EXCLUSIVE
    từng bảng đang có (thứ tự cố định); (4) kiểm còn hàng — ảnh chụp sau khoá; (5) còn hàng mà cờ
    chưa bật ⇒ ``RETURN`` (KHÔNG xoá gì, Python báo lỗi miền); không thì DROP. Chờ khoá quá trần
    (ở bước khoá HAY bước xoá) ⇒ ``RAISE`` mang dấu ``_DAU_CHO_KHOA`` ⇒ cả câu lùi, không xoá gì.
    ``cho_phep`` chỉ nhận ``bool`` ⇒ chèn đúng một trong hai chữ ``true`` / ``false``.
    """
    if not isinstance(cho_phep, bool):
        raise TypeError("cho_phep phải là bool")
    khoa = "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n'
        "        END IF;\n" % (b, b)
        for b in (XOA, TAI)
    )
    kiem = "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            co_hang := co_hang OR EXISTS (SELECT 1 FROM "%s");\n'
        "        END IF;\n" % (b, b)
        for b in (XOA, TAI)
    )
    return (
        "DO $hdts20261104_ha_cap$\n"
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
        "    EXCEPTION WHEN lock_not_available THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END;\n"
        "END\n"
        "$hdts20261104_ha_cap$"
        % (
            _DAU_CAN_RC,
            TRAN_CHO_KHOA,
            khoa,
            kiem,
            "true" if cho_phep else "false",
            TAI,
            XOA,
            _DAU_CHO_KHOA,
        )
    )


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
    try:
        bind.execute(text(_sql_ha_cap(os.environ.get(CO_CHO_PHEP_XOA) == "1")))
    except DBAPIError as e:
        # So dấu trên THÔNG BÁO của CSDL (``e.orig``), KHÔNG trên ``str(e)``: ``str(e)`` của
        # SQLAlchemy chép cả câu lệnh — mà câu ``DO`` chứa CẢ HAI dấu ⇒ mọi lỗi (vd chờ khoá quá
        # trần) từng bị báo nhầm là "cần READ COMMITTED" (lượt G phát hiện bằng ca chờ khoá).
        loi = str(e.orig) if getattr(e, "orig", None) is not None else ""
        if _DAU_CAN_RC in loi:
            raise HaCapCanReadCommitted(
                "Hạ cấp hdts20261104 cần mức cô lập READ COMMITTED. Không xoá gì."
            ) from None
        if _DAU_CHO_KHOA in loi:
            raise HaCapChoKhoaQuaTran(
                "Hạ cấp hdts20261104 dừng: chờ khoá bảng vết xoá / nhật ký tải quá %s (có "
                "giao dịch khác đang dùng bảng). Không xoá gì, phiên bản không đổi — chạy lại "
                "khi bảng rảnh." % TRAN_CHO_KHOA
            ) from None
        raise
    # Câu DO KHÔNG xoá ⇔ còn hàng mà cờ chưa bật ⇒ báo lỗi miền (danh sách bảng chỉ để báo).
    con = [
        b
        for b in (XOA, TAI)
        if bind.execute(text("SELECT to_regclass(:b)"), {"b": b}).scalar() is not None
    ]
    if con:
        con_hang = [
            b
            for b in con
            if bind.execute(text('SELECT EXISTS (SELECT 1 FROM "%s")' % b)).scalar()
        ]
        raise ConVetVanBanHoiDong(
            "Bảng %s còn dữ liệu (vết xoá / nhật ký tải bộ văn bản Hội đồng). Không xoá gì. "
            "Sao lưu rồi đặt %s=1 nếu thật sự muốn xoá."
            % (", ".join(con_hang or con), CO_CHO_PHEP_XOA)
        )
