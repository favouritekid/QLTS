"""Công cụ ghép tên trường THCS — bảng ghép ``thcs_school_name_mapping`` (owner 22-11, đề xuất danh mục THCS Phần B1).

Revision ID: thcsmap20261122
Revises: thcsnb20261122
Create Date: 2026-11-22

Bảng: tên trường THCS đã chuẩn hoá → ``vn_school.id``, người ghép, lúc ghép; duy nhất theo tên chuẩn hoá. Câu
``CREATE TABLE`` / ``CREATE INDEX`` chép NGUYÊN từ model ``app/models/thcs_school_name_mapping.py``
(``tests/unit/test_thcs_school_mapping_ddl.py`` so hai bên).

MỘT câu ``DO`` mỗi chiều (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch).

``downgrade``: FAIL-CLOSED — còn dòng ghép ⇒ DỪNG, không xoá gì, trừ khi đặt
``THCS_MAPPING_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Dòng ghép là công sức tra
cứu của cán bộ; xoá mất thì phải ghép lại tay ~100 nhóm.
"""
import os
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "thcsmap20261122"
down_revision: Union[str, None] = "thcsnb20261122"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"
DOWNGRADE_FLAG = "THCS_MAPPING_DOWNGRADE_DROP_DATA_ENABLED"

CREATE_TABLE = """CREATE TABLE thcs_school_name_mapping (
	id BIGSERIAL NOT NULL,
	normalized_name VARCHAR(255) NOT NULL,
	school_id BIGINT NOT NULL,
	mapped_by_user_id INTEGER NOT NULL,
	mapped_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_thcs_school_name_mapping_normalized_name UNIQUE (normalized_name),
	CONSTRAINT ck_thcs_school_name_mapping_normalized_name_nonempty CHECK (length(btrim(normalized_name)) > 0),
	FOREIGN KEY(school_id) REFERENCES vn_school (id) ON DELETE RESTRICT,
	FOREIGN KEY(mapped_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)"""

CREATE_INDEXES = (
    "CREATE INDEX ix_thcs_school_name_mapping_mapped_by_user_id ON thcs_school_name_mapping (mapped_by_user_id)",
    "CREATE INDEX ix_thcs_school_name_mapping_school_id ON thcs_school_name_mapping (school_id)",
)


class UpgradeLockTimeout(RuntimeError):
    """Chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


class ThcsMappingDataPresent(RuntimeError):
    """downgrade gặp dòng ghép mà cờ cho phép xoá chưa bật — không xoá gì."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _upgrade_sql() -> str:
    body = ";\n    ".join(s.strip() for s in (CREATE_TABLE, *CREATE_INDEXES))
    return f"""
DO $thcsmap$
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    -- Chỉ tạo khi CHƯA có: CSDL test dựng bằng create_all (model HEAD) đã có sẵn bảng này.
    IF to_regclass('thcs_school_name_mapping') IS NULL THEN
        {body};
    END IF;
    RAISE NOTICE 'thcsmap20261122: bang ghep ten truong THCS da tao';
END
$thcsmap$
"""


#: SQLSTATE riêng khi hạ cấp gặp dòng ghép mà cờ chưa bật (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE).
SQLSTATE_DOWNGRADE_DATA_PRESENT = "QLT01"


def _downgrade_sql(allow_drop_data: bool) -> str:
    """Kiểm + xoá trong CÙNG câu ``DO`` (khoá bảng trước khi đếm) ⇒ không có khe giữa "đếm = 0" và "DROP"."""
    return f"""
DO $thcsmap_down$
DECLARE
    n bigint;
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE thcs_school_name_mapping IN ACCESS EXCLUSIVE MODE;
    SELECT count(*) INTO n FROM thcs_school_name_mapping;
    IF n > 0 AND NOT {'true' if allow_drop_data else 'false'} THEN
        RAISE EXCEPTION 'thcsmap20261122: con % dong ghep — khong xoa', n
            USING ERRCODE = '{SQLSTATE_DOWNGRADE_DATA_PRESENT}';
    END IF;
    DROP TABLE thcs_school_name_mapping;
    RAISE NOTICE 'thcsmap20261122: da go bang ghep ten truong THCS (% dong)', n;
END
$thcsmap_down$
"""


def _chay(sql: str, chieu: str) -> None:
    bind = op.get_bind()
    try:
        # exec_driver_sql: câu có ``$`` (dollar-quote) — không qua ``text()``.
        bind.exec_driver_sql(sql)
    except DBAPIError as e:
        if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "%s thcsmap20261122 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % (chieu, LOCK_TIMEOUT)
            ) from None
        raise


def upgrade() -> None:
    _chay(_upgrade_sql(), "Nâng cấp")


def downgrade() -> None:
    """FAIL-CLOSED: còn dòng ghép ⇒ dừng, không xoá gì, trừ khi ``THCS_MAPPING_DOWNGRADE_DROP_DATA_ENABLED=1``."""
    allow = os.environ.get(DOWNGRADE_FLAG) == "1"
    try:
        _chay(_downgrade_sql(allow), "Hạ cấp")
    except DBAPIError as e:
        if _sqlstate(e) == SQLSTATE_DOWNGRADE_DATA_PRESENT:
            raise ThcsMappingDataPresent(
                "Hạ cấp thcsmap20261122 dừng: còn dòng ghép tên trường THCS. Không xoá gì. Đặt "
                "%s=1 nếu thật sự muốn xoá." % DOWNGRADE_FLAG
            ) from None
        raise
