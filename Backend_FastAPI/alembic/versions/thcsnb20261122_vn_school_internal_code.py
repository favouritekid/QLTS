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

UPGRADE_SQL = f"""
DO $thcsnb$
DECLARE
    v_max integer;
BEGIN
    PERFORM set_config('lock_timeout', '{LOCK_TIMEOUT}', true);
    LOCK TABLE vn_school IN SHARE ROW EXCLUSIVE MODE;
    {SQL_CREATE_SEQUENCE};
    SELECT max(substring(moet_school_code FROM 3)::integer) INTO v_max
      FROM vn_school WHERE moet_school_code ~ '^NB[0-9]{{6}}$';
    IF v_max IS NOT NULL THEN
        PERFORM setval('vn_school_internal_code_seq', v_max, true);
    END IF;
    ALTER TABLE vn_school ADD CONSTRAINT ck_vn_school_internal_code_format CHECK ({SQL_CK_INTERNAL_CODE});
    CREATE UNIQUE INDEX uq_vn_school_internal_code ON vn_school (moet_school_code) WHERE {SQL_UQ_INTERNAL_CODE_WHERE};
    RAISE NOTICE 'thcsnb20261122: ma noi bo NB da cai (so lon nhat da cap: %)', coalesce(v_max, 0);
END
$thcsnb$
"""

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
        if _sqlstate(e) == _SQLSTATE_LOCK_TIMEOUT:
            raise UpgradeLockTimeout(
                "%s thcsnb20261122 dừng: chờ khoá quá %s. Câu DO đã rollback trọn — chạy lại khi bảng rảnh."
                % (chieu, LOCK_TIMEOUT)
            ) from None
        raise


def upgrade() -> None:
    _chay(UPGRADE_SQL, "Nâng cấp")


def downgrade() -> None:
    _chay(DOWNGRADE_SQL, "Hạ cấp")
