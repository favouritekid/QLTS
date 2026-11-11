# app/models/council_config_lock_ddl.py
"""K-2 (owner 11-11) — trigger CHẶN sửa năm học / ngành và xoá dòng cấu hình đã được Quyết định đã ký dùng tới.

Đặc tả: ``logs-P5/cong-bo-ket-qua/vong-giao-dien/DAC-TA-VONG-GIAO-DIEN-GD1-BAN2-2026-11-11.md`` mục 2.5.1 + bản 3
mục 2.5.1 (F274). Quyết định owner: ``vong-giao-dien/QUYET-DINH-OWNER-DAC-TA-2026-11-11.md`` câu 2.

Vì sao: dòng Quyết định đếm chỗ chỉ tiêu theo khoá CHỤP ở dòng bộ (``admission_path_id`` → ``academic_info_id`` →
``offering_id`` + ``academic_year``). Sửa chuỗi cấu hình sau khi đã ghi nhận làm các hàm đếm đặt cùng một em vào
những ô khác nhau; Q-J1 (``quota_occupancy_service.kiem_khoa_dem_dong_bo``) khi ấy chặn cả huỷ ghi nhận ⇒ kẹt.
Owner chọn KHOÁ cấu hình đã được dùng (năm mới ⇒ tạo dòng mới), KHÔNG làm nút Admin bỏ qua (Codex lần 16 G.4).

Vị từ "đã được dùng": có dòng Quyết định CHƯA huỷ ghi nhận (:data:`DIEU_KIEN_DONG_GIU_HO_SO` — gồm văn bản hết
hiệu lực và dòng đang bị điều chỉnh bỏ: huỷ ghi nhận văn bản huỷ / điều chỉnh sẽ đưa chúng trở lại) nối về dòng
bộ có khoá đếm trỏ tới dòng cấu hình. KHÔNG lọc theo cờ của dòng.

Tầng chủ sở hữu bất biến = trigger CSDL (bắt mọi đường ghi, kể cả xoá dây chuyền từ bảng cha). Lỗi mang
SQLSTATE :data:`SQLSTATE_CAU_HINH_DA_DUNG`; ``app/middleware/exception_handlers.py`` đổi thành 409 câu dễ hiểu.

Bản này là bản cho ``create_all()`` (CSDL test không chạy Alembic — khuôn ``finance/duplicate_guard_ddl.py``). Bản
thật: migration ``hdts20261111`` (một câu ``DO``: khoá bảng → đếm dòng đã lệch → dừng / cài — F274). Hai bản khoá
bằng ``tests/unit/test_council_config_lock_ddl_lockin.py`` (so từng câu sau khi chuẩn hoá khoảng trắng). Migration
KHÔNG import module này (migration phải tái lập đúng lịch sử của nó).
"""
from sqlalchemy import DDL, event

from app.models.base import Base

#: SQLSTATE riêng của trigger (5 ký tự, lớp tự đặt) — đọc bằng ``ma_loi_csdl``, không đọc chữ thông báo.
SQLSTATE_CAU_HINH_DA_DUNG = "QLK02"

#: Câu báo cho người dùng (409) khi trigger chặn.
THONG_DIEP_CAU_HINH_DA_DUNG = (
    "Dòng cấu hình ngành – năm học (hoặc đường xét) này đã được Quyết định đã ký dùng tới — không sửa năm học / "
    "ngành, không xoá. Năm học mới hãy tạo dòng cấu hình mới."
)

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

#: ``UPDATE OF`` chỉ những cột thuộc chuỗi đếm — sửa chỉ tiêu, tên, ưu đãi… không chạy trigger.
#: ``CREATE OR REPLACE`` (PostgreSQL 14+): ``create_all()`` gọi nhiều lần trong một phiên pytest; migration chạy lại
#: được sau khi tiến trình chết giữa câu cài và câu cập nhật ``alembic_version``.
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

#: Số dòng Quyết định chưa huỷ ghi nhận có khoá đếm ĐÃ LỆCH cấu hình hiện tại — cùng nghĩa với ``thieu_dong_nguon``
#: / ``thieu_khoa`` / ``lech_chuoi_cau_hinh`` của ``kiem_khoa_dem_dong_bo`` (test so hai bản:
#: ``tests/api/test_council_config_lock_api.py::test_vi_tu_lech_sql_bang_python``). Migration chạy câu này DƯỚI khoá
#: bảng trước khi cài trigger; > 0 ⇒ dừng.
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

#: KHÔNG dùng ký tự ``%`` trong các câu dưới: ``DDL()`` nội suy chuỗi bằng toán tử ``%`` (``%`` trần ⇒ lỗi định dạng
#: lúc ``create_all``); KHÔNG dùng ``::`` (``text()`` của migration hiểu ``:tên`` là tham số).
#: Thứ tự có ý nghĩa: hàm trước, trigger sau.
CAC_CAU_LENH = (SQL_FN_HOC_VU, SQL_FN_DUONG_XET, *SQL_TRIGGERS)


def _dang_ky():
    """Gắn vào ``after_create`` của METADATA (mọi bảng đã có mặt) — như ``duplicate_guard_ddl``."""
    for cau in CAC_CAU_LENH:
        event.listen(Base.metadata, "after_create", DDL(cau).execute_if(dialect="postgresql"))


_dang_ky()
