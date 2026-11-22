"""GĐ2-C C2 — bảng lựa chọn của Ban thư ký + trigger "chỉ thêm, chỉ khi lần xét nháp" + dòng Casbin cho route Ban thư ký.

Revision ID: gd2cs20261122
Revises: gd2c20261122
Create Date: 2026-11-22

Nguồn: QĐB:12, QĐB:18; ĐT3 §3, §11; thiết kế GĐ2-C 22-11 §2.2, §4, §6 hàng C2; owner C5 / C6 22-11. Không đổi dữ liệu có sẵn.

MỘT câu ``DO`` làm TẤT CẢ (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ở bất kỳ bước nào ⇒ không còn
gì dở dang, phiên bản Alembic chưa đổi, chạy lại được. Trong câu ấy:

0. ``lock_timeout`` 10 s rồi ``LOCK TABLE`` các bảng CÓ SẴN được khoá ngoại trỏ tới, THỨ TỰ CỐ ĐỊNH (:data:`LOCKS`): ``"user"`` →
   ``admission_review_session`` → ``admission_review_run`` (SHARE ROW EXCLUSIVE — đúng khoá mà ``ADD FOREIGN KEY`` cần, lấy ngay từ
   đầu để khỏi nâng khoá giữa chừng; cùng chiều GĐ2-B: người dùng trước, lần xét trước lượt chạy). Quá 10 s ⇒ câu ``DO`` rollback
   trọn, báo ``UpgradeLockTimeout``.
1. tạo bảng + chỉ mục — chép NGUYÊN câu ``CREATE`` theo model ``app/models/admission_review_selection.py``
   (``tests/integration/test_gd2c_c2_migration.py`` so lược đồ sau nâng cấp với CSDL dựng thẳng từ model);
2. hàm + trigger — chép NGUYÊN từ ``app/models/admission_review_selection_ddl.py`` (``tests/unit/test_gd2c_c2_ddl_lockin.py`` so
   từng câu sau khi chuẩn hoá khoảng trắng). Hàm gọi ``admission_review_assert_session_draft`` của ``gd2b20261121``;
3. dòng Casbin cho route Ban thư ký (:data:`CASBIN_POLICIES` — chép CỨNG từ ``policy_templates.GD2C_REVIEW_SECRETARY_OBJECTS``;
   test khoá bằng nhau): chèn ``WHERE NOT EXISTS`` rồi đếm; lệch ⇒ ``RAISE`` (SQLSTATE :data:`SQLSTATE_CASBIN_COUNT`) ⇒ rollback.

``downgrade``: FAIL-CLOSED — còn dòng lựa chọn ⇒ DỪNG, không xoá gì (SQLSTATE :data:`SQLSTATE_DOWNGRADE_DATA_PRESENT`), trừ khi
đặt ``GD2C_C2_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Bảng rỗng ⇒ hạ được, nâng lại được.
Hạ cấp gỡ luôn dòng Casbin mang ``template_id`` của migration này (route Ban thư ký trở về 403 như trước C2).
"""

import os
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "gd2cs20261122"
down_revision: Union[str, None] = "gd2c20261122"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"
#: SQLSTATE: đếm dòng Casbin sau khi chèn lệch số cần (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE).
SQLSTATE_CASBIN_COUNT = "QLC23"
#: SQLSTATE của điểm dừng hạ cấp.
SQLSTATE_DOWNGRADE_DATA_PRESENT = "QLC24"
DOWNGRADE_FLAG = "GD2C_C2_DOWNGRADE_DROP_DATA_ENABLED"

#: Bảng CÓ SẴN được khoá ngoại trỏ tới — ĐÚNG thứ tự khoá (cả nâng lẫn hạ cấp).
LOCKS = (
    ('"user"', "SHARE ROW EXCLUSIVE"),
    ("admission_review_session", "SHARE ROW EXCLUSIVE"),
    ("admission_review_run", "SHARE ROW EXCLUSIVE"),
)
NEW_TABLE = "admission_review_selection"

# ---------------------------------------------------------------------------------------------------------------------
# 1. Bảng + chỉ mục (theo model; dạng chữ của ``CreateTable`` / ``CreateIndex`` SQLAlchemy 2.0, dialect postgresql).
# ---------------------------------------------------------------------------------------------------------------------
CREATE_TABLES = (
    """CREATE TABLE admission_review_selection (
	id SERIAL NOT NULL,
	session_id INTEGER NOT NULL,
	academic_year INTEGER NOT NULL,
	profile_id INTEGER NOT NULL,
	kind VARCHAR(40) NOT NULL,
	choice_id INTEGER,
	based_on_run_id INTEGER NOT NULL,
	based_on_row_hash VARCHAR(64) NOT NULL,
	decided_by_user_id INTEGER NOT NULL,
	decided_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	note TEXT,
	supersedes_id INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT uq_admission_review_selection_supersedes UNIQUE (supersedes_id),
	CONSTRAINT ck_admission_review_selection_kind CHECK (kind IN ('admit_over_major_quota','consider_next_choice','defer_supplement','admit_without_ethnic_bonus','exclude_this_session','keep_despite_inactive')),
	CONSTRAINT ck_admission_review_selection_row_hash CHECK (based_on_row_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_admission_review_selection_note CHECK (note IS NULL OR length(btrim(note)) > 0),
	CONSTRAINT ck_admission_review_selection_note_required CHECK (kind NOT IN ('exclude_this_session','defer_supplement') OR note IS NOT NULL),
	CONSTRAINT ck_admission_review_selection_supersedes_order CHECK (supersedes_id IS NULL OR supersedes_id < id),
	CONSTRAINT fk_admission_review_selection_session FOREIGN KEY(session_id, academic_year) REFERENCES admission_review_session (id, academic_year) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_selection_run FOREIGN KEY(based_on_run_id) REFERENCES admission_review_run (id) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_selection_decided_by FOREIGN KEY(decided_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_selection_supersedes FOREIGN KEY(supersedes_id) REFERENCES admission_review_selection (id) ON DELETE RESTRICT
)""",
)

CREATE_INDEXES = (
    "CREATE UNIQUE INDEX uq_admission_review_selection_root ON admission_review_selection (session_id, profile_id) "
    "WHERE supersedes_id IS NULL",
    "CREATE INDEX ix_admission_review_selection_session_profile ON admission_review_selection (session_id, profile_id)",
    "CREATE INDEX ix_admission_review_selection_based_on_run_id ON admission_review_selection (based_on_run_id)",
    "CREATE INDEX ix_admission_review_selection_decided_by_user_id ON admission_review_selection (decided_by_user_id)",
)

# ---------------------------------------------------------------------------------------------------------------------
# 2. Hàm + trigger — chép NGUYÊN từ app/models/admission_review_selection_ddl.py (migration KHÔNG import mã ứng dụng).
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_SELECTION_GUARD = """
CREATE OR REPLACE FUNCTION admission_review_selection_guard()
RETURNS TRIGGER AS $$
DECLARE
    v_run_session integer;
    v_run_kind text;
    v_run_status text;
    v_row_hash text;
    v_row_choice integer;
    v_prev_session integer;
    v_prev_profile integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'admission_review_selection chi them'
            USING ERRCODE = 'QLC22';
    END IF;
    PERFORM admission_review_assert_session_draft(NEW.session_id);
    SELECT r.session_id, r.kind, r.status INTO v_run_session, v_run_kind, v_run_status
      FROM admission_review_run r
     WHERE r.id = NEW.based_on_run_id;
    IF v_run_session IS DISTINCT FROM NEW.session_id
       OR v_run_kind IS DISTINCT FROM 'evaluate'
       OR v_run_status IS DISTINCT FROM 'done' THEN
        RAISE EXCEPTION 'admission_review_selection dua vao luot khong hop le'
            USING ERRCODE = 'QLC22';
    END IF;
    SELECT w.row_hash, w.considered_choice_id INTO v_row_hash, v_row_choice
      FROM admission_review_row w
     WHERE w.run_id = NEW.based_on_run_id
       AND w.profile_id = NEW.profile_id;
    IF NOT FOUND
       OR v_row_hash IS DISTINCT FROM NEW.based_on_row_hash
       OR v_row_choice IS DISTINCT FROM NEW.choice_id THEN
        RAISE EXCEPTION 'admission_review_selection dua vao dong khong khop'
            USING ERRCODE = 'QLC22';
    END IF;
    IF NEW.supersedes_id IS NOT NULL THEN
        SELECT p.session_id, p.profile_id INTO v_prev_session, v_prev_profile
          FROM admission_review_selection p
         WHERE p.id = NEW.supersedes_id;
        IF v_prev_session IS DISTINCT FROM NEW.session_id
           OR v_prev_profile IS DISTINCT FROM NEW.profile_id THEN
            RAISE EXCEPTION 'admission_review_selection thay dong khong cung ho so'
                USING ERRCODE = 'QLC22';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_SELECTION_GUARD = """
CREATE TRIGGER trg_admission_review_selection_guard
BEFORE INSERT OR UPDATE OR DELETE ON admission_review_selection
FOR EACH ROW EXECUTE FUNCTION admission_review_selection_guard()
"""

STATEMENTS = (SQL_FN_SELECTION_GUARD, SQL_TRIGGER_SELECTION_GUARD)
FUNCTION_SIGNATURES = ("admission_review_selection_guard()",)

# ---------------------------------------------------------------------------------------------------------------------
# 3. Casbin — (v0, v1, v2, v3) chép CỨNG (migration không phụ thuộc mã ứng dụng đang đổi); khoá bằng
#    ``policy_templates.GD2C_REVIEW_SECRETARY_OBJECTS`` ở ``tests/unit/test_gd2c_c2_ddl_lockin.py``. Cán bộ ALLOW; Quản lý / Kế
#    toán kế thừa cán bộ; Admin wildcard. Kế toán KHÔNG deny: cổng ``require_review_secretary`` trả 404 như người chưa gán.
# ---------------------------------------------------------------------------------------------------------------------
_SECRETARY_OBJECTS = (
    ("/api/admission-config/quota-tables/{academic_year}", "GET"),
    ("/api/admission-config/review-sessions/{session_id}/selections", "GET"),
    ("/api/admission-config/review-sessions/{session_id}/selections/{profile_id}", "GET"),
    ("/api/admission-config/review-sessions/{session_id}/selections/{profile_id}", "PUT"),
)
CASBIN_POLICIES = tuple(("role:officer", o, a, "allow") for o, a in _SECRETARY_OBJECTS)
CASBIN_TEMPLATE_ID = "_gd2cs20261122_review_secretary"


def _casbin_block_sql() -> str:
    """Thân PL/pgSQL nhúng vào câu ``DO`` của nâng cấp (dùng biến ``n_casbin``). Chèn ``WHERE NOT EXISTS`` rồi đếm; lệch ⇒
    ``RAISE`` ⇒ cả câu ``DO`` rollback. Khuôn ``gd2a20261118``."""
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
        "        RAISE EXCEPTION 'gd2cs20261122: can %% dong casbin, thay %%', %d, n_casbin USING ERRCODE = '%s';\n"
        "    END IF" % (chen, dk, len(CASBIN_POLICIES), len(CASBIN_POLICIES), SQLSTATE_CASBIN_COUNT)
    )


class UpgradeLockTimeout(RuntimeError):
    """upgrade / downgrade chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


class GD2CC2DataPresent(RuntimeError):
    """downgrade gặp dòng lựa chọn của Ban thư ký mà cờ cho phép xoá chưa bật — không xoá gì."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _lock_sql() -> str:
    """``set_config('lock_timeout')`` rồi ``LOCK TABLE`` từng bảng có sẵn theo :data:`LOCKS`."""
    lines = ["PERFORM set_config('lock_timeout', '%s', true)" % LOCK_TIMEOUT]
    lines += ["LOCK TABLE %s IN %s MODE" % (t, m) for t, m in LOCKS]
    return ";\n    ".join(lines)


def _upgrade_sql() -> str:
    body = ";\n    ".join(s.strip() for s in (*CREATE_TABLES, *CREATE_INDEXES, *STATEMENTS))
    return f"""
DO $gd2c_c2$
DECLARE
    n_casbin bigint;
BEGIN
    {_lock_sql()};
    {body};
{_casbin_block_sql()};
    RAISE NOTICE 'gd2cs20261122: bang lua chon Ban thu ky + trigger + casbin da cai';
END
$gd2c_c2$
"""


def _raise_lock_timeout(e: DBAPIError, chieu: str) -> None:
    if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
        raise UpgradeLockTimeout(
            "%s gd2cs20261122 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh." % (chieu, LOCK_TIMEOUT)
        ) from None


def upgrade() -> None:
    bind = op.get_bind()
    try:
        # exec_driver_sql: thân hàm plpgsql có ``$$`` — không qua ``text()``.
        bind.exec_driver_sql(_upgrade_sql())
    except DBAPIError as e:
        _raise_lock_timeout(e, "Nâng cấp")
        raise


def _downgrade_sql() -> str:
    return f"""
DO $gd2c_c2_down$
DECLARE
    n_rows bigint;
BEGIN
    {_lock_sql()};
    LOCK TABLE {NEW_TABLE} IN ACCESS EXCLUSIVE MODE;
    SELECT count(*) INTO n_rows FROM {NEW_TABLE};
    IF n_rows > 0 AND current_setting('gd2c_c2.allow_drop_data', true) IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'gd2cs20261122 downgrade: con % dong lua chon Ban thu ky - dung, khong xoa gi', n_rows
            USING ERRCODE = '{SQLSTATE_DOWNGRADE_DATA_PRESENT}';
    END IF;
    DROP TRIGGER IF EXISTS trg_admission_review_selection_guard ON {NEW_TABLE};
    DROP TABLE {NEW_TABLE};
    DROP FUNCTION IF EXISTS admission_review_selection_guard();
    DELETE FROM casbin_rule WHERE ptype = 'p' AND template_id = '{CASBIN_TEMPLATE_ID}';
END
$gd2c_c2_down$
"""


def downgrade() -> None:
    """FAIL-CLOSED: còn dòng lựa chọn ⇒ dừng, trừ khi ``GD2C_C2_DOWNGRADE_DROP_DATA_ENABLED=1``."""
    bind = op.get_bind()
    if os.environ.get(DOWNGRADE_FLAG) == "1":
        bind.exec_driver_sql("SELECT set_config('gd2c_c2.allow_drop_data', '1', false)")
    try:
        bind.exec_driver_sql(_downgrade_sql())
    except DBAPIError as e:
        _raise_lock_timeout(e, "Hạ cấp")
        if _sqlstate(e) == SQLSTATE_DOWNGRADE_DATA_PRESENT:
            raise GD2CC2DataPresent(
                "Hạ cấp gd2cs20261122 dừng: còn dòng lựa chọn của Ban thư ký. Không xoá gì. Đặt "
                "GD2C_C2_DOWNGRADE_DROP_DATA_ENABLED=1 nếu thật sự muốn xoá."
            ) from None
        raise
    finally:
        bind.exec_driver_sql("SELECT set_config('gd2c_c2.allow_drop_data', '', false)")
