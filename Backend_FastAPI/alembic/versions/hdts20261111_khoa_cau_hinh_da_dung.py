"""K-2 — khoá dòng cấu hình đã được Quyết định đã ký dùng tới (trigger chặn sửa năm học / ngành, chặn xoá).

Revision ID: hdts20261111
Revises: hdts20261107
Create Date: 2026-11-11

Owner 11-11 (``logs-P5/cong-bo-ket-qua/vong-giao-dien/QUYET-DINH-OWNER-DAC-TA-2026-11-11.md`` câu 2). Đặc tả: vòng giao
diện bản 2 mục 2.5.1 + bản 3 mục 2.5.1 (F274 — Codex review bản 2).

``env.py`` chạy ``AUTOCOMMIT`` ⇒ mỗi câu là một giao dịch. Vì vậy TOÀN BỘ phần kiểm + cài nằm trong MỘT câu ``DO``
(một câu = một giao dịch): kiểm mức cô lập = ``read committed`` (khác ⇒ ``QLK2C``, không cài gì — F280: ở REPEATABLE READ
/ SERIALIZABLE ảnh chụp của giao dịch chốt ở câu ĐẦU TIÊN trong ``DO`` — trước khi có khoá — nên phép đếm sau khoá vẫn
đọc dữ liệu CŨ: phiên sửa cấu hình commit bản lệch trong lúc nâng cấp chờ khoá thì vẫn bị đếm là 0 và trigger vẫn được
cài; ở READ COMMITTED mỗi câu trong ``DO`` lấy ảnh mới nên phép đếm sau khoá thấy dữ liệu đã commit) → đặt
``lock_timeout`` → ``LOCK TABLE`` hai bảng cấu hình ở mức ``SHARE ROW EXCLUSIVE``
(xung đột với ``ROW EXCLUSIVE`` của INSERT / UPDATE / DELETE ⇒ phiên sửa cấu hình đang mở phải kết thúc trước, phiên
mới không bắt đầu sửa được tới khi câu này xong; đọc và ``FOR UPDATE`` của ghi nhận KHÔNG bị chặn) → ĐẾM dòng Quyết
định chưa huỷ ghi nhận có khoá đếm đã lệch cấu hình → > 0 thì ``RAISE`` (cả câu lùi, không cài gì) → cài hai hàm +
hai trigger. Lỗi ở bất kỳ bước nào (gồm trigger thứ hai) ⇒ cả câu lùi: không còn hàm / trigger nào, phiên bản
Alembic không đổi (câu cập nhật phiên bản chạy SAU ``upgrade()``).

Các câu SQL dưới CHÉP NGUYÊN VĂN ``app/models/council_config_lock_ddl.py`` (bản cho ``create_all()`` của CSDL test);
``tests/unit/test_council_config_lock_ddl_lockin.py`` so hai bên. Migration KHÔNG import mã ứng dụng.
``CREATE OR REPLACE``: chạy lại được nếu tiến trình chết giữa câu ``DO`` và câu cập nhật ``alembic_version``.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "hdts20261111"
down_revision: Union[str, None] = "hdts20261107"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Trần chờ khoá bảng cấu hình (phiên sửa cấu hình giữ lâu hơn ⇒ upgrade đỏ ``55P03``, không cài gì).
TRAN_CHO_KHOA = "15s"
#: SQLSTATE khi phát hiện dữ liệu đã lệch (khác SQLSTATE của trigger — ``QLK02``).
SQLSTATE_DA_LECH = "QLK2M"
#: SQLSTATE khi phiên chạy nâng cấp KHÔNG ở READ COMMITTED (F280) — khác ``QLK2M`` để người vận hành phân biệt "dữ liệu
#: lệch" với "cấu hình phiên sai"; cùng khuôn ``QLLG3`` của hạ cấp ``hdts20261112``.
SQLSTATE_CAN_READ_COMMITTED = "QLK2C"

SQL_FN_HOC_VU = """
CREATE OR REPLACE FUNCTION chan_sua_hoc_vu_da_tham_chieu()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.offering_id IS NOT DISTINCT FROM OLD.offering_id
       AND NEW.academic_year IS NOT DISTINCT FROM OLD.academic_year THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM council_document_set_row b
        JOIN council_decision_row r ON r.set_row_id = b.id
        WHERE b.academic_info_id = OLD.id
          AND r.trang_thai_cha <> 'huy_ghi_nhan'
    ) THEN
        RAISE EXCEPTION 'offering_academic_info da duoc Quyet dinh da ky dung toi'
            USING ERRCODE = 'QLK02';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

SQL_FN_DUONG_XET = """
CREATE OR REPLACE FUNCTION chan_sua_duong_xet_da_tham_chieu()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.academic_info_id IS NOT DISTINCT FROM OLD.academic_info_id THEN
        RETURN NEW;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM council_document_set_row b
        JOIN council_decision_row r ON r.set_row_id = b.id
        WHERE b.admission_path_id = OLD.id
          AND r.trang_thai_cha <> 'huy_ghi_nhan'
    ) THEN
        RAISE EXCEPTION 'admission_path da duoc Quyet dinh da ky dung toi'
            USING ERRCODE = 'QLK02';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

SQL_TRIGGERS = (
    """
CREATE OR REPLACE TRIGGER trg_chan_sua_hoc_vu_da_tham_chieu
BEFORE UPDATE OF offering_id, academic_year OR DELETE ON offering_academic_info
FOR EACH ROW EXECUTE FUNCTION chan_sua_hoc_vu_da_tham_chieu();
""",
    """
CREATE OR REPLACE TRIGGER trg_chan_sua_duong_xet_da_tham_chieu
BEFORE UPDATE OF academic_info_id OR DELETE ON admission_path
FOR EACH ROW EXECUTE FUNCTION chan_sua_duong_xet_da_tham_chieu();
""",
)

SQL_DEM_LECH = """
SELECT count(*)
FROM council_decision_row r
LEFT JOIN council_document_set_row b ON b.id = r.set_row_id
LEFT JOIN offering_academic_info oai ON oai.id = b.academic_info_id
LEFT JOIN admission_path ap ON ap.id = b.admission_path_id
WHERE r.trang_thai_cha <> 'huy_ghi_nhan'
  AND (
       b.id IS NULL
    OR b.admission_path_id IS NULL
    OR b.academic_info_id IS NULL
    OR b.offering_id IS NULL
    OR ap.academic_info_id IS DISTINCT FROM b.academic_info_id
    OR oai.offering_id IS DISTINCT FROM b.offering_id
    OR oai.academic_year IS DISTINCT FROM b.academic_year
  )
"""

CAC_CAU_LENH = (SQL_FN_HOC_VU, SQL_FN_DUONG_XET, *SQL_TRIGGERS)


def _bo_dau_cham_phay(cau: str) -> str:
    return cau.strip().rstrip(";").strip()


def khoi_do_nang_cap() -> str:
    """MỘT câu ``DO`` (một giao dịch): kiểm mức cô lập → khoá → đếm → dừng / cài. Phép kiểm mức cô lập PHẢI đứng đầu
    (trước ``set_config``): nó tự nó cũng là một câu lấy ảnh chụp, nhưng ở mức khác READ COMMITTED nó dừng ngay nên ảnh
    ấy không bao giờ được dùng để đếm. Ký tự ``%`` và ``::`` không xuất hiện (``text()``)."""
    cai = "".join("    EXECUTE $f$%s$f$;\n" % _bo_dau_cham_phay(c) for c in CAC_CAU_LENH)
    return (
        "DO $k2$\n"
        "DECLARE n bigint;\n"
        "BEGIN\n"
        "    IF current_setting('transaction_isolation') <> 'read committed' THEN\n"
        "        RAISE EXCEPTION USING ERRCODE = '" + SQLSTATE_CAN_READ_COMMITTED + "', MESSAGE = 'K2: nang cap can "
        "READ COMMITTED - khong cai trigger';\n"
        "    END IF;\n"
        "    PERFORM set_config('lock_timeout', '" + TRAN_CHO_KHOA + "', true);\n"
        "    LOCK TABLE offering_academic_info, admission_path IN SHARE ROW EXCLUSIVE MODE;\n"
        "    EXECUTE $f$" + _bo_dau_cham_phay(SQL_DEM_LECH) + "$f$ INTO n;\n"
        "    IF n > 0 THEN\n"
        "        RAISE EXCEPTION USING ERRCODE = '" + SQLSTATE_DA_LECH + "', MESSAGE = 'K2: ' || n || "
        "' dong Quyet dinh chua huy ghi nhan co khoa dem da lech cau hinh - khong cai trigger';\n"
        "    END IF;\n"
        + cai +
        "END $k2$"
    )


KHOI_DO_HA_CAP = (
    "DO $k2$\n"
    "BEGIN\n"
    "    PERFORM set_config('lock_timeout', '" + TRAN_CHO_KHOA + "', true);\n"
    "    DROP TRIGGER IF EXISTS trg_chan_sua_hoc_vu_da_tham_chieu ON offering_academic_info;\n"
    "    DROP TRIGGER IF EXISTS trg_chan_sua_duong_xet_da_tham_chieu ON admission_path;\n"
    "    DROP FUNCTION IF EXISTS chan_sua_hoc_vu_da_tham_chieu();\n"
    "    DROP FUNCTION IF EXISTS chan_sua_duong_xet_da_tham_chieu();\n"
    "END $k2$"
)


def upgrade() -> None:
    op.get_bind().execute(text(khoi_do_nang_cap()))


def downgrade() -> None:
    op.get_bind().execute(text(KHOI_DO_HA_CAP))
