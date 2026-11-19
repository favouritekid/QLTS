# app/models/admission_quota_ddl.py
"""GĐ2-A — trigger CHẶN sửa chỉ tiêu ngành / nhóm / trần / thành viên khi bảng chỉ tiêu năm đã khoá (đặc tả GĐ2 bản 3 §3:
"trigger ``BEFORE UPDATE OF annual_admission_quota`` chặn khi bảng chỉ tiêu ``locked`` (khuôn ``QLK02``)"; ca biên D14
"Sửa chỉ tiêu / trần khi bảng đã khoá ⇒ CSDL chặn; mở khoá bảng (lý do)").

Tầng chủ sở hữu bất biến "bảng đã khoá thì không đổi" = trigger CSDL: bắt mọi đường ghi — API bảng chỉ tiêu, API sửa học
vụ có sẵn (``PATCH /api/admin/academic-info/{id}``), SQL tay, xoá dây chuyền. Dịch vụ bảng chỉ tiêu chỉ kiểm trước để trả
câu 409 rõ (lớp phụ).

Tranh chấp: hàm kiểm khoá dòng ``admission_quota_table`` của năm ``FOR SHARE`` (KHÔNG lọc theo trạng thái — khoá cả dòng
``draft``). Lệnh khoá bảng (``FOR UPDATE``) vì thế phải chờ mọi giao dịch đang sửa chỉ tiêu của năm ấy kết thúc, và giao
dịch sửa chỉ tiêu bắt đầu sau lệnh khoá thì chờ rồi đọc lại dòng (READ COMMITTED) ⇒ thấy ``locked`` ⇒ dừng. Không có ca
"khoá xong rồi chỉ tiêu mới đổi". Năm chưa có bảng ⇒ không có gì để khoá ⇒ cho qua.

Lỗi mang SQLSTATE :data:`SQLSTATE_QUOTA_TABLE_LOCKED`; ``app/middleware/exception_handlers.py`` đổi thành 409 câu dễ hiểu.

GĐ2-F1 (luật B, owner 19-11): trigger trên ``offering_academic_info`` mở rộng — thêm nhánh ``INSERT`` (tạo học vụ CÓ chỉ tiêu
cho năm đã khoá) và theo dõi thêm ``academic_year`` (chuyển học vụ có chỉ tiêu vào / ra năm đã khoá); xem
:data:`STATEMENTS_F1`. Học vụ chỉ tiêu TRỐNG vẫn tạo / chuyển được (cấu hình học phí sớm).

Bản này cho ``create_all()`` (CSDL test không chạy Alembic — khuôn ``council_config_lock_ddl``). Bản thật: migration
``gd2a20261118`` (:data:`STATEMENTS_GD2A`) rồi ``gd2f20261119`` (:data:`STATEMENTS_F1`) chép NGUYÊN câu;
``tests/unit/test_gd2a_quota_ddl_lockin.py`` / ``tests/unit/test_gd2f_trigger_luat_b_lockin.py`` so sau khi chuẩn hoá khoảng
trắng.
Migration KHÔNG import module này. KHÔNG dùng ``%`` (``DDL()`` nội suy bằng ``%``) và KHÔNG dùng ``::`` (``text()`` hiểu
``:tên`` là tham số).
"""
from sqlalchemy import DDL, event

from app.models.base import Base

#: SQLSTATE riêng (5 ký tự, lớp tự đặt) — đọc bằng ``db_error_codes``, không đọc chữ thông báo.
SQLSTATE_QUOTA_TABLE_LOCKED = "QLC01"

#: Câu báo cho người dùng (409) khi trigger chặn — và khi lớp kiểm trước ở dịch vụ chặn cùng luật (cùng hình dạng phản hồi).
MESSAGE_QUOTA_TABLE_LOCKED = (
    "Bảng chỉ tiêu năm này đã khoá — không nhập / sửa chỉ tiêu ngành, không chuyển học vụ có chỉ tiêu vào hay ra năm này, "
    "không sửa nhóm ngành, trần nhóm hay thành viên nhóm. Admin mở khoá bảng (có lý do) trước khi sửa."
)

SQL_FN_ASSERT_UNLOCKED = """
CREATE OR REPLACE FUNCTION admission_quota_assert_table_unlocked(p_year integer)
RETURNS void AS $$
DECLARE
    v_status text;
BEGIN
    IF p_year IS NULL THEN
        RETURN;
    END IF;
    SELECT t.status INTO v_status
      FROM admission_quota_table t
     WHERE t.academic_year = p_year
       FOR SHARE;
    IF v_status = 'locked' THEN
        RAISE EXCEPTION 'admission_quota_table da khoa'
            USING ERRCODE = 'QLC01';
    END IF;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_ACADEMIC_INFO_QUOTA = """
CREATE OR REPLACE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.annual_admission_quota IS NOT DISTINCT FROM OLD.annual_admission_quota THEN
        RETURN NEW;
    END IF;
    PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
    IF NEW.academic_year IS DISTINCT FROM OLD.academic_year THEN
        PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_GROUP_ROWS = """
CREATE OR REPLACE FUNCTION chan_sua_nhom_chi_tieu_khi_bang_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

SQL_FN_TABLE_DELETE = """
CREATE OR REPLACE FUNCTION chan_xoa_bang_chi_tieu_da_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'locked' THEN
        RAISE EXCEPTION 'admission_quota_table da khoa'
            USING ERRCODE = 'QLC01';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql
"""

#: ``UPDATE OF annual_admission_quota`` — sửa học phí, tên, ưu đãi… của học vụ không chạy trigger. (GĐ2-A; trigger trên
#: ``offering_academic_info`` được THAY ở F1 — :data:`SQL_TRIGGER_ACADEMIC_INFO_F1`.)
SQL_TRIGGERS = (
    """
CREATE TRIGGER trg_chan_sua_chi_tieu_nganh_khi_bang_khoa
BEFORE UPDATE OF annual_admission_quota ON offering_academic_info
FOR EACH ROW EXECUTE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
""",
    """
CREATE TRIGGER trg_chan_sua_nhom_chi_tieu_khi_bang_khoa
BEFORE INSERT OR UPDATE OR DELETE ON admission_quota_group
FOR EACH ROW EXECUTE FUNCTION chan_sua_nhom_chi_tieu_khi_bang_khoa()
""",
    """
CREATE TRIGGER trg_chan_sua_thanh_vien_nhom_khi_bang_khoa
BEFORE INSERT OR UPDATE OR DELETE ON admission_quota_group_member
FOR EACH ROW EXECUTE FUNCTION chan_sua_nhom_chi_tieu_khi_bang_khoa()
""",
    """
CREATE TRIGGER trg_chan_xoa_bang_chi_tieu_da_khoa
BEFORE DELETE ON admission_quota_table
FOR EACH ROW EXECUTE FUNCTION chan_xoa_bang_chi_tieu_da_khoa()
""",
)

#: GĐ2-A — NGUYÊN VĂN migration ``gd2a20261118`` (``tests/unit/test_gd2a_quota_ddl_lockin.py`` so từng câu). Thứ tự có ý
#: nghĩa: hàm trước (hàm kiểm chung trước hàm trigger gọi nó), trigger sau.
STATEMENTS_GD2A = (
    SQL_FN_ASSERT_UNLOCKED,
    SQL_FN_ACADEMIC_INFO_QUOTA,
    SQL_FN_GROUP_ROWS,
    SQL_FN_TABLE_DELETE,
    *SQL_TRIGGERS,
)

# ── GĐ2-F1 — luật B (owner chốt 19-11): khoá bảng năm ĐÓNG BĂNG chỉ tiêu nhưng vẫn cho cấu hình học phí sớm ────────────
# R1 tạo học vụ cho năm đã khoá: cho nếu chỉ tiêu TRỐNG (NULL); có chỉ tiêu (kể cả 0 — trống ≠ 0) ⇒ chặn.
# R2 nhập / đổi chỉ tiêu học vụ của năm đã khoá ⇒ chặn (như GĐ2-A).
# R3 chuyển năm học vụ có chỉ tiêu (OLD hoặc NEW khác NULL) VÀO hoặc RA năm đã khoá ⇒ chặn, KỂ CẢ khi con số không đổi.
#    (GĐ2-A chỉ chạy khi ``annual_admission_quota`` đổi ⇒ lệnh chỉ đổi ``academic_year`` lọt qua hẳn.)
# Bản thật: migration ``gd2f20261119`` chép NGUYÊN hai câu dưới (``tests/unit/test_gd2f_trigger_luat_b_lockin.py`` so). Hàm
# kiểm chung ``admission_quota_assert_table_unlocked`` (khoá dòng bảng ``FOR SHARE``) GIỮ nguyên của GĐ2-A.
SQL_FN_ACADEMIC_INFO_QUOTA_F1 = """
CREATE OR REPLACE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.annual_admission_quota IS NOT NULL THEN
            PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.academic_year IS NOT DISTINCT FROM OLD.academic_year THEN
        IF NEW.annual_admission_quota IS NOT DISTINCT FROM OLD.annual_admission_quota THEN
            RETURN NEW;
        END IF;
        PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
        RETURN NEW;
    END IF;
    IF OLD.annual_admission_quota IS NULL AND NEW.annual_admission_quota IS NULL THEN
        RETURN NEW;
    END IF;
    PERFORM admission_quota_assert_table_unlocked(OLD.academic_year);
    PERFORM admission_quota_assert_table_unlocked(NEW.academic_year);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

#: ``CREATE OR REPLACE TRIGGER`` (PostgreSQL 14+) THAY trigger GĐ2-A cùng tên: thêm ``INSERT``, theo dõi thêm ``academic_year``.
#: Sửa học phí, tên, ưu đãi, công bố, xoá mềm… của học vụ vẫn không chạy trigger.
SQL_TRIGGER_ACADEMIC_INFO_F1 = """
CREATE OR REPLACE TRIGGER trg_chan_sua_chi_tieu_nganh_khi_bang_khoa
BEFORE INSERT OR UPDATE OF annual_admission_quota, academic_year ON offering_academic_info
FOR EACH ROW EXECUTE FUNCTION chan_sua_chi_tieu_nganh_khi_bang_khoa()
"""

STATEMENTS_F1 = (SQL_FN_ACADEMIC_INFO_QUOTA_F1, SQL_TRIGGER_ACADEMIC_INFO_F1)

#: Bản cho ``create_all()``: GĐ2-A rồi F1 THAY hàm + trigger học vụ ⇒ trạng thái cuối = head Alembic (``gd2f20261119``).
STATEMENTS = (*STATEMENTS_GD2A, *STATEMENTS_F1)


def _register():
    """Gắn vào ``after_create`` của METADATA (mọi bảng đã có mặt). ``CREATE TRIGGER`` chạy lại được nhờ ĐÚNG helper của
    ``duplicate_guard_ddl`` (một nguồn); ``STATEMENTS`` giữ nguyên văn để khớp migration."""
    from app.models.finance.duplicate_guard_ddl import _lam_chay_lai_duoc

    for statement in STATEMENTS:
        event.listen(
            Base.metadata, "after_create", DDL(_lam_chay_lai_duoc(statement)).execute_if(dialect="postgresql")
        )


_register()
