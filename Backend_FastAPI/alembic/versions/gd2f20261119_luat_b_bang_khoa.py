"""GĐ2-F1 — luật B (owner chốt 19-11): khoá bảng chỉ tiêu năm ĐÓNG BĂNG chỉ tiêu nhưng vẫn cho cấu hình học phí sớm.

Revision ID: gd2f20261119
Revises: gd2a20261118
Create Date: 2026-11-19

Thay hàm + trigger ``trg_chan_sua_chi_tieu_nganh_khi_bang_khoa`` trên ``offering_academic_info`` (GĐ2-A: chỉ
``BEFORE UPDATE OF annual_admission_quota``, thoát sớm khi chỉ tiêu không đổi ⇒ lệnh chỉ đổi ``academic_year`` lọt qua):

* R1 — ``INSERT`` học vụ CÓ chỉ tiêu (kể cả 0; trống ≠ 0) cho năm đã khoá ⇒ chặn; chỉ tiêu TRỐNG ⇒ cho.
* R2 — đổi chỉ tiêu học vụ của năm đã khoá ⇒ chặn (như GĐ2-A).
* R3 — chuyển năm học vụ có chỉ tiêu (OLD hoặc NEW khác NULL) VÀO hoặc RA năm đã khoá ⇒ chặn, kể cả khi con số không đổi.

Hai câu chép NGUYÊN từ ``app/models/admission_quota_ddl.py`` (:data:`STATEMENTS_F1`;
``tests/unit/test_gd2f_trigger_luat_b_lockin.py`` so từng câu). Hàm kiểm chung ``admission_quota_assert_table_unlocked`` và các
trigger nhóm / thành viên / bảng của GĐ2-A KHÔNG đổi. Migration GĐ2-A KHÔNG sửa.

MỘT câu ``DO`` mỗi chiều (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ⇒ không còn gì dở dang.
Chờ khoá tối đa ``LOCK_TIMEOUT`` (10 s) — quá ⇒ rollback trọn, báo ``UpgradeLockTimeout``.

``downgrade``: trả ĐÚNG hàm + trigger của GĐ2-A (chép nguyên; trigger dạng ``CREATE OR REPLACE`` vì tên đã có). Không đổi dữ
liệu ở cả hai chiều ⇒ không cần cờ cho phép.
"""
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "gd2f20261119"
down_revision: Union[str, None] = "gd2a20261118"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"

# ---------------------------------------------------------------------------------------------------------------------
# upgrade — NGUYÊN VĂN ``admission_quota_ddl.STATEMENTS_F1``.
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_ACADEMIC_INFO_QUOTA_F1 = """
CREATE OR REPLACE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.annual_admission_quota IS NOT NULL THEN
            PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.academic_year IS NOT DISTINCT FROM OLD.academic_year THEN
        IF NEW.annual_admission_quota IS NOT DISTINCT FROM OLD.annual_admission_quota THEN
            RETURN NEW;
        END IF;
        PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
        RETURN NEW;
    END IF;
    IF OLD.annual_admission_quota IS NULL AND NEW.annual_admission_quota IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
    PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_ACADEMIC_INFO_F1 = """
CREATE OR REPLACE TRIGGER trg_chan_sua_chi_tieu_nganh_khi_bang_khoa
BEFORE INSERT OR UPDATE OF annual_admission_quota, academic_year ON offering_academic_info
FOR EACH ROW EXECUTE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
"""

UPGRADE_STATEMENTS = (SQL_FN_ACADEMIC_INFO_QUOTA_F1, SQL_TRIGGER_ACADEMIC_INFO_F1)

# ---------------------------------------------------------------------------------------------------------------------
# downgrade — NGUYÊN VĂN hàm GĐ2-A (``admission_quota_ddl.SQL_FN_ACADEMIC_INFO_QUOTA``) + trigger GĐ2-A dạng
# ``CREATE OR REPLACE`` (``admission_quota_ddl.SQL_TRIGGERS[0]``).
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_ACADEMIC_INFO_QUOTA_GD2A = """
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

SQL_TRIGGER_ACADEMIC_INFO_GD2A = """
CREATE OR REPLACE TRIGGER trg_chan_sua_chi_tieu_nganh_khi_bang_khoa
BEFORE UPDATE OF annual_admission_quota ON offering_academic_info
FOR EACH ROW EXECUTE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
"""

DOWNGRADE_STATEMENTS = (SQL_FN_ACADEMIC_INFO_QUOTA_GD2A, SQL_TRIGGER_ACADEMIC_INFO_GD2A)


class UpgradeLockTimeout(RuntimeError):
    """Chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _do_sql(statements, nhan: str, thong_bao: str) -> str:
    body = ";\n    ".join(s.strip() for s in statements)
    return f"""
DO ${nhan}$
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE offering_academic_info IN SHARE ROW EXCLUSIVE MODE;
    {body};
    RAISE NOTICE '{thong_bao}';
END
${nhan}$
"""


def _chay(statements, nhan: str, thong_bao: str, chieu: str) -> None:
    bind = op.get_bind()
    try:
        # exec_driver_sql: thân hàm plpgsql có ``$$`` — không qua ``text()``.
        bind.exec_driver_sql(_do_sql(statements, nhan, thong_bao))
    except DBAPIError as e:
        if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "%s gd2f20261119 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % (chieu, LOCK_TIMEOUT)
            ) from None
        raise


def upgrade() -> None:
    _chay(UPGRADE_STATEMENTS, "gd2f", "gd2f20261119: trigger luat B (INSERT + academic_year) da cai", "Nâng cấp")


def downgrade() -> None:
    _chay(DOWNGRADE_STATEMENTS, "gd2f_down", "gd2f20261119: tra trigger GD2-A", "Hạ cấp")
