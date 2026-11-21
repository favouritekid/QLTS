# app/models/admission_review_ddl.py
"""GĐ2-B — trigger giữ bất biến của lần xét nháp / điểm sàn / lượt chạy / dòng kết quả (đặc tả GĐ2-B bản 4 §4.2; hợp đồng
API bản 4 §1.3, §6, §7). Tầng chủ sở hữu = trigger CSDL: bắt mọi đường ghi, kể cả SQL tay. Dịch vụ chỉ kiểm trước để trả lỗi
nghiệp vụ rõ (lớp phụ).

Bốn trigger (mỗi bảng một), một hàm kiểm chung:

* ``admission_review_assert_session_draft(id)`` — đọc dòng lần xét ``FOR SHARE`` (khuôn ``admission_quota_assert_table_unlocked``
  của GĐ2-A) rồi đòi ``status = 'draft'`` — KHÔNG có dòng cũng là "không nháp" (fail-closed). ``FOR SHARE`` xung đột với khoá dòng
  mà giao dịch huỷ (E5: ``FOR UPDATE`` rồi ``UPDATE``) giữ ⇒ một lệnh ghi sàn (kể cả SQL tay) đến trong lúc huỷ đang dở phải CHỜ,
  rồi đọc lại dòng (READ COMMITTED) ⇒ thấy ``cancelled`` ⇒ dừng. Không có ca "huỷ xong mà vẫn có sàn mới chen vào".
* điểm sàn — INSERT / UPDATE / DELETE chỉ khi lần xét (cũ và mới) đang ``draft`` ⇒ SQLSTATE :data:`SQLSTATE_REVIEW_SESSION_NOT_DRAFT`.
* lần xét — không ``DELETE``; dòng ``cancelled`` không sửa được nữa (:data:`SQLSTATE_REVIEW_SESSION_NOT_DRAFT`); năm của lần xét
  không đổi (E4 đọc năm TRƯỚC khi lấy khoá năm — hợp đồng §2 E4 "năm của lần xét không bao giờ đổi"); chuyển sang ``cancelled``
  khi còn dòng sàn ⇒ dừng (P4: lần xét đã huỷ không giữ sàn nào — E5 xoá sàn TRƯỚC rồi mới chuyển trạng thái).
* lượt chạy — chỉ tạo ở ``queued`` / ``running``; chỉ đi ``queued → running → done / failed``; ``done`` / ``failed`` là cuối (không
  sửa); không ``DELETE``.
* dòng kết quả — chỉ ``INSERT``, chỉ khi lượt đang ``running`` (đọc dòng lượt ``FOR SHARE`` — cùng lý do như sàn: lệnh chuyển
  ``done`` và lệnh chèn dòng không chen nhau); ``UPDATE`` / ``DELETE`` ⇒ dừng.

SQLSTATE (lớp tự đặt, 5 ký tự; đã kiểm còn trống trong toàn repo 21-11 — ``tests/unit/test_gd2b_ddl_lockin.py`` khoá):

* :data:`SQLSTATE_REVIEW_SESSION_NOT_DRAFT` (``QLC02``) — ``middleware/exception_handlers.database_error_handler`` đổi ra 409 CÙNG
  ``error_code`` / ``reason_code`` / ``detail`` với lỗi kiểm trước ở dịch vụ (``REVIEW_SESSION_NOT_DRAFT``), không có ``status``.
* :data:`SQLSTATE_REVIEW_IMMUTABLE` (``QLC03``) — dữ liệu lần xét bất biến (xoá lần xét, đổi năm, huỷ khi còn sàn, lượt / dòng đã
  xong). Không đường API nào của GĐ2-B tới được (dịch vụ không làm các việc ấy) ⇒ KHÔNG đổi ở handler: gặp là lỗi lập trình ⇒ rơi
  xuống nhánh chung 500 ``INTERNAL_ERROR`` như mọi lỗi CSDL khác (hợp đồng §5 "lỗi không lường; không ghi gì").

Bản này cho ``create_all()`` (CSDL test không chạy Alembic — khuôn ``admission_quota_ddl``). Bản thật: migration ``gd2b20261121``
chép NGUYÊN :data:`STATEMENTS` (``tests/unit/test_gd2b_ddl_lockin.py`` so từng câu sau khi chuẩn hoá khoảng trắng). Migration
KHÔNG import module này. KHÔNG dùng ``%`` (``DDL()`` nội suy bằng ``%``) và KHÔNG dùng ``::`` (``text()`` hiểu ``:tên`` là tham số).
"""
from sqlalchemy import DDL, event

from app.models.base import Base

#: Lần xét không ở ``draft`` (ghi sàn / sửa lần xét đã huỷ) — handler đổi ra 409 ``REVIEW_SESSION_NOT_DRAFT``.
SQLSTATE_REVIEW_SESSION_NOT_DRAFT = "QLC02"
#: Dữ liệu lần xét bất biến — KHÔNG đổi ở handler (500 nếu lọt tới API).
SQLSTATE_REVIEW_IMMUTABLE = "QLC03"

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

#: NGUYÊN VĂN migration ``gd2b20261121`` (``tests/unit/test_gd2b_ddl_lockin.py`` so từng câu). Thứ tự có ý nghĩa: hàm kiểm chung
#: trước hàm trigger gọi nó; hàm trước trigger.
STATEMENTS = (
    SQL_FN_ASSERT_SESSION_DRAFT,
    SQL_FN_SESSION_GUARD,
    SQL_FN_FLOOR_GUARD,
    SQL_FN_RUN_GUARD,
    SQL_FN_ROW_GUARD,
    *SQL_TRIGGERS,
)

#: Tên hàm (kèm chữ ký) — hạ cấp gỡ đúng danh sách này; test so với các câu ``CREATE FUNCTION`` ở trên.
FUNCTION_SIGNATURES = (
    "admission_review_assert_session_draft(integer)",
    "admission_review_session_guard()",
    "admission_review_floor_guard()",
    "admission_review_run_guard()",
    "admission_review_row_guard()",
)


def _register():
    """Gắn vào ``after_create`` của METADATA (mọi bảng đã có mặt). ``CREATE TRIGGER`` chạy lại được nhờ ĐÚNG helper của
    ``duplicate_guard_ddl`` (một nguồn); :data:`STATEMENTS` giữ nguyên văn để khớp migration."""
    from app.models.finance.duplicate_guard_ddl import _lam_chay_lai_duoc

    for statement in STATEMENTS:
        event.listen(
            Base.metadata, "after_create", DDL(_lam_chay_lai_duoc(statement)).execute_if(dialect="postgresql")
        )


_register()
