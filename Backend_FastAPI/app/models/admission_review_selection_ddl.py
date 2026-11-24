# app/models/admission_review_selection_ddl.py
"""GĐ2-C C2 — trigger giữ bất biến của bảng lựa chọn Ban thư ký (``admission_review_selection``; thiết kế GĐ2-C 22-11 §2.2, §6
hàng C2; ĐT3 T16 "lựa chọn chỉ ghi khi ``draft``"). Tầng chủ sở hữu = trigger CSDL: bắt mọi đường ghi, kể cả SQL tay. Dịch vụ chỉ
kiểm trước để trả lỗi nghiệp vụ rõ (lớp phụ).

MỘT trigger ``BEFORE INSERT OR UPDATE OR DELETE``, MỘT hàm:

1. ``UPDATE`` / ``DELETE`` ⇒ dừng (:data:`SQLSTATE_SELECTION_IMMUTABLE`) — **chỉ thêm**; "đổi ý" là dòng mới có ``supersedes_id``.
2. ``INSERT`` chỉ khi lần xét đang ``draft``: gọi ĐÚNG hàm kiểm chung của GĐ2-B ``admission_review_assert_session_draft`` (đọc
   dòng lần xét ``FOR SHARE``; không phải ``draft`` / không có ⇒ ``QLC02`` — ``middleware/exception_handlers`` đổi ra 409
   ``REVIEW_SESSION_NOT_DRAFT``). MỘT nguồn với điểm sàn; ``FOR SHARE`` xung đột với khoá dòng của giao dịch huỷ / khoá lần xét ⇒
   lựa chọn đến trong lúc huỷ đang dở phải CHỜ rồi thấy ``cancelled`` ⇒ dừng.
3. ``based_on_run_id`` phải là lượt ``evaluate`` ĐÃ XONG của CHÍNH lần xét; dòng kết quả (lượt ấy, hồ sơ ấy) phải có và khớp
   ``based_on_row_hash`` + ``choice_id`` (NV được xếp của dòng) — không ghi được lựa chọn dựa trên một dòng không có thật. Lượt
   ``done`` và dòng của nó bất biến (trigger GĐ2-B) ⇒ không cần khoá.
4. ``supersedes_id`` (nếu có) phải trỏ dòng của CÙNG (lần xét, hồ sơ). Một dòng bị thay tối đa một lần (UNIQUE) và dòng thay đứng
   sau (CHECK ``supersedes_id < id``) — ở bảng, không ở trigger.

Phép so "dòng dựa vào là dòng của lượt MỚI NHẤT" (``SELECTION_STALE``, ĐT3 T9) KHÔNG ở đây: "mới nhất" phụ thuộc thời điểm; dịch vụ
so dưới khoá dòng lần xét ``FOR UPDATE`` (lượt chạy ghi kết quả cũng khoá dòng ấy ⇒ hai việc nối tiếp).

SQLSTATE riêng (5 ký tự, lớp tự đặt; đã kiểm còn trống trong ``app/`` + ``alembic/`` của nền tích hợp 22-11 — GĐ2-B dùng
``QLC01``–``QLC04``, ``QLC10``–``QLC12``; C1 ``QLC20``–``QLC21``):

* :data:`SQLSTATE_SELECTION_IMMUTABLE` (``QLC22``) — sửa / xoá lựa chọn, hoặc dòng dựa vào / dòng bị thay không hợp lệ. Dịch vụ
  không bao giờ chạm tới (chỉ chèn, sau khi đã tự kiểm) ⇒ gặp mã này = có đường ghi sai ⇒ để 500 (fail-closed), KHÔNG đổi ở
  handler (khuôn ``QLC03`` của GĐ2-B, ``QLC20`` của C1).

Bản cho ``create_all()`` (CSDL test không chạy Alembic — khuôn ``admission_review_ddl``). Bản thật: migration ``gd2cs20261122``
chép NGUYÊN :data:`STATEMENTS` (``tests/unit/test_gd2c_c2_ddl_lockin.py`` so từng câu). KHÔNG dùng ``%`` (``DDL()`` nội suy bằng
``%``) và ``::`` (``text()`` hiểu ``:tên`` là tham số).
"""
from sqlalchemy import DDL, event

from app.models.base import Base

#: Lựa chọn bất biến / dòng dựa vào không hợp lệ — KHÔNG đổi ở handler (500 nếu lọt tới API).
SQLSTATE_SELECTION_IMMUTABLE = "QLC22"

SQL_FN_SELECTION_GUARD = """
CREATE OR REPLACE FUNCTION admission_review_selection_guard()
RETURNS TRIGGER AS $$
DECLARE
    v_run_session integer;
    v_run_kind text;
    v_run_status text;
    v_row_hash text;
    v_row_choice integer;
    v_prev_session integer;
    v_prev_profile integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'admission_review_selection chi them'
            USING ERRCODE = 'QLC22';
    END IF;
    PERFORM admission_review_assert_session_draft(NEW.session_id);
    SELECT r.session_id, r.kind, r.status INTO v_run_session, v_run_kind, v_run_status
      FROM admission_review_run r
     WHERE r.id = NEW.based_on_run_id;
    IF v_run_session IS DISTINCT FROM NEW.session_id
       OR v_run_kind IS DISTINCT FROM 'evaluate'
       OR v_run_status IS DISTINCT FROM 'done' THEN
        RAISE EXCEPTION 'admission_review_selection dua vao luot khong hop le'
            USING ERRCODE = 'QLC22';
    END IF;
    SELECT w.row_hash, w.considered_choice_id INTO v_row_hash, v_row_choice
      FROM admission_review_row w
     WHERE w.run_id = NEW.based_on_run_id
       AND w.profile_id = NEW.profile_id;
    IF NOT FOUND
       OR v_row_hash IS DISTINCT FROM NEW.based_on_row_hash
       OR v_row_choice IS DISTINCT FROM NEW.choice_id THEN
        RAISE EXCEPTION 'admission_review_selection dua vao dong khong khop'
            USING ERRCODE = 'QLC22';
    END IF;
    IF NEW.supersedes_id IS NOT NULL THEN
        SELECT p.session_id, p.profile_id INTO v_prev_session, v_prev_profile
          FROM admission_review_selection p
         WHERE p.id = NEW.supersedes_id;
        IF v_prev_session IS DISTINCT FROM NEW.session_id
           OR v_prev_profile IS DISTINCT FROM NEW.profile_id THEN
            RAISE EXCEPTION 'admission_review_selection thay dong khong cung ho so'
                USING ERRCODE = 'QLC22';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""

SQL_TRIGGER_SELECTION_GUARD = """
CREATE TRIGGER trg_admission_review_selection_guard
BEFORE INSERT OR UPDATE OR DELETE ON admission_review_selection
FOR EACH ROW EXECUTE FUNCTION admission_review_selection_guard()
"""

#: NGUYÊN VĂN migration ``gd2cs20261122``. Thứ tự: hàm trước trigger.
STATEMENTS = (SQL_FN_SELECTION_GUARD, SQL_TRIGGER_SELECTION_GUARD)

#: Tên hàm (kèm chữ ký) — hạ cấp gỡ đúng danh sách này; test so với các câu ``CREATE FUNCTION`` ở trên.
FUNCTION_SIGNATURES = ("admission_review_selection_guard()",)


def _register():
    """Gắn vào ``after_create`` của METADATA (mọi bảng đã có mặt — hàm gọi ``admission_review_assert_session_draft`` của GĐ2-B,
    đăng ký TRƯỚC module này trong ``app/models/__init__.py``). ``CREATE TRIGGER`` chạy lại được nhờ ĐÚNG helper của
    ``duplicate_guard_ddl`` (một nguồn); :data:`STATEMENTS` giữ nguyên văn để khớp migration."""
    from app.models.finance.duplicate_guard_ddl import _lam_chay_lai_duoc

    for statement in STATEMENTS:
        event.listen(
            Base.metadata, "after_create", DDL(_lam_chay_lai_duoc(statement)).execute_if(dialect="postgresql")
        )


_register()
