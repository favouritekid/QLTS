"""GĐ1b — duyệt giấy nhanh, duyệt chéo tạm thời, dấu tải xuống, tệp bằng chứng, người tải / người nhận giấy.

Revision ID: gd1b20261117
Revises: hdts20261113
Create Date: 2026-11-17

Đặc tả: ``logs-P5/cong-bo-ket-qua/gd1b/DAC-TA-GD1B-DUYET-GIAY-NHANH-BAN3-6-2026-11-17.md`` (sha256 ``9ef02da2…4e2e``,
Codex 67 ĐẠT) §4.3, §4.4, §4.6b, §5.1, §6, §10. GO viết mã owner 17-11.

MỘT câu ``DO`` làm TẤT CẢ (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ở bất kỳ bước nào
⇒ không còn gì dở dang, phiên bản Alembic chưa đổi, chạy lại được. Trong câu ấy:

1. tạo 5 bảng mới (câu ``CREATE TABLE`` / ``CREATE INDEX`` chép NGUYÊN từ model — ``tests/unit/test_gd1b_models_khop_migration.py``
   so hai bên);
2. thêm 4 cột ``profile_document`` (``uploaded_by`` RESTRICT, hai cờ "không rõ", ``row_version``);
3. khôi phục người tải §4.4 — bản ghi nhật ký MỚI NHẤT trong các hành động đổi tệp (``uploaded``, ``reset``,
   ``paper_submitted``, ``deleted``) của đúng dòng giấy; nhận actor CHỈ khi hành động = ``uploaded``, ``new_file_path`` = tệp
   hiện tại (khác rỗng), actor còn tồn tại. Không đủ ⇒ ``uploaded_by_unknown``. Không suy từ nguồn khác;
4. giấy bản giấy (không tệp) ``paper_submitted`` / ``verified`` mất người nhận ⇒ ``paper_submitted_by_unknown``;
5. đếm trước / sau, lệch ⇒ ``RAISE``; rồi mới thêm I1, I2 (kiểm toàn bảng);
6. điền ngược ``document_download_log`` từ mọi dòng ``downloaded`` có actor (đếm, lệch ⇒ ``RAISE``);
7. điền ngược ``document_evidence_file`` cho giấy thường ``verified`` có tệp — sha256 / tệp mất tính bằng Python TRƯỚC câu
   ``DO`` (đọc đĩa, chỉ đọc), truyền vào như một hằng JSON; trong câu ``DO`` đối chiếu lại đúng tập giấy + đường dẫn, lệch ⇒
   ``RAISE``. Giấy ``verified`` có tệp mà KHÔNG có bản ghi nhật ký ``verified`` ⇒ ``RAISE`` (không bịa nhật ký; ghi chú
   ở ``gd1b/KE-HOACH-VIET-MA-GD1B-2026-11-17.md`` — đo trên production trước khi xin GO deploy);
9. ``user_activity_log.target_user_id`` ⇒ ``ON DELETE SET NULL`` (K4: tài khoản BỊ thao tác không phải "đã từng thao
   tác"; trước đây ORM tự gán NULL qua ``User.activities_received``) — ``app/services/user_deletion_policy.py``;
8. trigger ``row_version`` (tạo SAU khi điền ngược để mọi dòng cũ giữ ``row_version = 1``) — câu chép NGUYÊN từ
   ``app/models/admission_config/document_row_version_ddl.py``.

Casbin cho route mới thêm khi route chốt (cùng PR, trước khi xin merge).

``downgrade``: FAIL-CLOSED — còn dòng ở bảng mới, hoặc cột mới còn giá trị khác mặc định ⇒ DỪNG, không xoá gì, trừ khi đặt
``GD1B_DOWNGRADE_DROP_DATA_ENABLED=1`` (cờ CHO PHÉP, mặc định tắt, đúng chữ ``1``).
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence, Union

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "gd1b20261117"
down_revision: Union[str, None] = "hdts20261113"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"

#: SQLSTATE riêng cho từng điểm dừng (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE ⇒ người vận hành đọc mã để biết
#: dừng vì đâu). QLB01 người tải lệch · QLB02 người nhận lệch · QLB03 dấu tải lệch · QLB04 tập giấy bằng chứng đổi
#: trong lúc nâng cấp · QLB05 giấy đã duyệt có tệp mà không có nhật ký verified · QLB06 dòng bằng chứng lệch ·
#: QLB07 ``user_activity_log.target_user_id`` không có đúng một khoá ngoại.
SQLSTATE_NO_VERIFIED_AUDIT = "QLB05"
SQLSTATE_DOWNGRADE_DATA_PRESENT = "QLB10"

#: Gốc ứng dụng (``/app`` trong ảnh) — ``file_path`` của giấy lưu TƯƠNG ĐỐI (``uploads/admissions/{id}/…``).
APP_ROOT = Path(__file__).resolve().parents[2]

#: Thẻ dollar-quote của hằng JSON tệp bằng chứng. Phải không xuất hiện trong dữ liệu (kiểm trước khi chèn).
_EVIDENCE_TAG = "$gd1b_evidence$"

# ---------------------------------------------------------------------------------------------------------------------
# 1. Bảng mới — chép NGUYÊN từ model (``CreateTable(...).compile(postgresql)``). Thứ tự: bảng được tham chiếu trước.
# ---------------------------------------------------------------------------------------------------------------------
CREATE_TABLES = (
    """CREATE TABLE document_cross_review_grant (
	id SERIAL NOT NULL,
	grantee_user_id INTEGER NOT NULL,
	unit_id INTEGER NOT NULL,
	allow_verify BOOLEAN DEFAULT false NOT NULL,
	allow_reject BOOLEAN DEFAULT false NOT NULL,
	granted_by_user_id INTEGER NOT NULL,
	granted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	reason TEXT NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	revoked_by_user_id INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT ck_cross_review_grant_action CHECK (allow_verify OR allow_reject),
	CONSTRAINT ck_cross_review_grant_reason CHECK (length(btrim(reason)) > 0),
	CONSTRAINT ck_cross_review_grant_max_days CHECK (expires_at > granted_at AND expires_at <= granted_at + interval '14 days'),
	CONSTRAINT ck_cross_review_grant_revoked_pair CHECK ((revoked_at IS NULL) = (revoked_by_user_id IS NULL)),
	FOREIGN KEY(grantee_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	FOREIGN KEY(unit_id) REFERENCES organization_unit (id) ON DELETE RESTRICT,
	FOREIGN KEY(granted_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	FOREIGN KEY(revoked_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE document_download_log (
	id BIGSERIAL NOT NULL,
	actor_user_id INTEGER NOT NULL,
	profile_id INTEGER NOT NULL,
	document_row_id INTEGER NOT NULL,
	document_type_code VARCHAR(100),
	downloaded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	ip_address VARCHAR(45),
	user_agent VARCHAR(500),
	source_audit_id INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY(actor_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	UNIQUE (source_audit_id)
)""",
    """CREATE TABLE document_evidence_file (
	id SERIAL NOT NULL,
	profile_document_id INTEGER NOT NULL,
	verification_audit_id INTEGER NOT NULL,
	profile_id INTEGER NOT NULL,
	file_path VARCHAR(500) NOT NULL,
	sha256 VARCHAR(64),
	verified_by_user_id INTEGER,
	verified_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	file_missing BOOLEAN DEFAULT false NOT NULL,
	retention_basis VARCHAR(100),
	retain_until DATE,
	PRIMARY KEY (id),
	CONSTRAINT ck_document_evidence_file_sha256 CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'),
	CONSTRAINT ck_document_evidence_file_sha256_present CHECK (file_missing OR sha256 IS NOT NULL),
	FOREIGN KEY(profile_document_id) REFERENCES profile_document (id) ON DELETE RESTRICT,
	UNIQUE (verification_audit_id),
	FOREIGN KEY(verification_audit_id) REFERENCES document_audit_log (id) ON DELETE RESTRICT,
	FOREIGN KEY(verified_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE document_bulk_batch (
	batch_id UUID NOT NULL,
	actor_user_id INTEGER NOT NULL,
	review_mode VARCHAR(10) DEFAULT 'batch' NOT NULL,
	grant_id INTEGER,
	filter_json JSONB NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	include_optional BOOLEAN DEFAULT false NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	confirmation_text TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	finalized_by_user_id INTEGER,
	finalized_at TIMESTAMP WITH TIME ZONE,
	finalize_reason TEXT,
	status VARCHAR(20) DEFAULT 'previewed' NOT NULL,
	ip_address VARCHAR(45),
	user_agent VARCHAR(500),
	PRIMARY KEY (batch_id),
	CONSTRAINT ck_document_bulk_batch_status CHECK (status IN ('previewed','processing','completed','stopped','interrupted')),
	CONSTRAINT ck_document_bulk_batch_review_mode CHECK (review_mode IN ('batch','cross')),
	CONSTRAINT ck_document_bulk_batch_grant CHECK ((review_mode = 'cross') = (grant_id IS NOT NULL)),
	CONSTRAINT ck_document_bulk_batch_finalized_pair CHECK ((finalized_at IS NULL) = (finalized_by_user_id IS NULL)),
	FOREIGN KEY(actor_user_id) REFERENCES "user" (id) ON DELETE RESTRICT,
	FOREIGN KEY(grant_id) REFERENCES document_cross_review_grant (id) ON DELETE RESTRICT,
	FOREIGN KEY(finalized_by_user_id) REFERENCES "user" (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE document_bulk_batch_item (
	batch_id UUID NOT NULL,
	document_row_id INTEGER NOT NULL,
	profile_id INTEGER NOT NULL,
	document_type_code VARCHAR(100),
	expected_row_version INTEGER NOT NULL,
	result VARCHAR(20),
	reason_code VARCHAR(60),
	message TEXT,
	updated_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_document_bulk_batch_item PRIMARY KEY (batch_id, document_row_id),
	CONSTRAINT ck_document_bulk_batch_item_result CHECK (result IS NULL OR result IN ('recorded','error','not_processed')),
	FOREIGN KEY(batch_id) REFERENCES document_bulk_batch (batch_id) ON DELETE CASCADE
)""",
)

CREATE_INDEXES = (
    "CREATE INDEX ix_document_cross_review_grant_granted_by_user_id ON document_cross_review_grant (granted_by_user_id)",
    "CREATE INDEX ix_document_cross_review_grant_grantee_user_id ON document_cross_review_grant (grantee_user_id)",
    "CREATE INDEX ix_document_cross_review_grant_revoked_by_user_id ON document_cross_review_grant (revoked_by_user_id)",
    "CREATE INDEX ix_document_cross_review_grant_unit_id ON document_cross_review_grant (unit_id)",
    "CREATE INDEX ix_document_download_log_actor_user_id ON document_download_log (actor_user_id)",
    "CREATE INDEX ix_document_download_log_document_row_id ON document_download_log (document_row_id)",
    "CREATE INDEX ix_document_download_log_profile_id ON document_download_log (profile_id)",
    "CREATE INDEX ix_document_evidence_file_file_path ON document_evidence_file (file_path)",
    "CREATE INDEX ix_document_evidence_file_profile_document_id ON document_evidence_file (profile_document_id)",
    "CREATE INDEX ix_document_evidence_file_profile_id ON document_evidence_file (profile_id)",
    "CREATE INDEX ix_document_evidence_file_verified_by_user_id ON document_evidence_file (verified_by_user_id)",
    "CREATE INDEX ix_document_bulk_batch_actor_created ON document_bulk_batch (actor_user_id, created_at)",
    "CREATE INDEX ix_document_bulk_batch_actor_user_id ON document_bulk_batch (actor_user_id)",
    "CREATE INDEX ix_document_bulk_batch_finalized_by_user_id ON document_bulk_batch (finalized_by_user_id)",
    "CREATE INDEX ix_document_bulk_batch_grant_id ON document_bulk_batch (grant_id)",
    "CREATE INDEX ix_document_bulk_batch_item_profile_id ON document_bulk_batch_item (profile_id)",
    "CREATE INDEX ix_profile_document_uploaded_by ON profile_document (uploaded_by)",
)

# ---------------------------------------------------------------------------------------------------------------------
# 2. Cột mới trên profile_document + I1 / I2 — CHECK chép NGUYÊN chuỗi của model.
# ---------------------------------------------------------------------------------------------------------------------
ADD_PROFILE_DOCUMENT_COLUMNS = (
    'ALTER TABLE profile_document ADD COLUMN uploaded_by INTEGER REFERENCES "user" (id) ON DELETE RESTRICT',
    "ALTER TABLE profile_document ADD COLUMN uploaded_by_unknown BOOLEAN DEFAULT false NOT NULL",
    "ALTER TABLE profile_document ADD COLUMN paper_submitted_by_unknown BOOLEAN DEFAULT false NOT NULL",
    "ALTER TABLE profile_document ADD COLUMN row_version INTEGER DEFAULT 1 NOT NULL",
)

CHECK_I1_NAME = "ck_profile_document_uploader_known"
CHECK_I1_SQL = "category <> 'path' OR file_path IS NULL OR uploaded_by IS NOT NULL OR uploaded_by_unknown"
CHECK_I2_NAME = "ck_profile_document_receiver_known"
CHECK_I2_SQL = (
    "category <> 'path' OR file_path IS NOT NULL "
    "OR status NOT IN ('paper_submitted','verified') "
    "OR paper_submitted_by IS NOT NULL OR paper_submitted_by_unknown"
)

# ---------------------------------------------------------------------------------------------------------------------
# 8. Trigger row_version — chép NGUYÊN từ app/models/admission_config/document_row_version_ddl.py.
# ---------------------------------------------------------------------------------------------------------------------
SQL_FN_ROW_VERSION = """
CREATE OR REPLACE FUNCTION profile_document_bump_row_version()
RETURNS TRIGGER AS $$
BEGIN
    NEW.row_version := OLD.row_version + 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_ROW_VERSION = """
CREATE TRIGGER trg_profile_document_row_version
BEFORE UPDATE ON profile_document
FOR EACH ROW EXECUTE FUNCTION profile_document_bump_row_version()
"""

#: Tập giấy cần dòng bằng chứng (đọc ở Python để tính sha256 VÀ đọc lại trong câu DO — PHẢI cùng một vị từ).
EVIDENCE_CANDIDATES_WHERE = (
    "d.category = 'path' AND d.status = 'verified' AND d.file_path IS NOT NULL AND d.file_path <> ''"
)


class GD1BDataPresent(RuntimeError):
    """downgrade gặp dữ liệu GĐ1b mà cờ cho phép xoá chưa bật — không xoá gì."""


class UpgradeLockTimeout(RuntimeError):
    """upgrade chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _evidence_payload(bind) -> str:
    """Đọc tập giấy ứng viên + tính sha256 trên đĩa (CHỈ ĐỌC). Trả hằng JSON để nhúng vào câu ``DO``."""
    rows = bind.execute(
        text("SELECT d.id, d.file_path FROM profile_document d WHERE " + EVIDENCE_CANDIDATES_WHERE + " ORDER BY d.id")
    ).all()
    payload = []
    for doc_id, file_path in rows:
        p = Path(file_path)
        if not p.is_absolute():
            p = APP_ROOT / p
        if p.is_file():
            payload.append({"doc_id": int(doc_id), "path": file_path, "sha": _sha256_of(p), "missing": False})
        else:
            payload.append({"doc_id": int(doc_id), "path": file_path, "sha": None, "missing": True})
    raw = json.dumps(payload, ensure_ascii=False)
    if _EVIDENCE_TAG in raw or "$$" in raw:
        raise RuntimeError("gd1b20261117: đường dẫn tệp chứa thẻ dollar-quote — dừng, cần xử lý tay")
    return raw


def _upgrade_sql(evidence_json: str) -> str:
    ddl = ";\n".join(
        (*CREATE_TABLES, *CREATE_INDEXES[:-1], *ADD_PROFILE_DOCUMENT_COLUMNS, CREATE_INDEXES[-1])
    )
    return f"""
DO $gd1b$
DECLARE
    n_file_docs bigint;
    n_paper_missing bigint;
    n_filled bigint;
    n_unknown bigint;
    n_paper_flagged bigint;
    n_download_src bigint;
    n_download_ins bigint;
    n_ev_candidates bigint;
    n_ev_payload bigint;
    n_ev_matched bigint;
    n_ev_no_audit bigint;
    n_ev_ins bigint;
    n_fk bigint;
    v_fk name;
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE profile_document, document_audit_log, user_activity_log IN SHARE ROW EXCLUSIVE MODE;

    -- 1 + 2. Bảng, chỉ mục, cột mới.
    {ddl};

    -- 2b. K4: user_activity_log.target_user_id (tài khoản BỊ thao tác) ⇒ ON DELETE SET NULL. Tên ràng buộc đọc từ
    --     pg_constraint (không đoán); đúng MỘT khoá ngoại trên cột ấy, khác ⇒ dừng.
    SELECT count(*) INTO n_fk FROM pg_constraint c
     WHERE c.conrelid = 'user_activity_log'::regclass AND c.contype = 'f'
       AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute
                              WHERE attrelid = 'user_activity_log'::regclass AND attname = 'target_user_id')]::smallint[];
    IF n_fk <> 1 THEN
        RAISE EXCEPTION 'gd1b20261117: user_activity_log.target_user_id co % khoa ngoai', n_fk USING ERRCODE = 'QLB07';
    END IF;
    SELECT c.conname INTO v_fk FROM pg_constraint c
     WHERE c.conrelid = 'user_activity_log'::regclass AND c.contype = 'f'
       AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute
                              WHERE attrelid = 'user_activity_log'::regclass AND attname = 'target_user_id')]::smallint[];
    EXECUTE format('ALTER TABLE user_activity_log DROP CONSTRAINT %I', v_fk);
    ALTER TABLE user_activity_log ADD CONSTRAINT user_activity_log_target_user_id_fkey
        FOREIGN KEY (target_user_id) REFERENCES "user" (id) ON DELETE SET NULL;

    -- 3 + 4. Đếm TRƯỚC.
    SELECT count(*) INTO n_file_docs FROM profile_document
     WHERE category = 'path' AND file_path IS NOT NULL;
    SELECT count(*) INTO n_paper_missing FROM profile_document
     WHERE category = 'path' AND file_path IS NULL
       AND status IN ('paper_submitted','verified') AND paper_submitted_by IS NULL;

    -- 3. Khôi phục người tải (§4.4).
    WITH last_file_event AS (
        SELECT DISTINCT ON (l.profile_document_id)
               l.profile_document_id, l.action, l.new_file_path, l.actor_user_id
          FROM document_audit_log l
         WHERE l.action IN ('uploaded','reset','paper_submitted','deleted')
         ORDER BY l.profile_document_id, l.created_at DESC, l.id DESC
    )
    UPDATE profile_document d
       SET uploaded_by = e.actor_user_id
      FROM last_file_event e
     WHERE e.profile_document_id = d.id
       AND d.category = 'path'
       AND d.file_path IS NOT NULL AND d.file_path <> ''
       AND e.action = 'uploaded'
       AND e.new_file_path = d.file_path
       AND e.actor_user_id IS NOT NULL
       AND EXISTS (SELECT 1 FROM "user" u WHERE u.id = e.actor_user_id);
    GET DIAGNOSTICS n_filled = ROW_COUNT;

    UPDATE profile_document SET uploaded_by_unknown = true
     WHERE category = 'path' AND file_path IS NOT NULL AND uploaded_by IS NULL;
    GET DIAGNOSTICS n_unknown = ROW_COUNT;

    -- 4. Người nhận bản giấy mất ⇒ "không rõ" (không khôi phục từ nhật ký).
    UPDATE profile_document SET paper_submitted_by_unknown = true
     WHERE category = 'path' AND file_path IS NULL
       AND status IN ('paper_submitted','verified') AND paper_submitted_by IS NULL;
    GET DIAGNOSTICS n_paper_flagged = ROW_COUNT;

    -- 5. Đếm SAU — lệch ⇒ dừng.
    IF n_filled + n_unknown <> n_file_docs THEN
        RAISE EXCEPTION 'gd1b20261117: nguoi tai lech — co tep % , dien % , khong ro %', n_file_docs, n_filled, n_unknown
            USING ERRCODE = 'QLB01';
    END IF;
    IF n_paper_flagged <> n_paper_missing THEN
        RAISE EXCEPTION 'gd1b20261117: nguoi nhan lech — thieu % , danh dau %', n_paper_missing, n_paper_flagged
            USING ERRCODE = 'QLB02';
    END IF;
    ALTER TABLE profile_document ADD CONSTRAINT {CHECK_I1_NAME} CHECK ({CHECK_I1_SQL});
    ALTER TABLE profile_document ADD CONSTRAINT {CHECK_I2_NAME} CHECK ({CHECK_I2_SQL});

    -- 6. Dấu tải xuống (K4c).
    SELECT count(*) INTO n_download_src FROM document_audit_log
     WHERE action = 'downloaded' AND actor_user_id IS NOT NULL;
    INSERT INTO document_download_log
           (actor_user_id, profile_id, document_row_id, document_type_code, downloaded_at,
            ip_address, user_agent, source_audit_id)
    SELECT l.actor_user_id, d.profile_id, d.id, t.code, l.created_at, l.ip_address, l.user_agent, l.id
      FROM document_audit_log l
      JOIN profile_document d ON d.id = l.profile_document_id
      LEFT JOIN config_document_type t ON t.id = d.document_type_id
     WHERE l.action = 'downloaded' AND l.actor_user_id IS NOT NULL;
    GET DIAGNOSTICS n_download_ins = ROW_COUNT;
    IF n_download_ins <> n_download_src THEN
        RAISE EXCEPTION 'gd1b20261117: dau tai lech — nguon % , chen %', n_download_src, n_download_ins
            USING ERRCODE = 'QLB03';
    END IF;

    -- 7. Tệp bằng chứng.
    CREATE TEMP TABLE gd1b_evidence_payload ON COMMIT DROP AS
    SELECT x.doc_id, x.path, x.sha, x.missing
      FROM jsonb_to_recordset(CAST({_EVIDENCE_TAG}{evidence_json}{_EVIDENCE_TAG} AS jsonb))
           AS x(doc_id integer, path text, sha text, missing boolean);
    SELECT count(*) INTO n_ev_candidates FROM profile_document d WHERE {EVIDENCE_CANDIDATES_WHERE};
    SELECT count(*) INTO n_ev_payload FROM gd1b_evidence_payload;
    SELECT count(*) INTO n_ev_matched
      FROM gd1b_evidence_payload p JOIN profile_document d ON d.id = p.doc_id
     WHERE {EVIDENCE_CANDIDATES_WHERE} AND d.file_path = p.path;
    IF n_ev_candidates <> n_ev_payload OR n_ev_matched <> n_ev_payload THEN
        RAISE EXCEPTION 'gd1b20261117: tap giay bang chung doi trong luc nang cap — ung vien % , doc dia % , khop %',
            n_ev_candidates, n_ev_payload, n_ev_matched USING ERRCODE = 'QLB04';
    END IF;
    SELECT count(*) INTO n_ev_no_audit
      FROM gd1b_evidence_payload p
     WHERE NOT EXISTS (SELECT 1 FROM document_audit_log l
                        WHERE l.profile_document_id = p.doc_id AND l.action = 'verified');
    IF n_ev_no_audit > 0 THEN
        RAISE EXCEPTION 'gd1b20261117: % giay da duyet co tep nhung khong co nhat ky verified — khong dien nguoc duoc bang chung',
            n_ev_no_audit USING ERRCODE = 'QLB05';
    END IF;
    INSERT INTO document_evidence_file
           (profile_document_id, verification_audit_id, profile_id, file_path, sha256,
            verified_by_user_id, verified_at, file_missing)
    SELECT d.id, a.id, d.profile_id, d.file_path, p.sha, d.verified_by,
           COALESCE(d.verified_at, a.created_at), p.missing
      FROM gd1b_evidence_payload p
      JOIN profile_document d ON d.id = p.doc_id
      JOIN LATERAL (SELECT l.id, l.created_at FROM document_audit_log l
                     WHERE l.profile_document_id = d.id AND l.action = 'verified'
                     ORDER BY l.created_at DESC, l.id DESC LIMIT 1) a ON true;
    GET DIAGNOSTICS n_ev_ins = ROW_COUNT;
    IF n_ev_ins <> n_ev_payload THEN
        RAISE EXCEPTION 'gd1b20261117: bang chung lech — can % , chen %', n_ev_payload, n_ev_ins
            USING ERRCODE = 'QLB06';
    END IF;

    -- 8. Trigger row_version (SAU điền ngược).
    {SQL_FN_ROW_VERSION.strip()};
    {SQL_TRIGGER_ROW_VERSION.strip()};

    RAISE NOTICE 'gd1b20261117: co tep % (dien % , khong ro %), ban giay mat nguoi nhan %, dau tai %, bang chung % ',
        n_file_docs, n_filled, n_unknown, n_paper_flagged, n_download_ins, n_ev_ins;
END
$gd1b$
"""


def upgrade() -> None:
    bind = op.get_bind()
    evidence_json = _evidence_payload(bind)
    try:
        # exec_driver_sql: hằng JSON chứa ``"khoá":`` — ``text()`` sẽ hiểu ``:tên`` là tham số.
        bind.exec_driver_sql(_upgrade_sql(evidence_json))
    except DBAPIError as e:
        if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "Nâng cấp gd1b20261117 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % LOCK_TIMEOUT
            ) from None
        raise


DOWNGRADE_SQL = """
DO $gd1b_down$
DECLARE
    n_rows bigint;
BEGIN
    PERFORM set_config('lock_timeout', '10s', true);
    LOCK TABLE profile_document IN SHARE ROW EXCLUSIVE MODE;
    SELECT (SELECT count(*) FROM document_bulk_batch_item) + (SELECT count(*) FROM document_bulk_batch)
         + (SELECT count(*) FROM document_cross_review_grant) + (SELECT count(*) FROM document_evidence_file)
         + (SELECT count(*) FROM document_download_log WHERE source_audit_id IS NULL)
         + (SELECT count(*) FROM profile_document WHERE uploaded_by IS NOT NULL)
      INTO n_rows;
    IF n_rows > 0 AND current_setting('gd1b.allow_drop_data', true) IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'gd1b20261117 downgrade: con % dong du lieu GD1b — dung, khong xoa gi', n_rows
            USING ERRCODE = 'QLB10';
    END IF;
    DROP TRIGGER IF EXISTS trg_profile_document_row_version ON profile_document;
    DROP FUNCTION IF EXISTS profile_document_bump_row_version();
    ALTER TABLE profile_document DROP CONSTRAINT IF EXISTS ck_profile_document_receiver_known;
    ALTER TABLE profile_document DROP CONSTRAINT IF EXISTS ck_profile_document_uploader_known;
    DROP TABLE document_bulk_batch_item;
    DROP TABLE document_bulk_batch;
    DROP TABLE document_cross_review_grant;
    DROP TABLE document_evidence_file;
    DROP TABLE document_download_log;
    ALTER TABLE profile_document DROP COLUMN row_version;
    ALTER TABLE profile_document DROP COLUMN paper_submitted_by_unknown;
    ALTER TABLE profile_document DROP COLUMN uploaded_by_unknown;
    ALTER TABLE profile_document DROP COLUMN uploaded_by;
    ALTER TABLE user_activity_log DROP CONSTRAINT user_activity_log_target_user_id_fkey;
    ALTER TABLE user_activity_log ADD CONSTRAINT user_activity_log_target_user_id_fkey
        FOREIGN KEY (target_user_id) REFERENCES "user" (id);
END
$gd1b_down$
"""


def downgrade() -> None:
    """FAIL-CLOSED: dấu tải điền ngược (``source_audit_id`` khác NULL) tái tạo được từ nhật ký nên không tính là dữ liệu
    mới; mọi thứ khác còn dòng ⇒ dừng, trừ khi ``GD1B_DOWNGRADE_DROP_DATA_ENABLED=1``."""
    bind = op.get_bind()
    if os.environ.get("GD1B_DOWNGRADE_DROP_DATA_ENABLED") == "1":
        bind.exec_driver_sql("SELECT set_config('gd1b.allow_drop_data', '1', false)")
    try:
        bind.exec_driver_sql(DOWNGRADE_SQL)
    except DBAPIError as e:
        if _sqlstate(e) == SQLSTATE_DOWNGRADE_DATA_PRESENT:
            raise GD1BDataPresent(
                "Hạ cấp gd1b20261117 dừng: còn dữ liệu GĐ1b. Không xoá gì. Đặt GD1B_DOWNGRADE_DROP_DATA_ENABLED=1 nếu "
                "thật sự muốn xoá."
            ) from None
        raise
    finally:
        bind.exec_driver_sql("SELECT set_config('gd1b.allow_drop_data', '', false)")
