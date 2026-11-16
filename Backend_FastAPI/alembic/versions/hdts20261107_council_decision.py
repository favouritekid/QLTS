"""Ghi nhận Quyết định ĐÃ KÝ của bộ văn bản Hội đồng (F230 — lượt I, owner 06-11 C1–C7 + 07-11 E1).

Revision ID: hdts20261107
Revises: hdts20261105
Create Date: 2026-11-07

Đặc tả: ``logs-P5/cong-bo-ket-qua/ma-gd1/DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` mục 1 (+ mục 8).

Sáu bảng MỚI + bốn cột MỚI trên ``council_document_set``:

* ``council_document_set_row`` — một dòng của bộ (id hồ sơ, trạng thái lúc dựng, khoá đếm của NV in);
* ``council_decision`` — một tờ giấy đã ký (trúng tuyển / bổ sung / điều chỉnh / văn bản huỷ);
* ``council_decision_row`` — hồ sơ trong một văn bản; cờ ``trang_thai_cha`` do CSDL lan từ văn bản
  (khoá ngoại ghép ON UPDATE CASCADE — K2); dòng khớp ĐÚNG dòng bộ + hồ sơ nguồn (khoá ngoại ghép);
* ``council_decision_scan`` — bản scan PDF;
* ``council_decision_hold`` — nhóm "chờ Admin quyết" (F244, C7);
* ``council_document_event`` — nhật ký sự kiện độc lập (không khoá ngoại).

CHECK / biểu thức chỉ mục viết lại ĐÚNG chuỗi của model (``app/models/council_document.py``) — CSDL
test dựng bằng ``create_all()``; ``tests/unit/test_council_decision_models.py`` so hai bên.

Lệnh chạm bảng ĐANG CÓ (thêm cột / CHECK / chỉ mục trên ``council_document_set``) nằm trong MỘT câu
``DO`` tự đặt ``lock_timeout`` = :data:`LOCK_TIMEOUT` (khuôn F227 — ``hdts20261104``). F258 (Codex lần
14): ``env.py`` chạy ở ``AUTOCOMMIT`` nên trần đặt trong câu ``DO`` hết hiệu lực ngay sau câu ấy — ``upgrade``
đặt thêm trần ở MỨC PHIÊN cho MỌI lệnh DDL (``CREATE TABLE`` có khoá ngoại tới ``admission_profile``), trả
lại giá trị cũ khi xong. Quá trần ở bất kỳ lệnh nào ⇒ :class:`UpgradeLockTimeout`, mã thoát ≠ 0, phiên
bản chưa đổi; phần đã tạo giữ nguyên và chạy lại đi tiếp tới head (mọi lệnh ``IF NOT EXISTS``).

``downgrade`` là MỘT câu ``DO`` (khoá + kiểm + xoá) mang trần của chính nó; sau câu ấy chỉ còn ``SELECT
to_regclass`` (không chờ khoá) ⇒ không cần trần mức phiên.

``downgrade`` XOÁ sáu bảng + bốn cột — tức xoá mọi ghi nhận Quyết định đã ký, scan, nhóm chờ, nhật ký
sự kiện ⇒ FAIL-CLOSED: còn hàng (hoặc cột mới còn giá trị) ⇒ DỪNG, không xoá gì, trừ khi đặt
``COUNCIL_DECISION_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Khoá +
kiểm + xoá là MỘT câu ``DO`` (READ COMMITTED bắt buộc; trần chờ khoá như trên).
"""

import os
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "hdts20261107"
down_revision: Union[str, None] = "hdts20261105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SET_TABLE = "council_document_set"
SET_ROW_TABLE = "council_document_set_row"
DECISION_TABLE = "council_decision"
DECISION_ROW_TABLE = "council_decision_row"
SCAN_TABLE = "council_decision_scan"
HOLD_TABLE = "council_decision_hold"
EVENT_TABLE = "council_document_event"
#: Thứ tự xoá khi hạ cấp (bảng phụ thuộc trước).
NEW_TABLES_DROP_ORDER = (HOLD_TABLE, SCAN_TABLE, EVENT_TABLE, DECISION_ROW_TABLE, DECISION_TABLE, SET_ROW_TABLE)
NEW_SET_COLUMNS = (
    "dung_lai_tu_set_id",
    "ban_ky_so_quyet_dinh",
    "ban_ky_ngay",
    "cho_quyet_dinh_goc_id",
)

MAX_REASON_LENGTH = 1000
CHECK_SHA_CONTENT = "sha256 = encode(sha256(noi_dung), 'hex')"
CHECK_SIZE = "kich_thuoc > 0 AND kich_thuoc = octet_length(noi_dung)"
EFFECTIVE_ROW_CONDITION = "trang_thai_cha = 'hieu_luc' AND bi_bo_boi_id IS NULL"

CHECK_SET_SIGNED_COPY_COMPLETE = "(ban_ky_so_quyet_dinh IS NULL) = (ban_ky_ngay IS NULL)"
CHECK_SET_REBUILD_HAS_SIGNED_COPY = (
    "dung_lai_tu_set_id IS NULL OR ban_ky_so_quyet_dinh IS NOT NULL"
)
CHECK_SET_ONE_MODE = "ban_ky_so_quyet_dinh IS NULL OR cho_quyet_dinh_goc_id IS NULL"
CHECK_SET_SIGNED_COPY_NUMBER = (
    "ban_ky_so_quyet_dinh IS NULL OR ban_ky_so_quyet_dinh ~ '^[0-9]{1,6}$'"
)
CHECK_SET_ROW_SEQ = "stt >= 1"

CHECK_DECISION_KIND = "loai IN ('trung_tuyen', 'bo_sung', 'dieu_chinh', 'van_ban_huy')"
CHECK_DECISION_STATUS = "trang_thai IN ('hieu_luc', 'het_hieu_luc', 'huy_ghi_nhan')"
CHECK_DECISION_K3_ROOT = "(loai IN ('bo_sung', 'dieu_chinh')) = (goc_id IS NOT NULL)"
CHECK_DECISION_K3_CANCEL = "(loai = 'van_ban_huy') = (huy_qd_id IS NOT NULL)"
CHECK_DECISION_K3_EXPIRED = "(trang_thai = 'het_hieu_luc') = (het_hieu_luc_boi_id IS NOT NULL)"
CHECK_DECISION_K3_CANCELLATION = "loai <> 'van_ban_huy' OR trang_thai <> 'het_hieu_luc'"
CHECK_DECISION_K3_REVOKED = (
    "(trang_thai = 'huy_ghi_nhan') = (huy_ghi_nhan_boi_id IS NOT NULL "
    "AND huy_ghi_nhan_luc IS NOT NULL AND ly_do_huy_ghi_nhan IS NOT NULL)"
)
CHECK_DECISION_K3_NUMBER = "so_quyet_dinh ~ '^[0-9]{1,6}$'"
CHECK_DECISION_K3_SCOPE = "pham_vi_so = CAST(EXTRACT(YEAR FROM ngay_ky) AS integer)"
CHECK_DECISION_K3_REASON = (
    "ly_do_huy_ghi_nhan IS NULL OR char_length(btrim(ly_do_huy_ghi_nhan)) > 0"
)
CHECK_DECISION_K3_SELF_REFERENCE = (
    "(goc_id IS NULL OR goc_id <> id) AND (huy_qd_id IS NULL OR huy_qd_id <> id)"
)
CHECK_DECISION_K4 = "set_id IS NOT NULL OR NOT can_bo OR trang_thai = 'huy_ghi_nhan'"
CHECK_DECISION_K4B = "can_bo OR set_id IS NULL"
CHECK_DECISION_K4C = "loai NOT IN ('trung_tuyen', 'bo_sung') OR can_bo"
CHECK_DECISION_K4D = "loai <> 'van_ban_huy' OR NOT can_bo"
CHECK_DECISION_FILE_SHA = (
    "sha_tep_quyet_dinh IS NULL OR sha_tep_quyet_dinh ~ '^[0-9a-f]{64}$'"
)
CHECK_DECISION_PROFILE_COUNT = "so_ho_so >= 0"
CONDITION_U1 = "trang_thai <> 'huy_ghi_nhan'"
CONDITION_U2 = "trang_thai <> 'huy_ghi_nhan' AND set_id IS NOT NULL"
CONDITION_U4 = "loai = 'van_ban_huy' AND trang_thai = 'hieu_luc'"

CHECK_DECISION_ROW_K5A = "profile_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
CHECK_DECISION_ROW_K5B = "set_row_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"
CHECK_DECISION_ROW_K5C = "set_id IS NOT NULL OR trang_thai_cha = 'huy_ghi_nhan'"  # F257
CHECK_DECISION_ROW_SET = "bi_bo_boi_id IS NULL OR bi_bo_boi_id <> decision_id"
CHECK_DECISION_ROW_SEQ = "stt >= 1"

CHECK_SCAN_TYPE = "kieu = 'application/pdf'"

CHECK_HOLD_ENTRY_REASON = "ly_do_vao IN ('qd_bi_huy', 'bi_bo_boi_van_ban_bi_huy')"
CHECK_HOLD_STATUS = "trang_thai IN ('cho_quyet', 'da_cho_xet_lai', 'vo_hieu')"
CHECK_HOLD_H3 = "profile_id IS NOT NULL OR trang_thai = 'vo_hieu'"
CHECK_HOLD_H4_RECHECK = (
    "trang_thai <> 'da_cho_xet_lai' OR (quyet_boi_id IS NOT NULL "
    "AND quyet_luc IS NOT NULL AND ly_do_quyet IS NOT NULL)"
)
CHECK_HOLD_H4_PENDING = "trang_thai <> 'cho_quyet' OR quyet_luc IS NULL"
CHECK_HOLD_H4_VOID = "(trang_thai = 'vo_hieu') = (vo_hieu_luc IS NOT NULL)"
CHECK_HOLD_REASON = "ly_do_quyet IS NULL OR char_length(btrim(ly_do_quyet)) > 0"
CONDITION_H1 = "trang_thai = 'cho_quyet'"

EVENT_KINDS = (
    "tao_bo",
    "xoa_bo",
    "tao_bo_dieu_chinh",
    "dung_lai_ban_ky",
    "ghi_nhan",
    "ghi_nhan_dieu_chinh",
    "huy_ghi_nhan",
    "huy_hieu_luc",
    "cho_xet_lai",
    "tai_scan",
)
CHECK_EVENT_KIND = "loai IN (%s)" % ", ".join("'%s'" % x for x in EVENT_KINDS)
CHECK_EVENT_FIGURES = "jsonb_typeof(so_lieu) = 'object'"

DROP_DATA_ENABLED_ENV = "COUNCIL_DECISION_DOWNGRADE_DROP_DATA_ENABLED"
#: Trần kỹ thuật chờ khoá (F227 — owner 06-11 giữ 10 giây). CÙNG giá trị với
#: ``hdts20261103.LOCK_TIMEOUT`` / ``hdts20261104.LOCK_TIMEOUT`` (test khoá ba bản bằng nhau).
LOCK_TIMEOUT = "10s"

_MARK_NEEDS_READ_COMMITTED = "HDTS20261107_CAN_READ_COMMITTED"
_MARK_LOCK_TIMEOUT = "HDTS20261107_CHO_KHOA_QUA_TRAN"


class CouncilDecisionDataPresent(RuntimeError):
    """downgrade gặp bảng / cột mới còn dữ liệu mà cờ cho phép xoá chưa bật — không xoá gì."""


class DowngradeNeedsReadCommitted(RuntimeError):
    """downgrade chạy ở mức cô lập khác READ COMMITTED — không xoá gì."""


class DowngradeLockTimeout(RuntimeError):
    """downgrade chờ khoá quá ``LOCK_TIMEOUT`` — câu ``DO`` lùi, không xoá gì."""


class UpgradeLockTimeout(RuntimeError):
    """upgrade chờ khoá quá ``LOCK_TIMEOUT`` ở BẤT KỲ lệnh DDL nào (F258). Phiên bản Alembic CHƯA đổi;
    phần đã tạo (``AUTOCOMMIT`` ⇒ mỗi lệnh tự commit) GIỮ nguyên — mọi lệnh đều ``IF NOT EXISTS`` nên
    chạy lại ``alembic upgrade`` khi bảng rảnh sẽ đi tiếp tới head."""


def _add_set_columns_sql() -> str:
    """MỘT câu ``DO``: đặt trần chờ khoá NGAY TRONG câu; thêm bốn cột + bốn CHECK + hai chỉ mục
    trên ``council_document_set`` (chạy lại được — ``IF NOT EXISTS``). Quá trần ⇒ ``RAISE`` mang
    dấu ⇒ cả câu lùi."""
    constraints = (
        ("ck_council_document_set_ban_ky_du", CHECK_SET_SIGNED_COPY_COMPLETE),
        ("ck_council_document_set_dung_lai_ban_ky", CHECK_SET_REBUILD_HAS_SIGNED_COPY),
        ("ck_council_document_set_mot_che_do", CHECK_SET_ONE_MODE),
        ("ck_council_document_set_so_ban_ky", CHECK_SET_SIGNED_COPY_NUMBER),
    )
    ck = "".join(
        "        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '%s') THEN\n"
        '            ALTER TABLE "%s" ADD CONSTRAINT %s CHECK (%s);\n'
        "        END IF;\n" % (name, SET_TABLE, name, expression)
        for name, expression in constraints
    )
    return (
        "DO $hdts20261107_cot_bo$\n"
        "BEGIN\n"
        "    PERFORM set_config('lock_timeout', '%s', true);\n"
        "    BEGIN\n"
        '        ALTER TABLE "%s"\n'
        "            ADD COLUMN IF NOT EXISTS dung_lai_tu_set_id integer\n"
        '                REFERENCES "%s" (id) ON DELETE SET NULL,\n'
        "            ADD COLUMN IF NOT EXISTS ban_ky_so_quyet_dinh varchar(6),\n"
        "            ADD COLUMN IF NOT EXISTS ban_ky_ngay date,\n"
        "            ADD COLUMN IF NOT EXISTS cho_quyet_dinh_goc_id integer;\n"
        "%s"
        "        CREATE INDEX IF NOT EXISTS ix_council_document_set_dung_lai_tu_set_id\n"
        '            ON "%s" (dung_lai_tu_set_id);\n'
        "        CREATE INDEX IF NOT EXISTS ix_council_document_set_cho_quyet_dinh_goc_id\n"
        '            ON "%s" (cho_quyet_dinh_goc_id);\n'
        "    EXCEPTION WHEN lock_not_available THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END;\n"
        "END\n"
        "$hdts20261107_cot_bo$"
        % (LOCK_TIMEOUT, SET_TABLE, SET_TABLE, ck, SET_TABLE, SET_TABLE, _MARK_LOCK_TIMEOUT)
    )


def _downgrade_sql(allowed: bool) -> str:
    """MỘT câu ``DO`` (khuôn ``hdts20261104``): chặn khi không phải READ COMMITTED; trần chờ khoá;
    khoá ACCESS EXCLUSIVE bộ → sáu bảng mới (thứ tự cố định); kiểm còn hàng / cột mới còn giá trị
    bằng ảnh chụp SAU khoá; còn mà cờ chưa bật ⇒ ``RETURN`` (không xoá gì); không thì xoá bảng
    (phụ thuộc trước) rồi bốn cột. ``allowed`` chỉ nhận ``bool``."""
    if not isinstance(allowed, bool):
        raise TypeError("cho_phep phải là bool")
    lock_sql = '        LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n' % SET_TABLE + "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            LOCK TABLE "%s" IN ACCESS EXCLUSIVE MODE;\n'
        "        END IF;\n" % (b, b)
        for b in reversed(NEW_TABLES_DROP_ORDER)
    )
    check_sql = "".join(
        "        IF to_regclass('%s') IS NOT NULL THEN\n"
        '            co_hang := co_hang OR EXISTS (SELECT 1 FROM "%s");\n'
        "        END IF;\n" % (b, b)
        for b in NEW_TABLES_DROP_ORDER
    ) + "".join(
        "        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = '%s'\n"
        "                   AND column_name = '%s') THEN\n"
        "            EXECUTE 'SELECT EXISTS (SELECT 1 FROM \"%s\" WHERE %s IS NOT NULL)'\n"
        "                INTO co_cot;\n"
        "            co_hang := co_hang OR co_cot;\n"
        "        END IF;\n" % (SET_TABLE, c, SET_TABLE, c)
        for c in NEW_SET_COLUMNS
    )
    drop_tables = "".join('        DROP TABLE IF EXISTS "%s";\n' % b for b in NEW_TABLES_DROP_ORDER)
    drop_columns = '        ALTER TABLE "%s" %s;\n' % (
        SET_TABLE,
        ", ".join("DROP COLUMN IF EXISTS %s" % c for c in reversed(NEW_SET_COLUMNS)),
    )
    return (
        "DO $hdts20261107_ha_cap$\n"
        "DECLARE\n"
        "    co_hang boolean := false;\n"
        "    co_cot boolean := false;\n"
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
        "%s%s"
        "    EXCEPTION WHEN lock_not_available THEN\n"
        "        RAISE EXCEPTION '%s';\n"
        "    END;\n"
        "END\n"
        "$hdts20261107_ha_cap$"
        % (
            _MARK_NEEDS_READ_COMMITTED,
            LOCK_TIMEOUT,
            lock_sql,
            check_sql,
            "true" if allowed else "false",
            drop_tables,
            drop_columns,
            _MARK_LOCK_TIMEOUT,
        )
    )


def _database_error_text(e: DBAPIError) -> str:
    # So dấu trên THÔNG BÁO của CSDL (``e.orig``), KHÔNG trên ``str(e)`` (chép cả câu lệnh — bài
    # học lượt G).
    return str(e.orig) if getattr(e, "orig", None) is not None else ""


#: SQLSTATE của "hết trần chờ khoá" (``lock_timeout``) — PostgreSQL ``lock_not_available``.
_SQLSTATE_LOCK_TIMEOUT = "55P03"


def _sqlstate(e: DBAPIError) -> str:
    """SQLSTATE của lỗi CSDL (asyncpg qua SQLAlchemy: ``e.orig.sqlstate`` / ``pgcode``, hoặc trên
    ``__cause__``); không có ⇒ chuỗi rỗng. KHÔNG đọc thông điệp."""
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str):
                return v
    return ""


def upgrade() -> None:
    """F258 (Codex lần 14): ``env.py`` chạy migration ở ``AUTOCOMMIT`` ⇒ ``set_config(…, true)`` trong câu
    ``DO`` chỉ sống trong CHÍNH câu ấy. Trần chờ khoá phải phủ MỌI lệnh DDL (các ``CREATE TABLE`` có khoá
    ngoại tới ``admission_profile`` / ``council_document_set`` lấy SHARE ROW EXCLUSIVE — một giao dịch đang
    ghi hồ sơ làm chúng chờ, và hàng đợi khoá chặn luôn mọi phiên đọc / ghi hồ sơ sau nó). Đặt trần ở MỨC
    PHIÊN cho cả ``upgrade``; xong thì trả về giá trị cũ (migration sau trong cùng lượt không bị đổi)."""
    bind = op.get_bind()
    previous_timeout = bind.execute(text("SELECT current_setting('lock_timeout')")).scalar()
    bind.execute(
        text("SELECT set_config('lock_timeout', :t, false)"), {"t": LOCK_TIMEOUT}
    )
    try:
        _upgrade_steps(bind)
    except DBAPIError as e:
        if _MARK_LOCK_TIMEOUT in _database_error_text(e) or _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "Nâng cấp hdts20261107 dừng: chờ khoá quá %s (có giao dịch khác đang dùng bảng bộ văn "
                "bản / hồ sơ). Phiên bản CHƯA đổi; phần đã tạo giữ nguyên (mọi lệnh IF NOT EXISTS) — "
                "chạy lại `alembic upgrade head` khi bảng rảnh để đi tiếp." % LOCK_TIMEOUT
            ) from None
        raise
    bind.execute(text("SELECT set_config('lock_timeout', :t, false)"), {"t": previous_timeout})


def _upgrade_steps(bind) -> None:
    bind.execute(text(_add_set_columns_sql()))

    op.create_table(
        SET_ROW_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=False),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("status_luc_dung", sa.String(length=32), nullable=False),
        sa.Column("nv_in_id", sa.BigInteger(), nullable=True),
        sa.Column("admission_path_id", sa.Integer(), nullable=True),
        sa.Column("academic_info_id", sa.Integer(), nullable=True),
        sa.Column("offering_id", sa.Integer(), nullable=True),
        sa.Column("major_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["set_id"], [SET_TABLE + ".id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["admission_profile.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("set_id", "stt", name="uq_council_document_set_row_stt"),
        sa.UniqueConstraint(
            "set_id", "profile_id", name="uq_council_document_set_row_profile"
        ),
        sa.UniqueConstraint(
            "id", "set_id", "profile_id", name="uq_council_document_set_row_dich"
        ),
        sa.CheckConstraint(CHECK_SET_ROW_SEQ, name="ck_council_document_set_row_stt"),
        if_not_exists=True,
    )
    for column in ("set_id", "profile_id"):
        op.create_index(
            "ix_council_document_set_row_%s" % column, SET_ROW_TABLE, [column], if_not_exists=True
        )

    op.create_table(
        DECISION_TABLE,
        # ``id`` nằm trong khoá ngoại ghép K6 ⇒ phải khai tự tăng tường minh (như model).
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("loai", sa.String(length=16), nullable=False),
        sa.Column("can_bo", sa.Boolean(), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=True),
        sa.Column("goc_id", sa.Integer(), nullable=True),
        sa.Column("huy_qd_id", sa.Integer(), nullable=True),
        sa.Column("het_hieu_luc_boi_id", sa.Integer(), nullable=True),
        sa.Column("so_quyet_dinh", sa.String(length=6), nullable=False),
        sa.Column("ngay_ky", sa.Date(), nullable=False),
        sa.Column("pham_vi_so", sa.Integer(), nullable=False),
        sa.Column("trang_thai", sa.String(length=16), nullable=False),
        sa.Column(
            "tham_so_ban_ky", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("so_ho_so", sa.Integer(), nullable=False),
        sa.Column("sha_tep_quyet_dinh", sa.String(length=64), nullable=True),
        sa.Column("xac_nhan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ghi_chu_mau", sa.String(length=MAX_REASON_LENGTH), nullable=True),
        sa.Column("ghi_nhan_boi_id", sa.Integer(), nullable=False),
        sa.Column(
            "ghi_nhan_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("huy_ghi_nhan_boi_id", sa.Integer(), nullable=True),
        sa.Column("huy_ghi_nhan_luc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ly_do_huy_ghi_nhan", sa.String(length=MAX_REASON_LENGTH), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["set_id"], [SET_TABLE + ".id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["goc_id"], [DECISION_TABLE + ".id"]),
        sa.ForeignKeyConstraint(["huy_qd_id"], [DECISION_TABLE + ".id"]),
        sa.UniqueConstraint("id", "trang_thai", name="uq_council_decision_id_trang_thai"),
        sa.UniqueConstraint("id", "set_id", name="uq_council_decision_id_set"),
        sa.UniqueConstraint("id", "huy_qd_id", name="uq_council_decision_id_huy"),
        sa.ForeignKeyConstraint(
            ["het_hieu_luc_boi_id", "id"],
            [DECISION_TABLE + ".id", DECISION_TABLE + ".huy_qd_id"],
            name="fk_council_decision_k6",
        ),
        sa.CheckConstraint(CHECK_DECISION_KIND, name="ck_council_decision_loai"),
        sa.CheckConstraint(CHECK_DECISION_STATUS, name="ck_council_decision_trang_thai"),
        sa.CheckConstraint(CHECK_DECISION_K3_ROOT, name="ck_council_decision_k3_goc"),
        sa.CheckConstraint(CHECK_DECISION_K3_CANCEL, name="ck_council_decision_k3_huy"),
        sa.CheckConstraint(CHECK_DECISION_K3_EXPIRED, name="ck_council_decision_k3_het"),
        sa.CheckConstraint(CHECK_DECISION_K3_CANCELLATION, name="ck_council_decision_k3_vbh"),
        sa.CheckConstraint(CHECK_DECISION_K3_REVOKED, name="ck_council_decision_k3_hgn"),
        sa.CheckConstraint(CHECK_DECISION_K3_NUMBER, name="ck_council_decision_k3_so"),
        sa.CheckConstraint(CHECK_DECISION_K3_SCOPE, name="ck_council_decision_k3_pham_vi"),
        sa.CheckConstraint(CHECK_DECISION_K3_REASON, name="ck_council_decision_k3_ly_do"),
        sa.CheckConstraint(CHECK_DECISION_K3_SELF_REFERENCE, name="ck_council_decision_k3_tu_tro"),
        sa.CheckConstraint(CHECK_DECISION_K4, name="ck_council_decision_k4"),
        sa.CheckConstraint(CHECK_DECISION_K4B, name="ck_council_decision_k4b"),
        sa.CheckConstraint(CHECK_DECISION_K4C, name="ck_council_decision_k4c"),
        sa.CheckConstraint(CHECK_DECISION_K4D, name="ck_council_decision_k4d"),
        sa.CheckConstraint(CHECK_DECISION_FILE_SHA, name="ck_council_decision_sha_tep"),
        sa.CheckConstraint(CHECK_DECISION_PROFILE_COUNT, name="ck_council_decision_so_ho_so"),
        if_not_exists=True,
    )
    for column in ("set_id", "goc_id", "huy_qd_id"):
        op.create_index(
            "ix_council_decision_%s" % column, DECISION_TABLE, [column], if_not_exists=True
        )
    op.create_index(
        "uq_council_decision_u1_so",
        DECISION_TABLE,
        ["so_quyet_dinh", "pham_vi_so"],
        unique=True,
        postgresql_where=sa.text(CONDITION_U1),
        if_not_exists=True,
    )
    op.create_index(
        "uq_council_decision_u2_bo",
        DECISION_TABLE,
        ["set_id"],
        unique=True,
        postgresql_where=sa.text(CONDITION_U2),
        if_not_exists=True,
    )
    op.create_index(
        "uq_council_decision_u4_huy",
        DECISION_TABLE,
        ["huy_qd_id"],
        unique=True,
        postgresql_where=sa.text(CONDITION_U4),
        if_not_exists=True,
    )

    op.create_table(
        DECISION_ROW_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("trang_thai_cha", sa.String(length=16), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=True),
        sa.Column("set_row_id", sa.Integer(), nullable=True),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("stt", sa.Integer(), nullable=False),
        sa.Column("bi_bo_boi_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bi_bo_boi_id"], [DECISION_TABLE + ".id"]),
        sa.ForeignKeyConstraint(
            ["decision_id", "trang_thai_cha"],
            [DECISION_TABLE + ".id", DECISION_TABLE + ".trang_thai"],
            onupdate="CASCADE",
            name="fk_council_decision_row_k2",
        ),
        sa.ForeignKeyConstraint(
            ["decision_id", "set_id"],
            [DECISION_TABLE + ".id", DECISION_TABLE + ".set_id"],
            onupdate="CASCADE",
            name="fk_council_decision_row_bo",
        ),
        sa.ForeignKeyConstraint(
            ["set_row_id", "set_id", "profile_id"],
            [SET_ROW_TABLE + ".id", SET_ROW_TABLE + ".set_id", SET_ROW_TABLE + ".profile_id"],
            onupdate="CASCADE",
            ondelete="SET NULL (set_row_id)",
            name="fk_council_decision_row_dong_bo",
        ),
        sa.CheckConstraint(CHECK_DECISION_ROW_K5A, name="ck_council_decision_row_k5a"),
        sa.CheckConstraint(CHECK_DECISION_ROW_K5B, name="ck_council_decision_row_k5b"),
        sa.CheckConstraint(CHECK_DECISION_ROW_K5C, name="ck_council_decision_row_k5c"),
        sa.CheckConstraint(CHECK_DECISION_ROW_SET, name="ck_council_decision_row_bo"),
        sa.CheckConstraint(CHECK_DECISION_ROW_SEQ, name="ck_council_decision_row_stt"),
        sa.UniqueConstraint("decision_id", "stt", name="uq_council_decision_row_stt"),
        sa.UniqueConstraint(
            "decision_id", "set_row_id", name="uq_council_decision_row_u5"
        ),
        if_not_exists=True,
    )
    for column in ("decision_id", "profile_id", "bi_bo_boi_id"):
        op.create_index(
            "ix_council_decision_row_%s" % column, DECISION_ROW_TABLE, [column], if_not_exists=True
        )
    op.create_index(
        "uq_council_decision_row_u3_ho_so",
        DECISION_ROW_TABLE,
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text(EFFECTIVE_ROW_CONDITION),
        if_not_exists=True,
    )

    op.create_table(
        SCAN_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kich_thuoc", sa.BigInteger(), nullable=False),
        sa.Column("kieu", sa.String(length=64), nullable=False),
        sa.Column("noi_dung", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["decision_id"], [DECISION_TABLE + ".id"]),
        sa.UniqueConstraint("decision_id"),
        sa.CheckConstraint(
            CHECK_SHA_CONTENT, name="ck_council_decision_scan_sha256_noi_dung"
        ),
        sa.CheckConstraint(
            CHECK_SIZE, name="ck_council_decision_scan_kich_thuoc"
        ),
        sa.CheckConstraint(CHECK_SCAN_TYPE, name="ck_council_decision_scan_kieu"),
        if_not_exists=True,
    )

    op.create_table(
        HOLD_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("decision_row_id", sa.Integer(), nullable=False),
        sa.Column("van_ban_huy_id", sa.Integer(), nullable=False),
        sa.Column("ly_do_vao", sa.String(length=32), nullable=False),
        sa.Column("trang_thai", sa.String(length=16), nullable=False),
        sa.Column(
            "tao_luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("quyet_boi_id", sa.Integer(), nullable=True),
        sa.Column("quyet_luc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ly_do_quyet", sa.String(length=MAX_REASON_LENGTH), nullable=True),
        sa.Column("vo_hieu_boi_id", sa.Integer(), nullable=True),
        sa.Column("vo_hieu_luc", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["admission_profile.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["decision_row_id"], [DECISION_ROW_TABLE + ".id"]),
        sa.ForeignKeyConstraint(["van_ban_huy_id"], [DECISION_TABLE + ".id"]),
        sa.CheckConstraint(
            CHECK_HOLD_ENTRY_REASON, name="ck_council_decision_hold_ly_do_vao"
        ),
        sa.CheckConstraint(
            CHECK_HOLD_STATUS, name="ck_council_decision_hold_trang_thai"
        ),
        sa.CheckConstraint(CHECK_HOLD_H3, name="ck_council_decision_hold_h3"),
        sa.CheckConstraint(CHECK_HOLD_H4_RECHECK, name="ck_council_decision_hold_h4_xl"),
        sa.CheckConstraint(CHECK_HOLD_H4_PENDING, name="ck_council_decision_hold_h4_cq"),
        sa.CheckConstraint(CHECK_HOLD_H4_VOID, name="ck_council_decision_hold_h4_vh"),
        sa.CheckConstraint(CHECK_HOLD_REASON, name="ck_council_decision_hold_ly_do"),
        sa.UniqueConstraint(
            "van_ban_huy_id", "profile_id", name="uq_council_decision_hold_h2"
        ),
        if_not_exists=True,
    )
    for column in ("profile_id", "van_ban_huy_id"):
        op.create_index(
            "ix_council_decision_hold_%s" % column, HOLD_TABLE, [column], if_not_exists=True
        )
    op.create_index(
        "uq_council_decision_hold_h1_cho",
        HOLD_TABLE,
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text(CONDITION_H1),
        if_not_exists=True,
    )

    op.create_table(
        EVENT_TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("loai", sa.String(length=32), nullable=False),
        sa.Column("set_id", sa.Integer(), nullable=True),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("hold_id", sa.Integer(), nullable=True),
        sa.Column("nguoi_id", sa.Integer(), nullable=True),
        sa.Column(
            "luc",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("so_lieu", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(CHECK_EVENT_KIND, name="ck_council_document_event_loai"),
        sa.CheckConstraint(
            CHECK_EVENT_FIGURES, name="ck_council_document_event_so_lieu"
        ),
        if_not_exists=True,
    )
    for column in ("set_id", "decision_id", "luc"):
        op.create_index(
            "ix_council_document_event_%s" % column, EVENT_TABLE, [column], if_not_exists=True
        )


def downgrade() -> None:
    bind = op.get_bind()
    try:
        bind.execute(text(_downgrade_sql(os.environ.get(DROP_DATA_ENABLED_ENV) == "1")))
    except DBAPIError as e:
        error_text = _database_error_text(e)
        if _MARK_NEEDS_READ_COMMITTED in error_text:
            raise DowngradeNeedsReadCommitted(
                "Hạ cấp hdts20261107 cần mức cô lập READ COMMITTED. Không xoá gì."
            ) from None
        if _MARK_LOCK_TIMEOUT in error_text:
            raise DowngradeLockTimeout(
                "Hạ cấp hdts20261107 dừng: chờ khoá quá %s (có giao dịch khác đang dùng bảng). "
                "Không xoá gì, phiên bản không đổi." % LOCK_TIMEOUT
            ) from None
        raise
    # Câu DO KHÔNG xoá ⇔ còn dữ liệu mà cờ chưa bật ⇒ báo lỗi miền.
    remaining = [
        b
        for b in NEW_TABLES_DROP_ORDER
        if bind.execute(text("SELECT to_regclass(:b)"), {"b": b}).scalar() is not None
    ]
    if remaining:
        raise CouncilDecisionDataPresent(
            "Bảng / cột ghi nhận Quyết định đã ký còn dữ liệu. Không xoá gì. Sao lưu rồi đặt "
            "%s=1 nếu thật sự muốn xoá." % DROP_DATA_ENABLED_ENV
        )
