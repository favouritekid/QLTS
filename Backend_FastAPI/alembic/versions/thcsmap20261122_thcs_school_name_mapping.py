"""Công cụ ghép tên trường THCS — bảng ghép ``thcs_school_name_mapping`` (owner 22-11, đề xuất danh mục THCS Phần B1).

Revision ID: thcsmap20261122
Revises: thcsnb20261122
Create Date: 2026-11-22

Bảng: tên trường THCS đã chuẩn hoá → ``vn_school.id``, người ghép, lúc ghép; duy nhất theo tên chuẩn hoá. Câu
``CREATE TABLE`` / ``CREATE INDEX`` chép NGUYÊN từ model ``app/models/thcs_school_name_mapping.py``
(``tests/unit/test_thcs_school_mapping_ddl.py`` so hai bên).

MỘT câu ``DO`` mỗi chiều (``env.py`` chạy ``AUTOCOMMIT`` ⇒ chỉ một câu mới là một giao dịch).

Bảng CHƯA có ⇒ tạo. ĐÃ có (CSDL test dựng bằng ``create_all``, hoặc một lượt trước) ⇒ SO ĐỊNH NGHĨA với một bảng mẫu tạm
dựng từ đúng câu trên: bảng (bảng thường, không UNLOGGED), cột (tên · kiểu · NOT NULL · collation · mặc định — mặc định
``nextval`` so ĐÍCH DANH sequence, xem ``_SIG_COT``), ràng buộc (khoá chính · duy nhất · CHECK), chỉ mục, và hai khoá
ngoại (cột → bảng(cột), ON DELETE RESTRICT, ON UPDATE NO ACTION, MATCH SIMPLE, KHÔNG trì hoãn, đã kiểm). Lệch ⇒ RAISE
``QLT05`` (``ExistingTableMismatch``), không ghi head (rà 23-11 F3: trước đây chỉ dò theo TÊN ⇒ bảng cũ lệch cột vẫn qua
và vẫn in "da tao"; rà Codex 23-11 F'1: mọi ``nextval(...)`` từng thu về một chữ, khoá ngoại chưa xét trì hoãn).

Nhánh "đã có" CHỈ ĐỌC (catalog + bảng mẫu TẠM, lùi cùng câu ``DO``): không ghi đối tượng thật nào, không ``setval`` ⇒
lệch thì không còn gì bị đổi. Nhánh "chưa có" chỉ có DDL (thuộc giao dịch).

Giới hạn đã biết: phép so khoá định nghĩa TẠI revision này. Một migration SAU đổi bảng này (thêm cột, chỉ mục…) thì CSDL
``create_all`` của model mới sẽ LỆCH ở đây khi nâng ``create_all → head`` ⇒ migration ấy phải sửa luôn nhánh này.

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


class ExistingTableMismatch(RuntimeError):
    """upgrade gặp bảng ``thcs_school_name_mapping`` đã có nhưng LỆCH định nghĩa model — câu ``DO`` rollback trọn,
    phiên bản Alembic không đổi; so tay rồi gỡ / sửa bảng ấy trước khi nâng lại."""


def _sqlstate(e: DBAPIError) -> str:
    orig = getattr(e, "orig", None)
    for o in (orig, getattr(orig, "__cause__", None)):
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if isinstance(v, str) and v:
                return v
    return ""


#: SQLSTATE riêng khi bảng ghép CÙNG TÊN đã có nhưng LỆCH định nghĩa (cột / ràng buộc / khoá ngoại / chỉ mục).
SQLSTATE_TABLE_MISMATCH = "QLT05"
_MAU = "thcsmap_mau"


def _mau_sql() -> list[str]:
    """Câu dựng MẪU đúng định nghĩa trên bảng TẠM (cùng câu ``CREATE TABLE`` / ``CREATE INDEX``, đổi tên bảng) để
    PostgreSQL tự chuẩn hoá — so với bảng đã có mà không chép tay chuỗi deparse. BỎ hai dòng ``FOREIGN KEY``: bảng tạm
    không được tham chiếu bảng thường ("constraints on temporary tables may reference only temporary tables"); khoá
    ngoại so bằng thuộc tính catalog (``_FK_KHOP``). Khuôn ``CREATE_TABLE`` đổi ⇒ ném lỗi ngay khi nạp (không đoán)."""
    dong = CREATE_TABLE.split("\n")
    dau = "CREATE TABLE thcs_school_name_mapping ("
    if dong[0] != dau or dong[-1] != ")" or sum(1 for d in dong if d.strip().startswith("FOREIGN KEY")) != 2:
        raise RuntimeError("thcsmap20261122: khuôn CREATE_TABLE đổi — sửa _mau_sql cho khớp")
    dong = [d for d in dong if not d.strip().startswith("FOREIGN KEY")]
    dong[0] = "CREATE TEMP TABLE %s (" % _MAU
    dong[-2] = dong[-2].rstrip().rstrip(",")
    dong[-1] = ") ON COMMIT DROP"
    chi_muc = [s.replace(" ON thcs_school_name_mapping (", " ON %s (" % _MAU, 1) for s in CREATE_INDEXES]
    if any(" ON %s (" % _MAU not in s for s in chi_muc):
        raise RuntimeError("thcsmap20261122: khuôn CREATE_INDEXES đổi — sửa _mau_sql cho khớp")
    return ["\n".join(dong), *chi_muc]


#: Chữ ký CỘT: tên · kiểu (kèm typmod) · NOT NULL · collation · mặc định. Thứ tự cột KHÔNG so (xếp theo tên — ứng dụng
#: chỉ dùng tên cột).
#:
#: Mặc định ``nextval`` (BIGSERIAL): tên sequence đi theo tên bảng nên chữ của bảng thật và bảng mẫu luôn khác ⇒
#: KHÔNG so chữ, mà so ĐÍCH DANH sequence được trỏ tới (rà Codex 23-11 F'1: bản trước thu mọi ``nextval(...)`` về một chữ ⇒ cột
#: trỏ NHẦM sequence vẫn "khớp"):
#:
#: * sequence lấy theo PHỤ THUỘC của biểu thức mặc định (``pg_depend`` từ ``pg_attrdef``) — OID, không đọc chữ ⇒ không
#:   vướng schema / dấu nháy / ``::regclass``;
#: * biểu thức phải ĐÚNG ``nextval('<sequence ấy>'::regclass)`` — dựng bằng chính hàm in ``regclass`` mà ``pg_get_expr``
#:   dùng ⇒ cùng cách viết schema / dấu nháy ở hai phía;
#: * sequence mang tên chuẩn ``<bảng>_<cột>_seq`` CÙNG schema với bảng, THUỘC đúng cột (``OWNED BY``, phụ thuộc ``a``),
#:   và cùng tham số (kiểu, start, increment, min, max, cache, cycle).
#:
#: Không thoả vế đầu ⇒ in NGUYÊN chữ mặc định (mang tên sequence thật) ⇒ khác bảng mẫu ⇒ lệch (fail-closed).
_SIG_COT = """
SELECT string_agg(format('%s %s %s %s %s', a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                         coalesce(co.collname, '-'),
                         CASE WHEN d.adbin IS NULL THEN '-'
                              WHEN sq.oid IS NOT NULL
                               AND pg_get_expr(d.adbin, d.adrelid)
                                   = format('nextval(%L::regclass)', sq.oid::regclass::text)
                              THEN format('nextval(<sequence ten-chuan=%s thuoc-cot=%s %s %s %s %s %s %s %s>)',
                                          sq.relname = format('%s_%s_seq', r.relname, a.attname)
                                            AND sq.relnamespace = r.relnamespace,
                                          EXISTS (SELECT 1 FROM pg_depend o
                                                   WHERE o.classid = 'pg_class'::regclass AND o.objid = sq.oid
                                                     AND o.refclassid = 'pg_class'::regclass
                                                     AND o.refobjid = a.attrelid AND o.refobjsubid = a.attnum
                                                     AND o.deptype = 'a'),
                                          format_type(sq.seqtypid, NULL), sq.seqstart, sq.seqincrement, sq.seqmin,
                                          sq.seqmax, sq.seqcache, sq.seqcycle)
                              ELSE pg_get_expr(d.adbin, d.adrelid) END),
                  ', ' ORDER BY a.attname COLLATE "C")
  FROM pg_attribute a
  JOIN pg_class r ON r.oid = a.attrelid
  LEFT JOIN pg_collation co ON co.oid = a.attcollation
  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  LEFT JOIN LATERAL (
        SELECT s.oid, s.relname, s.relnamespace, p.seqtypid, p.seqstart, p.seqincrement, p.seqmin, p.seqmax,
               p.seqcache, p.seqcycle
          FROM pg_depend x
          JOIN pg_class s ON s.oid = x.refobjid AND s.relkind = 'S'
          JOIN pg_sequence p ON p.seqrelid = s.oid
         WHERE x.classid = 'pg_attrdef'::regclass AND x.objid = d.oid AND x.refclassid = 'pg_class'::regclass
       ) sq ON true
 WHERE a.attrelid = {bang}::regclass AND a.attnum > 0 AND NOT a.attisdropped
"""
#: Chữ ký RÀNG BUỘC trừ khoá ngoại / NOT NULL (tên khoá chính theo tên bảng ⇒ bỏ tên khoá chính).
_SIG_RB = """
SELECT string_agg(format('%s|%s|%s', c.contype, CASE WHEN c.contype = 'p' THEN '' ELSE c.conname END,
                         pg_get_constraintdef(c.oid)),
                  ' # ' ORDER BY format('%s|%s|%s', c.contype, CASE WHEN c.contype = 'p' THEN '' ELSE c.conname END,
                                        pg_get_constraintdef(c.oid)) COLLATE "C")
  FROM pg_constraint c WHERE c.conrelid = {bang}::regclass AND c.contype NOT IN ('f', 'n')
"""
#: Chữ ký CHỈ MỤC (tên, trừ chỉ mục khoá chính · duy nhất · hợp lệ · phần sau ``USING``).
_SIG_CM = """
SELECT string_agg(format('%s|%s|%s|%s', CASE WHEN i.indisprimary THEN 'pk' ELSE ci.relname END, i.indisunique,
                         i.indisvalid, regexp_replace(pg_get_indexdef(i.indexrelid), '^.*? USING ', '')),
                  ' # ' ORDER BY format('%s|%s|%s|%s', CASE WHEN i.indisprimary THEN 'pk' ELSE ci.relname END,
                                        i.indisunique, i.indisvalid,
                                        regexp_replace(pg_get_indexdef(i.indexrelid), '^.*? USING ', '')) COLLATE "C")
  FROM pg_index i JOIN pg_class ci ON ci.oid = i.indexrelid WHERE i.indrelid = {bang}::regclass
"""
#: Khoá ngoại: đúng HAI, mỗi cái đúng cột → bảng(cột), ON DELETE RESTRICT, ON UPDATE NO ACTION, MATCH SIMPLE, đã kiểm,
#: KHÔNG trì hoãn (rà Codex 23-11 F'1: ``DEFERRABLE`` — kể cả ``INITIALLY IMMEDIATE`` — cho phép ``SET CONSTRAINTS …
#: DEFERRED`` dời phép kiểm tới COMMIT; model không khai ⇒ bảng thật mà trì hoãn được là LỆCH).
_FK_KHOP = """
SELECT count(*) FROM pg_constraint c
 WHERE c.conrelid = 'thcs_school_name_mapping'::regclass AND c.contype = 'f' AND c.convalidated
   AND NOT c.condeferrable AND NOT c.condeferred
   AND c.confdeltype = 'r' AND c.confupdtype = 'a' AND c.confmatchtype = 's'
   AND c.confrelid = {dich}::regclass
   AND c.conkey = ARRAY[(SELECT attnum FROM pg_attribute
                          WHERE attrelid = 'thcs_school_name_mapping'::regclass AND attname = {cot})]
   AND c.confkey = ARRAY[(SELECT attnum FROM pg_attribute WHERE attrelid = {dich}::regclass AND attname = 'id')]
"""


def _upgrade_sql() -> str:
    body = ";\n        ".join(s.strip() for s in (CREATE_TABLE, *CREATE_INDEXES))
    mau = ";\n        ".join(_mau_sql())
    that = "'thcs_school_name_mapping'"
    tam = "'%s'" % _MAU
    so_sanh = []
    for ten_phan, sig in (("cot", _SIG_COT), ("rang-buoc", _SIG_RB), ("chi-muc", _SIG_CM)):
        so_sanh.append(sig.format(bang=that).strip() + " INTO v_that;")
        so_sanh.append(sig.format(bang=tam).strip() + " INTO v_mau;")
        so_sanh.append("IF v_that IS DISTINCT FROM v_mau THEN v_lech := v_lech || ' %s'; END IF;" % ten_phan)
    so_sanh_sql = "\n        ".join(so_sanh)
    fk_truong = _FK_KHOP.format(dich="'vn_school'", cot="'school_id'").strip()
    fk_nguoi = _FK_KHOP.format(dich="'\"user\"'", cot="'mapped_by_user_id'").strip()
    return f"""
DO $thcsmap$
DECLARE
    v_that text;
    v_mau text;
    n_fk integer;
    v_lech text := '';
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    IF to_regclass('thcs_school_name_mapping') IS NULL THEN
        {body};
        RAISE NOTICE 'thcsmap20261122: bang ghep ten truong THCS: da tao';
    ELSE
        -- Đã có (CSDL test dựng bằng create_all, hoặc lượt trước): SO ĐỊNH NGHĨA, lệch ⇒ RAISE (rà 23-11 F3).
        -- Nhánh này CHỈ ĐỌC (bảng mẫu TẠM lùi cùng câu DO): không ghi đối tượng thật nào.
        {mau};
        IF NOT EXISTS (SELECT 1 FROM pg_class WHERE oid = 'thcs_school_name_mapping'::regclass
                        AND relkind = 'r' AND relpersistence = 'p') THEN
            v_lech := v_lech || ' bang';
        END IF;
        {so_sanh_sql}
        SELECT count(*) INTO n_fk FROM pg_constraint
         WHERE conrelid = 'thcs_school_name_mapping'::regclass AND contype = 'f';
        IF n_fk <> 2 OR ({fk_truong}) <> 1 OR ({fk_nguoi}) <> 1 THEN
            v_lech := v_lech || ' khoa-ngoai';
        END IF;
        DROP TABLE {_MAU};
        IF v_lech <> '' THEN
            RAISE EXCEPTION 'thcsmap20261122: bang thcs_school_name_mapping da co nhung LECH:%', v_lech
                USING ERRCODE = '{SQLSTATE_TABLE_MISMATCH}';
        END IF;
        RAISE NOTICE 'thcsmap20261122: bang ghep ten truong THCS: da co, khop';
    END IF;
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
        if _sqlstate(e) == SQLSTATE_TABLE_MISMATCH:
            raise ExistingTableMismatch(
                "%s thcsmap20261122 dừng (SQLSTATE %s): bảng thcs_school_name_mapping đã có nhưng LỆCH định nghĩa "
                "model (bảng / cột / ràng buộc / khoá ngoại / chỉ mục). Nhánh so chỉ đọc ⇒ không gì bị đổi, phiên bản "
                "Alembic không đổi."
                % (chieu, SQLSTATE_TABLE_MISMATCH)
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
