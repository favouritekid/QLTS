"""Lượt gửi ghi nhận Quyết định — bảng ``council_decision_submission`` (vòng giao diện GĐ1).

Revision ID: hdts20261112
Revises: hdts20261111
Create Date: 2026-11-11

Đặc tả: ``logs-P5/cong-bo-ket-qua/vong-giao-dien/DAC-TA-VONG-GIAO-DIEN-GD1-BAN2-2026-11-11.md`` mục 3.7 (+ bản 3 mục
3.7.2, 3.7.6). Mã lượt do máy chủ cấp (uuid) — mất mạng không gây ghi đôi, không báo sai "chưa ghi".

``env.py`` chạy ``AUTOCOMMIT`` ⇒ tạo bảng + chỉ mục trong MỘT câu ``DO`` (một giao dịch, tự đặt ``lock_timeout`` — khoá
ngoại tới ``council_document_set`` / ``council_decision`` / ``user`` lấy khoá trên bảng đích). ``IF NOT EXISTS``: chạy
lại được nếu tiến trình chết giữa câu ``DO`` và câu cập nhật ``alembic_version``.

CHECK / chỉ mục viết lại ĐÚNG chuỗi của model ``app/models/council_document.py`` (``CHECK_LUOT_*``,
``DIEU_KIEN_LUOT_CHO_GUI``); ``tests/unit/test_council_decision_submission_model.py`` so hai bên. Migration KHÔNG import
mã ứng dụng.

Hạ cấp: bảng còn dòng ⇒ DỪNG (vết lượt gửi là dữ liệu kiểm toán), không xoá gì.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "hdts20261112"
down_revision: Union[str, None] = "hdts20261111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRAN_CHO_KHOA = "15s"

SQL_TAO_BANG = """
CREATE TABLE IF NOT EXISTS council_decision_submission (
    id serial PRIMARY KEY,
    ma uuid NOT NULL,
    set_id integer NULL,
    set_id_luc_tao integer NOT NULL,
    trang_thai varchar(16) NOT NULL,
    decision_id integer NULL,
    noi_dung_sha varchar(64) NULL,
    nguoi_tao_id integer NOT NULL,
    tao_luc timestamptz NOT NULL DEFAULT now(),
    ket_thuc_luc timestamptz NULL,
    CONSTRAINT fk_council_decision_submission_set FOREIGN KEY (set_id)
        REFERENCES council_document_set (id) ON DELETE SET NULL,
    CONSTRAINT fk_council_decision_submission_decision FOREIGN KEY (decision_id)
        REFERENCES council_decision (id),
    CONSTRAINT fk_council_decision_submission_nguoi_tao FOREIGN KEY (nguoi_tao_id)
        REFERENCES "user" (id),
    CONSTRAINT uq_council_decision_submission_ma UNIQUE (ma),
    CONSTRAINT uq_council_decision_submission_decision UNIQUE (decision_id),
    CONSTRAINT ck_council_decision_submission_trang_thai CHECK (trang_thai IN ('cho_gui', 'da_ghi', 'da_chan')),
    CONSTRAINT ck_council_decision_submission_qd CHECK ((trang_thai = 'da_ghi') = (decision_id IS NOT NULL)),
    CONSTRAINT ck_council_decision_submission_sha CHECK ((trang_thai = 'da_ghi') = (noi_dung_sha IS NOT NULL)),
    CONSTRAINT ck_council_decision_submission_sha_hex CHECK (noi_dung_sha IS NULL OR noi_dung_sha ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_council_decision_submission_ket_thuc CHECK ((trang_thai = 'cho_gui') = (ket_thuc_luc IS NULL)),
    CONSTRAINT ck_council_decision_submission_cho_co_bo CHECK (trang_thai <> 'cho_gui' OR set_id IS NOT NULL),
    CONSTRAINT ck_council_decision_submission_bo_khop CHECK (set_id IS NULL OR set_id = set_id_luc_tao)
)
"""

SQL_CHI_MUC = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_council_decision_submission_cho_gui "
    "ON council_decision_submission (set_id) WHERE trang_thai = 'cho_gui'",
    "CREATE INDEX IF NOT EXISTS ix_council_decision_submission_set_id_luc_tao "
    "ON council_decision_submission (set_id_luc_tao)",
)


#: Tên ràng buộc KỲ VỌNG (13 — khoá chính tự đặt tên ``<bảng>_pkey``). So THEO TÊN, không đếm toàn bộ (PostgreSQL 18
#: thêm ràng buộc NOT NULL vào ``pg_constraint``).
RANG_BUOC_KY_VONG = (
    "council_decision_submission_pkey",
    "fk_council_decision_submission_set",
    "fk_council_decision_submission_decision",
    "fk_council_decision_submission_nguoi_tao",
    "uq_council_decision_submission_ma",
    "uq_council_decision_submission_decision",
    "ck_council_decision_submission_trang_thai",
    "ck_council_decision_submission_qd",
    "ck_council_decision_submission_sha",
    "ck_council_decision_submission_sha_hex",
    "ck_council_decision_submission_ket_thuc",
    "ck_council_decision_submission_cho_co_bo",
    "ck_council_decision_submission_bo_khop",
)
CHI_MUC_KY_VONG = ("uq_council_decision_submission_cho_gui", "ix_council_decision_submission_set_id_luc_tao")
#: SQLSTATE khi bảng / chỉ mục cùng tên có sẵn mà KHÁC HÌNH (``IF NOT EXISTS`` đã bỏ qua im lặng) — fail-closed.
SQLSTATE_KHAC_HINH = "QLLG2"


def _mang(ten) -> str:
    return "ARRAY[" + ", ".join("'%s'" % t for t in ten) + "]"


def khoi_do_nang_cap() -> str:
    """MỘT câu ``DO`` (một giao dịch): tạo bảng + chỉ mục (``IF NOT EXISTS`` — chạy lại được), rồi KIỂM HÌNH ngay trong câu
    ấy: đủ 13 ràng buộc theo tên trên đúng bảng này + đủ 2 chỉ mục trên đúng bảng này; thiếu ⇒ ``RAISE`` (cả câu lùi). Không
    có bước kiểm này thì một bảng / quan hệ cùng tên có sẵn mà khác hình làm ``IF NOT EXISTS`` bỏ qua IM LẶNG và migration
    vẫn "xanh" (phiên B phát hiện khi viết hướng dẫn vận hành)."""
    cai = "".join("    EXECUTE $f$%s$f$;\n" % c.strip() for c in (SQL_TAO_BANG, *SQL_CHI_MUC))
    return (
        "DO $lg$\n"
        "DECLARE n bigint;\n"
        "BEGIN\n"
        "    PERFORM set_config('lock_timeout', '" + TRAN_CHO_KHOA + "', true);\n"
        + cai
        + "    SELECT count(*) INTO n FROM pg_constraint WHERE conrelid = to_regclass('council_decision_submission') "
        "AND conname = ANY (" + _mang(RANG_BUOC_KY_VONG) + ");\n"
        "    IF n <> " + str(len(RANG_BUOC_KY_VONG)) + " THEN\n"
        "        RAISE EXCEPTION USING ERRCODE = '" + SQLSTATE_KHAC_HINH + "', MESSAGE = 'Bang luot gui co san khac hinh: ' "
        "|| n || ' rang buoc dung ten - khong ghi nhan migration';\n"
        "    END IF;\n"
        "    SELECT count(*) INTO n FROM pg_indexes WHERE schemaname = current_schema() "
        "AND tablename = 'council_decision_submission' AND indexname = ANY (" + _mang(CHI_MUC_KY_VONG) + ");\n"
        "    IF n <> " + str(len(CHI_MUC_KY_VONG)) + " THEN\n"
        "        RAISE EXCEPTION USING ERRCODE = '" + SQLSTATE_KHAC_HINH + "', MESSAGE = 'Chi muc luot gui thieu: ' "
        "|| n || ' - khong ghi nhan migration';\n"
        "    END IF;\n"
        "END $lg$"
    )


KHOI_DO_HA_CAP = (
    "DO $lg$\n"
    "DECLARE n bigint;\n"
    "BEGIN\n"
    "    PERFORM set_config('lock_timeout', '" + TRAN_CHO_KHOA + "', true);\n"
    "    IF to_regclass('council_decision_submission') IS NOT NULL THEN\n"
    "        EXECUTE 'SELECT count(*) FROM council_decision_submission' INTO n;\n"
    "        IF n > 0 THEN\n"
    "            RAISE EXCEPTION USING ERRCODE = 'QLLG1', MESSAGE = 'Bang luot gui con ' || n || ' dong - khong ha cap';\n"
    "        END IF;\n"
    "        DROP TABLE council_decision_submission;\n"
    "    END IF;\n"
    "END $lg$"
)


def upgrade() -> None:
    op.get_bind().execute(text(khoi_do_nang_cap()))


def downgrade() -> None:
    op.get_bind().execute(text(KHOI_DO_HA_CAP))
