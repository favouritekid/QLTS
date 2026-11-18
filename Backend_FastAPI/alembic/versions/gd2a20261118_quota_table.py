"""GĐ2-A — bảng chỉ tiêu năm, nhóm ngành + trần, thành viên nhóm; trigger chặn sửa khi bảng đã khoá.

Revision ID: gd2a20261118
Revises: gd1b20261117
Create Date: 2026-11-18

Đặc tả: ``logs-P5/cong-bo-ket-qua/gd2/DAC-TA-GD2-LAN-XET-TUYEN-BAN3-2026-11-18.md`` (sha256 ``4230f936…``) §3; sửa 3.2
(``7da4e206…``). GO viết mã owner 18-11 (PR đầu GĐ2 = GĐ2-0 + GĐ2-A). Không đổi dữ liệu có sẵn.

MỘT câu ``DO`` làm TẤT CẢ (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ở bất kỳ bước nào ⇒
không còn gì dở dang, phiên bản Alembic chưa đổi, chạy lại được. Trong câu ấy:

1. ``offering_academic_info`` thêm ``UNIQUE (id, academic_year)`` — đích khoá ngoại ghép của thành viên nhóm;
2. tạo ba bảng + chỉ mục (chép theo model ``app/models/admission_quota_table.py`` —
   ``tests/integration/test_gd2a_migration.py`` so lược đồ sau nâng cấp với CSDL dựng thẳng từ model);
3. hàm + trigger chặn sửa khi bảng đã khoá — chép NGUYÊN từ ``app/models/admission_quota_ddl.py``
   (``tests/unit/test_gd2a_quota_ddl_lockin.py`` so từng câu sau khi chuẩn hoá khoảng trắng);
4. GĐ2-0 (câu 2 owner 19-11): Casbin cho route ghi nhận minh chứng ưu tiên bằng bản giấy (``CASBIN_POLICIES``, ``template_id``
   riêng), chèn ``WHERE NOT EXISTS`` rồi đếm — CŨNG trong câu ``DO`` (câu riêng sẽ commit lẻ dưới AUTOCOMMIT).

Chờ khoá tối đa ``LOCK_TIMEOUT`` (10 s) — quá ⇒ câu ``DO`` rollback trọn, báo ``UpgradeLockTimeout``.

``downgrade``: FAIL-CLOSED — còn dòng ở ba bảng mới ⇒ DỪNG, không xoá gì (SQLSTATE ``QLC10``), trừ khi đặt
``GD2A_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Chỉ tiêu ngành nằm ở cột CÓ SẴN
``offering_academic_info.annual_admission_quota`` — hạ cấp KHÔNG đụng tới giá trị ấy.
"""

import os
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "gd2a20261118"
down_revision: Union[str, None] = "gd1b20261117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"
#: SQLSTATE của điểm dừng hạ cấp (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE).
SQLSTATE_DOWNGRADE_DATA_PRESENT = "QLC10"

# ---------------------------------------------------------------------------------------------------------------------
# 1–2. Ràng buộc mới + bảng mới. Thứ tự: bảng được tham chiếu trước.
# ---------------------------------------------------------------------------------------------------------------------
ADD_ACADEMIC_INFO_UNIQUE = (
    "ALTER TABLE offering_academic_info ADD CONSTRAINT uq_offering_academic_info_id_year UNIQUE (id, academic_year)"
)

CREATE_TABLES = (
    """CREATE TABLE admission_quota_table (
	academic_year INTEGER NOT NULL,
	status VARCHAR(10) DEFAULT 'draft' NOT NULL,
	locked_by_user_id INTEGER,
	locked_at TIMESTAMP WITH TIME ZONE,
	version INTEGER DEFAULT 1 NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (academic_year),
	CONSTRAINT ck_admission_quota_table_status CHECK (status IN ('draft','locked')),
	CONSTRAINT ck_admission_quota_table_locked_by CHECK ((status = 'locked') = (locked_by_user_id IS NOT NULL)),
	CONSTRAINT ck_admission_quota_table_locked_pair CHECK ((locked_by_user_id IS NULL) = (locked_at IS NULL)),
	CONSTRAINT ck_admission_quota_table_version CHECK (version >= 1),
	FOREIGN KEY(locked_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE admission_quota_group (
	id SERIAL NOT NULL,
	academic_year INTEGER NOT NULL,
	code VARCHAR(30) NOT NULL,
	name VARCHAR(255) NOT NULL,
	ceiling INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_admission_quota_group_year_code UNIQUE (academic_year, code),
	CONSTRAINT uq_admission_quota_group_id_year UNIQUE (id, academic_year),
	CONSTRAINT ck_admission_quota_group_ceiling CHECK (ceiling >= 0),
	CONSTRAINT ck_admission_quota_group_code CHECK (length(btrim(code)) > 0),
	CONSTRAINT ck_admission_quota_group_name CHECK (length(btrim(name)) > 0),
	FOREIGN KEY(academic_year) REFERENCES admission_quota_table (academic_year) ON DELETE RESTRICT
)""",
    """CREATE TABLE admission_quota_group_member (
	id SERIAL NOT NULL,
	group_id INTEGER NOT NULL,
	offering_academic_info_id INTEGER NOT NULL,
	academic_year INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_admission_quota_group_member_oai UNIQUE (offering_academic_info_id),
	CONSTRAINT fk_admission_quota_group_member_group FOREIGN KEY(group_id, academic_year) REFERENCES admission_quota_group (id, academic_year) ON DELETE CASCADE,
	CONSTRAINT fk_admission_quota_group_member_oai FOREIGN KEY(offering_academic_info_id, academic_year) REFERENCES offering_academic_info (id, academic_year) ON DELETE RESTRICT
)""",
)

CREATE_INDEXES = (
    "CREATE INDEX ix_admission_quota_table_locked_by_user_id ON admission_quota_table (locked_by_user_id)",
    "CREATE INDEX ix_admission_quota_group_member_group_id ON admission_quota_group_member (group_id)",
)

# ---------------------------------------------------------------------------------------------------------------------
# 3. Hàm + trigger — chép NGUYÊN từ app/models/admission_quota_ddl.py (migration KHÔNG import mã ứng dụng).
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_ASSERT_UNLOCKED = """
CREATE OR REPLACE FUNCTION admission_quota_assert_table_unlocked(p_year integer)
RETURNS void AS $$
DECLARE
    v_status text;
BEGIN
    IF p_year IS NULL THEN
        RETURN;
    END IF;
    SELECT t.status INTO v_status
      FROM admission_quota_table t
     WHERE t.academic_year = p_year
       FOR SHARE;
    IF v_status = 'locked' THEN
        RAISE EXCEPTION 'admission_quota_table da khoa'
            USING ERRCODE = 'QLC01';
    END IF;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_ACADEMIC_INFO_QUOTA = """
CREATE OR REPLACE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.annual_admission_quota IS NOT DISTINCT FROM OLD.annual_admission_quota THEN
        RETURN NEW;
    END IF;
    PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
    IF NEW.academic_year IS DISTINCT FROM OLD.academic_year THEN
        PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_GROUP_ROWS = """
CREATE OR REPLACE FUNCTION chan_sua_nhom_chi_tieu_khi_bang_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_TABLE_DELETE = """
CREATE OR REPLACE FUNCTION chan_xoa_bang_chi_tieu_da_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'locked' THEN
        RAISE EXCEPTION 'admission_quota_table da khoa'
            USING ERRCODE = 'QLC01';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGERS = (
    """
CREATE TRIGGER trg_chan_sua_chi_tieu_nganh_khi_bang_khoa
BEFORE UPDATE OF annual_admission_quota ON offering_academic_info
FOR EACH ROW EXECUTE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
""",
    """
CREATE TRIGGER trg_chan_sua_nhom_chi_tieu_khi_bang_khoa
BEFORE INSERT OR UPDATE OR DELETE ON admission_quota_group
FOR EACH ROW EXECUTE FUNCTION chan_sua_nhom_chi_tieu_khi_bang_khoa()
""",
    """
CREATE TRIGGER trg_chan_sua_thanh_vien_nhom_khi_bang_khoa
BEFORE INSERT OR UPDATE OR DELETE ON admission_quota_group_member
FOR EACH ROW EXECUTE FUNCTION chan_sua_nhom_chi_tieu_khi_bang_khoa()
""",
    """
CREATE TRIGGER trg_chan_xoa_bang_chi_tieu_da_khoa
BEFORE DELETE ON admission_quota_table
FOR EACH ROW EXECUTE FUNCTION chan_xoa_bang_chi_tieu_da_khoa()
""",
)

STATEMENTS = (
    SQL_FN_ASSERT_UNLOCKED,
    SQL_FN_ACADEMIC_INFO_QUOTA,
    SQL_FN_GROUP_ROWS,
    SQL_FN_TABLE_DELETE,
    *SQL_TRIGGERS,
)


#: Casbin cho route GĐ2-0 (v0, v1, v2, v3) — chép CỨNG (migration không phụ thuộc mã ứng dụng đang đổi);
#: ``tests/unit/test_gd2_minh_chung_uu_tien_luat.py`` khoá bằng ``policy_templates.GD2_PRIORITY_PAPER_OBJECTS``. Admin qua wildcard;
#: Quản lý kế thừa cán bộ; kế toán kế thừa cán bộ ⇒ deny tường minh.
_PRIORITY_PAPER = (("/api/v2/admissions/*/priority-evidence/*/paper-submitted", "POST"),)
CASBIN_POLICIES = (
    tuple(("role:officer", o, a, "allow") for o, a in _PRIORITY_PAPER)
    + tuple(("role:accountant", o, a, "deny") for o, a in _PRIORITY_PAPER)
)
CASBIN_TEMPLATE_ID = "_gd2a20261118_priority_paper"


def _casbin_block_sql() -> str:
    """Thân PL/pgSQL nhúng vào câu ``DO`` của nâng cấp (dùng biến ``n_casbin``). Chèn ``WHERE NOT EXISTS`` rồi đếm; lệch ⇒
    ``RAISE`` (``QLC11``) ⇒ cả câu ``DO`` rollback."""
    chen = ";\n".join(
        "    INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at) "
        "SELECT 'p', '{0}', '{1}', '{2}', '{3}', '{t}', now() WHERE NOT EXISTS (SELECT 1 FROM casbin_rule "
        "WHERE ptype = 'p' AND v0 = '{0}' AND v1 = '{1}' AND v2 = '{2}' AND v3 = '{3}')".format(*p, t=CASBIN_TEMPLATE_ID)
        for p in CASBIN_POLICIES
    )
    dk = " OR ".join("(v0 = '%s' AND v1 = '%s' AND v2 = '%s' AND v3 = '%s')" % p for p in CASBIN_POLICIES)
    return (
        "%s;\n"
        "    SELECT COUNT(DISTINCT (v0, v1, v2, v3)) INTO n_casbin FROM casbin_rule WHERE ptype = 'p' AND (%s);\n"
        "    IF n_casbin <> %d THEN\n"
        "        RAISE EXCEPTION 'gd2a20261118: can %% dong casbin, thay %%', %d, n_casbin USING ERRCODE = 'QLC11';\n"
        "    END IF" % (chen, dk, len(CASBIN_POLICIES), len(CASBIN_POLICIES))
    )


class UpgradeLockTimeout(RuntimeError):
    """upgrade chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


class GD2ADataPresent(RuntimeError):
    """downgrade gặp dữ liệu GĐ2-A mà cờ cho phép xoá chưa bật — không xoá gì."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _upgrade_sql() -> str:
    body = ";\n    ".join(
        s.strip() for s in (ADD_ACADEMIC_INFO_UNIQUE, *CREATE_TABLES, *CREATE_INDEXES, *STATEMENTS)
    )
    return f"""
DO $gd2a$
DECLARE
    n_casbin bigint;
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE offering_academic_info IN SHARE ROW EXCLUSIVE MODE;
    {body};
{_casbin_block_sql()};
    RAISE NOTICE 'gd2a20261118: bang chi tieu nam + nhom nganh + trigger khoa + casbin GD2-0 da cai';
END
$gd2a$
"""


def upgrade() -> None:
    bind = op.get_bind()
    try:
        # exec_driver_sql: thân hàm plpgsql có ``$$`` — không qua ``text()``.
        bind.exec_driver_sql(_upgrade_sql())
    except DBAPIError as e:
        if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "Nâng cấp gd2a20261118 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % LOCK_TIMEOUT
            ) from None
        raise


DOWNGRADE_SQL = """
DO $gd2a_down$
DECLARE
    n_rows bigint;
BEGIN
    PERFORM set_config('lock_timeout', '10s', true);
    LOCK TABLE admission_quota_table, admission_quota_group, admission_quota_group_member, offering_academic_info
        IN SHARE ROW EXCLUSIVE MODE;
    SELECT (SELECT count(*) FROM admission_quota_table) + (SELECT count(*) FROM admission_quota_group)
         + (SELECT count(*) FROM admission_quota_group_member)
      INTO n_rows;
    IF n_rows > 0 AND current_setting('gd2a.allow_drop_data', true) IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'gd2a20261118 downgrade: con % dong du lieu GD2-A — dung, khong xoa gi', n_rows
            USING ERRCODE = 'QLC10';
    END IF;
    DROP TRIGGER IF EXISTS trg_chan_sua_chi_tieu_nganh_khi_bang_khoa ON offering_academic_info;
    DROP TRIGGER IF EXISTS trg_chan_sua_nhom_chi_tieu_khi_bang_khoa ON admission_quota_group;
    DROP TRIGGER IF EXISTS trg_chan_sua_thanh_vien_nhom_khi_bang_khoa ON admission_quota_group_member;
    DROP TRIGGER IF EXISTS trg_chan_xoa_bang_chi_tieu_da_khoa ON admission_quota_table;
    DROP TABLE admission_quota_group_member;
    DROP TABLE admission_quota_group;
    DROP TABLE admission_quota_table;
    DROP FUNCTION IF EXISTS chan_sua_chi_tieu_nganh_khi_bang_khoa();
    DROP FUNCTION IF EXISTS chan_sua_nhom_chi_tieu_khi_bang_khoa();
    DROP FUNCTION IF EXISTS chan_xoa_bang_chi_tieu_da_khoa();
    DROP FUNCTION IF EXISTS admission_quota_assert_table_unlocked(integer);
    ALTER TABLE offering_academic_info DROP CONSTRAINT uq_offering_academic_info_id_year;
    DELETE FROM casbin_rule WHERE ptype = 'p' AND template_id = '_gd2a20261118_priority_paper';
END
$gd2a_down$
"""


def downgrade() -> None:
    """FAIL-CLOSED: còn dòng ở ba bảng mới ⇒ dừng, trừ khi ``GD2A_DOWNGRADE_DROP_DATA_ENABLED=1``."""
    bind = op.get_bind()
    if os.environ.get("GD2A_DOWNGRADE_DROP_DATA_ENABLED") == "1":
        bind.exec_driver_sql("SELECT set_config('gd2a.allow_drop_data', '1', false)")
    try:
        bind.exec_driver_sql(DOWNGRADE_SQL)
    except DBAPIError as e:
        if _sqlstate(e) == SQLSTATE_DOWNGRADE_DATA_PRESENT:
            raise GD2ADataPresent(
                "Hạ cấp gd2a20261118 dừng: còn dữ liệu bảng chỉ tiêu GĐ2-A. Không xoá gì. Đặt "
                "GD2A_DOWNGRADE_DROP_DATA_ENABLED=1 nếu thật sự muốn xoá."
            ) from None
        raise
    finally:
        bind.exec_driver_sql("SELECT set_config('gd2a.allow_drop_data', '', false)")
