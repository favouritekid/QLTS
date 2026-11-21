"""GĐ2-B — lần xét nháp, điểm sàn, lượt chạy kiểm hồ sơ, dòng kết quả + trigger bất biến; ``offering_admission_round`` thêm
UNIQUE (id, academic_year).

Revision ID: gd2b20261121
Revises: gd2f20261119
Create Date: 2026-11-21

Đặc tả: ``logs-P5/cong-bo-ket-qua/gd2/DAC-TA-GD2-B-HOP-NHAT-BAN4-2026-11-20.md`` (sha256 ``6247a1a8…``) §4.1, §4.2; hợp đồng API
bản 4 (``b877fba1…``); kế hoạch triển khai 21-11 + biên bản owner K1–K4 21-11 (đợt 1, lát L1). Không đổi dữ liệu có sẵn. KHÔNG thêm
dòng Casbin (Admin đã có ``/*``).

MỘT câu ``DO`` làm TẤT CẢ (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ở bất kỳ bước nào ⇒ không còn
gì dở dang, phiên bản Alembic chưa đổi, chạy lại được. Trong câu ấy:

0. ``lock_timeout`` 10 s rồi ``LOCK TABLE`` mọi bảng CÓ SẴN bị chạm, THỨ TỰ CỐ ĐỊNH (:data:`LOCKS`): ``"user"`` → ``offering_admission_round``
   (ACCESS EXCLUSIVE — ``ADD CONSTRAINT UNIQUE`` cần, lấy ngay từ đầu để khỏi nâng khoá giữa chừng) → ``offering_academic_info`` →
   ``admission_quota_table`` (SHARE ROW EXCLUSIVE — đủ cho tạo khoá ngoại trỏ tới). Thứ tự ``offering_academic_info`` trước
   ``admission_quota_table`` cùng chiều thứ tự khoá toàn hệ (``core/review_year_lock.py``: … → học vụ → bảng chỉ tiêu).
1. ``offering_admission_round`` thêm ``UNIQUE (id, academic_year)`` — đích khoá ngoại ghép (đợt, năm) của lần xét (§4.1);
2. tạo bốn bảng + chỉ mục (chép theo model ``app/models/admission_review.py`` — ``tests/integration/test_gd2b_migration.py`` so
   lược đồ sau nâng cấp với CSDL dựng thẳng từ model; ``tests/unit/test_gd2b_ddl_lockin.py`` so tên + chữ CHECK);
3. hàm + trigger — chép NGUYÊN từ ``app/models/admission_review_ddl.py`` (:data:`STATEMENTS`; test lock-in so từng câu).

Chờ khoá quá ``LOCK_TIMEOUT`` ⇒ câu ``DO`` rollback trọn, báo :class:`UpgradeLockTimeout` (khuôn ``gd2a20261118``). Deploy giờ vắng
(``"user"`` bị chặn ghi trong lúc nâng — vài trăm mili giây trên CSDL rảnh).

``downgrade``: FAIL-CLOSED — còn dòng ở BẤT KỲ bảng nào trong bốn bảng mới ⇒ DỪNG, không xoá gì (SQLSTATE
:data:`SQLSTATE_DOWNGRADE_DATA_PRESENT` ``QLC12`` — ``QLC10`` đã thuộc ``gd2a20261118``), trừ khi đặt
``GD2B_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``). Khoá cùng thứ tự với nâng cấp rồi mới đếm.
"""

import os
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "gd2b20261121"
down_revision: Union[str, None] = "gd2f20261119"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"
#: SQLSTATE của điểm dừng hạ cấp (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE).
SQLSTATE_DOWNGRADE_DATA_PRESENT = "QLC12"
#: Cờ CHO PHÉP hạ cấp xoá dữ liệu (mặc định tắt; chỉ đúng chữ ``1`` mới bật).
DROP_DATA_ENABLED_ENV = "GD2B_DOWNGRADE_DROP_DATA_ENABLED"

#: Bảng CÓ SẴN bị chạm, ĐÚNG thứ tự khoá (cả nâng lẫn hạ cấp).
LOCKS = (
    ('"user"', "SHARE ROW EXCLUSIVE"),
    ("offering_admission_round", "ACCESS EXCLUSIVE"),
    ("offering_academic_info", "SHARE ROW EXCLUSIVE"),
    ("admission_quota_table", "SHARE ROW EXCLUSIVE"),
)
#: Bốn bảng mới — thứ tự xoá (bảng con trước).
NEW_TABLES = ("admission_review_row", "admission_review_run", "admission_review_floor", "admission_review_session")

# ---------------------------------------------------------------------------------------------------------------------
# 1–2. Ràng buộc mới + bảng mới. Thứ tự: bảng được tham chiếu trước.
# ---------------------------------------------------------------------------------------------------------------------
ADD_ROUND_UNIQUE = (
    "ALTER TABLE offering_admission_round ADD CONSTRAINT uq_offering_admission_round_id_year UNIQUE (id, academic_year)"
)

CREATE_TABLES = (
    """CREATE TABLE admission_review_session (
	id SERIAL NOT NULL,
	academic_year INTEGER NOT NULL,
	admission_round_id INTEGER NOT NULL,
	seq_no INTEGER NOT NULL,
	status VARCHAR(20) DEFAULT 'draft' NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	created_by_user_id INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	cancelled_by_user_id INTEGER,
	cancelled_at TIMESTAMP WITH TIME ZONE,
	cancel_reason TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_admission_review_session_year_seq UNIQUE (academic_year, seq_no),
	CONSTRAINT uq_admission_review_session_id_year UNIQUE (id, academic_year),
	CONSTRAINT ck_admission_review_session_status CHECK (status IN ('draft','cancelled')),
	CONSTRAINT ck_admission_review_session_seq_no CHECK (seq_no > 0),
	CONSTRAINT ck_admission_review_session_version CHECK (version >= 1),
	CONSTRAINT ck_admission_review_session_cancelled CHECK ((status = 'cancelled') = (cancelled_by_user_id IS NOT NULL AND cancelled_at IS NOT NULL AND cancel_reason IS NOT NULL AND btrim(cancel_reason) <> '')),
	CONSTRAINT ck_admission_review_session_cancel_clear CHECK (status = 'cancelled' OR (cancelled_by_user_id IS NULL AND cancelled_at IS NULL AND cancel_reason IS NULL)),
	CONSTRAINT fk_admission_review_session_quota_table FOREIGN KEY(academic_year) REFERENCES admission_quota_table (academic_year) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_session_round FOREIGN KEY(admission_round_id, academic_year) REFERENCES offering_admission_round (id, academic_year) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_session_created_by FOREIGN KEY(created_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_session_cancelled_by FOREIGN KEY(cancelled_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE admission_review_floor (
	id SERIAL NOT NULL,
	session_id INTEGER NOT NULL,
	academic_year INTEGER NOT NULL,
	offering_academic_info_id INTEGER NOT NULL,
	floor_score NUMERIC(5, 2) NOT NULL,
	updated_by_user_id INTEGER NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_admission_review_floor_session_oai UNIQUE (session_id, offering_academic_info_id),
	CONSTRAINT ck_admission_review_floor_score CHECK (floor_score >= 0),
	CONSTRAINT fk_admission_review_floor_session FOREIGN KEY(session_id, academic_year) REFERENCES admission_review_session (id, academic_year) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_floor_oai FOREIGN KEY(offering_academic_info_id, academic_year) REFERENCES offering_academic_info (id, academic_year) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_floor_updated_by FOREIGN KEY(updated_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE admission_review_run (
	id SERIAL NOT NULL,
	session_id INTEGER NOT NULL,
	kind VARCHAR(20) NOT NULL,
	status VARCHAR(20) NOT NULL,
	rule_version VARCHAR(50) NOT NULL,
	requested_by_user_id INTEGER NOT NULL,
	requested_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	duration_ms INTEGER,
	inputs JSONB NOT NULL,
	summary JSONB,
	quota_view JSONB,
	error_code VARCHAR(100),
	PRIMARY KEY (id),
	CONSTRAINT ck_admission_review_run_kind CHECK (kind IN ('evaluate')),
	CONSTRAINT ck_admission_review_run_status CHECK (status IN ('queued','running','done','failed')),
	CONSTRAINT ck_admission_review_run_state_columns CHECK ((status <> 'queued' OR (started_at IS NULL AND finished_at IS NULL AND duration_ms IS NULL AND summary IS NULL AND quota_view IS NULL AND error_code IS NULL)) AND (status <> 'running' OR (started_at IS NOT NULL AND finished_at IS NULL AND duration_ms IS NULL AND summary IS NULL AND quota_view IS NULL AND error_code IS NULL)) AND (status <> 'done' OR (started_at IS NOT NULL AND finished_at IS NOT NULL AND duration_ms IS NOT NULL AND summary IS NOT NULL AND quota_view IS NOT NULL AND error_code IS NULL)) AND (status <> 'failed' OR (started_at IS NOT NULL AND finished_at IS NOT NULL AND duration_ms IS NOT NULL AND summary IS NULL AND quota_view IS NULL AND error_code IS NOT NULL))),
	CONSTRAINT ck_admission_review_run_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
	CONSTRAINT fk_admission_review_run_session FOREIGN KEY(session_id) REFERENCES admission_review_session (id) ON DELETE RESTRICT,
	CONSTRAINT fk_admission_review_run_requested_by FOREIGN KEY(requested_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE admission_review_row (
	id SERIAL NOT NULL,
	run_id INTEGER NOT NULL,
	profile_id INTEGER NOT NULL,
	profile_status VARCHAR(20) NOT NULL,
	tab VARCHAR(20) NOT NULL,
	reason_codes TEXT[] DEFAULT '{}' NOT NULL,
	flags TEXT[] DEFAULT '{}' NOT NULL,
	decision_hints TEXT[] DEFAULT '{}' NOT NULL,
	document_gaps JSONB,
	considered_choice_id INTEGER,
	considered_display_order INTEGER,
	considered_offering_academic_info_id INTEGER,
	considered_offering_id INTEGER,
	considered_admission_path_id INTEGER,
	considered_major_code VARCHAR(50),
	considered_major_name VARCHAR(255),
	considered_offering_type VARCHAR(100),
	subject_total NUMERIC(5, 2),
	area_score NUMERIC(5, 2),
	object_score NUMERIC(5, 2),
	priority_total NUMERIC(5, 2),
	review_total NUMERIC(5, 2),
	floor_score NUMERIC(5, 2),
	rank_in_major INTEGER,
	within_seats BOOLEAN,
	ethnic_priority_state VARCHAR(30),
	per_choice JSONB DEFAULT '[]' NOT NULL,
	prior_year_findings JSONB DEFAULT '[]' NOT NULL,
	row_hash VARCHAR(64) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_admission_review_row_run_profile UNIQUE (run_id, profile_id),
	CONSTRAINT ck_admission_review_row_tab CHECK (tab IN ('auto','needs_decision','not_passed','ineligible')),
	CONSTRAINT ck_admission_review_row_hash CHECK (row_hash ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_admission_review_row_placed CHECK ((tab IN ('auto','needs_decision')) = (considered_choice_id IS NOT NULL)),
	CONSTRAINT ck_admission_review_row_placed_fields CHECK (considered_choice_id IS NULL OR (considered_display_order IS NOT NULL AND considered_offering_academic_info_id IS NOT NULL AND considered_offering_id IS NOT NULL AND considered_admission_path_id IS NOT NULL AND review_total IS NOT NULL)),
	CONSTRAINT ck_admission_review_row_reasons CHECK (tab = 'auto' OR cardinality(reason_codes) > 0),
	CONSTRAINT ck_admission_review_row_ethnic_state CHECK (ethnic_priority_state IS NULL OR ethnic_priority_state IN ('not_applicable','full_evidence','provisional_by_commune','undetermined')),
	CONSTRAINT ck_admission_review_row_per_choice_array CHECK (jsonb_typeof(per_choice) = 'array'),
	CONSTRAINT ck_admission_review_row_prior_year_findings_array CHECK (jsonb_typeof(prior_year_findings) = 'array'),
	CONSTRAINT ck_admission_review_row_profile_condition CHECK (tab <> 'ineligible' OR per_choice <> '[]' OR (ethnic_priority_state IS NULL AND review_total IS NULL)),
	CONSTRAINT fk_admission_review_row_run FOREIGN KEY(run_id) REFERENCES admission_review_run (id) ON DELETE RESTRICT
)""",
)

CREATE_INDEXES = (
    "CREATE INDEX ix_admission_review_session_created_by_user_id ON admission_review_session (created_by_user_id)",
    "CREATE INDEX ix_admission_review_session_cancelled_by_user_id ON admission_review_session (cancelled_by_user_id)",
    "CREATE INDEX ix_admission_review_floor_oai ON admission_review_floor (offering_academic_info_id)",
    "CREATE INDEX ix_admission_review_floor_updated_by_user_id ON admission_review_floor (updated_by_user_id)",
    "CREATE UNIQUE INDEX uq_admission_review_run_session_active ON admission_review_run (session_id) "
    "WHERE status IN ('queued','running')",
    "CREATE INDEX ix_admission_review_run_session_id ON admission_review_run (session_id)",
    "CREATE INDEX ix_admission_review_run_requested_by_user_id ON admission_review_run (requested_by_user_id)",
)

# ---------------------------------------------------------------------------------------------------------------------
# 3. Hàm + trigger — chép NGUYÊN từ app/models/admission_review_ddl.py (migration KHÔNG import mã ứng dụng).
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_ASSERT_SESSION_DRAFT = """
CREATE OR REPLACE FUNCTION admission_review_assert_session_draft(p_session_id integer)
RETURNS void AS $$
DECLARE
    v_status text;
BEGIN
    SELECT s.status INTO v_status
      FROM admission_review_session s
     WHERE s.id = p_session_id
       FOR SHARE;
    IF v_status IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'admission_review_session khong o trang thai nhap'
            USING ERRCODE = 'QLC02';
    END IF;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_SESSION_GUARD = """
CREATE OR REPLACE FUNCTION admission_review_session_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'admission_review_session khong xoa duoc'
            USING ERRCODE = 'QLC03';
    END IF;
    IF OLD.status = 'cancelled' THEN
        RAISE EXCEPTION 'admission_review_session da huy'
            USING ERRCODE = 'QLC02';
    END IF;
    IF NEW.academic_year IS DISTINCT FROM OLD.academic_year THEN
        RAISE EXCEPTION 'admission_review_session khong doi nam'
            USING ERRCODE = 'QLC03';
    END IF;
    IF NEW.status = 'cancelled' AND EXISTS (
        SELECT 1 FROM admission_review_floor f WHERE f.session_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'admission_review_session con diem san'
            USING ERRCODE = 'QLC03';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_FLOOR_GUARD = """
CREATE OR REPLACE FUNCTION admission_review_floor_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM admission_review_assert_session_draft(OLD.session_id);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM admission_review_assert_session_draft(NEW.session_id);
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_RUN_GUARD = """
CREATE OR REPLACE FUNCTION admission_review_run_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'admission_review_run khong xoa duoc'
            USING ERRCODE = 'QLC03';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('queued', 'running') THEN
            RAISE EXCEPTION 'admission_review_run chi tao o queued hoac running'
                USING ERRCODE = 'QLC03';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status NOT IN ('queued', 'running') THEN
        RAISE EXCEPTION 'admission_review_run da xong khong sua duoc'
            USING ERRCODE = 'QLC03';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
       AND NOT (OLD.status = 'queued' AND NEW.status = 'running')
       AND NOT (OLD.status = 'running' AND NEW.status IN ('done', 'failed')) THEN
        RAISE EXCEPTION 'admission_review_run chuyen trang thai sai'
            USING ERRCODE = 'QLC03';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_ROW_GUARD = """
CREATE OR REPLACE FUNCTION admission_review_row_guard()
RETURNS TRIGGER AS $$
DECLARE
    v_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'admission_review_row chi them'
            USING ERRCODE = 'QLC03';
    END IF;
    SELECT r.status INTO v_status
      FROM admission_review_run r
     WHERE r.id = NEW.run_id
       FOR SHARE;
    IF v_status IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'admission_review_run khong o trang thai running'
            USING ERRCODE = 'QLC03';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGERS = (
    """
CREATE TRIGGER trg_admission_review_session_guard
BEFORE UPDATE OR DELETE ON admission_review_session
FOR EACH ROW EXECUTE FUNCTION admission_review_session_guard()
""",
    """
CREATE TRIGGER trg_admission_review_floor_guard
BEFORE INSERT OR UPDATE OR DELETE ON admission_review_floor
FOR EACH ROW EXECUTE FUNCTION admission_review_floor_guard()
""",
    """
CREATE TRIGGER trg_admission_review_run_guard
BEFORE INSERT OR UPDATE OR DELETE ON admission_review_run
FOR EACH ROW EXECUTE FUNCTION admission_review_run_guard()
""",
    """
CREATE TRIGGER trg_admission_review_row_guard
BEFORE INSERT OR UPDATE OR DELETE ON admission_review_row
FOR EACH ROW EXECUTE FUNCTION admission_review_row_guard()
""",
)

STATEMENTS = (
    SQL_FN_ASSERT_SESSION_DRAFT,
    SQL_FN_SESSION_GUARD,
    SQL_FN_FLOOR_GUARD,
    SQL_FN_RUN_GUARD,
    SQL_FN_ROW_GUARD,
    *SQL_TRIGGERS,
)

FUNCTION_SIGNATURES = (
    "admission_review_assert_session_draft(integer)",
    "admission_review_session_guard()",
    "admission_review_floor_guard()",
    "admission_review_run_guard()",
    "admission_review_row_guard()",
)


class UpgradeLockTimeout(RuntimeError):
    """upgrade / downgrade chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


class GD2BDataPresent(RuntimeError):
    """downgrade gặp dữ liệu GĐ2-B mà cờ cho phép xoá chưa bật — không xoá gì."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _lock_sql() -> str:
    """``set_config('lock_timeout')`` rồi ``LOCK TABLE`` từng bảng có sẵn theo :data:`LOCKS` (một câu / bảng — chế độ khác nhau)."""
    lines = ["PERFORM set_config('lock_timeout', '%s', true)" % LOCK_TIMEOUT]
    lines += ["LOCK TABLE %s IN %s MODE" % (t, m) for t, m in LOCKS]
    return ";\n    ".join(lines)


def _upgrade_sql() -> str:
    body = ";\n    ".join(s.strip() for s in (ADD_ROUND_UNIQUE, *CREATE_TABLES, *CREATE_INDEXES, *STATEMENTS))
    return f"""
DO $gd2b$
BEGIN
    {_lock_sql()};
    {body};
    RAISE NOTICE 'gd2b20261121: lan xet nhap + diem san + luot chay + dong ket qua + trigger da cai';
END
$gd2b$
"""


def _raise_lock_timeout(e: DBAPIError, chieu: str) -> None:
    if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
        raise UpgradeLockTimeout(
            "%s gd2b20261121 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh." % (chieu, LOCK_TIMEOUT)
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
    dem = " + ".join("(SELECT count(*) FROM %s)" % t for t in NEW_TABLES)
    return f"""
DO $gd2b_down$
DECLARE
    n_rows bigint;
BEGIN
    {_lock_sql()};
    LOCK TABLE {", ".join(reversed(NEW_TABLES))} IN ACCESS EXCLUSIVE MODE;
    SELECT {dem} INTO n_rows;
    IF n_rows > 0 AND current_setting('gd2b.allow_drop_data', true) IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'gd2b20261121 downgrade: con du lieu GD2-B - dung, khong xoa gi'
            USING ERRCODE = '{SQLSTATE_DOWNGRADE_DATA_PRESENT}';
    END IF;
    DROP TABLE {", ".join(NEW_TABLES)};
    DROP FUNCTION {", ".join(FUNCTION_SIGNATURES)};
    ALTER TABLE offering_admission_round DROP CONSTRAINT uq_offering_admission_round_id_year;
    RAISE NOTICE 'gd2b20261121: da ha cap';
END
$gd2b_down$
"""


def downgrade() -> None:
    """FAIL-CLOSED: còn dòng ở bốn bảng mới ⇒ dừng, trừ khi ``GD2B_DOWNGRADE_DROP_DATA_ENABLED=1`` (đúng chữ ``1``)."""
    bind = op.get_bind()
    if os.environ.get(DROP_DATA_ENABLED_ENV) == "1":
        bind.exec_driver_sql("SELECT set_config('gd2b.allow_drop_data', '1', false)")
    try:
        bind.exec_driver_sql(_downgrade_sql())
    except DBAPIError as e:
        if _sqlstate(e) == SQLSTATE_DOWNGRADE_DATA_PRESENT:
            raise GD2BDataPresent(
                "Hạ cấp gd2b20261121 dừng (SQLSTATE %s): còn dữ liệu lần xét GĐ2-B. Không xoá gì. Đặt %s=1 nếu thật sự "
                "muốn xoá." % (SQLSTATE_DOWNGRADE_DATA_PRESENT, DROP_DATA_ENABLED_ENV)
            ) from None
        _raise_lock_timeout(e, "Hạ cấp")
        raise
    finally:
        bind.exec_driver_sql("SELECT set_config('gd2b.allow_drop_data', '', false)")
