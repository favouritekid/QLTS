"""Danh mục THCS — mã nội bộ ``NB`` + 6 số cho trường THCS (owner 22-11, đề xuất danh mục THCS Phần A1).

Revision ID: thcsnb20261122
Revises: gd2f20261119
Create Date: 2026-11-22

Căn cứ: ``logs-P5/cong-bo-ket-qua/gd2/l3/QUYET-DINH-OWNER-DE-XUAT-THCS-4-CAU-2026-11-22.md`` (mặc định điều phối chọn,
owner không phản đối: mã nội bộ ``NB`` + 6 số; bộ nạp danh mục Bộ bỏ qua mã ``NB``).

MỘT câu ``DO`` mỗi chiều (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch): hỏng ở bất kỳ bước nào ⇒
không còn gì dở dang, phiên bản Alembic chưa đổi, chạy lại được. Nâng cấp:

1. sequence ``vn_school_internal_code_seq`` (1..999999, ``NO CYCLE`` — hết số ⇒ lỗi, không quay vòng);
2. nếu đã có trường ``NB…`` (ca hạ cấp rồi nâng lại) ⇒ ``setval`` tới số lớn nhất đã cấp, để mã mới không trùng;
3. CHECK ``ck_vn_school_internal_code_format`` (mã ``NB…`` đúng khuôn + có mã xã) — chuỗi chép NGUYÊN từ model;
4. chỉ mục duy nhất ``uq_vn_school_internal_code`` trên các mã ``NB…`` (toàn bảng, kể cả trường đã ngừng).

Mỗi đối tượng chỉ tạo khi CHƯA có (``to_regclass`` / ``pg_constraint``): CSDL test dựng bằng ``create_all`` của model
HEAD đã có sẵn chúng, và các test migration cũ (vd ``test_gd2a_migration``) nâng tới ``head`` trên CSDL ấy. Câu tạo vẫn
chép NGUYÊN từ model; ``test_thcs_danh_muc_migration.py`` gỡ chúng rồi nâng để đo đúng đường tạo.

Đối tượng ĐÃ có thì SO ĐỊNH NGHĨA (rà 23-11 F3 — trước đây chỉ dò theo TÊN): sequence theo ``pg_sequence`` (kiểu, start,
increment, min, max, cycle); CHECK + chỉ mục so với MẪU dựng trên bảng tạm ``(LIKE vn_school)``. Lệch ⇒ RAISE ``QLT02`` /
``QLT03`` / ``QLT04`` (``ExistingObjectMismatch``), câu ``DO`` rollback trọn, không ghi head. Khớp ⇒ NOTICE "da co, khop".

Dòng cũ vi phạm CHECK (mã bắt đầu bằng ``NB`` sẵn có) ⇒ câu ``ALTER TABLE`` lỗi ⇒ cả câu ``DO`` rollback. Trước khi
nâng cấp production, đo (chỉ đọc): ``SELECT count(*) FROM vn_school WHERE upper(btrim(moet_school_code)) LIKE 'NB%'``
phải = 0.

Hạ cấp: gỡ chỉ mục, CHECK, sequence. KHÔNG xoá dòng nào — trường ``NB…`` đã tạo vẫn còn; nâng lại thì bước 2 nối tiếp
số thứ tự. Không đổi dữ liệu ở cả hai chiều ⇒ không cần cờ cho phép.
"""
from typing import Sequence, Union

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "thcsnb20261122"
down_revision: Union[str, None] = "gd2f20261119"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "10s"
_SQLSTATE_LOCK_TIMEOUT = "55P03"

# ---------------------------------------------------------------------------------------------------------------------
# Chép NGUYÊN từ ``app/models/vn_school.py`` (``CK_VN_SCHOOL_INTERNAL_CODE_FORMAT_SQL`` /
# ``UQ_VN_SCHOOL_INTERNAL_CODE_WHERE_SQL`` / ``VN_SCHOOL_INTERNAL_CODE_SEQ``). Migration không import mã ứng dụng đang
# đổi; ``tests/unit/test_vn_school_thcs_noi_bo_ddl.py`` so hai bên.
# ---------------------------------------------------------------------------------------------------------------------
SQL_CREATE_SEQUENCE = (
    "CREATE SEQUENCE vn_school_internal_code_seq INCREMENT BY 1 MINVALUE 1 MAXVALUE 999999 START WITH 1 NO CYCLE"
)
SQL_CK_INTERNAL_CODE = (
    "NOT (upper(btrim(moet_school_code)) LIKE 'NB%') "
    "OR (moet_school_code ~ '^NB[0-9]{6}$' AND commune_code IS NOT NULL)"
)
SQL_UQ_INTERNAL_CODE_WHERE = "upper(btrim(moet_school_code)) LIKE 'NB%'"

#: SQLSTATE riêng khi đối tượng CÙNG TÊN đã có nhưng LỆCH định nghĩa (``env.py`` che chữ lỗi CSDL, chỉ giữ SQLSTATE).
SQLSTATE_SEQUENCE_MISMATCH = "QLT02"
SQLSTATE_CHECK_MISMATCH = "QLT03"
SQLSTATE_INDEX_MISMATCH = "QLT04"

# Đối tượng đã có (CSDL dựng bằng ``create_all``, hoặc lượt trước dở dang) thì SO ĐỊNH NGHĨA, lệch ⇒ RAISE (rà 23-11 F3:
# trước đây chỉ dò theo TÊN ⇒ bảng / ràng buộc cũ lệch vẫn qua, Alembic vẫn ghi head, lỗi chỉ lộ khi ứng dụng chạy).
# CHECK + chỉ mục: dựng MẪU đúng câu trên một bảng tạm ``(LIKE vn_school)`` (cùng kiểu cột) để PostgreSQL tự chuẩn hoá
# biểu thức, rồi so NGUYÊN chuỗi ``pg_get_constraintdef`` / phần sau ``USING`` của ``pg_get_indexdef`` — không chép tay
# chuỗi deparse (đổi theo phiên bản PostgreSQL). Bảng tạm ``ON COMMIT DROP`` + DROP tường minh.
UPGRADE_SQL = f"""
DO $thcsnb$
DECLARE
    v_max integer;
    v_ghi text := '';
    v_mau text;
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE vn_school IN SHARE ROW EXCLUSIVE MODE;
    CREATE TEMP TABLE thcsnb_mau (LIKE vn_school) ON COMMIT DROP;
    ALTER TABLE thcsnb_mau ADD CONSTRAINT thcsnb_mau_ck CHECK ({SQL_CK_INTERNAL_CODE});
    CREATE UNIQUE INDEX thcsnb_mau_uq ON thcsnb_mau (moet_school_code) WHERE {SQL_UQ_INTERNAL_CODE_WHERE};

    IF to_regclass('vn_school_internal_code_seq') IS NULL THEN
        {SQL_CREATE_SEQUENCE};
        v_ghi := v_ghi || ' sequence: da tao;';
    ELSIF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_sequence s ON s.seqrelid = c.oid
        WHERE c.oid = to_regclass('vn_school_internal_code_seq') AND c.relkind = 'S'
          AND s.seqtypid = 'bigint'::regtype AND s.seqstart = 1 AND s.seqincrement = 1
          AND s.seqmin = 1 AND s.seqmax = 999999 AND NOT s.seqcycle
    ) THEN
        v_ghi := v_ghi || ' sequence: da co, khop;';
    ELSE
        RAISE EXCEPTION 'thcsnb20261122: vn_school_internal_code_seq da co nhung LECH dinh nghia'
            USING ERRCODE = '{SQLSTATE_SEQUENCE_MISMATCH}';
    END IF;
    SELECT max(substring(moet_school_code FROM 3)::integer) INTO v_max
      FROM vn_school WHERE moet_school_code ~ '^NB[0-9]{{6}}$';
    IF v_max IS NOT NULL THEN
        PERFORM setval('vn_school_internal_code_seq', v_max, true);
    END IF;

    SELECT pg_get_constraintdef(oid) INTO v_mau FROM pg_constraint
     WHERE conrelid = 'thcsnb_mau'::regclass AND conname = 'thcsnb_mau_ck';
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_vn_school_internal_code_format' AND conrelid = 'vn_school'::regclass
    ) THEN
        ALTER TABLE vn_school ADD CONSTRAINT ck_vn_school_internal_code_format CHECK ({SQL_CK_INTERNAL_CODE});
        v_ghi := v_ghi || ' check: da tao;';
    ELSIF v_mau IS NOT NULL AND EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_vn_school_internal_code_format' AND conrelid = 'vn_school'::regclass
          AND contype = 'c' AND convalidated AND pg_get_constraintdef(oid) = v_mau
    ) THEN
        v_ghi := v_ghi || ' check: da co, khop;';
    ELSE
        RAISE EXCEPTION 'thcsnb20261122: ck_vn_school_internal_code_format da co nhung LECH dinh nghia'
            USING ERRCODE = '{SQLSTATE_CHECK_MISMATCH}';
    END IF;

    SELECT regexp_replace(pg_get_indexdef(indexrelid), '^.*? USING ', '') INTO v_mau FROM pg_index
     WHERE indexrelid = 'thcsnb_mau_uq'::regclass;
    IF to_regclass('uq_vn_school_internal_code') IS NULL THEN
        CREATE UNIQUE INDEX uq_vn_school_internal_code ON vn_school (moet_school_code) WHERE {SQL_UQ_INTERNAL_CODE_WHERE};
        v_ghi := v_ghi || ' chi muc: da tao;';
    ELSIF v_mau IS NOT NULL AND EXISTS (
        SELECT 1 FROM pg_index
        WHERE indexrelid = to_regclass('uq_vn_school_internal_code') AND indrelid = 'vn_school'::regclass
          AND indisunique AND indisvalid
          AND regexp_replace(pg_get_indexdef(indexrelid), '^.*? USING ', '') = v_mau
    ) THEN
        v_ghi := v_ghi || ' chi muc: da co, khop;';
    ELSE
        RAISE EXCEPTION 'thcsnb20261122: uq_vn_school_internal_code da co nhung LECH dinh nghia'
            USING ERRCODE = '{SQLSTATE_INDEX_MISMATCH}';
    END IF;

    DROP TABLE thcsnb_mau;
    RAISE NOTICE 'thcsnb20261122: ma noi bo NB:% (so lon nhat da cap: %)', v_ghi, coalesce(v_max, 0);
END
$thcsnb$
"""

#: SQLSTATE ⇒ đối tượng lệch (câu báo của Python — chữ lỗi CSDL bị ``env.py`` che).
_DOI_TUONG_LECH = {
    SQLSTATE_SEQUENCE_MISMATCH: "sequence vn_school_internal_code_seq",
    SQLSTATE_CHECK_MISMATCH: "CHECK ck_vn_school_internal_code_format",
    SQLSTATE_INDEX_MISMATCH: "chỉ mục uq_vn_school_internal_code",
}

DOWNGRADE_SQL = f"""
DO $thcsnb_down$
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE vn_school IN SHARE ROW EXCLUSIVE MODE;
    DROP INDEX uq_vn_school_internal_code;
    ALTER TABLE vn_school DROP CONSTRAINT ck_vn_school_internal_code_format;
    DROP SEQUENCE vn_school_internal_code_seq;
    RAISE NOTICE 'thcsnb20261122: da go ma noi bo NB (du lieu giu nguyen)';
END
$thcsnb_down$
"""


class UpgradeLockTimeout(RuntimeError):
    """Chờ khoá quá ``LOCK_TIMEOUT``. Câu ``DO`` rollback trọn ⇒ không còn gì dở dang; chạy lại khi bảng rảnh."""


class ExistingObjectMismatch(RuntimeError):
    """Đối tượng cùng tên đã có nhưng LỆCH định nghĩa. Câu ``DO`` rollback trọn, phiên bản Alembic không đổi —
    người vận hành so tay rồi gỡ / sửa đối tượng ấy trước khi nâng lại."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


def _chay(sql: str, chieu: str) -> None:
    bind = op.get_bind()
    try:
        # exec_driver_sql: câu có ``$`` (dollar-quote) — không qua ``text()``.
        bind.exec_driver_sql(sql)
    except DBAPIError as e:
        ma = _sqlstate(e)
        if ma == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "%s thcsnb20261122 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % (chieu, LOCK_TIMEOUT)
            ) from None
        if ma in _DOI_TUONG_LECH:
            raise ExistingObjectMismatch(
                "%s thcsnb20261122 dừng (SQLSTATE %s): %s đã có nhưng LỆCH định nghĩa của model. Câu DO đã rollback "
                "trọn, phiên bản Alembic không đổi. So tay rồi gỡ / sửa đối tượng ấy trước khi nâng lại."
                % (chieu, ma, _DOI_TUONG_LECH[ma])
            ) from None
        raise


def upgrade() -> None:
    _chay(UPGRADE_SQL, "Nâng cấp")


def downgrade() -> None:
    _chay(DOWNGRADE_SQL, "Hạ cấp")
