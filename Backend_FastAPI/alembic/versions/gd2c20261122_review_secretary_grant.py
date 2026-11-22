"""GĐ2-C C1 — bảng quyền "Thư ký Hội đồng" gán theo từng người + trigger "chỉ thu hồi, không xoá".

Revision ID: gd2c20261122
Revises: gd2b20261121
Create Date: 2026-11-22

Nguồn: QĐB:26; thiết kế GĐ2-C 22-11 §2.2 (``logs-P5/cong-bo-ket-qua/gd2/gd2c/THIET-KE-GD2-C-2026-11-22.md``); owner C1
22-11 "Không hết hạn, giữ tới khi Admin thu hồi" ⇒ KHÔNG có cột hết hạn. Không đổi dữ liệu có sẵn; không thêm dòng
Casbin (route gán / thu hồi / liệt kê chỉ Admin — Admin đi qua wildcard).

⚠️ Chuỗi Alembic: nền gốc của C1 (PR-B ``42a497c8``) có head ``gd2f20261119``. Nền tích hợp GĐ2-C C2 (22-11) gộp C1 lên
GĐ2-B (``gd2b20261121``, cũng nối sau ``gd2f20261119``) ⇒ ``down_revision`` đổi sang ``gd2b20261121`` — một head (ca
``test_mot_head_alembic`` đỏ nếu hai head). Thân migration không đổi: C1 không phụ thuộc bảng nào của GĐ2-B.

MỘT câu ``DO`` làm TẤT CẢ (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ở bất kỳ bước nào ⇒
không còn gì dở dang, phiên bản Alembic chưa đổi, chạy lại được. Trong câu ấy:

1. tạo bảng + chỉ mục — chép NGUYÊN câu ``CREATE`` sinh từ model ``app/models/admission_review_secretary.py``
   (``tests/integration/test_gd2c_c1_migration.py`` so lược đồ sau nâng cấp với CSDL dựng thẳng từ model);
2. hàm + trigger "chỉ thu hồi, không xoá" — chép NGUYÊN từ ``app/models/admission_review_secretary_ddl.py``
   (``tests/unit/test_gd2c_c1_ddl_lockin.py`` so từng câu sau khi chuẩn hoá khoảng trắng).

Khoá ngoại tới ``"user"`` lấy khoá ``SHARE ROW EXCLUSIVE`` trên bảng ``user`` (chặn ghi ``user`` trong lúc câu ``DO`` chạy —
vài mili giây trên bảng rỗng). Chờ khoá tối đa ``LOCK_TIMEOUT`` (10 s) — quá ⇒ câu ``DO`` rollback trọn, báo
``UpgradeLockTimeout``.

``downgrade``: FAIL-CLOSED — còn dòng quyền ⇒ DỪNG, không xoá gì (SQLSTATE ``QLC21``), trừ khi đặt
``GD2C_C1_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Bảng rỗng ⇒ hạ được, nâng lại được.
"""

import os
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "gd2c20261122"
down_revision: Union[str, None] = "gd2b20261121"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"
#: SQLSTATE của điểm dừng hạ cấp (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE).
SQLSTATE_DOWNGRADE_DATA_PRESENT = "QLC21"
DOWNGRADE_FLAG = "GD2C_C1_DOWNGRADE_DROP_DATA_ENABLED"

# ---------------------------------------------------------------------------------------------------------------------
# 1. Bảng + chỉ mục (sinh từ model bằng ``CreateTable`` / ``CreateIndex`` của SQLAlchemy 2.0.44, dialect postgresql).
# ---------------------------------------------------------------------------------------------------------------------
CREATE_TABLES = (
    """CREATE TABLE admission_review_secretary_grant (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	granted_by_user_id INTEGER NOT NULL,
	granted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	reason TEXT NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	revoked_by_user_id INTEGER,
	revoke_reason TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_review_secretary_grant_reason CHECK (length(btrim(reason)) > 0),
	CONSTRAINT ck_review_secretary_grant_revoked_triple CHECK ((revoked_at IS NULL) = (revoked_by_user_id IS NULL) AND (revoked_at IS NULL) = (revoke_reason IS NULL)),
	CONSTRAINT ck_review_secretary_grant_revoke_reason CHECK (revoke_reason IS NULL OR length(btrim(revoke_reason)) > 0),
	FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	FOREIGN KEY(granted_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	FOREIGN KEY(revoked_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
)

CREATE_INDEXES = (
    "CREATE INDEX ix_admission_review_secretary_grant_granted_by_user_id ON admission_review_secretary_grant "
    "(granted_by_user_id)",
    "CREATE INDEX ix_admission_review_secretary_grant_revoked_by_user_id ON admission_review_secretary_grant "
    "(revoked_by_user_id)",
    "CREATE INDEX ix_admission_review_secretary_grant_user_id ON admission_review_secretary_grant (user_id)",
    "CREATE UNIQUE INDEX uq_review_secretary_grant_active_user ON admission_review_secretary_grant (user_id) "
    "WHERE revoked_at IS NULL",
)

# ---------------------------------------------------------------------------------------------------------------------
# 2. Hàm + trigger — chép NGUYÊN từ app/models/admission_review_secretary_ddl.py (migration KHÔNG import mã ứng dụng).
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_REVOKE_ONLY = """
CREATE OR REPLACE FUNCTION admission_review_secretary_grant_revoke_only()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'admission_review_secretary_grant: chi thu hoi, khong xoa'
            USING ERRCODE = 'QLC20';
    END IF;
    IF OLD.revoked_at IS NOT NULL
       OR NEW.revoked_at IS NULL
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.user_id IS DISTINCT FROM OLD.user_id
       OR NEW.granted_by_user_id IS DISTINCT FROM OLD.granted_by_user_id
       OR NEW.granted_at IS DISTINCT FROM OLD.granted_at
       OR NEW.reason IS DISTINCT FROM OLD.reason THEN
        RAISE EXCEPTION 'admission_review_secretary_grant: chi duoc ghi thu hoi mot lan, khong sua lan gan'
            USING ERRCODE = 'QLC20';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_REVOKE_ONLY = """
CREATE TRIGGER trg_admission_review_secretary_grant_revoke_only
BEFORE UPDATE OR DELETE ON admission_review_secretary_grant
FOR EACH ROW EXECUTE FUNCTION admission_review_secretary_grant_revoke_only()
"""

STATEMENTS = (SQL_FN_REVOKE_ONLY, SQL_TRIGGER_REVOKE_ONLY)
FUNCTION_SIGNATURES = ("admission_review_secretary_grant_revoke_only()",)


class UpgradeLockTimeout(RuntimeError):
    """upgrade chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


class GD2CC1DataPresent(RuntimeError):
    """downgrade gặp dòng quyền Thư ký mà cờ cho phép xoá chưa bật — không xoá gì."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _upgrade_sql() -> str:
    body = ";\n    ".join(s.strip() for s in (*CREATE_TABLES, *CREATE_INDEXES, *STATEMENTS))
    return f"""
DO $gd2c_c1$
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    {body};
    RAISE NOTICE 'gd2c20261122: bang quyen Thu ky Hoi dong + trigger chi thu hoi da cai';
END
$gd2c_c1$
"""


def upgrade() -> None:
    bind = op.get_bind()
    try:
        # exec_driver_sql: thân hàm plpgsql có ``$$`` — không qua ``text()``.
        bind.exec_driver_sql(_upgrade_sql())
    except DBAPIError as e:
        if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "Nâng cấp gd2c20261122 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % LOCK_TIMEOUT
            ) from None
        raise


DOWNGRADE_SQL = """
DO $gd2c_c1_down$
DECLARE
    n_rows bigint;
BEGIN
    PERFORM set_config('lock_timeout', '10s', true);
    LOCK TABLE admission_review_secretary_grant IN SHARE ROW EXCLUSIVE MODE;
    SELECT count(*) INTO n_rows FROM admission_review_secretary_grant;
    IF n_rows > 0 AND current_setting('gd2c_c1.allow_drop_data', true) IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'gd2c20261122 downgrade: con % dong quyen Thu ky Hoi dong — dung, khong xoa gi', n_rows
            USING ERRCODE = 'QLC21';
    END IF;
    DROP TRIGGER IF EXISTS trg_admission_review_secretary_grant_revoke_only ON admission_review_secretary_grant;
    DROP TABLE admission_review_secretary_grant;
    DROP FUNCTION IF EXISTS admission_review_secretary_grant_revoke_only();
END
$gd2c_c1_down$
"""


def downgrade() -> None:
    """FAIL-CLOSED: còn dòng quyền ⇒ dừng, trừ khi ``GD2C_C1_DOWNGRADE_DROP_DATA_ENABLED=1``."""
    bind = op.get_bind()
    if os.environ.get(DOWNGRADE_FLAG) == "1":
        bind.exec_driver_sql("SELECT set_config('gd2c_c1.allow_drop_data', '1', false)")
    try:
        bind.exec_driver_sql(DOWNGRADE_SQL)
    except DBAPIError as e:
        if _sqlstate(e) == SQLSTATE_DOWNGRADE_DATA_PRESENT:
            raise GD2CC1DataPresent(
                "Hạ cấp gd2c20261122 dừng: còn dòng quyền Thư ký Hội đồng. Không xoá gì. Đặt "
                "GD2C_C1_DOWNGRADE_DROP_DATA_ENABLED=1 nếu thật sự muốn xoá."
            ) from None
        raise
    finally:
        bind.exec_driver_sql("SELECT set_config('gd2c_c1.allow_drop_data', '', false)")
